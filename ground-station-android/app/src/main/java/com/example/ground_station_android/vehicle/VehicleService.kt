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

    private val DEFAULT_HOST = "192.168.0.123"
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
                        Throttle(split[1].toIntOrNull() ?: 0),
                        Steering(split[2].toIntOrNull() ?: 0)
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
) {
    val type = MessageType.tele

    override fun toString(): String {
        return "$type:$seq,${throttle.value},${steering.value}"
    }
}

data class CameraStartParams(val width: Int, val height: Int, val framerate: Int) {
    init {
        require(width in 640..2592)
        require(height in 480..1944)
        require(framerate in 1..90)
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
