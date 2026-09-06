// Camera service: pushes live video from the on-board OV2640/OV5640 to the
// ground station over UDP.
//
// TRANSPORT vs. the Raspberry Pi build: the Pi spawned `rpicam-vid` and pushed
// H.264 (MIMETYPE_VIDEO_AVC) over UDP. The ESP32-S3 has no H.264 encoder - the
// camera peripheral produces JPEG - so the payload is now MJPEG: one
// independently decodable JPEG per frame. The transport is unchanged: the
// vehicle still pushes datagrams to the ground station's video port, so the
// ground station needs no reachable server and no connection setup.
//
// A JPEG frame does not fit in one datagram, so each frame is split into
// chunks that fit inside the WiFi MTU (see kVideoChunkPayloadBytes) and
// carries a 16-byte header the receiver reassembles by frame id. Both sides
// must agree on this layout - `../ground-station-android`'s CameraService.kt
// is the other half.
//
//   offset size field
//   0      2    magic 'J','F'
//   2      1    version (kVideoProtocolVersion)
//   3      1    flags, reserved, 0
//   4      2    frame id, wraps at 2^16
//   6      2    chunk index within the frame
//   8      2    chunk count for the frame
//   10     2    reserved, 0
//   12     4    total JPEG size in bytes
//   16     ..   payload
//
// All multi-byte fields are big-endian. Chunk N of a frame carries bytes
// [N * kVideoChunkPayloadBytes, ...) of the JPEG, so a receiver can place a
// chunk without having seen any other.
//
// The control messages are unchanged: START_CAMERA / STOP_CAMERA still start
// and stop the stream, and START_CAMERA's optional "width,height,framerate"
// still selects the format.
#pragma once

#include <Arduino.h>
#include <IPAddress.h>

namespace camera_service {

// Wire constants, shared with the ground station.
constexpr uint8_t kVideoProtocolVersion = 1;
constexpr size_t kVideoHeaderBytes = 16;
// Header + payload must stay under the 1500-byte WiFi MTU, or every chunk is
// IP-fragmented and one lost fragment costs the whole chunk.
constexpr size_t kVideoChunkPayloadBytes = 1400;

// Brings up the camera peripheral. Must be called once, before start(), and
// early in boot while PSRAM is still unfragmented. Returns false if the
// sensor could not be initialized.
bool init();

// Start pushing frames to `destination` on config.camera.video_port with the
// requested format. Safe to call repeatedly: a running stream is retargeted
// and reconfigured in place (e.g. when the resolution changes, or when the
// ground station reconnects from a new address).
void start(IPAddress destination, int width, int height, int framerate);

// Stop pushing. Safe to call anytime, including when already stopped.
void stop();

bool isStreaming();

// Human-readable description of where frames are going, for logs -
// e.g. "udp://192.168.4.2:9999", or "udp/9999 (no ground station yet)".
String streamTarget();

}  // namespace camera_service
