package com.example.ground_station_android.vehicle

import android.media.MediaCodec
import android.media.MediaFormat
import android.util.Log
import android.view.Surface
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.yield
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress

class CameraService {

    private val DEFAULT_PORT = 9999
    private val mutex = Mutex()

    private val _bitrateMbps = MutableStateFlow(0f)
    val bitrateMbps = _bitrateMbps.asStateFlow()

    suspend fun startCamera(surface: Surface) = withContext(Dispatchers.IO) {
        mutex.withLock {
            var socket: DatagramSocket? = null
            var codec: MediaCodec? = null
            _bitrateMbps.value = 0f
            try {
                Log.d("CameraService", "Starting camera on port $DEFAULT_PORT")
                socket = DatagramSocket(null).apply {
                    reuseAddress = true
                    soTimeout = 1000 // Allow the loop to check isActive even if no packets arrive
                    bind(InetSocketAddress(DEFAULT_PORT))
                    receiveBufferSize = 2 * 1024 * 1024
                }

                codec = MediaCodec.createDecoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)
                val format =
                    MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, 1280, 720)

                codec.configure(format, surface, null, 0)
                codec.start()

                val buffer = ByteArray(65535)
                val packet = DatagramPacket(buffer, buffer.size)

                var bytesInInterval = 0L
                var lastIntervalTime = System.currentTimeMillis()

                while (isActive) {
                    try {
                        socket.receive(packet)
                        bytesInInterval += packet.length

                        val now = System.currentTimeMillis()
                        val elapsed = now - lastIntervalTime
                        if (elapsed >= 1000) {
                            // Calculate Mbps: (bytes * 8 bits/byte) / (1024 * 1024 bits/Mbit) / seconds
                            val mbps = (bytesInInterval * 8f) / (1024 * 1024) / (elapsed / 1000f)
                            _bitrateMbps.value = mbps
                            bytesInInterval = 0
                            lastIntervalTime = now
                        }

                        val inputIndex = codec.dequeueInputBuffer(1000)
                        if (inputIndex >= 0) {
                            val inputBuffer = codec.getInputBuffer(inputIndex)
                            inputBuffer?.clear()
                            inputBuffer?.put(packet.data, 0, packet.length)
                            codec.queueInputBuffer(inputIndex, 0, packet.length, 0, 0)
                        }

                        val info = MediaCodec.BufferInfo()
                        var outputIndex = codec.dequeueOutputBuffer(info, 0)
                        while (outputIndex >= 0) {
                            codec.releaseOutputBuffer(outputIndex, true)
                            outputIndex = codec.dequeueOutputBuffer(info, 0)
                        }
                    } catch (e: Exception) {
                        if (isActive) yield()
                    }
                }
            } catch (e: Exception) {
                if (isActive) Log.e("CameraService", "Stream error", e)
            } finally {
                withContext(NonCancellable) {
                    Log.d("CameraService", "Cleaning up camera resources")
                    _bitrateMbps.value = 0f
                    socket?.close()
                    try {
                        codec?.stop()
                    } catch (e: Exception) {
                    }
                    try {
                        codec?.release()
                    } catch (e: Exception) {
                    }
                    Log.d("CameraService", "Camera cleaned up")
                }
            }
        }
    }

    fun stopCamera() {
    }
}
