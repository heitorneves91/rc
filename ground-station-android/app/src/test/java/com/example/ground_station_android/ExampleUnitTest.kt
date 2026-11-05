package com.example.ground_station_android

import com.example.ground_station_android.vehicle.Configuration
import com.example.ground_station_android.vehicle.ConfigureMessage
import com.example.ground_station_android.vehicle.Steering
import com.example.ground_station_android.vehicle.TelemetryMessage
import com.example.ground_station_android.vehicle.Throttle
import org.junit.Test

import org.junit.Assert.*

class ExampleUnitTest {
    @Test
    fun steeringTrimConfigureMessage_serializesCorrectly() {
        val msg = ConfigureMessage(
            seq = 42L,
            configuration = Configuration.STEERING_TRIM,
            value = "-15"
        )
        assertEquals("conf:42,STEERING_TRIM,-15", msg.toString())
    }

    @Test
    fun telemetryMessage_includesSteeringTrimUs() {
        val msg = TelemetryMessage(
            seq = 7L,
            throttle = Throttle(30),
            steering = Steering(-20),
            steeringTrimUs = 35
        )
        assertEquals("tele:7,30,-20,35", msg.toString())
    }

    @Test
    fun computeJoystickValues_scalesAndCapsThrottleToMaxSpeedPercent() {
        val areaHeight = 1000f

        // Halfway up the full throttle range (dy = 250) at 30% max speed -> 15%
        val (_, halfThrottle) = computeJoystickValues(
            dx = 0f,
            dy = 250f,
            areaHeight = areaHeight,
            maxYValue = 30
        )
        assertEquals(15, halfThrottle)

        // Full throttle drag (dy = 500) and beyond (dy = 800) at 30% max speed -> capped at 30%
        val (_, fullThrottle) = computeJoystickValues(
            dx = 0f,
            dy = 500f,
            areaHeight = areaHeight,
            maxYValue = 30
        )
        assertEquals(30, fullThrottle)

        val (_, overDragThrottle) = computeJoystickValues(
            dx = 0f,
            dy = 800f,
            areaHeight = areaHeight,
            maxYValue = 30
        )
        assertEquals(30, overDragThrottle)
    }

    @Test
    fun computeJoystickValues_reachesFullSteeringWithReducedHorizontalDrag() {
        val areaHeight = 900f

        // 1/6 of areaHeight (150px) to the right reaches +100% steering,
        // and 150px to the left reaches -100% steering (300px total lock-to-lock).
        val (rightSteer, _) = computeJoystickValues(
            dx = 150f,
            dy = 0f,
            areaHeight = areaHeight
        )
        assertEquals(100, rightSteer)

        val (leftSteer, _) = computeJoystickValues(
            dx = -150f,
            dy = 0f,
            areaHeight = areaHeight
        )
        assertEquals(-100, leftSteer)
    }
}