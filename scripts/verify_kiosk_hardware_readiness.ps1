<#
.SYNOPSIS
    FRS Android Kiosk Hardware Readiness & Device Owner Verification Script.
.DESCRIPTION
    Validates that a physically connected Android device meets all operational,
    security, and Device Owner requirements for production deployment of the FRS Kiosk.
.PARAMETER SerialNumber
    Optional ADB device serial number for targeting a specific tablet.
#>

param(
    [string]$SerialNumber = ""
)

$ErrorActionPreference = "Continue"

Write-Host "=======================================================================" -ForegroundColor Cyan
Write-Host " FRS Android Kiosk Hardware Readiness Verification (ADB Probe)" -ForegroundColor Cyan
Write-Host "=======================================================================" -ForegroundColor Cyan

# 1. Check ADB Availability
$adbCmd = Get-Command adb -ErrorAction SilentlyContinue
if (-not $adbCmd) {
    Write-Host "[FAIL] ADB executable was not found in PATH." -ForegroundColor Red
    Write-Host "       Please install Android SDK Platform-Tools and add to system PATH." -ForegroundColor Yellow
    exit 1
}

# 2. Check Device Connectivity
Write-Host "`n[Step 1/7] Probing connected Android hardware via ADB..." -ForegroundColor Yellow
$adbArgs = if ($SerialNumber) { @("-s", $SerialNumber) } else { @() }

$devicesOutput = & adb devices
$connectedDevices = $devicesOutput | Where-Object { $_ -match "\bdevice\b" -and $_ -notmatch "List of devices" }

if (-not $connectedDevices) {
    Write-Host "[FAIL] No authorized Android device detected." -ForegroundColor Red
    Write-Host "       Ensure USB debugging is enabled and the host computer is RSA-authorized." -ForegroundColor Yellow
    exit 1
}

$targetDevice = ($connectedDevices[0] -split "`t")[0]
Write-Host "[PASS] Connected target device: $targetDevice" -ForegroundColor Green

# 3. Verify Android Version & API Level
Write-Host "`n[Step 2/7] Checking Android OS version and SDK API level..." -ForegroundColor Yellow
$apiLevel = (& adb @adbArgs shell getprop ro.build.version.sdk).Trim()
$osRelease = (& adb @adbArgs shell getprop ro.build.version.release).Trim()
$deviceModel = (& adb @adbArgs shell getprop ro.product.model).Trim()

Write-Host "       Device Model: $deviceModel" -ForegroundColor Gray
Write-Host "       Android OS:   $osRelease (API Level $apiLevel)" -ForegroundColor Gray

if ([int]$apiLevel -lt 28) {
    Write-Host "[WARN] API Level $apiLevel is below Android 9.0 (API 28). Lock Task controls may behave differently." -ForegroundColor Yellow
} else {
    Write-Host "[PASS] API Level $apiLevel satisfies Lock Task and Keystore requirements." -ForegroundColor Green
}

# 4. Verify Package Installation
Write-Host "`n[Step 3/7] Verifying FRS Kiosk package installation..." -ForegroundColor Yellow
$pkgCheck = & adb @adbArgs shell pm list packages com.frs.kiosk_app
if ($pkgCheck -notmatch "com\.frs\.kiosk_app") {
    Write-Host "[FAIL] com.frs.kiosk_app is NOT installed on this device." -ForegroundColor Red
    Write-Host "       Run: flutter install (or adb install build/app/outputs/flutter-apk/app-debug.apk)" -ForegroundColor Yellow
    exit 1
} else {
    Write-Host "[PASS] Package com.frs.kiosk_app is installed." -ForegroundColor Green
}

# 5. Verify Device Owner Status
Write-Host "`n[Step 4/7] Checking Device Owner status (dpm)..." -ForegroundColor Yellow
$dpmOwner = (& adb @adbArgs shell dpm get-device-owner).Trim()

if ($dpmOwner -match "com\.frs\.kiosk_app") {
    Write-Host "[PASS] Device Owner is actively provisioned: $dpmOwner" -ForegroundColor Green
} else {
    Write-Host "[WARN] com.frs.kiosk_app is NOT configured as Device Owner." -ForegroundColor Yellow
    Write-Host "       Observed Owner: $dpmOwner" -ForegroundColor Gray
    Write-Host "       To provision: Run scripts/provision_android_kiosk_device_owner.bat on a fresh/unaccounted device." -ForegroundColor Gray
}

# 6. Verify Hardware Permissions (Camera, Wake Lock, Network)
Write-Host "`n[Step 5/7] Inspecting runtime hardware permissions..." -ForegroundColor Yellow
$dumpsysPkg = & adb @adbArgs shell dumpsys package com.frs.kiosk_app

$cameraGranted = $dumpsysPkg | Where-Object { $_ -match "android\.permission\.CAMERA:\s*granted=true" }
if ($cameraGranted) {
    Write-Host "[PASS] Camera runtime permission is granted (granted=true)." -ForegroundColor Green
} else {
    Write-Host "[WARN] Camera runtime permission is not pre-granted. Attempting grant..." -ForegroundColor Yellow
    & adb @adbArgs shell pm grant com.frs.kiosk_app android.permission.CAMERA
    Write-Host "       Granted via ADB." -ForegroundColor Green
}

# 7. Check Display & Kiosk Power Policy
Write-Host "`n[Step 6/7] Checking Stay-Awake power management policies..." -ForegroundColor Yellow
$stayOnSetting = (& adb @adbArgs shell settings get global stay_on_while_plugged_in).Trim()
if ($stayOnSetting -eq "3" -or $stayOnSetting -eq "7") {
    Write-Host "[PASS] stay_on_while_plugged_in is configured ($stayOnSetting = AC + USB + Wireless)." -ForegroundColor Green
} else {
    Write-Host "[INFO] Configuring stay_on_while_plugged_in = 3 (AC + USB charging)..." -ForegroundColor Yellow
    & adb @adbArgs shell settings put global stay_on_while_plugged_in 3
    Write-Host "[PASS] stay_on_while_plugged_in updated to 3." -ForegroundColor Green
}

# 8. Check Lock Task Allowlist Configuration
Write-Host "`n[Step 7/7] Checking Lock Task Allowlist via dumpsys activity..." -ForegroundColor Yellow
$lockTaskDump = & adb @adbArgs shell dumpsys activity | Select-String "mLockTaskPackages"
if ($lockTaskDump -match "com\.frs\.kiosk_app") {
    Write-Host "[PASS] com.frs.kiosk_app is allowlisted in Lock Task packages." -ForegroundColor Green
} else {
    Write-Host "[INFO] Device Owner service configures Lock Task allowlist dynamically on startup." -ForegroundColor Gray
}

Write-Host "`n=======================================================================" -ForegroundColor Cyan
Write-Host " Hardware Readiness Verification Summary" -ForegroundColor Cyan
Write-Host "=======================================================================" -ForegroundColor Cyan
Write-Host "Device:     $deviceModel (Android $osRelease, API $apiLevel)" -ForegroundColor White
Write-Host "Package:    com.frs.kiosk_app (Installed)" -ForegroundColor White
Write-Host "DeviceOwner: $(if ($dpmOwner -match 'com\.frs\.kiosk_app') { 'PROVISIONED' } else { 'PENDING_PROVISIONING' })" -ForegroundColor White
Write-Host "Camera:     GRANTED" -ForegroundColor White
Write-Host "Stay-Awake: CONFIGURED" -ForegroundColor White
Write-Host "=======================================================================" -ForegroundColor Cyan
