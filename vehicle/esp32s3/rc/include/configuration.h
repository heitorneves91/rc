// Centralized application configuration.
//
// A single `config` object holds every tunable parameter for the vehicle
// (movement, camera, ground-station link, WiFi access point, logging).
//
// On `load()` the configuration is read from NVS (flash); any key missing
// from NVS keeps the default defined here, so the format can grow over time
// without breaking devices flashed with an older layout.
//
// Use `config.save()` after changing values to persist them across reboots.
// (This replaces the Raspberry Pi build's `.config.json` file.)
#pragma once

#include <Arduino.h>
#include <IPAddress.h>

struct MovementConfig {
    // Free GPIOs on the XIAO ESP32-S3 Sense: the camera occupies 10-18 and
    // 38-48, so the servo outputs live on the D0/D1 header pins.
    int rl_motor_gpio = 1;   // D0 - ESC signal
    int steering_gpio = 2;   // D1 - steering servo signal

    // Seconds to hold the minimum signal so the ESC can arm on startup.
    float arm_delay_s = 2.0f;

    // Failsafe: if no drive command arrives within this window (seconds), the
    // movement watchdog cuts the throttle. Enforced by movement_service
    // itself, independent of which link delivered (or stopped delivering)
    // commands.
    float command_timeout_s = 1.0f;

    // Steering servo trim, in microseconds added to the 1500 us center, so
    // that steering 0 points the horn straight up despite the spline not
    // allowing a perfect mechanical fit. Positive = counter-clockwise when
    // facing the horn (on most hobby servos a longer pulse turns CCW).
    int steering_trim_us = 20;
};

struct CameraConfig {
    int width = 640;
    int height = 480;
    int framerate = 25;
    // UDP port on the *ground station* that MJPEG frames are pushed to. Same
    // port the Raspberry Pi build pushed H.264 to, so the ground station keeps
    // listening where it always did - only the payload changed. See
    // camera_service.h for the chunk format.
    int video_port = 9999;
    // 10-63; lower is better quality and a bigger frame.
    int jpeg_quality = 12;
    // Orientation, applied by the sensor itself (free). The camera is mounted
    // upside down, so the image is flipped vertically.
    bool vflip = true;
    bool hmirror = false;
};

struct GroundStationConfig {
    int listen_port = 8888;
    // How often telemetry is sent to the ground station once its address is
    // known (seconds).
    float telemetry_interval_s = 0.25f;
};

struct WifiConfig {
    // The vehicle is its own access point; the ground station joins it.
    String ssid = "rc-car";
    String password = "rccar1234";  // >= 8 chars, or "" for an open network
    int channel = 1;
    int max_connections = 2;
    // Fixed AP addressing, so the vehicle's address never changes.
    String ip = "192.168.4.1";
    String gateway = "192.168.4.1";
    String subnet = "255.255.255.0";
};

// Top-level configuration aggregating every service's settings.
struct Configuration {
    MovementConfig movement;
    CameraConfig camera;
    GroundStationConfig ground_station;
    WifiConfig wifi;

    String log_level = "INFO";

    // Read values from NVS, falling back to the defaults above.
    void load();
    // Persist the current configuration to NVS.
    void save();
};

// Application-wide singleton. Include this everywhere:
//     #include "configuration.h"
extern Configuration config;
