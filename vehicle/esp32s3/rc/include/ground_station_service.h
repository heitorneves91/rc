// Ground-station link service.
//
// Receives commands from the ground station over UDP, applies them to the
// movement service, and streams telemetry back. The command-timeout failsafe
// lives in `movement_service`: this service simply feeds it commands; if they
// stop arriving, the movement watchdog cuts the throttle on its own.
//
// Wire protocol (shared with the Android ground station - change both sides
// together). Every message is UTF-8 text of the form
// `<type>:<seq>,<field>,<field>` where `seq` is a monotonically increasing
// counter used to drop stale/reordered UDP packets:
//
//     move:<seq>,<throttle>,<steering>                  ground -> vehicle, drive command
//     conf:<seq>,<configuration>,<value>                ground -> vehicle, e.g. GROUND_HELLO
//     tele:<seq>,<throttle>,<steering>,<steering_trim>  vehicle -> ground, telemetry
#pragma once

#include <Arduino.h>
#include <WiFiUdp.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace ground_station_service {

enum class ConfigurationCommand {
    GroundHello,
    StartCamera,
    StopCamera,
    SteeringTrim,
    Unknown
};

struct MoveMessage {
    long seq = -1;
    int throttle = 0;
    int steering = 0;

    static bool parse(const char* body, MoveMessage& out);
};

struct ConfigureMessage {
    long seq = -1;
    ConfigurationCommand configuration = ConfigurationCommand::Unknown;
    // Empty when the ground station sent no value. Note the Kotlin client
    // serializes a missing value as the literal "null", which is normalized
    // away here.
    String value;

    static bool parse(const char* body, ConfigureMessage& out);
};

// Owns the UDP socket, the receive loop and the telemetry sender.
class GroundStationService {
   public:
    // Binds the socket and starts the receive and telemetry tasks. Unlike the
    // Python version this returns immediately instead of blocking the caller.
    bool start();
    void stop();

    void sendTelemetry(int throttle, int steering);

   private:
    void run();
    void handle(char* msg, IPAddress addr, uint16_t port);
    void handleMove(const MoveMessage& msg);
    void handleConf(const ConfigureMessage& msg, IPAddress addr);
    void handleStartCamera(const ConfigureMessage& msg, IPAddress addr);
    void handleSteeringTrim(const ConfigureMessage& msg);
    void telemetryLoop();
    void startTelemetry();

    static void receiveTaskEntry(void* arg);
    static void telemetryTaskEntry(void* arg);

    WiFiUDP socket_;
    bool socket_open_ = false;

    // Telemetry destination, learned from the last packet received (handles
    // reconnects).
    IPAddress ground_station_addr_;
    uint16_t ground_station_port_ = 0;
    bool ground_station_known_ = false;

    // Highest move seq seen so far; older packets are dropped as stale.
    long last_move_seq_ = -1;
    long telemetry_seq_ = -1;

    TaskHandle_t receive_task_ = nullptr;
    TaskHandle_t telemetry_task_ = nullptr;
    volatile bool stop_ = false;
};

// Application-wide singleton.
extern GroundStationService service;

void sendTelemetry(int throttle, int steering);

}  // namespace ground_station_service
