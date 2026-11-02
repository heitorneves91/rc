# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The vehicle half of a remote-controlled car project.

- `esp32s3/rc/` — **the vehicle firmware.** PlatformIO/Arduino C++ for a
  **Seeed XIAO ESP32-S3 Sense**. Drives the ESC and steering servo, hosts its
  own WiFi access point, speaks a UDP protocol with the ground station, and
  pushes camera video to it.
- `rpi/` — **superseded.** The original Raspberry Pi Python implementation,
  kept as reference; the Pi hardware failed and the firmware above is a direct
  port of it. Do not add features here.
- `cad/` — FreeCAD model (`car.FCStd`) and exported `.3mf` print files.
- `teste.diy` — DIYLC circuit layout.

The operator side lives in the sibling directory `../ground-station-android`
(Kotlin/Compose Android app). The wire protocol is shared, so protocol changes
must be made on both sides.

## Commands

```bash
cd esp32s3/rc
pio run                       # build
pio run -t upload             # flash over USB
pio device monitor            # serial console, 115200
```

There is no test suite; `pio run` is the only check. `pio` lives at
`~/.platformio/penv/bin/pio` if it is not on PATH.

`platformio.ini` pins board-specific PSRAM/flash settings (`qio_opi`, 8 MB)
that the XIAO S3 Sense camera needs — changing them breaks framebuffer
allocation.

## Architecture

`src/main.cpp` is the composition root, mirroring the Pi build's `main.py`:
load config → logging → camera → WiFi AP → arm movement → start the link.
Every service owns its own FreeRTOS task, so `loop()` does nothing.

```
ground_station_service ──commands──▶ movement_service ──LEDC PWM──▶ ESC + servo
   (UDP :8888)   ▲                          │
                 └──── getState() ──────────┘  (telemetry task, 4 Hz)
   START/STOP_CAMERA ──▶ camera_service ──▶ chunked MJPEG (UDP → ground :9999)
   wifi_service ──▶ soft AP "rc-car" at 192.168.4.1
```

Each service is a namespace with a header in `include/` and its implementation
in `src/`, one pair per Python module it replaces. State is file-local in an
anonymous namespace, guarded by a FreeRTOS mutex where the Python used a
`threading.Lock`.

**`configuration`** — a single global `config` aggregating nested structs
(`movement`, `camera`, `ground_station`, `wifi`) plus `log_level`. Replaces the
Pi's `.config.json` with NVS (`Preferences`, namespace `"rc"`): `config.load()`
falls back to the compiled-in defaults for any key absent from flash, so the
layout can grow without bricking already-flashed devices. `config.save()`
persists.

**`movement_service`** — throttle/steering ints map to servo pulse widths
(`1000 + 10*throttle` µs; steering `1500 + steering_trim_us - 6.25*steering` µs,
negated because the linkage is reversed and 25% wider than the Pi build),
emitted by LEDC at 50 Hz, 14-bit (the S3's maximum duty resolution — 16 makes
`ledcSetup` fail), and clamped to 1000–2000 µs for the ESC, 800–2200 µs for the
steering servo. Owns the **failsafe**: a watchdog task cuts throttle
to 0 if no command arrives within
`config.movement.command_timeout_s`. This deliberately lives here, not in the
link layer, so *any* caller that stops feeding commands stops the vehicle.
Note the asymmetry: `setThrottle`/`setSteering` feed the watchdog,
`applyThrottle`/`applySteering` do not — the failsafe path uses the latter so
it stays latched until a real command arrives.

**`ground_station_service`** — one `WiFiUDP` socket polled from a receive task,
plus a telemetry task. The telemetry destination is learned from whatever
address sent the last packet. Move commands carry a monotonic `seq`; anything
`<=` the last seen seq is dropped as stale/reordered, and `GROUND_HELLO`
resets that counter because the client restarts its own sequence at −1 when it
reopens its socket.

**`camera_service`** — `esp_camera` plus a send task that pushes JPEG frames
over UDP (see **Video transport** below for the datagram layout). Initialized
at `FRAMESIZE_UXGA` early in boot (before WiFi, so PSRAM is unfragmented) and
scaled down per request; growing the frame size after init would need a buffer
larger than was reserved. The send loop polls a `streaming` flag every frame so
`stop()` can end it, and `stop()` waits for the task to actually exit so a
START arriving straight after a STOP does not find one still winding down. The
destination is not configured: `START_CAMERA` carries it implicitly, and
`ground_station_service` passes the address the command arrived from. The
socket here is a raw lwIP one rather than `WiFiUDP`, whose `write()` copies a
byte at a time — too slow for the hundreds of datagrams per second this
path emits.

### Hardware pin budget

The camera occupies GPIO 10–18 and 38–48, so the servo outputs use the free
header pins: **D0/GPIO1 = ESC**, **D1/GPIO2 = steering**. LEDC timer 0 /
channel 0 belong to the camera's XCLK, so movement uses channels 2 and 3
(LEDC timer 1). Any new PWM peripheral must avoid both.

### Wire protocol (UDP, UTF-8 text)

`<type>:<seq>,<field>,<field>` — must stay in sync with the Android app:

| Message | Direction | Payload |
| --- | --- | --- |
| `move:<seq>,<throttle>,<steering>` | ground → vehicle | drive command, ~25 Hz |
| `conf:<seq>,<configuration>,<value>` | ground → vehicle | `GROUND_HELLO`, `START_CAMERA` (optional `width,height,framerate`), `STOP_CAMERA` |
| `tele:<seq>,<throttle>,<steering>` | vehicle → ground | telemetry |

Video is the one message that is not text — see below.

Commands arrive on `ground_station.listen_port` (8888). The Kotlin client
interpolates an absent value as the literal string `"null"`; the parser
normalizes that to empty.

### Video transport — payload differs from the Pi build

The Pi ran `rpicam-vid` and pushed **H.264** over UDP to the ground station's
port 9999, where the Android app decoded it with `MediaCodec`. The ESP32-S3 has
no H.264 encoder, so the payload is now **MJPEG** — one self-contained JPEG per
frame, no `MediaCodec` in the path at all. The transport is unchanged: the
vehicle still pushes to `camera.video_port` (9999) at the address `START_CAMERA`
came from, so the ground station needs no reachable server.

A JPEG exceeds one datagram, so each frame is split into chunks of
`kVideoChunkPayloadBytes` (1400, to stay inside the WiFi MTU) behind a 16-byte
big-endian header: magic `JF`, version, flags, frame id, chunk index, chunk
count, reserved, total JPEG size. Chunk N carries JPEG bytes from
`N * 1400`, so chunks can be placed in any order. The layout is declared in
`include/camera_service.h`; the other half is `CameraService.kt`'s
`FrameAssembler` in `../ground-station-android`, and the two must change
together.

Loss is not recovered: an incomplete frame is discarded and the next whole
frame replaces it. That is why MJPEG is a good fit here — with no reference
frames, a lost frame cannot corrupt the ones after it.

## Conventions

- Services expose `init()`/`start()`/`stop()`/`shutdown()` free functions in a
  namespace; only `GroundStationService` is a class (it owns a socket).
- Log through `LOG_INFO`/`LOG_WARN`/`LOG_ERROR`/`LOG_DEBUG` from `logs.h` with
  the module name as the tag, honouring `config.log_level`.
- Comments and some strings may be in Portuguese.
- `cad/car.FCStd` is a large binary committed on nearly every change; commit
  messages for it are conventionally just `cad`.
