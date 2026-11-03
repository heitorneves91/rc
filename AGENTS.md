# AGENTS.md

This file provides guidance to AI coding agents when working in this repository.

## Project Overview

This repository contains both halves of a Wi-Fi controlled FPV remote-controlled (RC) car:

1. **`vehicle/`** — The onboard hardware design, 3D-printed CAD models, and ESP32-S3 firmware:
   - **MCU & Vision**: **Seeed Studio XIAO ESP32-S3 Sense** (ESP32-S3 @ 240 MHz, 8 MB QIO flash, 8 MB OPI PSRAM, on-board OV2640/OV5640 camera sensor, and Wi-Fi soft AP).
   - **Propulsion & Steering**: **A2212 1000KV** brushless outrunner drone motor driven by a hobby brushless ESC on **D0 / GPIO1**, plus a steering servo on **D1 / GPIO2**.
   - **Electronics (`vehicle/board.diy`)**: DIYLC perfboard layout (`48.26 × 63.5 mm`) with 3× RC low-pass signal-protection filters (`1 kΩ` series + `4.7 nF` shunt to GND) and dual `470 µF` + `100 nF` decoupling capacitor banks.
   - **CAD (`vehicle/cad/`)**: FreeCAD parametric models (`car.FCStd`, `assembly.FCStd`, `rear_assembly.FCStd`) and exported `.3mf` 3D-printable parts (chassis modules, body, ESP32/electronics supports, motor spur gear, and dogbone shafts).
   - **Firmware (`vehicle/esp32s3/rc/`)**: PlatformIO / Arduino C++ firmware. Detailed documentation for the vehicle side lives in [`vehicle/AGENTS.md`](vehicle/AGENTS.md).

2. **`ground-station-android/`** — The operator cockpit application for Android:
   - **Stack**: Kotlin + Jetpack Compose (`minSdk = 36`, `targetSdk = 36`), landscape-only full-screen UI.
   - **Networking**: Automatically joins the vehicle's `rc-car` Wi-Fi access point (`192.168.4.1`) via `WifiNetworkSpecifier` and binds the process to the Wi-Fi network (`WifiService.kt`).
   - **Control & Telemetry**: Sends `move` commands at ~25 Hz and `conf` commands to UDP `192.168.4.1:8888`, and receives `tele` state updates on the same socket (`VehicleService.kt`).
   - **Video Receiver**: Listens on UDP `:9999`, reassembles chunked MJPEG frames (`FrameAssembler`), decodes JPEGs with `BitmapFactory` (reusing bitmaps via `inBitmap`), and renders onto a full-screen `SurfaceView` (`CameraService.kt`).

## Shared Wire Protocols (Keep in Sync)

Any change to the command/telemetry protocol or video chunk header **must** be updated in both C++ (`vehicle/esp32s3/rc/`) and Kotlin (`ground-station-android/`):

- **Control & Telemetry (UDP `:8888`, UTF-8 text)**:
  - `move:<seq>,<throttle>,<steering>` — ground → vehicle (~25 Hz; `throttle` `0..100`, `steering` `-100..100`).
  - `conf:<seq>,<configuration>,<value>` — ground → vehicle (`GROUND_HELLO`, `START_CAMERA` with optional `width,height,framerate`, `STOP_CAMERA`, `STEERING_TRIM` with `trim_us` in `-500..500` persisted to NVS).
  - `tele:<seq>,<throttle>,<steering>,<steering_trim_us>` — vehicle → ground (4 Hz + immediate on `GROUND_HELLO` / `STEERING_TRIM`).
  - Implementations: `vehicle/esp32s3/rc/src/ground_station_service.cpp` ↔ `ground-station-android/app/src/main/java/com/example/ground_station_android/vehicle/VehicleService.kt`.

- **Video Stream (UDP `:9999`, binary chunked MJPEG)**:
  - 16-byte big-endian header (`'J','F'`, version `1`, flags `0`, `uint16 frame_id`, `uint16 chunk_index`, `uint16 chunk_count`, `uint16 reserved`, `uint32 total_jpeg_size`) followed by up to `1400` bytes of JPEG payload.
  - Implementations: `vehicle/esp32s3/rc/include/camera_service.h` & `src/camera_service.cpp` ↔ `ground-station-android/app/src/main/java/com/example/ground_station_android/vehicle/CameraService.kt`.

## Common Commands

### Vehicle Firmware (`vehicle/esp32s3/rc/`)

```bash
cd vehicle/esp32s3/rc
pio run                       # compile firmware
pio run -t upload             # flash over USB
pio device monitor            # serial console (115200 baud)
```
*(If `pio` is not on `PATH`, use `~/.platformio/penv/bin/pio`.)*

### Android Ground Station (`ground-station-android/`)

```bash
cd ground-station-android
./gradlew assembleDebug       # build debug APK
./gradlew test                # run unit tests
```
