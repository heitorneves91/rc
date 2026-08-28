// Composition root for the vehicle firmware.
//
// Mirrors the Raspberry Pi build's `main.py`: bring up configuration and
// logging, arm the actuators, then hand control to the ground-station link.
// The difference is that the link no longer blocks here - it runs in its own
// FreeRTOS task, so `loop()` stays free.
#include <Arduino.h>

#include "camera_service.h"
#include "configuration.h"
#include "ground_station_service.h"
#include "logs.h"
#include "movement_service.h"
#include "wifi_service.h"

namespace {
constexpr const char* kTag = "main";
}

void setup() {
    Serial.begin(115200);
    delay(3000);  // Give the USB CDC console time to enumerate.

    config.load();
    logs::init();
    LOG_INFO(kTag, "rc vehicle starting");

    // Before WiFi, so the camera gets its PSRAM framebuffers out of an
    // unfragmented heap.
    camera_service::init();

    wifi_service::startAccessPoint();

    // Arms the ESC (blocks for config.movement.arm_delay_s) and starts the
    // command-timeout watchdog.
    movement_service::init();

    if (!ground_station_service::service.start()) {
        LOG_ERROR(kTag, "ground-station link failed to start");
    }

    LOG_INFO(kTag, "ready - join '%s' and drive; video at %s", config.wifi.ssid.c_str(),
             camera_service::streamUrl().c_str());
}

void loop() {
    // Every service owns a task; nothing to do here.
    vTaskDelay(pdMS_TO_TICKS(1000));
}
