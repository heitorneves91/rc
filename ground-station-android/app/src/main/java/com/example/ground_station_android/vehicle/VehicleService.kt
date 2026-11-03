package com.example.ground_station_android.vehicle

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.SocketException
import java.util.concurrent.atomic.AtomicLong
import kotlin.time.Duration.Companion.milliseconds

class VehicleService {

    companion object {
        const val MIN_STEERING_TRIM_US = -500
        const val MAX_STEERING_TRIM_US = 500
        const val DEFAULT_STEERING_TRIM_US = 20
    }

    private val DEFAULT_HOST = "192.168.4.1"
    private val DEFAULT_PORT = 8888

    var address = InetAddress.getByName(DEFAULT_HOST)
    var port = DEFAULT_PORT
    private lateinit var socket: DatagramSocket

    @Volatile
    private var currSteering = Steering(0)

    @Volatile
    private var currThrottle = Throttle(0)

    private val lastSentSeq = AtomicLong(-1L)

    @Volatile
    private var lastRecvSeq = -1L

    private val ioScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var telemetryJob: Job? = null
    private var controlLoopJob: Job? = null

    private val _latestTelemetryMessage = MutableStateFlow<TelemetryMessage?>(null)
    val telemetry = _latestTelemetryMessage.asStateFlow()

    init {
        openSocket()
    }

    fun steer(steering: Steering) {
        currSteering = steering
    }

    fun throttle(throttle: Throttle) {
        currThrottle = throttle
    }

    fun startCamera(params: CameraStartParams? = null) {
        configure(Configuration.START_CAMERA, params?.toString())
    }

    fun stopCamera() {
        configure(Configuration.STOP_CAMERA)
    }

    fun setSteeringTrim(trimUs: Int) {
        val clamped = trimUs.coerceIn(MIN_STEERING_TRIM_US, MAX_STEERING_TRIM_US)
        configure(Configuration.STEERING_TRIM, clamped.toString())
    }

    fun configure(configuration: Configuration, value: String? = null) {
        send(
            ConfigureMessage(
                seq = lastSentSeq.incrementAndGet(),
                configuration = configuration,
                value = value,
            )
        )
    }

    fun reopenSocket(host: String = DEFAULT_HOST, port: Int = DEFAULT_PORT) {
        address = InetAddress.getByName(host)
        this.port = port
        socket.close()
        lastSentSeq.set(-1L)
        lastRecvSeq = -1L
        openSocket()
    }

    private fun groundHello() {
        configure(Configuration.GROUND_HELLO)
    }

    private fun openSocket() {
        socket = DatagramSocket()
        groundHello()
        startTelemetry()
        startControlLoop()
    }

    private fun startTelemetry() {
        telemetryJob?.cancel()
        telemetryJob = ioScope.launch {
            val buffer = ByteArray(32 * 1024)
            while (isActive) {
                try {
                    val packet = DatagramPacket(buffer, buffer.size)
                    socket.receive(packet)
                    val text = String(
                        packet.data,
                        0,
                        packet.length,
                        Charsets.UTF_8
                    )

                    if (!text.startsWith(MessageType.tele.toString() + ":")) {
                        Log.i("VehicleService", "received non-telemetry message: $text")
                        continue
                    }

                    val split = text.substring(5).split(",")
                    if (split.size < 3) continue

                    val recvSeq = split[0].toLongOrNull() ?: continue
                    if (lastRecvSeq >= recvSeq) {
                        Log.i(
                            "VehicleService",
                            "received out-of-order message (lastRecvSeq=$lastRecvSeq): $text"
                        )
                        continue
                    }

                    lastRecvSeq = recvSeq

                    _latestTelemetryMessage.value = TelemetryMessage(
                        seq = recvSeq,
                        throttle = Throttle(split[1].trim().toIntOrNull() ?: 0),
                        steering = Steering(split[2].trim().toIntOrNull() ?: 0),
                        steeringTrimUs = split.getOrNull(3)?.trim()?.toIntOrNull()
                            ?: DEFAULT_STEERING_TRIM_US
                    )
                } catch (e: SocketException) {
                    break // socket closed
                } catch (e: Exception) {
                    Log.e("VehicleService", "Telemetry error", e)
                }
            }
        }
    }

    private fun startControlLoop() {
        controlLoopJob?.cancel()
        controlLoopJob = ioScope.launch {
            while (isActive) {
                try {
                    val msg = MoveMessage(
                        seq = lastSentSeq.incrementAndGet(),
                        throttle = currThrottle,
                        steering = currSteering
                    )
                    sendImmediate(msg)
                } catch (e: Exception) {
                    // socket closed or IO error
                }
                delay(40.milliseconds) // ~25Hz
            }
        }
    }

    private fun send(msg: Any) {
        ioScope.launch {
            try {
                sendImmediate(msg)
            } catch (e: Exception) {
                Log.e("VehicleService", "Send error", e)
            }
        }
    }

    private fun sendImmediate(msg: Any) {
        val data = msg.toString().toByteArray(Charsets.UTF_8)
        socket.send(
            DatagramPacket(
                data,
                data.size,
                address,
                port
            )
        )
    }
}

enum class MessageType {
    move,
    conf,
    tele
}

data class MoveMessage(
    val seq: Long,
    val throttle: Throttle,
    val steering: Steering,
) {
    val type = MessageType.move

    override fun toString(): String {
        return "$type:$seq,${throttle.value},${steering.value}"
    }
}

enum class Configuration {
    GROUND_HELLO,
    START_CAMERA,
    STOP_CAMERA,
    STEERING_TRIM,
}

data class ConfigureMessage(
    val seq: Long,
    val configuration: Configuration,
    val value: String? = null,
) {
    val type = MessageType.conf

    override fun toString(): String {
        return "$type:$seq,$configuration,$value"
    }
}

data class TelemetryMessage(
    val seq: Long,
    val throttle: Throttle,
    val steering: Steering,
    val steeringTrimUs: Int = VehicleService.DEFAULT_STEERING_TRIM_US,
) {
    val type = MessageType.tele

    override fun toString(): String {
        return "$type:$seq,${throttle.value},${steering.value},$steeringTrimUs"
    }
}

data class CameraStartParams(val width: Int, val height: Int, val framerate: Int) {
    init {
        require(width in MIN_WIDTH..MAX_WIDTH)
        require(height in MIN_HEIGHT..MAX_HEIGHT)
        require(framerate in MIN_FRAMERATE..MAX_FRAMERATE)
    }

    companion object {
        // 320x240 is the smallest frame size the vehicle firmware offers.
        const val MIN_WIDTH = 320
        const val MAX_WIDTH = 2592
        const val MIN_HEIGHT = 240
        const val MAX_HEIGHT = 1944
        const val MIN_FRAMERATE = 1
        const val MAX_FRAMERATE = 90
    }

    override fun toString(): String {
        return "$width,$height,$framerate"
    }
}

@JvmInline
value class Throttle(val value: Int) {
    init {
        require(value in -100..100)
    }
}

@JvmInline
value class Steering(val value: Int) {
    init {
        require(value in -100..100)
    }
}

/**
 * Starting points for the XIAO ESP32-S3 Sense: an OV2640 behind a small WiFi
 * antenna. The OV2640 only reaches ~15 fps at 720p and above but runs near
 * 25-30 fps at SVGA and below, and the soft AP sustains a few Mbps of UDP in
 * practice, so frame rate is kept over resolution - it matters more for
 * driving. Sizes are ones the sensor supports natively (the firmware rounds
 * anything else down). Rough rates assume the default JPEG quality (12).
 */
enum class CameraPreset(val label: String, val params: CameraStartParams) {
    // 720p puts the OV2640 in its full-resolution mode, capped at ~15 fps, so
    // this trades frame rate for detail; it needs a clean, close link.
    VERY_STRONG("Very strong", CameraStartParams(1280, 720, 15)), // ~13 Mbps
    STRONG("Strong", CameraStartParams(800, 600, 25)),  // ~12 Mbps
    AVERAGE("Average", CameraStartParams(640, 480, 20)), // ~7 Mbps
    WEAK("Weak", CameraStartParams(480, 320, 15)),      // ~3.5 Mbps
}
