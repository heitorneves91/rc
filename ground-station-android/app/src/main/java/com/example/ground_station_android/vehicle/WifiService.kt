package com.example.ground_station_android.vehicle

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiManager
import android.net.wifi.WifiNetworkSpecifier
import android.net.wifi.WifiNetworkSuggestion
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

enum class WifiConnectionStatus {
    DISCONNECTED,
    CONNECTING,
    CONNECTED,
    FAILED
}

class WifiService(private val context: Context) {

    private val connectivityManager =
        context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager

    private val _connectionStatus = MutableStateFlow(WifiConnectionStatus.DISCONNECTED)
    val connectionStatus = _connectionStatus.asStateFlow()

    private var currentCallback: ConnectivityManager.NetworkCallback? = null

    fun connectToVehicleWifi(
        ssid: String = DEFAULT_SSID,
        passphrase: String = DEFAULT_PASSPHRASE,
        onConnected: (() -> Unit)? = null
    ) {
        _connectionStatus.value = WifiConnectionStatus.CONNECTING

        disconnect()

        val specifier = WifiNetworkSpecifier.Builder()
            .setSsid(ssid)
            .setWpa2Passphrase(passphrase)
            .build()

        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .setNetworkSpecifier(specifier)
            .build()

        try {
            val wifiManager =
                context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
            val suggestion = WifiNetworkSuggestion.Builder()
                .setSsid(ssid)
                .setWpa2Passphrase(passphrase)
                .build()
            wifiManager?.addNetworkSuggestions(listOf(suggestion))
        } catch (e: Exception) {
            Log.w(TAG, "Failed to add network suggestion", e)
        }

        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                Log.i(TAG, "Connected to Wi-Fi network: $ssid")
                connectivityManager.bindProcessToNetwork(network)
                _connectionStatus.value = WifiConnectionStatus.CONNECTED
                onConnected?.invoke()
            }

            override fun onUnavailable() {
                Log.w(TAG, "Failed to connect or request rejected for: $ssid")
                _connectionStatus.value = WifiConnectionStatus.FAILED
            }

            override fun onLost(network: Network) {
                Log.i(TAG, "Lost connection to Wi-Fi network: $ssid")
                connectivityManager.bindProcessToNetwork(null)
                _connectionStatus.value = WifiConnectionStatus.DISCONNECTED
            }
        }

        currentCallback = callback

        try {
            connectivityManager.requestNetwork(request, callback)
        } catch (e: Exception) {
            Log.e(TAG, "Error requesting Wi-Fi network", e)
            _connectionStatus.value = WifiConnectionStatus.FAILED
        }
    }

    fun disconnect() {
        currentCallback?.let {
            try {
                connectivityManager.unregisterNetworkCallback(it)
            } catch (e: Exception) {
                Log.e(TAG, "Error unregistering callback", e)
            }
            currentCallback = null
        }
        connectivityManager.bindProcessToNetwork(null)
        _connectionStatus.value = WifiConnectionStatus.DISCONNECTED
    }

    companion object {
        private const val TAG = "WifiService"
        const val DEFAULT_SSID = "rc-car"
        const val DEFAULT_PASSPHRASE = "rccar1234"
    }
}
