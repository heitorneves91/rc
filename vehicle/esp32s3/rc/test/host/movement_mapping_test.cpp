#include <cassert>
#include <climits>
#include "movement_mapping.h"

int main() {
    using namespace movement_mapping;
    // Neutral must stop a bidirectional ESC; minimum pulse is full reverse.
    assert(throttlePulseUs(0) == 1500);
    assert(throttlePulseUs(-100) == 1000);
    assert(throttlePulseUs(100) == 2000);
    assert(throttlePulseUs(-30) == 1350);
    assert(throttlePulseUs(30) == 1650);
    assert(throttlePulseUs(INT_MIN) == 1000);
    assert(throttlePulseUs(INT_MAX) == 2000);

    // Travel reduction preserves the trimmed center and reversed linkage.
    assert(steeringPulseUs(0, 20, 50) == 1520);
    assert(steeringPulseUs(100, 20, 50) == 1302);
    assert(steeringPulseUs(-100, 20, 50) == 1738);
    assert(steeringPulseUs(100, 20, 100) == 1083);
    assert(steeringPulseUs(-100, 20, 100) == 1957);
    for (int limit = 1; limit <= 100; ++limit) {
        assert(steeringPulseUs(0, 20, limit) == 1520);
        for (int input = -100; input <= 100; ++input) {
            const int pulse = steeringPulseUs(input, 20, limit);
            assert(pulse >= 800 && pulse <= 2200);
        }
    }
    assert(steeringPulseUs(INT_MIN, INT_MAX, INT_MAX) == 2200);
    assert(steeringPulseUs(INT_MAX, INT_MIN, INT_MAX) == 800);
}
