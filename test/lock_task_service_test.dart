import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kiosk_app/services/lock_task_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('LockTaskService tests', () {
    const channel = MethodChannel('com.frs.kiosk_app/kiosk_lock');
    final log = <MethodCall>[];

    setUp(() {
      log.clear();
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (MethodCall methodCall) async {
        log.add(methodCall);
        switch (methodCall.method) {
          case 'startLockTask':
            return true;
          case 'stopLockTask':
            return true;
          case 'isDeviceOwner':
            return true;
          case 'isLockTaskPermitted':
            return true;
          case 'enableKioskMode':
            return true;
          default:
            return null;
        }
      });
    });

    tearDown(() {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, null);
    });

    test('startLockTask and stopLockTask invoke channel methods', () async {
      const service = LockTaskService(channel: channel);
      // In flutter_test default target platform is android (or can be tested with channel directly)
      final start = await service.startLockTask();
      expect(start, isTrue);
      expect(log.last.method, 'startLockTask');

      final stop = await service.stopLockTask();
      expect(stop, isTrue);
      expect(log.last.method, 'stopLockTask');
    });

    test('isDeviceOwner and isLockTaskPermitted query device admin status', () async {
      const service = LockTaskService(channel: channel);
      final isOwner = await service.isDeviceOwner();
      expect(isOwner, isTrue);
      expect(log.last.method, 'isDeviceOwner');

      final isPermitted = await service.isLockTaskPermitted();
      expect(isPermitted, isTrue);
      expect(log.last.method, 'isLockTaskPermitted');
    });

    test('enableKioskMode configures device policy and starts lock task', () async {
      const service = LockTaskService(channel: channel);
      final enabled = await service.enableKioskMode();
      expect(enabled, isTrue);
      expect(log.last.method, 'enableKioskMode');
    });
  });
}
