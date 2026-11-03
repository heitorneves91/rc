#include "ground_station_service.h"

#include <string.h>

#include "camera_service.h"
#include "configuration.h"
#include "logs.h"
#include "movement_service.h"

namespace ground_station_service {
namespace {

constexpr const char* kTag = "ground_station_service";
constexpr size_t kMaxPacket = 1024;

ConfigurationCommand parseConfiguration(const char* name) {
    if (strcmp(name, "GROUND_HELLO") == 0) return ConfigurationCommand::GroundHello;
    if (strcmp(name, "START_CAMERA") == 0) return ConfigurationCommand::StartCamera;
    if (strcmp(name, "STOP_CAMERA") == 0) return ConfigurationCommand::StopCamera;
    if (strcmp(name, "STEERING_TRIM") == 0) return ConfigurationCommand::SteeringTrim;
    return ConfigurationCommand::Unknown;
}

}  // namespace

GroundStationService service;

bool MoveMessage::parse(const char* body, MoveMessage& out) {
    return sscanf(body, "%ld,%d,%d", &out.seq, &out.throttle, &out.steering) == 3;
}

bool ConfigureMessage::parse(const char* body, ConfigureMessage& out) {
    const char* first = strchr(body, ',');
    if (first == nullptr) {
        return false;
    }
    out.seq = strtol(body, nullptr, 10);

    const char* name_start = first + 1;
    const char* second = strchr(name_start, ',');

    char name[32];
    const size_t name_len = second != nullptr ? static_cast<size_t>(second - name_start)
                                              : strlen(name_start);
    if (name_len >= sizeof(name)) {
        return false;
    }
    memcpy(name, name_start, name_len);
    name[name_len] = '\0';
    out.configuration = parseConfiguration(name);

    // The value itself may contain commas (e.g. START_CAMERA's
    // "width,height,framerate"), so keep everything after the name. The Kotlin
    // client interpolates a missing value as "null"; treat that as absent.
    out.value = second != nullptr ? String(second + 1) : String();
    if (out.value == "null") {
        out.value = "";
    }
    return true;
}

bool GroundStationService::start() {
    stop_ = false;

    if (!socket_.begin(config.ground_station.listen_port)) {
        LOG_ERROR(kTag, "failed to bind udp/%d", config.ground_station.listen_port);
        return false;
    }
    socket_open_ = true;
    LOG_INFO(kTag, "listening on udp/%d", config.ground_station.listen_port);

    startTelemetry();
    xTaskCreate(receiveTaskEntry, "gs-receive", 4096, this, /*priority=*/6, &receive_task_);
    return true;
}

void GroundStationService::stop() {
    stop_ = true;
    vTaskDelay(pdMS_TO_TICKS(100));
    if (socket_open_) {
        socket_.stop();
        socket_open_ = false;
    }
}

void GroundStationService::receiveTaskEntry(void* arg) {
    static_cast<GroundStationService*>(arg)->run();
}

void GroundStationService::telemetryTaskEntry(void* arg) {
    static_cast<GroundStationService*>(arg)->telemetryLoop();
}

void GroundStationService::run() {
    char buffer[kMaxPacket];

    while (!stop_) {
        const int size = socket_.parsePacket();
        if (size <= 0) {
            // WiFiUDP has no blocking receive; poll fast enough not to add
            // latency to a ~25 Hz command stream.
            vTaskDelay(pdMS_TO_TICKS(2));
            continue;
        }

        const int read = socket_.read(buffer, sizeof(buffer) - 1);
        if (read <= 0) {
            continue;
        }
        buffer[read] = '\0';

        // Trim trailing whitespace/newlines, matching the Python .strip().
        int end = read;
        while (end > 0 && isspace(static_cast<unsigned char>(buffer[end - 1]))) {
            buffer[--end] = '\0';
        }

        handle(buffer, socket_.remoteIP(), socket_.remotePort());
    }

    receive_task_ = nullptr;
    vTaskDelete(nullptr);
}

void GroundStationService::handle(char* msg, IPAddress addr, uint16_t port) {
    LOG_DEBUG(kTag, "%s", msg);

    ground_station_addr_ = addr;
    ground_station_port_ = port;
    ground_station_known_ = true;

    if (strncmp(msg, "move:", 5) == 0) {
        MoveMessage move;
        if (!MoveMessage::parse(msg + 5, move)) {
            LOG_WARN(kTag, "bad message: %s", msg);
            return;
        }
        handleMove(move);
    } else if (strncmp(msg, "conf:", 5) == 0) {
        ConfigureMessage conf;
        if (!ConfigureMessage::parse(msg + 5, conf)) {
            LOG_WARN(kTag, "bad message: %s", msg);
            return;
        }
        handleConf(conf, addr);
    } else {
        LOG_WARN(kTag, "unknown message: %s", msg);
    }
}

void GroundStationService::handleMove(const MoveMessage& msg) {
    // UDP can deliver out of order; ignore anything not newer than the last.
    if (msg.seq <= last_move_seq_) {
        return;
    }
    last_move_seq_ = msg.seq;
    movement_service::setThrottle(msg.throttle);
    movement_service::setSteering(msg.steering);
}

void GroundStationService::handleConf(const ConfigureMessage& msg, IPAddress addr) {
    switch (msg.configuration) {
        case ConfigurationCommand::GroundHello:
            LOG_INFO(kTag, "ground station hello from %s", addr.toString().c_str());
            // The client restarts its sequence counter at -1 when it reopens
            // its socket, so a reconnect must reset ours too - otherwise every
            // command from the new session looks stale and is dropped.
            last_move_seq_ = -1;
            if (telemetry_task_ != nullptr) {
                xTaskNotifyGive(telemetry_task_);
            }
            break;
        case ConfigurationCommand::StartCamera:
            // Video is pushed, so the camera needs somewhere to push it: the
            // address this command came from, same as telemetry.
            handleStartCamera(msg, addr);
            break;
        case ConfigurationCommand::StopCamera:
            camera_service::stop();
            break;
        case ConfigurationCommand::SteeringTrim:
            handleSteeringTrim(msg);
            break;
        case ConfigurationCommand::Unknown:
            LOG_WARN(kTag, "unknown configuration command");
            break;
    }
}

void GroundStationService::handleStartCamera(const ConfigureMessage& msg, IPAddress addr) {
    // Optional "width,height,framerate". Absent -> defaults. The client sends
    // either all three or none; anything else is rejected and the camera is
    // not started.
    int width = config.camera.width;
    int height = config.camera.height;
    int framerate = config.camera.framerate;

    if (msg.value.length() > 0) {
        if (sscanf(msg.value.c_str(), "%d,%d,%d", &width, &height, &framerate) != 3) {
            LOG_WARN(kTag, "bad camera params '%s', not starting", msg.value.c_str());
            return;
        }
    }

    camera_service::start(addr, width, height, framerate);
}

void GroundStationService::handleSteeringTrim(const ConfigureMessage& msg) {
    int trim_us = 0;
    if (msg.value.length() == 0 || sscanf(msg.value.c_str(), "%d", &trim_us) != 1) {
        LOG_WARN(kTag, "bad steering trim '%s', ignoring", msg.value.c_str());
        return;
    }

    movement_service::setSteeringTrimUs(trim_us);
    if (telemetry_task_ != nullptr) {
        xTaskNotifyGive(telemetry_task_);
    }
}

void GroundStationService::startTelemetry() {
    if (telemetry_task_ != nullptr) {
        return;
    }
    xTaskCreate(telemetryTaskEntry, "gs-telemetry", 3072, this, /*priority=*/4, &telemetry_task_);
}

void GroundStationService::telemetryLoop() {
    // Periodically report the vehicle's current state - but only once a ground
    // station has announced itself.
    while (!stop_) {
        ulTaskNotifyTake(
            pdTRUE,
            pdMS_TO_TICKS(
                static_cast<uint32_t>(config.ground_station.telemetry_interval_s * 1000.0f)));
        if (stop_) {
            break;
        }
        if (!ground_station_known_) {
            continue;
        }
        int throttle = 0;
        int steering = 0;
        movement_service::getState(throttle, steering);
        sendTelemetry(throttle, steering);
    }

    telemetry_task_ = nullptr;
    vTaskDelete(nullptr);
}

void GroundStationService::sendTelemetry(int throttle, int steering) {
    if (!socket_open_ || !ground_station_known_) {
        return;
    }
    telemetry_seq_++;

    char msg[64];
    const int len = snprintf(msg, sizeof(msg), "tele:%ld,%d,%d,%d", telemetry_seq_, throttle,
                             steering, config.movement.steering_trim_us);

    socket_.beginPacket(ground_station_addr_, ground_station_port_);
    socket_.write(reinterpret_cast<const uint8_t*>(msg), len);
    socket_.endPacket();
}

void sendTelemetry(int throttle, int steering) { service.sendTelemetry(throttle, steering); }

}  // namespace ground_station_service
