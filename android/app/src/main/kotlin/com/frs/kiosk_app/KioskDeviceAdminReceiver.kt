package com.frs.kiosk_app

import android.app.admin.DeviceAdminReceiver
import android.content.Context
import android.content.Intent
import android.widget.Toast

/**
 * DeviceAdminReceiver enabling dedicated kiosk lockdown, Lock Task pinning,
 * and hardware security controls for the FRS Attendance Tablet.
 */
class KioskDeviceAdminReceiver : DeviceAdminReceiver() {
    override fun onEnabled(context: Context, intent: Intent) {
        super.onEnabled(context, intent)
        Toast.makeText(context, "FRS Kiosk Device Owner Enabled", Toast.LENGTH_SHORT).show()
    }

    override fun onDisabled(context: Context, intent: Intent) {
        super.onDisabled(context, intent)
        Toast.makeText(context, "FRS Kiosk Device Owner Disabled", Toast.LENGTH_SHORT).show()
    }
}
