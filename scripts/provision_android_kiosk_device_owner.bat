@echo off
REM ==============================================================================
REM FRS Android Kiosk Device Owner Provisioning Script
REM
REM Pre-requisite: The tablet must be freshly factory reset with NO accounts
REM configured, or provisioned via QR code enrollment.
REM ==============================================================================

echo [1/4] Checking connected ADB devices...
adb devices
if %ERRORLEVEL% NEQ 0 (
    echo Error: ADB not found or device not connected.
    exit /b 1
)

echo [2/4] Setting FRS Attendance Kiosk as Device Owner...
adb shell dpm set-device-owner com.frs.kiosk_app/.KioskDeviceAdminReceiver
if %ERRORLEVEL% NEQ 0 (
    echo Warning: If you see "Not allowed to set the device owner because there are already some accounts on the device",
    echo please remove all Google/corporate accounts from Settings or factory reset the tablet.
)

echo [3/4] Granting runtime hardware permissions (Camera, Storage, Stay-on-while-charging)...
adb shell pm grant com.frs.kiosk_app android.permission.CAMERA
adb shell svc power stayon true
adb shell settings put global stay_on_while_plugged_in 3

echo [4/4] Launching FRS Attendance Kiosk...
adb shell am start -n com.frs.kiosk_app/.MainActivity

echo.
echo Device Owner configuration complete. The tablet is locked into FRS Attendance Kiosk mode.
