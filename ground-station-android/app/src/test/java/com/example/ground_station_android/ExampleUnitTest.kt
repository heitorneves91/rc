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
}