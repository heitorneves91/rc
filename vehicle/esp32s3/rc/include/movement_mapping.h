// Pure actuator mappings, shared by the firmware and host-side checks.
#pragma once

namespace movement_mapping {
constexpr int clamp(int value, int low, int high) {
    return value < low ? low : (value > high ? high : value);
}

// Bidirectional PWM ESC: reverse / neutral / forward = 1000 / 1500 / 2000 us.
constexpr int throttlePulseUs(int throttle) {
    return 1500 + 5 * clamp(throttle, -100, 100);
}

// Reversed linkage; 100% retains the previous 4.375 us per input unit.
constexpr int steeringPulseUs(int steering, int trim_us, int limit_percent) {
    return clamp(1500 + clamp(trim_us, -500, 500)
                 - clamp(steering, -100, 100) * 35 * clamp(limit_percent, 1, 100) / 800,
                 800, 2200);
}
}  // namespace movement_mapping
