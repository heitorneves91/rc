// Movement service: drives the ESC (throttle) and steering servo.
//
// Also owns the command-timeout failsafe. A background watchdog task watches
// the time since the last drive command; if more than
// `config.movement.command_timeout_s` elapses, it cuts the throttle to the
// minimum (safe) signal. This keeps the failsafe a movement concern,
// independent of which link delivered the commands - any caller that stops
// feeding commands will cause the vehicle to stop, with no cooperation
// required from the link.
//
// On the Raspberry Pi this used pigpio's `set_servo_pulsewidth`; here the
// pulses come from the ESP32 LEDC peripheral at 50 Hz.
#pragma once

#include <Arduino.h>

namespace movement_service {

// Arms the ESC (holds the minimum signal for `arm_delay_s`) and starts the
// watchdog. Returns false if the LEDC channels could not be set up.
bool init();

// Stops the watchdog and cuts the throttle. Safe to call more than once.
void shutdown();

// `force` writes the actuators even before init() has completed - used
// during arming, and for manual bring-up.
void setThrottle(int throttle, bool force = false);
void setSteering(int steering, bool force = false);

// Current (throttle, steering) as last written to the actuators.
void getState(int& throttle, int& steering);

bool failsafeActive();

}  // namespace movement_service
