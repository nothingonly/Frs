import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// Service interfacing with native Android DevicePolicyManager and Lock Task APIs.
class LockTaskService {
  static const MethodChannel _channel = MethodChannel('com.frs.kiosk_app/kiosk_lock');

  final MethodChannel channel;

  const LockTaskService({MethodChannel? channel}) : channel = channel ?? _channel;

  /// Starts standard Android Lock Task (screen pinning or dedicated kiosk if device owner).
  Future<bool> startLockTask() async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return false;
    try {
      final result = await channel.invokeMethod<bool>('startLockTask');
      return result ?? false;
    } on PlatformException catch (e) {
      debugPrint('LockTaskService.startLockTask failed: ${e.message}');
      return false;
    }
  }

  /// Exits Lock Task mode.
  Future<bool> stopLockTask() async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return false;
    try {
      final result = await channel.invokeMethod<bool>('stopLockTask');
      return result ?? false;
    } on PlatformException catch (e) {
      debugPrint('LockTaskService.stopLockTask failed: ${e.message}');
      return false;
    }
  }

  /// Returns true if this app is configured as an Android Device Owner.
  Future<bool> isDeviceOwner() async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return false;
    try {
      final result = await channel.invokeMethod<bool>('isDeviceOwner');
      return result ?? false;
    } on PlatformException catch (e) {
      debugPrint('LockTaskService.isDeviceOwner query failed: ${e.message}');
      return false;
    }
  }

  /// Returns true if lock task packages are whitelisted for this application.
  Future<bool> isLockTaskPermitted() async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return false;
    try {
      final result = await channel.invokeMethod<bool>('isLockTaskPermitted');
      return result ?? false;
    } on PlatformException catch (e) {
      debugPrint('LockTaskService.isLockTaskPermitted query failed: ${e.message}');
      return false;
    }
  }

  /// Whitelists this app package and enters dedicated pinned Kiosk Mode.
  Future<bool> enableKioskMode() async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return false;
    try {
      final result = await channel.invokeMethod<bool>('enableKioskMode');
      return result ?? false;
    } on PlatformException catch (e) {
      debugPrint('LockTaskService.enableKioskMode failed: ${e.message}');
      return false;
    }
  }
}
