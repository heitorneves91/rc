#include "camera_service.h"

#include <WiFi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

#include "configuration.h"
#include "esp_camera.h"
#include "esp_http_server.h"
#include "logs.h"

namespace camera_service {
namespace {

constexpr const char* kTag = "camera_service";

// --- PIN CONFIGURATION FOR SEEED XIAO ESP32-S3 SENSE ---
#define PWDN_GPIO_NUM -1
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 10
#define SIOD_GPIO_NUM 40
#define SIOC_GPIO_NUM 39
#define Y9_GPIO_NUM 48
#define Y8_GPIO_NUM 11
#define Y7_GPIO_NUM 12
#define Y6_GPIO_NUM 14
#define Y5_GPIO_NUM 16
#define Y4_GPIO_NUM 18
#define Y3_GPIO_NUM 17
#define Y2_GPIO_NUM 15
#define VSYNC_GPIO_NUM 38
#define HREF_GPIO_NUM 47
#define PCLK_GPIO_NUM 13

// HTTP multipart stream separation boundaries.
#define PART_BOUNDARY "123456789000000000000987654321"
const char* kStreamContentType = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
const char* kStreamBoundary = "\r\n--" PART_BOUNDARY "\r\n";
const char* kStreamPart = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

// Guards `httpd` / `streaming` so START and STOP from the receive loop can't
// race, mirroring the Pi service's `_lock`.
SemaphoreHandle_t lock = nullptr;
httpd_handle_t httpd = nullptr;
bool camera_ready = false;

// Read by the stream handler on every frame so stop() can unblock it: the
// handler loops forever, and httpd_stop() waits for handlers to return.
volatile bool streaming = false;
volatile uint32_t min_frame_interval_ms = 40;

class Lock {
   public:
    Lock() { xSemaphoreTake(lock, portMAX_DELAY); }
    ~Lock() { xSemaphoreGive(lock); }
};

void ensureLock() {
    if (lock == nullptr) {
        lock = xSemaphoreCreateMutex();
    }
}

// Nearest sensor frame size at or below the requested dimensions. The ground
// station may ask for anything (its CameraStartParams allows up to 2592x1944);
// the sensor only supports a fixed ladder.
framesize_t frameSizeFor(int width, int height) {
    struct Entry {
        framesize_t size;
        int width;
        int height;
    };
    // Descending, so the first fit is the largest one that is small enough.
    static const Entry kSizes[] = {
        {FRAMESIZE_UXGA, 1600, 1200}, {FRAMESIZE_SXGA, 1280, 1024},
        {FRAMESIZE_HD, 1280, 720},    {FRAMESIZE_XGA, 1024, 768},
        {FRAMESIZE_SVGA, 800, 600},   {FRAMESIZE_VGA, 640, 480},
        {FRAMESIZE_HVGA, 480, 320},   {FRAMESIZE_QVGA, 320, 240},
    };
    for (const Entry& entry : kSizes) {
        if (width >= entry.width && height >= entry.height) {
            return entry.size;
        }
    }
    return FRAMESIZE_QVGA;
}

// Handler for the live MJPEG stream endpoint.
esp_err_t streamHandler(httpd_req_t* req) {
    esp_err_t res = httpd_resp_set_type(req, kStreamContentType);
    if (res != ESP_OK) {
        return res;
    }
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

    LOG_INFO(kTag, "stream client connected");
    uint32_t last_frame_ms = 0;

    while (streaming) {
        // Pace to the requested framerate instead of streaming flat out; the
        // WiFi link, not the sensor, is the bottleneck.
        const uint32_t now = millis();
        const uint32_t since_last = now - last_frame_ms;
        if (since_last < min_frame_interval_ms) {
            vTaskDelay(pdMS_TO_TICKS(min_frame_interval_ms - since_last));
        }
        last_frame_ms = millis();

        camera_fb_t* fb = esp_camera_fb_get();
        if (!fb) {
            LOG_ERROR(kTag, "camera capture failed");
            res = ESP_FAIL;
            break;
        }

        char part_buf[64];
        const size_t hlen =
            snprintf(part_buf, sizeof(part_buf), kStreamPart, static_cast<unsigned>(fb->len));
        res = httpd_resp_send_chunk(req, part_buf, hlen);
        if (res == ESP_OK) {
            res = httpd_resp_send_chunk(req, reinterpret_cast<const char*>(fb->buf), fb->len);
        }
        if (res == ESP_OK) {
            res = httpd_resp_send_chunk(req, kStreamBoundary, strlen(kStreamBoundary));
        }

        esp_camera_fb_return(fb);

        if (res != ESP_OK) {
            // Client went away, or the socket died.
            break;
        }
    }

    LOG_INFO(kTag, "stream client disconnected");
    return res;
}

// Minimal page so a browser can just open http://<vehicle ip>/
const char* kIndexHtml =
    "<!DOCTYPE html><html><head>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>RC Camera</title>"
    "<style>body{margin:0;background:#111}img{width:100%;height:auto;display:block}</style>"
    "</head><body><img src='/stream'></body></html>";

esp_err_t indexHandler(httpd_req_t* req) {
    httpd_resp_set_type(req, "text/html");
    return httpd_resp_send(req, kIndexHtml, HTTPD_RESP_USE_STRLEN);
}

// Caller must hold `lock`.
bool startServerLocked() {
    if (httpd != nullptr) {
        return true;
    }

    httpd_config_t httpd_config = HTTPD_DEFAULT_CONFIG();
    httpd_config.server_port = config.camera.stream_port;
    httpd_config.ctrl_port = config.camera.stream_port + 1000;
    // One session for the stream, one spare so the index page still loads.
    httpd_config.max_open_sockets = 3;

    httpd_uri_t index_uri = {
        .uri = "/", .method = HTTP_GET, .handler = indexHandler, .user_ctx = nullptr};
    httpd_uri_t stream_uri = {
        .uri = "/stream", .method = HTTP_GET, .handler = streamHandler, .user_ctx = nullptr};

    if (httpd_start(&httpd, &httpd_config) != ESP_OK) {
        LOG_ERROR(kTag, "failed to start HTTP server on port %d", config.camera.stream_port);
        httpd = nullptr;
        return false;
    }
    httpd_register_uri_handler(httpd, &index_uri);
    httpd_register_uri_handler(httpd, &stream_uri);
    return true;
}

// Caller must hold `lock`.
void stopServerLocked() {
    if (httpd == nullptr) {
        return;
    }
    LOG_INFO(kTag, "stopping stream");
    // Let any in-flight stream handler fall out of its loop before httpd_stop
    // blocks waiting for it.
    streaming = false;
    vTaskDelay(pdMS_TO_TICKS(min_frame_interval_ms + 50));
    httpd_stop(httpd);
    httpd = nullptr;
}

}  // namespace

bool init() {
    ensureLock();

    camera_config_t cam;
    cam.ledc_channel = LEDC_CHANNEL_0;
    cam.ledc_timer = LEDC_TIMER_0;
    cam.pin_d0 = Y2_GPIO_NUM;
    cam.pin_d1 = Y3_GPIO_NUM;
    cam.pin_d2 = Y4_GPIO_NUM;
    cam.pin_d3 = Y5_GPIO_NUM;
    cam.pin_d4 = Y6_GPIO_NUM;
    cam.pin_d5 = Y7_GPIO_NUM;
    cam.pin_d6 = Y8_GPIO_NUM;
    cam.pin_d7 = Y9_GPIO_NUM;
    cam.pin_xclk = XCLK_GPIO_NUM;
    cam.pin_pclk = PCLK_GPIO_NUM;
    cam.pin_vsync = VSYNC_GPIO_NUM;
    cam.pin_href = HREF_GPIO_NUM;
    cam.pin_sccb_sda = SIOD_GPIO_NUM;
    cam.pin_sccb_scl = SIOC_GPIO_NUM;
    cam.pin_pwdn = PWDN_GPIO_NUM;
    cam.pin_reset = RESET_GPIO_NUM;
    cam.xclk_freq_hz = 20000000;
    cam.pixel_format = PIXFORMAT_JPEG;  // Compressed format for network streaming
    cam.grab_mode = CAMERA_GRAB_LATEST;
    cam.fb_location = CAMERA_FB_IN_PSRAM;
    cam.jpeg_quality = config.camera.jpeg_quality;
    cam.fb_count = 2;  // Buffered frames in active PSRAM
    // Allocate for the largest format the sensor offers; start() then scales
    // down. Growing the frame size after init would need a bigger buffer than
    // was reserved.
    cam.frame_size = FRAMESIZE_UXGA;

    const esp_err_t err = esp_camera_init(&cam);
    if (err != ESP_OK) {
        LOG_ERROR(kTag, "camera init failed with error 0x%x", err);
        camera_ready = false;
        return false;
    }

    camera_ready = true;

    sensor_t* sensor = esp_camera_sensor_get();
    if (sensor != nullptr) {
        sensor->set_framesize(sensor, frameSizeFor(config.camera.width, config.camera.height));
    }
    LOG_INFO(kTag, "camera ready");
    return true;
}

void start(int width, int height, int framerate) {
    ensureLock();
    if (!camera_ready) {
        LOG_ERROR(kTag, "camera not initialized, not starting stream");
        return;
    }

    Lock guard;

    framerate = constrain(framerate, 1, 60);
    min_frame_interval_ms = 1000 / framerate;

    sensor_t* sensor = esp_camera_sensor_get();
    if (sensor != nullptr) {
        sensor->set_framesize(sensor, frameSizeFor(width, height));
    }

    if (!startServerLocked()) {
        return;
    }
    streaming = true;

    LOG_INFO(kTag, "streaming %dx%d @ %d fps -> %s", width, height, framerate,
             streamUrl().c_str());
}

void stop() {
    ensureLock();
    Lock guard;
    stopServerLocked();
}

bool isStreaming() { return streaming; }

String streamUrl() {
    String url = "http://" + WiFi.softAPIP().toString();
    if (config.camera.stream_port != 80) {
        url += ":" + String(config.camera.stream_port);
    }
    return url + "/stream";
}

}  // namespace camera_service
