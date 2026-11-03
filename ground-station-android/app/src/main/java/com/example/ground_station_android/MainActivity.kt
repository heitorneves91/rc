package com.example.ground_station_android

import android.os.Bundle
import android.os.SystemClock
import android.view.SurfaceHolder
import android.view.SurfaceView
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.VerticalDivider
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.example.ground_station_android.ui.theme.GroundstationandroidTheme
import com.example.ground_station_android.vehicle.CameraService
import com.example.ground_station_android.vehicle.CameraPreset
import com.example.ground_station_android.vehicle.CameraStartParams
import com.example.ground_station_android.vehicle.Steering
import com.example.ground_station_android.vehicle.Throttle
import com.example.ground_station_android.vehicle.VehicleService
import com.example.ground_station_android.vehicle.WifiConnectionStatus
import com.example.ground_station_android.vehicle.WifiService
import kotlinx.coroutines.delay
import java.util.Locale

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        val windowInsetsController =
            WindowCompat.getInsetsController(window, window.decorView)
        windowInsetsController.systemBarsBehavior =
            WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        windowInsetsController.hide(WindowInsetsCompat.Type.systemBars())

        setContent {
            val context = LocalContext.current
            val wifiService = remember(context) { WifiService(context.applicationContext) }
            val wifiStatus by wifiService.connectionStatus.collectAsState()

            val vehicleService = remember { VehicleService() }
            val cameraService = remember { CameraService() }
            val telemetry by vehicleService.telemetry.collectAsState()
            val bitrate by cameraService.bitrateMbps.collectAsState()

            var isCameraActive by remember {
                mutableStateOf(false)
            }

            var showCameraSettings by remember { mutableStateOf(false) }
            var cameraParams by remember {
                mutableStateOf(CameraPreset.AVERAGE.params)
            }

            var steeringTrimUs by remember {
                mutableStateOf(VehicleService.DEFAULT_STEERING_TRIM_US)
            }
            var lastTrimCommandTimeMs by remember { mutableStateOf(0L) }
            var showSteeringTrimDialog by remember { mutableStateOf(false) }

            LaunchedEffect(telemetry?.steeringTrimUs) {
                val remoteTrim = telemetry?.steeringTrimUs ?: return@LaunchedEffect
                val elapsed = SystemClock.elapsedRealtime() - lastTrimCommandTimeMs
                if (elapsed < 500L) {
                    delay(500L - elapsed)
                }
                telemetry?.steeringTrimUs?.let { steeringTrimUs = it }
            }

            val updateSteeringTrim: (Int) -> Unit = { newTrim ->
                val clamped = newTrim.coerceIn(
                    VehicleService.MIN_STEERING_TRIM_US,
                    VehicleService.MAX_STEERING_TRIM_US
                )
                steeringTrimUs = clamped
                lastTrimCommandTimeMs = SystemClock.elapsedRealtime()
                vehicleService.setSteeringTrim(clamped)
            }

            if (showCameraSettings) {
                CameraSettingsDialog(
                    initialParams = cameraParams,
                    onDismiss = { showCameraSettings = false },
                    onConfirm = {
                        cameraParams = it
                        showCameraSettings = false
                        if (isCameraActive) {
                            vehicleService.startCamera(it)
                        }
                    }
                )
            }

            if (showSteeringTrimDialog) {
                SteeringTrimDialog(
                    currentTrimUs = steeringTrimUs,
                    onApplyTrim = updateSteeringTrim,
                    onDismiss = { showSteeringTrimDialog = false }
                )
            }

            GroundstationandroidTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = Color.Black
                ) {
                    Box(Modifier.fillMaxSize()) {
                        CameraView(cameraService, isCameraActive)

                        Row(
                            Modifier.fillMaxSize()
                        ) {
                            val labelColor = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.15f)
                            val labelSize = 120.sp

                            JoystickArea(
                                modifier = Modifier
                                    .weight(1f)
                                    .fillMaxHeight(),
                                onMove = { _, y ->
                                    vehicleService.throttle(Throttle(y))
                                }
                            ) {
                                Column(
                                    modifier = Modifier
                                        .fillMaxSize()
                                        .padding(32.dp),
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                    verticalArrangement = Arrangement.SpaceBetween
                                ) {
                                    Text(
                                        "▲",
                                        fontSize = labelSize,
                                        color = labelColor,
                                        fontWeight = FontWeight.Bold
                                    )
                                    Text(
                                        "▼",
                                        fontSize = labelSize,
                                        color = labelColor,
                                        fontWeight = FontWeight.Bold
                                    )
                                }
                            }

                            VerticalDivider()

                            Column(
                                modifier = Modifier
                                    .weight(0.5f)
                                    .fillMaxHeight()
                                    .padding(vertical = 12.dp)
                                    .verticalScroll(rememberScrollState()),
                                horizontalAlignment = Alignment.CenterHorizontally,
                                verticalArrangement = Arrangement.spacedBy(
                                    10.dp,
                                    Alignment.CenterVertically
                                )
                            ) {
                                // Wi-Fi Connection
                                Surface(
                                    onClick = {
                                        wifiService.connectToVehicleWifi(
                                            onConnected = {
                                                vehicleService.reopenSocket()
                                            }
                                        )
                                    },
                                    shape = RoundedCornerShape(24.dp),
                                    color = Color.White.copy(alpha = 0.2f)
                                ) {
                                    Row(
                                        modifier = Modifier.padding(
                                            horizontal = 16.dp,
                                            vertical = 10.dp
                                        ),
                                        verticalAlignment = Alignment.CenterVertically,
                                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                                    ) {
                                        val (dotColor, statusText) = when (wifiStatus) {
                                            WifiConnectionStatus.CONNECTED -> Color(0xFF4CAF50) to "rc-car CONNECTED"
                                            WifiConnectionStatus.CONNECTING -> Color(0xFFFFB74D) to "CONNECTING..."
                                            WifiConnectionStatus.FAILED -> Color(0xFFE57373) to "RETRY WI-FI"
                                            WifiConnectionStatus.DISCONNECTED -> Color.White.copy(
                                                alpha = 0.5f
                                            ) to "CONNECT WI-FI"
                                        }
                                        Box(
                                            modifier = Modifier
                                                .size(8.dp)
                                                .background(dotColor, CircleShape)
                                        )
                                        Text(
                                            text = statusText,
                                            color = Color.White,
                                            fontSize = 12.sp,
                                            fontWeight = FontWeight.Bold,
                                            letterSpacing = 0.5.sp
                                        )
                                    }
                                }

                                // Camera Status
                                if (isCameraActive) {
                                    Column(
                                        horizontalAlignment = Alignment.CenterHorizontally,
                                        verticalArrangement = Arrangement.spacedBy(4.dp)
                                    ) {
                                        Row(
                                            verticalAlignment = Alignment.CenterVertically,
                                            horizontalArrangement = Arrangement.spacedBy(6.dp)
                                        ) {
                                            Box(
                                                modifier = Modifier
                                                    .size(8.dp)
                                                    .background(Color.Red, CircleShape)
                                            )
                                            Text(
                                                "LIVE",
                                                color = Color.Red,
                                                fontSize = 12.sp,
                                                fontWeight = FontWeight.Bold
                                            )
                                        }
                                        Text(
                                            String.format(Locale.US, "%.1f Mbps", bitrate),
                                            color = Color.White.copy(alpha = 0.7f),
                                            fontSize = 10.sp,
                                            fontWeight = FontWeight.Medium
                                        )
                                    }
                                }

                                // Camera Controls
                                Row(
                                    modifier = Modifier
                                        .background(
                                            Color.White.copy(alpha = 0.2f),
                                            RoundedCornerShape(24.dp)
                                        )
                                        .padding(4.dp),
                                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    IconButton(
                                        onClick = {
                                            vehicleService.startCamera(cameraParams)
                                            isCameraActive = true
                                        },
                                        colors = IconButtonDefaults.iconButtonColors(
                                            containerColor = if (isCameraActive) MaterialTheme.colorScheme.primary.copy(
                                                alpha = 0.4f
                                            ) else Color.Transparent,
                                            contentColor = Color.White
                                        )
                                    ) {
                                        Text("▶", fontSize = 24.sp, color = Color.White)
                                    }

                                    IconButton(
                                        onClick = {
                                            vehicleService.stopCamera()
                                            isCameraActive = false
                                        },
                                        enabled = isCameraActive,
                                        colors = IconButtonDefaults.iconButtonColors(
                                            contentColor = Color.White,
                                            disabledContentColor = Color.White.copy(alpha = 0.2f)
                                        )
                                    ) {
                                        Text(
                                            "■",
                                            fontSize = 24.sp,
                                            color = if (isCameraActive) Color.White else Color.White.copy(
                                                alpha = 0.2f
                                            )
                                        )
                                    }

                                    IconButton(
                                        onClick = { showCameraSettings = true },
                                        colors = IconButtonDefaults.iconButtonColors(
                                            contentColor = Color.White
                                        )
                                    ) {
                                        Text("⚙", fontSize = 24.sp, color = Color.White)
                                    }
                                }

                                // Steering Trim (Offset) Controls
                                Row(
                                    modifier = Modifier
                                        .background(
                                            Color.White.copy(alpha = 0.2f),
                                            RoundedCornerShape(24.dp)
                                        )
                                        .padding(horizontal = 4.dp, vertical = 2.dp),
                                    horizontalArrangement = Arrangement.spacedBy(2.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    IconButton(
                                        onClick = { updateSteeringTrim(steeringTrimUs - 5) },
                                        modifier = Modifier.size(36.dp),
                                        colors = IconButtonDefaults.iconButtonColors(
                                            contentColor = Color.White
                                        )
                                    ) {
                                        Text("−", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color.White)
                                    }

                                    Surface(
                                        onClick = { showSteeringTrimDialog = true },
                                        shape = RoundedCornerShape(16.dp),
                                        color = Color.Transparent
                                    ) {
                                        Column(
                                            modifier = Modifier.padding(horizontal = 6.dp, vertical = 4.dp),
                                            horizontalAlignment = Alignment.CenterHorizontally
                                        ) {
                                            Text(
                                                "STEER TRIM",
                                                fontSize = 8.sp,
                                                fontWeight = FontWeight.Bold,
                                                color = Color.White.copy(alpha = 0.6f),
                                                letterSpacing = 0.5.sp
                                            )
                                            Text(
                                                String.format(Locale.US, "%+d µs", steeringTrimUs),
                                                fontSize = 12.sp,
                                                fontWeight = FontWeight.Bold,
                                                color = Color.White
                                            )
                                        }
                                    }

                                    IconButton(
                                        onClick = { updateSteeringTrim(steeringTrimUs + 5) },
                                        modifier = Modifier.size(36.dp),
                                        colors = IconButtonDefaults.iconButtonColors(
                                            contentColor = Color.White
                                        )
                                    ) {
                                        Text("+", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color.White)
                                    }
                                }

                                Spacer(modifier = Modifier.height(4.dp))

                                Text(
                                    "TELEMETRY",
                                    fontWeight = FontWeight.ExtraBold,
                                    fontSize = 14.sp,
                                    color = Color.White.copy(alpha = 0.5f),
                                    letterSpacing = 1.sp
                                )
                                telemetry?.let {
                                    Column(
                                        horizontalAlignment = Alignment.CenterHorizontally,
                                        verticalArrangement = Arrangement.spacedBy(4.dp)
                                    ) {
                                        Text(
                                            "SEQ: ${it.seq}",
                                            color = Color.White.copy(alpha = 0.2f),
                                            fontSize = 8.sp
                                        )
                                        TelemetryValue("THROTTLE", "${it.throttle.value}%")
                                        TelemetryValue("STEERING", "${it.steering.value}%")
                                    }
                                } ?: Text(
                                    "WAITING",
                                    color = Color.White.copy(alpha = 0.4f),
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.Bold
                                )
                            }

                            VerticalDivider()

                            JoystickArea(
                                modifier = Modifier
                                    .weight(1f)
                                    .fillMaxHeight(),
                                onMove = { x, _ ->
                                    vehicleService.steer(Steering(x))
                                }
                            ) {
                                Row(
                                    modifier = Modifier
                                        .fillMaxSize()
                                        .padding(32.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.SpaceBetween
                                ) {
                                    Text(
                                        "◀",
                                        fontSize = labelSize,
                                        color = labelColor,
                                        fontWeight = FontWeight.Bold
                                    )
                                    Text(
                                        "▶",
                                        fontSize = labelSize,
                                        color = labelColor,
                                        fontWeight = FontWeight.Bold
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun TelemetryValue(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color.White)
        Text(
            label,
            fontSize = 9.sp,
            color = Color.White.copy(alpha = 0.4f),
            fontWeight = FontWeight.Bold
        )
    }
}

@Composable
fun CameraSettingsDialog(
    initialParams: CameraStartParams,
    onDismiss: () -> Unit,
    onConfirm: (CameraStartParams) -> Unit
) {
    var width by remember { mutableStateOf(initialParams.width.toString()) }
    var height by remember { mutableStateOf(initialParams.height.toString()) }
    var framerate by remember { mutableStateOf(initialParams.framerate.toString()) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Camera Settings") },
        text = {
            // Landscape-only app: presets plus fields are taller than the
            // screen, so the content must scroll to reach the manual fields.
            Column(
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.verticalScroll(rememberScrollState())
            ) {
                Text("Signal preset", fontSize = 12.sp, fontWeight = FontWeight.Bold)
                CameraPreset.entries.chunked(2).forEach { row ->
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        row.forEach { preset ->
                            OutlinedButton(
                                onClick = {
                                    width = preset.params.width.toString()
                                    height = preset.params.height.toString()
                                    framerate = preset.params.framerate.toString()
                                },
                                contentPadding = PaddingValues(horizontal = 4.dp, vertical = 8.dp),
                                modifier = Modifier.weight(1f)
                            ) {
                                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                    Text(preset.label, fontSize = 13.sp, fontWeight = FontWeight.Bold)
                                    Text(
                                        "${preset.params.width}x${preset.params.height}",
                                        fontSize = 10.sp
                                    )
                                    Text("${preset.params.framerate} fps", fontSize = 10.sp)
                                }
                            }
                        }
                    }
                }
                OutlinedTextField(
                    value = width,
                    onValueChange = { width = it },
                    label = { Text("Width (${CameraStartParams.MIN_WIDTH}-${CameraStartParams.MAX_WIDTH})") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = height,
                    onValueChange = { height = it },
                    label = { Text("Height (${CameraStartParams.MIN_HEIGHT}-${CameraStartParams.MAX_HEIGHT})") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = framerate,
                    onValueChange = { framerate = it },
                    label = { Text("Framerate (${CameraStartParams.MIN_FRAMERATE}-${CameraStartParams.MAX_FRAMERATE})") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    val w = width.toIntOrNull() ?: initialParams.width
                    val h = height.toIntOrNull() ?: initialParams.height
                    val f = framerate.toIntOrNull() ?: initialParams.framerate

                    onConfirm(
                        CameraStartParams(
                            w.coerceIn(CameraStartParams.MIN_WIDTH, CameraStartParams.MAX_WIDTH),
                            h.coerceIn(CameraStartParams.MIN_HEIGHT, CameraStartParams.MAX_HEIGHT),
                            f.coerceIn(CameraStartParams.MIN_FRAMERATE, CameraStartParams.MAX_FRAMERATE)
                        )
                    )
                }
            ) {
                Text("OK")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cancel")
            }
        }
    )
}

@Composable
fun SteeringTrimDialog(
    currentTrimUs: Int,
    onApplyTrim: (Int) -> Unit,
    onDismiss: () -> Unit
) {
    var trimInput by remember(currentTrimUs) { mutableStateOf(currentTrimUs.toString()) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Steering Trim (Offset)") },
        text = {
            Column(
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.verticalScroll(rememberScrollState())
            ) {
                Text(
                    "Adjusts the steering servo center offset in microseconds (µs) and saves it to the vehicle's NVS flash memory.",
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    String.format(
                        Locale.US,
                        "Current: %+d µs (center pulse %d µs)",
                        currentTrimUs,
                        1500 + currentTrimUs
                    ),
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Bold
                )
                Row(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    listOf(-25, -5, -1, 1, 5, 25).forEach { step ->
                        OutlinedButton(
                            onClick = {
                                val next = (currentTrimUs + step).coerceIn(
                                    VehicleService.MIN_STEERING_TRIM_US,
                                    VehicleService.MAX_STEERING_TRIM_US
                                )
                                trimInput = next.toString()
                                onApplyTrim(next)
                            },
                            contentPadding = PaddingValues(horizontal = 2.dp, vertical = 6.dp),
                            modifier = Modifier.weight(1f)
                        ) {
                            Text(
                                String.format(Locale.US, "%+d", step),
                                fontSize = 12.sp,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }
                }
                Row(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    OutlinedButton(
                        onClick = {
                            trimInput = "0"
                            onApplyTrim(0)
                        },
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("Zero (0 µs)", fontSize = 12.sp)
                    }
                    OutlinedButton(
                        onClick = {
                            val def = VehicleService.DEFAULT_STEERING_TRIM_US
                            trimInput = def.toString()
                            onApplyTrim(def)
                        },
                        modifier = Modifier.weight(1f)
                    ) {
                        Text(
                            String.format(Locale.US, "Default (%+d µs)", VehicleService.DEFAULT_STEERING_TRIM_US),
                            fontSize = 12.sp
                        )
                    }
                }
                OutlinedTextField(
                    value = trimInput,
                    onValueChange = { trimInput = it },
                    label = {
                        Text(
                            "Steering Trim µs (${VehicleService.MIN_STEERING_TRIM_US} to ${VehicleService.MAX_STEERING_TRIM_US})"
                        )
                    },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    trimInput.trim().toIntOrNull()?.let { parsed ->
                        onApplyTrim(parsed)
                    }
                    onDismiss()
                }
            ) {
                Text("Save & Close")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Close")
            }
        }
    )
}

@Composable
fun CameraView(cameraService: CameraService, isStreaming: Boolean) {
    var surface by remember { mutableStateOf<android.view.Surface?>(null) }
    var surfaceGeneration by remember { mutableStateOf(0) }

    LaunchedEffect(isStreaming, surface, surfaceGeneration) {
        val s = surface
        if (isStreaming && s != null) {
            cameraService.startCamera(s)
        } else if (!isStreaming && s != null) {
            cameraService.clearSurface(s)
        }
    }

    AndroidView(
        factory = { context ->
            SurfaceView(context).apply {
                holder.addCallback(object : SurfaceHolder.Callback {
                    override fun surfaceCreated(holder: SurfaceHolder) {
                        cameraService.clearSurface(holder.surface)
                        surface = holder.surface
                        surfaceGeneration++
                    }

                    override fun surfaceChanged(
                        holder: SurfaceHolder,
                        format: Int,
                        width: Int,
                        height: Int
                    ) {
                    }

                    override fun surfaceDestroyed(holder: SurfaceHolder) {
                        surface = null
                    }
                })
            }
        },
        modifier = Modifier.fillMaxSize()
    )
}

@Composable
fun JoystickArea(
    modifier: Modifier = Modifier,
    onMove: (Int, Int) -> Unit,
    content: @Composable BoxScope.() -> Unit = {}
) {
    /**
     * This is vehicle received value if the user touched the bottom part of the screen and dragged
     * to the top (full range).
     */
    val bottomToTopPower = 200f
    val xMinValue = -100f
    val xMaxValue = 100f
    val yMinValue = 0.0f
    val yMaxValue = 100f

    var startPosition by remember {
        mutableStateOf<Offset?>(null)
    }
    var currentPosition by remember {
        mutableStateOf<Offset?>(null)
    }

    Box(
        modifier = modifier.pointerInput(Unit) {
            detectDragGestures(
                onDragStart = { offset ->
                    startPosition = offset
                    currentPosition = offset
                },
                onDrag = { change, _ ->
                    val start = startPosition ?: return@detectDragGestures
                    currentPosition = change.position

                    val dx = change.position.x - start.x
                    val dy = start.y - change.position.y

                    val scale = bottomToTopPower / size.height.toFloat()
                    val dxScaled = (dx * scale).coerceIn(xMinValue, xMaxValue).toInt()
                    val dyScaled = (dy * scale).coerceIn(yMinValue, yMaxValue).toInt()

                    onMove(dxScaled, dyScaled)

                    change.consume()
                },
                onDragEnd = {
                    startPosition = null
                    currentPosition = null
                    onMove(0, 0)
                },
                onDragCancel = {
                    startPosition = null
                    currentPosition = null
                    onMove(0, 0)
                }
            )
        }
    ) {
        content()
        val color = MaterialTheme.colorScheme.primary
        Canvas(modifier = Modifier.fillMaxSize()) {
            val start = startPosition
            val current = currentPosition
            if (start != null && current != null) {
                // Outer circle (base)
                drawCircle(
                    color = color,
                    radius = 100f,
                    center = start,
                    style = Stroke(width = 4f),
                    alpha = 0.5f
                )
                // Inner circle (knob)
                drawCircle(
                    color = color,
                    radius = 50f,
                    center = current,
                    alpha = 0.8f
                )
            }
        }
    }
}
