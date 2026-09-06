#include "movement_service.h"

#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <soc/soc_caps.h>

#include "configuration.h"
#include "logs.h"

namespace movement_service {
namespace {

constexpr const char* kTag = "movement_service";

// Standard hobby-servo/ESC signalling: a 1000-2000 us pulse every 20 ms.
constexpr int kServoFreqHz = 50;
constexpr int kServoPeriodUs = 1000000 / kServoFreqHz;
// 14 bits is the ESP32-S3's ceiling (SOC_LEDC_TIMER_BIT_WIDE_NUM); asking for
// 16 makes ledcSetup() fail outright. At 50 Hz that is still ~1.2 us per step
// over the 20 ms period, far finer than any ESC or servo resolves.
constexpr int kServoResolutionBits = 14;
constexpr uint32_t kServoMaxDuty = (1u << kServoResolutionBits) - 1;
constexpr int kMinPulseUs = 1000;
constexpr int kMaxPulseUs = 2000;

// LEDC timer 0 / channel 0 belong to the camera's XCLK (see camera_service),
// so the servos take channels 2 and 3, which share LEDC timer 1.
constexpr int kThrottleChannel = 2;
constexpr int kSteeringChannel = 3;

// ledcSetup()/ledcAttachChannel() only report an over-wide resolution or an
// out-of-range channel at boot, as a log line on a return value that is easy
// to lose. Assert the chip's limits here instead, so a bad constant is a build
// error on whichever core is compiling. (The capability macro was renamed
// between IDF 4.x and 5.x.)
#if defined(SOC_LEDC_TIMER_BIT_WIDTH)
static_assert(kServoResolutionBits <= SOC_LEDC_TIMER_BIT_WIDTH,
              "servo PWM resolution exceeds this chip's LEDC timer width");
#elif defined(SOC_LEDC_TIMER_BIT_WIDE_NUM)
static_assert(kServoResolutionBits <= SOC_LEDC_TIMER_BIT_WIDE_NUM,
              "servo PWM resolution exceeds this chip's LEDC timer width");
#endif
static_assert(kThrottleChannel < SOC_LEDC_CHANNEL_NUM && kSteeringChannel < SOC_LEDC_CHANNEL_NUM,
              "servo LEDC channel out of range for this chip");

// Same mapping the Raspberry Pi build used:
//   throttle -> 1000 + 10 * throttle us   (0..100 => 1000..2000 us)
//   steering -> 1500 +  5 * steering us   (-100..100 => 1000..2000 us)
constexpr int kThrottleBaseUs = 1000;
constexpr int kThrottleScaleUs = 10;
constexpr int kSteeringCenterUs = 1500;
constexpr int kSteeringScaleUs = 5;

bool initialized = false;

// Watchdog and current-state, guarded by `state_mutex`.
SemaphoreHandle_t state_mutex = nullptr;
uint32_t last_command_ms = 0;
bool failsafe_active = false;
// Last values written to the actuators, reported as telemetry.
int current_throttle = 0;
int current_steering = 0;

TaskHandle_t watchdog_task = nullptr;
volatile bool watchdog_stop = false;

// Scoped lock over `state_mutex`. Never nest these - the mutex is not
// recursive, mirroring the plain `threading.Lock` this replaces.
class StateLock {
   public:
    StateLock() { xSemaphoreTake(state_mutex, portMAX_DELAY); }
    ~StateLock() { xSemaphoreGive(state_mutex); }
};

void ensureMutex() {
    if (state_mutex == nullptr) {
        state_mutex = xSemaphoreCreateMutex();
    }
}

bool attachChannel(int pin, int channel) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    return ledcAttachChannel(pin, kServoFreqHz, kServoResolutionBits, channel);
#else
    if (ledcSetup(channel, kServoFreqHz, kServoResolutionBits) == 0) {
        return false;
    }
    ledcAttachPin(pin, channel);
    return true;
#endif
}

void writePulseUs(int channel, int pulse_us) {
    // The Pi build trusted the caller's range; clamping here means a bad or
    // hostile packet can never ask the ESC for an out-of-band pulse.
    pulse_us = constrain(pulse_us, kMinPulseUs, kMaxPulseUs);
    const uint32_t duty =
        static_cast<uint32_t>((static_cast<uint64_t>(pulse_us) * kServoMaxDuty) / kServoPeriodUs);
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcWriteChannel(channel, duty);
#else
    ledcWrite(channel, duty);
#endif
}

void applyThrottle(int throttle) {
    writePulseUs(kThrottleChannel, kThrottleBaseUs + kThrottleScaleUs * throttle);
    StateLock lock;
    current_throttle = throttle;
}

void applySteering(int steering) {
    writePulseUs(kSteeringChannel, kSteeringCenterUs + kSteeringScaleUs * steering);
    StateLock lock;
    current_steering = steering;
}

// Record that a live command was just received, clearing any failsafe.
void feedWatchdog() {
    StateLock lock;
    last_command_ms = millis();
    failsafe_active = false;
}

void triggerFailsafe() {
    // Cut throttle directly (not via setThrottle) so the watchdog timer is not
    // fed - the vehicle stays stopped until a real command arrives. Steering
    // is left where it is.
    {
        StateLock lock;
        failsafe_active = true;
    }
    LOG_WARN(kTag, "command timeout - failsafe, cutting throttle");
    applyThrottle(0);
}

void watchdogLoop(void* /*arg*/) {
    while (!watchdog_stop) {
        const uint32_t timeout_ms =
            static_cast<uint32_t>(config.movement.command_timeout_s * 1000.0f);
        // Poll several times per timeout window so the cut is reasonably prompt.
        const uint32_t interval_ms = max<uint32_t>(20, timeout_ms / 5);
        vTaskDelay(pdMS_TO_TICKS(interval_ms));
        if (watchdog_stop) {
            break;
        }

        uint32_t elapsed_ms;
        bool already_failed;
        {
            StateLock lock;
            elapsed_ms = millis() - last_command_ms;
            already_failed = failsafe_active;
        }

        if (elapsed_ms >= timeout_ms && !already_failed) {
            triggerFailsafe();
        }
    }

    watchdog_task = nullptr;
    vTaskDelete(nullptr);
}

void startWatchdog() {
    if (watchdog_task != nullptr) {
        return;
    }
    watchdog_stop = false;
    xTaskCreate(watchdogLoop, "movement-watchdog", 3072, nullptr, /*priority=*/5,
                &watchdog_task);
}

}  // namespace

void setThrottle(int throttle, bool force) {
    if (!initialized && !force) {
        LOG_WARN(kTag, "not yet initialized");
        return;
    }
    feedWatchdog();
    applyThrottle(throttle);
}

void setSteering(int steering, bool force) {
    if (!initialized && !force) {
        LOG_WARN(kTag, "not yet initialized");
        return;
    }
    feedWatchdog();
    applySteering(steering);
}

void getState(int& throttle, int& steering) {
    ensureMutex();
    StateLock lock;
    throttle = current_throttle;
    steering = current_steering;
}

bool failsafeActive() {
    ensureMutex();
    StateLock lock;
    return failsafe_active;
}

bool init() {
    initialized = false;
    ensureMutex();

    if (!attachChannel(config.movement.rl_motor_gpio, kThrottleChannel) ||
        !attachChannel(config.movement.steering_gpio, kSteeringChannel)) {
        LOG_ERROR(kTag, "failed to set up LEDC channels for the servo outputs");
        return false;
    }

    LOG_INFO(kTag, "minimal signal before energizing the ESC (gpio %d throttle, %d steering)",
             config.movement.rl_motor_gpio, config.movement.steering_gpio);
    setThrottle(0, /*force=*/true);
    setSteering(0, /*force=*/true);

    vTaskDelay(pdMS_TO_TICKS(static_cast<uint32_t>(config.movement.arm_delay_s * 1000.0f)));

    initialized = true;

    LOG_INFO(kTag, "starting command-timeout watchdog (%.2fs)", config.movement.command_timeout_s);
    startWatchdog();
    LOG_INFO(kTag, "done");
    return true;
}

void shutdown() {
    watchdog_stop = true;
    // Give the watchdog a moment to notice and delete itself.
    vTaskDelay(pdMS_TO_TICKS(50));
    initialized = false;
    applyThrottle(0);
}

}  // namespace movement_service
