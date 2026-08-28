// WiFi service: the vehicle is its own access point.
//
// New in the ESP32 build. The Raspberry Pi joined an existing network at a
// fixed address (192.168.0.123); the vehicle now creates the network itself
// on a fixed address, so there is no infrastructure to depend on in the field
// and the ground station always knows where to find it.
#pragma once

#include <Arduino.h>
#include <WiFi.h>

namespace wifi_service {

// Brings up the soft AP from `config.wifi`. Returns false if the AP could not
// be started.
bool startAccessPoint();

IPAddress ip();

}  // namespace wifi_service
