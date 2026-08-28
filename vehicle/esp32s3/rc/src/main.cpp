#include <Arduino.h>
#include <WiFi.h>
#include "esp_camera.h"
#include "esp_http_server.h"

// --- ACCESS POINT CREDENTIALS (the phone joins this network) ---
const char* ap_ssid     = "rc-car";
const char* ap_password = "rccar1234";   // must be >= 8 chars, or use "" for an open AP
const int   ap_channel  = 1;
const int   ap_max_conn = 2;

// Fixed AP addressing, so the stream URL never changes
IPAddress ap_ip(192, 168, 4, 1);
IPAddress ap_gateway(192, 168, 4, 1);
IPAddress ap_subnet(255, 255, 255, 0);

// --- PIN CONFIGURATION FOR SEEED XIAO ESP32-S3 SENSE ---
#define PWDN_GPIO_NUM     -1
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM     10
#define SIOD_GPIO_NUM     40
#define SIOC_GPIO_NUM     39
#define Y9_GPIO_NUM       48
#define Y8_GPIO_NUM       11
#define Y7_GPIO_NUM       12
#define Y6_GPIO_NUM       14
#define Y5_GPIO_NUM       16
#define Y4_GPIO_NUM       18
#define Y3_GPIO_NUM       17
#define Y2_GPIO_NUM       15
#define VSYNC_GPIO_NUM    38
#define HREF_GPIO_NUM     47
#define PCLK_GPIO_NUM     13

// HTTP Stream separation boundaries
#define PART_BOUNDARY "123456789000000000000987654321"
static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* _STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %break_len%\r\n\r\n";

httpd_handle_t stream_httpd = NULL;

// Handler for the live MJPEG stream endpoint
static esp_err_t stream_handler(httpd_req_t *req) {
    camera_fb_t * fb = NULL;
    esp_err_t res = ESP_OK;
    size_t _jpg_buf_len = 0;
    uint8_t * _jpg_buf = NULL;
    char * part_buf[64];

    res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
    if(res != ESP_OK) return res;

    while(true) {
        fb = esp_camera_fb_get();
        if (!fb) {
            Serial.println("Camera capture failed");
            res = ESP_FAIL;
        } else {
            _jpg_buf_len = fb->len;
            _jpg_buf = fb->buf;
        }
        if(res == ESP_OK){
            size_t hlen = snprintf((char *)part_buf, 64, _STREAM_PART, _jpg_buf_len);
            res = httpd_resp_send_chunk(req, (const char *)part_buf, hlen);
        }
        if(res == ESP_OK){
            res = httpd_resp_send_chunk(req, (const char *)_jpg_buf, _jpg_buf_len);
        }
        if(res == ESP_OK){
            res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
        }
        if(fb){
            esp_camera_fb_return(fb);
            fb = NULL;
            _jpg_buf = NULL;
        } else if(res != ESP_OK){
            break;
        }
    }
    return res;
}

// Minimal page so the phone can just open http://192.168.4.1/
static const char* _INDEX_HTML =
    "<!DOCTYPE html><html><head>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>RC Camera</title>"
    "<style>body{margin:0;background:#111}img{width:100%;height:auto;display:block}</style>"
    "</head><body><img src='/stream'></body></html>";

static esp_err_t index_handler(httpd_req_t *req) {
    httpd_resp_set_type(req, "text/html");
    return httpd_resp_send(req, _INDEX_HTML, HTTPD_RESP_USE_STRLEN);
}

void startCameraServer() {
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 80;

    httpd_uri_t index_uri = {
        .uri       = "/",
        .method    = HTTP_GET,
        .handler   = index_handler,
        .user_ctx  = NULL
    };

    httpd_uri_t stream_uri = {
        .uri       = "/stream",
        .method    = HTTP_GET,
        .handler   = stream_handler,
        .user_ctx  = NULL
    };

    if (httpd_start(&stream_httpd, &config) == ESP_OK) {
        httpd_register_uri_handler(stream_httpd, &index_uri);
        httpd_register_uri_handler(stream_httpd, &stream_uri);
        Serial.println("HTTP Server started successfully.");
    }
}

void setup() {
    Serial.begin(115200);
    delay(3000);

    // Camera Configuration Setup
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer = LEDC_TIMER_0;
    config.pin_d0 = Y2_GPIO_NUM;
    config.pin_d1 = Y3_GPIO_NUM;
    config.pin_d2 = Y4_GPIO_NUM;
    config.pin_d3 = Y5_GPIO_NUM;
    config.pin_d4 = Y6_GPIO_NUM;
    config.pin_d5 = Y7_GPIO_NUM;
    config.pin_d6 = Y8_GPIO_NUM;
    config.pin_d7 = Y9_GPIO_NUM;
    config.pin_xclk = XCLK_GPIO_NUM;
    config.pin_pclk = PCLK_GPIO_NUM;
    config.pin_vsync = VSYNC_GPIO_NUM;
    config.pin_href = HREF_GPIO_NUM;
    config.pin_sccb_sda = SIOD_GPIO_NUM;
    config.pin_sccb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn = PWDN_GPIO_NUM;
    config.pin_reset = RESET_GPIO_NUM;
    config.xclk_freq_hz = 20000000;
    config.frame_size = FRAMESIZE_VGA;    // Resolution: 640x480
    config.pixel_format = PIXFORMAT_JPEG; // Compressed format for network streaming
    config.grab_mode = CAMERA_GRAB_LATEST; 
    config.fb_location = CAMERA_FB_IN_PSRAM; 
    config.jpeg_quality = 12;             // 10-12 provides a clean balance of speed/quality
    config.fb_count = 2;                  // Buffered frames in active PSRAM

    // Initialize Camera
    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("Camera init failed with error 0x%x\n", err);
        return;
    }

    // Start the ESP as its own access point; the phone connects directly to it
    WiFi.mode(WIFI_AP);
    if (!WiFi.softAPConfig(ap_ip, ap_gateway, ap_subnet)) {
        Serial.println("softAPConfig failed");
    }
    if (!WiFi.softAP(ap_ssid, ap_password, ap_channel, /*hidden=*/0, ap_max_conn)) {
        Serial.println("Failed to start access point");
        return;
    }
    WiFi.setSleep(false);   // keeps the stream smooth

    Serial.printf("\nAccess Point up.\n  SSID: %s\n  Password: %s\n", ap_ssid, ap_password);
    Serial.print("Join that network, then open: http://");
    Serial.print(WiFi.softAPIP());
    Serial.println("/");

    startCameraServer();
}

void loop() {
    delay(1); // Yield execution to system threads
}
