package com.example.ground_station_android.vehicle

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.util.Log
import android.view.Surface
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.yield
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress
import java.net.SocketException
import java.net.SocketTimeoutException
import kotlin.coroutines.coroutineContext

/**
 * Receives the vehicle's video stream.
 *
 * The vehicle still *pushes* UDP datagrams to [DEFAULT_PORT], exactly as the
 * Raspberry Pi build did, but the payload is no longer H.264: the ESP32-S3 has
 * no H.264 encoder, so it sends MJPEG - one self-contained JPEG per frame -
 * and there is no [android.media.MediaCodec] in the path at all. Each JPEG is
 * larger than a datagram, so the vehicle splits it into chunks that carry a
 * 16-byte header; this class reassembles them and paints finished frames onto
 * the [Surface].
 *
 * The header layout is defined in the firmware's `include/camera_service.h`
 * and must be changed on both sides together:
 *
 *     offset size field
 *     0      2    magic 'J','F'
 *     2      1    version
 *     3      1    flags, reserved
 *     4      2    frame id, wraps at 2^16
 *     6      2    chunk index within the frame
 *     8      2    chunk count for the frame
 *     10     2    reserved
 *     12     4    total JPEG size in bytes
 *     16     ..   payload
 *
 * All multi-byte fields are big-endian, and chunk N holds JPEG bytes starting
 * at `N * CHUNK_PAYLOAD_BYTES`.
 *
 * Loss is expected on UDP and is not recovered: an incomplete frame is
 * dropped, and the next whole frame replaces it. That is the point of MJPEG
 * here - unlike H.264 there are no reference frames, so a lost frame cannot
 * corrupt the ones that follow.
 */
class CameraService {

    private val DEFAULT_PORT = 9999

    private val mutex = Mutex()

    private val _bitrateMbps = MutableStateFlow(0f)
    val bitrateMbps = _bitrateMbps.asStateFlow()

    suspend fun startCamera(surface: Surface) = withContext(Dispatchers.IO) {
        mutex.withLock {
            var socket: DatagramSocket? = null
            _bitrateMbps.value = 0f
            // CONFLATED: if decoding falls behind, show the newest frame and
            // discard what it replaced. Stale video is worse than dropped
            // video when you are driving by it.
            val frames = Channel<ByteArray>(Channel.CONFLATED)
            try {
                Log.d(TAG, "Listening for video on port $DEFAULT_PORT")
                socket = DatagramSocket(null).apply {
                    reuseAddress = true
                    soTimeout = 1000 // Allow the loop to check isActive even if no packets arrive
                    bind(InetSocketAddress(DEFAULT_PORT))
                    receiveBufferSize = 2 * 1024 * 1024
                }

                coroutineScope {
                    // Close the socket immediately on cancellation so a blocked
                    // socket.receive() in receiveLoop unblocks right away
                    // instead of holding the port and mutex until soTimeout.
                    coroutineContext[Job]?.invokeOnCompletion {
                        socket.close()
                    }
                    launch(Dispatchers.Default) { renderLoop(frames, surface) }
                    launch { receiveLoop(socket, frames) }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Log.e(TAG, "Stream error", e)
            } finally {
                withContext(NonCancellable) {
                    Log.d(TAG, "Cleaning up camera resources")
                    _bitrateMbps.value = 0f
                    frames.close()
                    socket?.close()
                    clearSurface(surface)
                    Log.d(TAG, "Camera cleaned up")
                }
            }
        }
    }

    fun clearSurface(surface: Surface) {
        if (!surface.isValid) return
        try {
            val canvas = surface.lockCanvas(null)
            try {
                canvas.drawColor(Color.BLACK)
            } finally {
                surface.unlockCanvasAndPost(canvas)
            }
        } catch (e: Exception) {
            Log.d(TAG, "Could not clear surface", e)
        }
    }

    /**
     * Reassemble datagrams into whole JPEGs. Kept free of decoding work so a
     * slow decode cannot make us miss chunks.
     */
    private suspend fun receiveLoop(socket: DatagramSocket, frames: Channel<ByteArray>) {
        val buffer = ByteArray(HEADER_BYTES + CHUNK_PAYLOAD_BYTES)
        val packet = DatagramPacket(buffer, buffer.size)
        val assembler = FrameAssembler()

        var bytesInInterval = 0L
        var lastIntervalTime = System.currentTimeMillis()

        while (coroutineContext.isActive) {
            try {
                // DatagramPacket.receive() shrinks the packet's length to the
                // bytes it read, and that length caps the *next* receive. The
                // last chunk of every frame is short, so without this reset
                // each frame would clip the one after it.
                packet.setLength(buffer.size)
                socket.receive(packet)
            } catch (e: SocketTimeoutException) {
                // No video for a second: the vehicle may not have started
                // pushing yet. Keep waiting, but drop any half-built frame.
                assembler.reset()
                _bitrateMbps.value = 0f
                bytesInInterval = 0
                lastIntervalTime = System.currentTimeMillis()
                continue
            } catch (e: SocketException) {
                if (!coroutineContext.isActive || socket.isClosed) break
                yield()
                continue
            } catch (e: Exception) {
                if (coroutineContext.isActive) yield()
                continue
            }

            bytesInInterval += packet.length
            val now = System.currentTimeMillis()
            val elapsed = now - lastIntervalTime
            if (elapsed >= 1000) {
                // (bytes * 8 bits/byte) / (1024 * 1024 bits/Mbit) / seconds
                _bitrateMbps.value = (bytesInInterval * 8f) / (1024 * 1024) / (elapsed / 1000f)
                bytesInInterval = 0
                lastIntervalTime = now
            }

            val frame = assembler.accept(buffer, packet.length, now) ?: continue
            frames.trySend(frame)
        }
    }

    /** Decode finished JPEGs and paint them, letterboxed, onto the surface. */
    private suspend fun renderLoop(frames: Channel<ByteArray>, surface: Surface) {
        val paint = Paint().apply { isFilterBitmap = true }
        val options = BitmapFactory.Options().apply { inMutable = true }
        var reusable: Bitmap? = null

        for (jpeg in frames) {
            // Hand the decoded frame the previous frame's memory when the
            // sizes match; at 25 fps fresh allocations would keep the GC busy.
            options.inBitmap = reusable
            val bitmap = try {
                BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size, options)
            } catch (e: IllegalArgumentException) {
                // inBitmap was not reusable for this frame (size changed).
                options.inBitmap = null
                reusable = null
                BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size, options)
            }
            if (bitmap == null) {
                Log.w(TAG, "undecodable frame of ${jpeg.size} bytes")
                continue
            }
            reusable = bitmap

            if (!surface.isValid) {
                delay(16)
                continue
            }

            try {
                val canvas = surface.lockCanvas(null)
                try {
                    canvas.drawColor(Color.BLACK)
                    canvas.drawBitmap(bitmap, null, fit(bitmap, canvas.width, canvas.height), paint)
                } finally {
                    surface.unlockCanvasAndPost(canvas)
                }
            } catch (e: IllegalArgumentException) {
                Log.d(TAG, "surface temporarily unavailable", e)
                delay(16)
            } catch (e: IllegalStateException) {
                Log.d(TAG, "surface temporarily unavailable", e)
                delay(16)
            }
        }
    }

    /** Largest centred rect with the frame's aspect ratio that fits the view. */
    private fun fit(bitmap: Bitmap, viewWidth: Int, viewHeight: Int): Rect {
        val scale = minOf(
            viewWidth.toFloat() / bitmap.width,
            viewHeight.toFloat() / bitmap.height
        )
        val width = (bitmap.width * scale).toInt()
        val height = (bitmap.height * scale).toInt()
        val left = (viewWidth - width) / 2
        val top = (viewHeight - height) / 2
        return Rect(left, top, left + width, top + height)
    }

    /**
     * Stopping is driven by cancelling [startCamera]; the vehicle is told to
     * stop pushing separately, via [VehicleService.stopCamera].
     */
    fun stopCamera() {
    }

    /**
     * Collects the chunks of one frame at a time. Chunks of a newer frame
     * abandon whatever is half-built, since a frame missing a chunk can never
     * be completed.
     */
    private class FrameAssembler {
        private var frameId = -1
        private var frameSize = 0
        private var chunkCount = 0
        private var receivedChunks = 0
        private var buffer = ByteArray(0)
        private var seen = BooleanArray(0)
        private var lastChunkAt = 0L

        fun reset() {
            frameId = -1
            receivedChunks = 0
        }

        /**
         * Feed one datagram. Returns the JPEG bytes once a frame is complete,
         * otherwise null.
         */
        fun accept(packet: ByteArray, length: Int, now: Long): ByteArray? {
            if (length < HEADER_BYTES) return null
            if (packet[0] != MAGIC_0 || packet[1] != MAGIC_1) return null
            if (packet[2].toInt() != PROTOCOL_VERSION) return null

            val id = readBE16(packet, 4)
            val chunkIndex = readBE16(packet, 6)
            val chunks = readBE16(packet, 8)
            val size = readBE32(packet, 12)
            val payloadLength = length - HEADER_BYTES

            if (chunks <= 0 || size <= 0 || size > MAX_FRAME_BYTES) return null
            // Guard against a corrupt header describing a frame that cannot
            // exist, before it is used to size a buffer or an index.
            if (chunks != (size + CHUNK_PAYLOAD_BYTES - 1) / CHUNK_PAYLOAD_BYTES) return null
            if (chunkIndex >= chunks) return null

            val offset = chunkIndex * CHUNK_PAYLOAD_BYTES
            if (offset + payloadLength > size) return null

            // A stream that restarts begins again at frame 1, which is
            // "older" than the id we left off at, so treat a gap in time as a
            // new stream rather than a flood of stale chunks.
            val restarted = now - lastChunkAt > STREAM_RESTART_GAP_MS
            lastChunkAt = now

            if (id != frameId) {
                if (frameId != -1 && !restarted && !isNewer(id, frameId)) return null
                frameId = id
                frameSize = size
                chunkCount = chunks
                receivedChunks = 0
                if (buffer.size < size) buffer = ByteArray(size)
                if (seen.size < chunks) seen = BooleanArray(chunks)
                seen.fill(false, 0, chunks)
            } else if (seen[chunkIndex]) {
                return null // Duplicate; already counted.
            }

            packet.copyInto(buffer, offset, HEADER_BYTES, HEADER_BYTES + payloadLength)
            seen[chunkIndex] = true
            receivedChunks++

            if (receivedChunks < chunkCount) return null

            // Complete: hand out a copy, since `buffer` is reused immediately.
            reset()
            return buffer.copyOf(frameSize)
        }

        /** True if [candidate] is ahead of [current] in a 16-bit wrapping counter. */
        private fun isNewer(candidate: Int, current: Int): Boolean {
            val delta = (candidate - current) and 0xFFFF
            return delta in 1 until 0x8000
        }

        private fun readBE16(bytes: ByteArray, at: Int): Int =
            ((bytes[at].toInt() and 0xFF) shl 8) or (bytes[at + 1].toInt() and 0xFF)

        private fun readBE32(bytes: ByteArray, at: Int): Int =
            ((bytes[at].toInt() and 0xFF) shl 24) or
                ((bytes[at + 1].toInt() and 0xFF) shl 16) or
                ((bytes[at + 2].toInt() and 0xFF) shl 8) or
                (bytes[at + 3].toInt() and 0xFF)
    }

    private companion object {
        const val TAG = "CameraService"

        // Wire constants, shared with the firmware's camera_service.h.
        const val HEADER_BYTES = 16
        const val CHUNK_PAYLOAD_BYTES = 1400
        const val PROTOCOL_VERSION = 1
        val MAGIC_0 = 'J'.code.toByte()
        val MAGIC_1 = 'F'.code.toByte()

        // A UXGA JPEG is well under this; the cap only stops a corrupt header
        // from sizing a buffer.
        const val MAX_FRAME_BYTES = 4 * 1024 * 1024

        // Silence longer than this means a new stream, not reordered chunks.
        const val STREAM_RESTART_GAP_MS = 500
    }
}
