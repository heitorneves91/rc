# AGENTS.md

This file provides guidance to AI coding agents when working with code in the `vehicle/` directory.

## What this is

The vehicle half of a remote-controlled car project:

- **Controller & Vision**: **Seeed Studio XIAO ESP32-S3 Sense** (ESP32-S3 with 8 MB OPI PSRAM, 8 MB flash, on-board OV2640/OV5640 camera, and Wi-Fi).
- **Powertrain & Actuators**: **A2212 1000KV** brushless outrunner drone motor driven by a hobby brushless ESC (throttle on **D0 / GPIO1**), plus a hobby steering servo (**D1 / GPIO2**).
- `esp32s3/rc/` — **the vehicle firmware.** PlatformIO/Arduino C++ targeting the XIAO ESP32-S3 Sense. Arms and drives the ESC and steering servo via LEDC PWM, hosts its own Wi-Fi soft AP (`rc-car` at `192.168.4.1`), speaks a custom UDP control/telemetry protocol with the ground station, and pushes chunked MJPEG camera video over UDP.
- `board.diy` — **electronics board layout** (DIY Layout Creator / DIYLC). Perfboard (`48.26 × 63.5 mm`) carrying:
  - Three RC low-pass / signal-protection channels (`R1`, `R4`, `R5` = `1 kΩ` series resistors; `C8`, `C9`, `C10` = `4.7 nF` shunt ceramic capacitors to ground, $f_c \approx 34\text{ kHz}$) between 3-pin headers `PH8` and `PH7` to protect ESP32-S3 GPIOs and filter ESC switching noise.
  - Dual power-rail decoupling banks (`C11`, `C13` = `470 µF` electrolytic in parallel with `C12`, `C14` = `100 nF` ceramic across headers `PH12`–`PH16`, `PH9`, `PH11`) to buffer servo/BEC current spikes.
- `cad/` — FreeCAD parametric models (`car.FCStd`, `assembly.FCStd`, `rear_assembly.FCStd`) and exported `.3mf` print files for the modular 3D-printed chassis, body, ESP32/electronics mounts, spur gear, and rear dogbone shafts (`36`–`42 mm`).

The operator side lives in the sibling directory `../ground-station-android` (Kotlin/Jetpack Compose Android app). The wire protocol is shared, so protocol changes must be made on both sides.

*(Historical note: the vehicle originally ran Python + `pigpio` + `rpicam-vid` on a Raspberry Pi in `rpi/`, which has since been removed; comments in the firmware occasionally reference the Pi build to explain porting choices.)*

## Commands

```bash
cd esp32s3/rc
pio run                       # build
pio run -t upload             # flash over USB
pio device monitor            # serial console, 115200
```

There is no test suite; `pio run` is the only check. `pio` lives at `~/.platformio/penv/bin/pio` if it is not on `PATH`.

`platformio.ini` pins board-specific PSRAM/flash settings (`qio_opi`, 8 MB, `-DBOARD_HAS_PSRAM`) that the XIAO ESP32-S3 Sense camera needs — changing them breaks framebuffer allocation.

## Architecture

`src/main.cpp` is the composition root:
load config → logging → camera → Wi-Fi AP → arm movement → start the link.
Every service owns its own FreeRTOS task, so `loop()` does nothing.

```
ground_station_service ──commands──▶ movement_service ──LEDC PWM──▶ ESC (A2212 1000KV) + servo
   (UDP :8888)   ▲                          │
                 └──── getState() ──────────┘  (telemetry task, 4 Hz)
   START/STOP_CAMERA ──▶ camera_service ──▶ chunked MJPEG (UDP → ground :9999)
   wifi_service ──▶ soft AP "rc-car" at 192.168.4.1
```

Each service is a namespace with a header in `include/` and its implementation in `src/`. State is file-local in an anonymous namespace, guarded by a FreeRTOS mutex where needed.

**`configuration`** — a single global `config` aggregating nested structs (`movement`, `camera`, `ground_station`, `wifi`) plus `log_level`. Persists to NVS (`Preferences`, namespace `"rc"`): `config.load()` falls back to the compiled-in defaults for any key absent from flash, so the layout can grow without bricking already-flashed devices. `config.save()` persists.

**`movement_service`** — throttle/steering ints map to servo pulse widths:
- **ESC / A2212 1000KV motor (`rl_motor_gpio = 1`)**: `1000 + 10 * throttle` µs (`0..100` → `1000..2000 µs`), clamped to `1000–2000 µs`. Holds `1000 µs` for `config.movement.arm_delay_s` (`2.0 s`) on `init()` so the brushless ESC arms cleanly before drive commands are accepted.
- **Steering servo (`steering_gpio = 2`)**: `1500 + steering_trim_us - 4.375 * steering` µs (default `steering_trim_us = 20` µs; negated because the mechanical linkage is reversed, and 70% of the earlier `6.25 µs/unit` mapping), clamped to `800–2200 µs`.
- Signals are emitted by LEDC at 50 Hz, 14-bit duty resolution (the ESP32-S3's ceiling `SOC_LEDC_TIMER_BIT_WIDE_NUM` — requesting 16 bits makes `ledcSetup` fail).
- Owns the **failsafe**: a watchdog task (`priority = 5`) cuts throttle to `0` (`1000 µs`) if no command arrives within `config.movement.command_timeout_s` (`1.0 s`). This deliberately lives here, not in the link layer, so *any* caller that stops feeding commands stops the vehicle. Note the asymmetry: `setThrottle`/`setSteering` feed the watchdog, whereas `applyThrottle`/`applySteering` do not — the failsafe path uses `applyThrottle(0)` so it stays latched until a real command arrives.

**`ground_station_service`** — one `WiFiUDP` socket polled from a receive task (`priority = 6`), plus a telemetry task (`priority = 4`, 4 Hz). The telemetry destination is learned from whatever address sent the last packet. Move commands carry a monotonic `seq`; anything `<=` the last seen seq is dropped as stale/reordered, and `GROUND_HELLO` resets that counter because the client restarts its own sequence at −1 when it reopens its socket.

**`camera_service`** — `esp_camera` plus a send task (`priority = 3`) that pushes JPEG frames over UDP (see **Video transport** below for the datagram layout). Initialized at `FRAMESIZE_UXGA` with 2 PSRAM framebuffers early in boot (before Wi-Fi, so PSRAM is unfragmented) and scaled down per request via `frameSizeFor(width, height)`. Also applies sensor-level vertical flip (`vflip = true`, since the camera is mounted upside down) and horizontal mirror (`hmirror = false`). The send loop polls a `streaming` flag every frame so `stop()` can end it, and `stop()` waits for the task to actually exit so a `START_CAMERA` arriving straight after a `STOP_CAMERA` does not find one still winding down. The socket is a raw lwIP UDP socket rather than `WiFiUDP`, whose byte-at-a-time `write()` is too slow for hundreds of datagrams per second.

### Hardware pin budget

The camera occupies GPIO `10–18` and `38–48` (`XCLK=10`, `SIOD=40`, `SIOC=39`, `Y2..Y9=15,17,18,16,14,12,11,48`, `VSYNC=38`, `HREF=47`, `PCLK=13`), so the actuator outputs use the free header pins:
- **D0 / GPIO1** = ESC signal (A2212 1000KV brushless motor)
- **D1 / GPIO2** = Steering servo signal

LEDC timer 0 / channel 0 belong to the camera's 20 MHz `XCLK`, so movement uses **channels 2 and 3** (`LEDC_TIMER_1`). Any new PWM peripheral must avoid both.

### Wire protocol (UDP, UTF-8 text)

`<type>:<seq>,<field>,<field>` — must stay in sync with the Android app (`../ground-station-android`):

| Message | Direction | Payload |
| --- | --- | --- |
| `move:<seq>,<throttle>,<steering>` | ground → vehicle | drive command (`throttle` `0..100`, `steering` `-100..100`), ~25 Hz |
| `conf:<seq>,<configuration>,<value>` | ground → vehicle | `GROUND_HELLO`, `START_CAMERA` (optional `width,height,framerate`), `STOP_CAMERA`, `STEERING_TRIM` (`trim_us` in `-500..500`, applied immediately and saved to NVS) |
| `tele:<seq>,<throttle>,<steering>,<steering_trim_us>` | vehicle → ground | telemetry, 4 Hz (plus immediate push on `GROUND_HELLO` and `STEERING_TRIM`) |

Video is the one message that is binary — see below.

Commands arrive on `ground_station.listen_port` (`8888`). The Kotlin client interpolates an absent value as the literal string `"null"`; `ConfigureMessage::parse` normalizes that to empty.

### Video transport (chunked MJPEG over UDP)

The ESP32-S3 camera peripheral outputs hardware-encoded **MJPEG** (one self-contained JPEG per frame) pushed over UDP to `camera.video_port` (`9999`) at the IP address `START_CAMERA` came from.

Because a JPEG frame exceeds a single Wi-Fi MTU, each frame is split into chunks of `kVideoChunkPayloadBytes` (`1400` bytes) prefixed with a 16-byte big-endian header:

| Offset | Size | Field |
| --- | --- | --- |
| `0` | 2 | Magic `'J'`, `'F'` |
| `2` | 1 | Protocol version (`1`) |
| `3` | 1 | Flags (reserved, `0`) |
| `4` | 2 | `frame_id` (uint16, wraps at $2^{16}$) |
| `6` | 2 | `chunk_index` within the frame (`0 .. chunk_count - 1`) |
| `8` | 2 | `chunk_count` for the frame |
| `10` | 2 | Reserved (`0`) |
| `12` | 4 | Total JPEG size in bytes |
| `16` | `<= 1400` | JPEG slice starting at `chunk_index * 1400` |

The layout is declared in `include/camera_service.h`; the receiving side is `CameraService.kt`'s `FrameAssembler` in `../ground-station-android`, and the two must change together. Incomplete frames are discarded on packet loss and replaced by the next complete frame.

## Conventions

- Services expose `init()`/`start()`/`stop()`/`shutdown()` free functions in a namespace; only `GroundStationService` is a class (it owns a `WiFiUDP` socket).
- Log through `LOG_INFO`/`LOG_WARN`/`LOG_ERROR`/`LOG_DEBUG` from `logs.h` with the module name as the tag, honouring `config.log_level`.
- Comments and some strings may be in Portuguese.
- `cad/car.FCStd` is a large binary committed on nearly every CAD change; commit messages for it are conventionally just `cad`.
