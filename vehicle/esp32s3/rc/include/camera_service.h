// Camera service: serves live video from the on-board OV2640/OV5640.
//
// TRANSPORT CHANGE vs. the Raspberry Pi build: the Pi spawned `rpicam-vid`
// and *pushed* H.264 over UDP to the ground station. The ESP32-S3 has no
// H.264 encoder - the camera peripheral produces JPEG - so the vehicle
// instead *serves* an MJPEG stream over HTTP and the ground station pulls it:
//
//     http://<vehicle ip>:<config.camera.stream_port>/stream
//
// The control messages are unchanged: START_CAMERA / STOP_CAMERA still start
// and stop the stream, and START_CAMERA's optional "width,height,framerate"
// still selects the format.
#pragma once

#include <Arduino.h>

namespace camera_service {

// Brings up the camera peripheral. Must be called once, before start(), and
// early in boot while PSRAM is still unfragmented. Returns false if the
// sensor could not be initialized.
bool init();

// (Re)start the MJPEG server with the requested format. Any running stream is
// reconfigured in place, so this is safe to call repeatedly (e.g. when the
// resolution changes).
void start(int width, int height, int framerate);

// Stop serving. Safe to call anytime.
void stop();

bool isStreaming();

// URL the ground station should open, e.g. "http://192.168.4.1/stream".
String streamUrl();

}  // namespace camera_service
