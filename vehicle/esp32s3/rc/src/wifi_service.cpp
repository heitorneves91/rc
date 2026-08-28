#include "wifi_service.h"

#include "configuration.h"
#include "logs.h"

namespace wifi_service {
namespace {

constexpr const char* kTag = "wifi_service";

IPAddress parseAddress(const String& text, IPAddress fallback) {
    IPAddress address;
    if (address.fromString(text)) {
        return address;
    }
    LOG_WARN(kTag, "invalid address %s, using %s", text.c_str(), fallback.toString().c_str());
    return fallback;
}

}  // namespace

bool startAccessPoint() {
    const IPAddress ap_ip = parseAddress(config.wifi.ip, IPAddress(192, 168, 4, 1));
    const IPAddress ap_gateway = parseAddress(config.wifi.gateway, ap_ip);
    const IPAddress ap_subnet = parseAddress(config.wifi.subnet, IPAddress(255, 255, 255, 0));

    WiFi.mode(WIFI_AP);
    if (!WiFi.softAPConfig(ap_ip, ap_gateway, ap_subnet)) {
        LOG_ERROR(kTag, "softAPConfig failed");
    }

    // An empty password means an open network; softAP() rejects anything
    // shorter than 8 characters.
    const char* password = config.wifi.password.length() > 0 ? config.wifi.password.c_str() : nullptr;
    if (!WiFi.softAP(config.wifi.ssid.c_str(), password, config.wifi.channel, /*hidden=*/0,
                     config.wifi.max_connections)) {
        LOG_ERROR(kTag, "failed to start access point");
        return false;
    }

    // Keeps the video stream and the command link smooth.
    WiFi.setSleep(false);

    LOG_INFO(kTag, "access point up: ssid=%s ip=%s", config.wifi.ssid.c_str(),
             WiFi.softAPIP().toString().c_str());
    return true;
}

IPAddress ip() { return WiFi.softAPIP(); }

}  // namespace wifi_service
