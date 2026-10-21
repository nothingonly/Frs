#!/usr/bin/env bash
# ==============================================================================
# FRS Android Kiosk Device Owner Provisioning Script (POSIX/macOS/Linux)
# ==============================================================================
set -euo pipefail

echo "[1/4] Checking connected ADB devices..."
adb devices

echo "[2/4] Setting FRS Attendance Kiosk as Device Owner..."
adb shell dpm set-device-owner com.frs.kiosk_app/.KioskDeviceAdminReceiver || {
    echo "Warning: If device owner assignment failed, ensure all accounts are removed or tablet is factory reset."
}

echo "[3/4] Granting runtime hardware permissions (Camera, Power stay-on)..."
adb shell pm grant com.frs.kiosk_app android.permission.CAMERA
adb shell svc power stayon true
adb shell settings put global stay_on_while_plugged_in 3

echo "[4/4] Launching FRS Attendance Kiosk..."
adb shell am start -n com.frs.kiosk_app/.MainActivity

echo "Device Owner configuration complete."
