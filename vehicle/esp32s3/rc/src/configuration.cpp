#include "configuration.h"

#include <Preferences.h>

#include "logs.h"

namespace {

// NVS namespace and keys. NVS keys are limited to 15 characters, hence the
// abbreviated names; they are an implementation detail of this file.
constexpr const char* kTag = "configuration";
constexpr const char* kNamespace = "rc";

Preferences prefs;

}  // namespace

Configuration config;

void Configuration::load() {
    // Read-write on purpose, even though load() only reads: nvs_open() creates
    // the namespace only in read-write mode, so a read-only open on a device
    // that has never called save() fails with NOT_FOUND and logs an NVS error
    // on every boot. Opening it this way creates an empty namespace instead,
    // and every getter below still falls back to the compiled-in default.
    if (!prefs.begin(kNamespace, /*readOnly=*/false)) {
        LOG_WARN(kTag, "NVS unavailable - using compiled-in defaults");
        return;
    }

    movement.rl_motor_gpio = prefs.getInt("mv_motor_gpio", movement.rl_motor_gpio);
    movement.steering_gpio = prefs.getInt("mv_steer_gpio", movement.steering_gpio);
    movement.arm_delay_s = prefs.getFloat("mv_arm_delay", movement.arm_delay_s);
    movement.command_timeout_s = prefs.getFloat("mv_cmd_tmout", movement.command_timeout_s);
    movement.steering_trim_us = prefs.getInt("mv_steer_trim", movement.steering_trim_us);

    camera.width = prefs.getInt("cam_width", camera.width);
    camera.height = prefs.getInt("cam_height", camera.height);
    camera.framerate = prefs.getInt("cam_fps", camera.framerate);
    camera.video_port = prefs.getInt("cam_port", camera.video_port);
    camera.jpeg_quality = prefs.getInt("cam_quality", camera.jpeg_quality);
    camera.vflip = prefs.getBool("cam_vflip", camera.vflip);
    camera.hmirror = prefs.getBool("cam_hmirror", camera.hmirror);

    ground_station.listen_port = prefs.getInt("gs_port", ground_station.listen_port);
    ground_station.telemetry_interval_s =
        prefs.getFloat("gs_tele_int", ground_station.telemetry_interval_s);

    wifi.ssid = prefs.getString("wifi_ssid", wifi.ssid);
    wifi.password = prefs.getString("wifi_pass", wifi.password);
    wifi.channel = prefs.getInt("wifi_chan", wifi.channel);
    wifi.max_connections = prefs.getInt("wifi_maxconn", wifi.max_connections);
    wifi.ip = prefs.getString("wifi_ip", wifi.ip);
    wifi.gateway = prefs.getString("wifi_gw", wifi.gateway);
    wifi.subnet = prefs.getString("wifi_subnet", wifi.subnet);

    log_level = prefs.getString("log_level", log_level);

    prefs.end();
}

void Configuration::save() {
    if (!prefs.begin(kNamespace, /*readOnly=*/false)) {
        return;
    }

    prefs.putInt("mv_motor_gpio", movement.rl_motor_gpio);
    prefs.putInt("mv_steer_gpio", movement.steering_gpio);
    prefs.putFloat("mv_arm_delay", movement.arm_delay_s);
    prefs.putFloat("mv_cmd_tmout", movement.command_timeout_s);
    prefs.putInt("mv_steer_trim", movement.steering_trim_us);

    prefs.putInt("cam_width", camera.width);
    prefs.putInt("cam_height", camera.height);
    prefs.putInt("cam_fps", camera.framerate);
    prefs.putInt("cam_port", camera.video_port);
    prefs.putInt("cam_quality", camera.jpeg_quality);
    prefs.putBool("cam_vflip", camera.vflip);
    prefs.putBool("cam_hmirror", camera.hmirror);

    prefs.putInt("gs_port", ground_station.listen_port);
    prefs.putFloat("gs_tele_int", ground_station.telemetry_interval_s);

    prefs.putString("wifi_ssid", wifi.ssid);
    prefs.putString("wifi_pass", wifi.password);
    prefs.putInt("wifi_chan", wifi.channel);
    prefs.putInt("wifi_maxconn", wifi.max_connections);
    prefs.putString("wifi_ip", wifi.ip);
    prefs.putString("wifi_gw", wifi.gateway);
    prefs.putString("wifi_subnet", wifi.subnet);

    prefs.putString("log_level", log_level);

    prefs.end();
}
