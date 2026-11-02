#include "camera_service.h"

#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <lwip/sockets.h>
#include <string.h>

#include "configuration.h"
#include "esp_camera.h"
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

// Guards start()/stop() against each other so two commands arriving back to
// back from the receive loop can't both create a task, mirroring the Pi
// service's `_lock`. The send loop itself takes no lock - see `dest_ipv4`.
SemaphoreHandle_t lock = nullptr;
bool camera_ready = false;

// Read by the send loop on every frame so stop() can unblock it.
volatile bool streaming = false;
volatile uint32_t min_frame_interval_ms = 40;

// Destination, as a raw network-order address and port. 32-bit loads are
// atomic on this core, so the send loop can pick up a new ground-station
// address mid-stream without a mutex on the hot path.
volatile uint32_t dest_ipv4 = 0;
volatile uint16_t dest_port = 0;

// Owned by the send task: set before it starts, cleared as the last thing it
// does. start()/stop() poll it under `lock` to decide whether a task exists,
// so it must be volatile - it is written by one task and read by another.
volatile bool sending = false;
int video_socket = -1;
uint16_t frame_id = 0;

// One datagram, reused for every chunk: WiFiUDP would copy the payload a byte
// at a time (see its write(const uint8_t*, size_t)), which is a poor trade for
// the ~500 packets/second this path emits, so the video socket is a plain
// lwIP one and each chunk is assembled here and handed to a single sendto().
uint8_t packet[kVideoHeaderBytes + kVideoChunkPayloadBytes];

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

void writeBE16(uint8_t* out, uint16_t value) {
    out[0] = static_cast<uint8_t>(value >> 8);
    out[1] = static_cast<uint8_t>(value);
}

void writeBE32(uint8_t* out, uint32_t value) {
    out[0] = static_cast<uint8_t>(value >> 24);
    out[1] = static_cast<uint8_t>(value >> 16);
    out[2] = static_cast<uint8_t>(value >> 8);
    out[3] = static_cast<uint8_t>(value);
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

// Resize, then re-assert the orientation. The flip is done by the sensor
// itself (a register bit), so it costs no cycles here or on the phone; it is
// re-applied after every resize in case the resolution tables touch it.
// The camera is mounted upside down, hence the vertical flip.
void configureSensor(int width, int height) {
    sensor_t* sensor = esp_camera_sensor_get();
    if (sensor == nullptr) {
        return;
    }
    sensor->set_framesize(sensor, frameSizeFor(width, height));
    sensor->set_vflip(sensor, config.camera.vflip ? 1 : 0);
    sensor->set_hmirror(sensor, config.camera.hmirror ? 1 : 0);
}

// Send one chunk, retrying once if lwIP is momentarily out of buffers - a
// burst of chunks can outrun the WiFi driver's tx queue. Returns false if the
// chunk was dropped.
bool sendChunk(size_t length, const sockaddr_in& to) {
    for (int attempt = 0; attempt < 2; ++attempt) {
        const int sent = sendto(video_socket, packet, length, 0,
                                reinterpret_cast<const sockaddr*>(&to), sizeof(to));
        if (sent == static_cast<int>(length)) {
            return true;
        }
        if (errno != ENOMEM && errno != EAGAIN && errno != EWOULDBLOCK) {
            return false;
        }
        vTaskDelay(pdMS_TO_TICKS(2));
    }
    return false;
}

// Split one JPEG across as many datagrams as it needs. A dropped chunk costs
// only its own frame: the receiver discards the incomplete frame and picks up
// the next one, which is why every frame is a self-contained JPEG.
void sendFrame(const camera_fb_t* fb) {
    const uint32_t ip = dest_ipv4;
    const uint16_t port = dest_port;
    if (ip == 0 || port == 0) {
        return;
    }

    sockaddr_in to = {};
    to.sin_family = AF_INET;
    to.sin_addr.s_addr = ip;
    to.sin_port = htons(port);

    const size_t chunk_count =
        (fb->len + kVideoChunkPayloadBytes - 1) / kVideoChunkPayloadBytes;
    if (chunk_count == 0 || chunk_count > 0xFFFF) {
        LOG_WARN(kTag, "frame of %u bytes does not fit the wire format, dropped",
                 static_cast<unsigned>(fb->len));
        return;
    }

    frame_id++;

    for (size_t index = 0; index < chunk_count; ++index) {
        const size_t offset = index * kVideoChunkPayloadBytes;
        const size_t payload = min(kVideoChunkPayloadBytes, fb->len - offset);

        packet[0] = 'J';
        packet[1] = 'F';
        packet[2] = kVideoProtocolVersion;
        packet[3] = 0;  // flags
        writeBE16(&packet[4], frame_id);
        writeBE16(&packet[6], static_cast<uint16_t>(index));
        writeBE16(&packet[8], static_cast<uint16_t>(chunk_count));
        writeBE16(&packet[10], 0);  // reserved
        writeBE32(&packet[12], static_cast<uint32_t>(fb->len));
        memcpy(&packet[kVideoHeaderBytes], fb->buf + offset, payload);

        if (!sendChunk(kVideoHeaderBytes + payload, to)) {
            // The rest of this frame is useless without it; the receiver will
            // discard the partial frame either way.
            LOG_DEBUG(kTag, "dropped frame %u at chunk %u/%u (errno %d)", frame_id,
                      static_cast<unsigned>(index), static_cast<unsigned>(chunk_count), errno);
            return;
        }
        // Hand the WiFi task a chance to drain the queue between chunks.
        taskYIELD();
    }
}

void sendLoop(void* /*arg*/) {
    LOG_INFO(kTag, "streaming to %s", streamTarget().c_str());
    uint32_t last_frame_ms = 0;

    while (streaming) {
        // Pace to the requested framerate instead of streaming flat out; the
        // WiFi link, not the sensor, is the bottleneck.
        const uint32_t since_last = millis() - last_frame_ms;
        if (since_last < min_frame_interval_ms) {
            vTaskDelay(pdMS_TO_TICKS(min_frame_interval_ms - since_last));
        }
        last_frame_ms = millis();

        camera_fb_t* fb = esp_camera_fb_get();
        if (!fb) {
            LOG_ERROR(kTag, "camera capture failed");
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        sendFrame(fb);
        esp_camera_fb_return(fb);
    }

    if (video_socket >= 0) {
        close(video_socket);
        video_socket = -1;
    }
    LOG_INFO(kTag, "stream stopped");
    sending = false;
    vTaskDelete(nullptr);
}

// Caller must hold `lock`.
bool openSocketLocked() {
    if (video_socket >= 0) {
        return true;
    }
    video_socket = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (video_socket < 0) {
        LOG_ERROR(kTag, "could not create video socket (errno %d)", errno);
        return false;
    }
    return true;
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

    configureSensor(config.camera.width, config.camera.height);
    LOG_INFO(kTag, "camera ready");
    return true;
}

void start(IPAddress destination, int width, int height, int framerate) {
    ensureLock();
    if (!camera_ready) {
        LOG_ERROR(kTag, "camera not initialized, not starting stream");
        return;
    }

    Lock guard;

    framerate = constrain(framerate, 1, 60);
    min_frame_interval_ms = 1000 / framerate;

    dest_ipv4 = static_cast<uint32_t>(destination);
    dest_port = static_cast<uint16_t>(config.camera.video_port);

    configureSensor(width, height);

    if (sending) {
        // Already running: the new destination and format above are picked up
        // on the next frame.
        LOG_INFO(kTag, "restreaming %dx%d @ %d fps -> %s", width, height, framerate,
                 streamTarget().c_str());
        return;
    }

    if (!openSocketLocked()) {
        return;
    }
    streaming = true;
    sending = true;
    // Priority below the receive (6), watchdog (5) and telemetry (4) tasks:
    // video is the one thing here that may be dropped without consequence.
    if (xTaskCreate(sendLoop, "cam-video", 4096, nullptr, /*priority=*/3, nullptr) != pdPASS) {
        LOG_ERROR(kTag, "could not start the video task");
        streaming = false;
        sending = false;
        close(video_socket);
        video_socket = -1;
        return;
    }

    LOG_INFO(kTag, "streaming %dx%d @ %d fps -> %s", width, height, framerate,
             streamTarget().c_str());
}

void stop() {
    ensureLock();
    Lock guard;
    if (!sending) {
        return;
    }
    LOG_INFO(kTag, "stopping stream");
    // The task notices on its next frame, then closes the socket and deletes
    // itself. Wait for it, so a START arriving right after this STOP does not
    // find a task that is still winding down.
    streaming = false;
    for (int waited_ms = 0; sending && waited_ms < 2000; waited_ms += 10) {
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    if (sending) {
        LOG_WARN(kTag, "video task did not stop in time");
    }
}

bool isStreaming() { return streaming; }

String streamTarget() {
    const uint32_t ip = dest_ipv4;
    if (ip == 0) {
        return "udp/" + String(config.camera.video_port) + " (no ground station yet)";
    }
    return "udp://" + IPAddress(ip).toString() + ":" + String(dest_port);
}

}  // namespace camera_service
