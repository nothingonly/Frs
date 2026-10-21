package com.frs.kiosk_app

import android.app.admin.DevicePolicyManager
import android.content.Context
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val LOCK_TASK_CHANNEL = "com.frs.kiosk_app/kiosk_lock"

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
            val dpm = getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, LOCK_TASK_CHANNEL).setMethodCallHandler { call, result ->
            when (call.method) {
                "startLockTask" -> {
                    try {
                        startLockTask()
                        result.success(true)
                    } catch (e: Exception) {
                        result.error("LOCK_TASK_ERROR", e.localizedMessage, null)
                    }
                }
                "stopLockTask" -> {
                    try {
                        stopLockTask()
                        result.success(true)
                    } catch (e: Exception) {
                        result.error("UNLOCK_TASK_ERROR", e.localizedMessage, null)
                    }
                }
                "isDeviceOwner" -> {
                    result.success(dpm.isDeviceOwnerApp(packageName))
                }
                "isLockTaskPermitted" -> {
                    result.success(dpm.isLockTaskPermitted(packageName))
                }
                "enableKioskMode" -> {
                    try {
                        val adminComponent = KioskDeviceAdminReceiver.getComponentName(this)
                        if (dpm.isDeviceOwnerApp(packageName)) {
                            dpm.setLockTaskPackages(adminComponent, arrayOf(packageName))
                        }
                        startLockTask()
                        result.success(true)
                    } catch (e: Exception) {
                        result.error("KIOSK_ENABLE_ERROR", e.localizedMessage, null)
                    }
                }
                else -> result.notImplemented()
            }
        }
    }
}
