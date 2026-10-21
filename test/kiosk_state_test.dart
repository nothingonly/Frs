import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:kiosk_app/config/app_config.dart';
import 'package:kiosk_app/models/punch_type.dart';
import 'package:kiosk_app/services/api_service.dart';
import 'package:kiosk_app/state/kiosk_state.dart';

class StateHttpClient extends http.BaseClient {
  StateHttpClient({required this.statusCode, required this.body, this.delay = Duration.zero});
  final int statusCode;
  final String body;
  final Duration delay;
  int callCount = 0;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    callCount++;
    if (delay > Duration.zero) await Future<void>.delayed(delay);
    return http.StreamedResponse(
      Stream<List<int>>.value(utf8.encode(body)),
      statusCode,
      headers: const {'content-type': 'application/json'},
    );
  }
}

const config = AppConfig(
  apiBaseUrl: 'http://localhost:8000',
  apiKeySecret: 'test-kiosk-device-credential-32chars-min',
  allowInsecureDevelopmentHttp: true,
);
final frames = <Uint8List>[
  Uint8List.fromList([10, 20, 30, 40]),
  Uint8List.fromList([40, 30, 20, 10]),
  Uint8List.fromList([12, 22, 32, 42]),
];

String successBody() => jsonEncode({
      'status': 'success',
      'attendance_id': 'att_test',
      'user_id': 'person_test',
      'employee_id': 'EMP001',
      'full_name': 'Test Employee',
      'department': 'Engineering',
      'punch_type': 'CHECK_IN',
      'timestamp': '2026-10-19T14:00:00Z',
      'similarity_score': 0.91,
      'threshold': 0.77,
      'message': 'Attendance recorded.',
    });

void main() {
  group('KioskState temporal attendance behavior', () {
    test('starts idle and cannot submit without a burst', () {
      final state = KioskState();
      expect(state.status, KioskStatus.idle);
      expect(state.hasUsableBurst, isFalse);
      expect(state.canSubmit, isFalse);
      state.dispose();
    });

    test('one frame is rejected; three actual frames allow 1:N submit', () {
      final state = KioskState();
      state.setCapturedImage(frames.first);
      expect(state.hasUsableBurst, isFalse);
      expect(state.canSubmit, isFalse);
      state.setCapturedImages(frames);
      expect(state.hasUsableBurst, isTrue);
      expect(state.canSubmit, isTrue);
      state.clearCapturedImage();
      expect(state.canSubmit, isFalse);
      state.dispose();
    });

    test('1:1 verification requires both employee ID and a complete burst', () {
      final state = KioskState();
      state.setCapturedImages(frames);
      expect(state.canSubmit1To1, isFalse);
      state.setEmployeeId('EMP001');
      expect(state.canSubmit1To1, isTrue);
      state.setEmployeeId('  ');
      expect(state.canSubmit1To1, isFalse);
      state.dispose();
    });

    test('punch selector and state listeners update synchronously', () {
      final state = KioskState();
      var notifications = 0;
      void listener() => notifications++;
      state.addListener(listener);
      state.setPunchType(PunchType.checkOut);
      state.setEmployeeId('EMP9');
      state.appendDigit('2');
      expect(state.punchType, PunchType.checkOut);
      expect(state.employeeId, 'EMP92');
      expect(notifications, greaterThanOrEqualTo(3));
      state.removeListener(listener);
      state.clearEmployeeId();
      expect(notifications, 3);
      state.dispose();
    });

    test('real API success changes state and preserves server-returned identity', () async {
      final client = StateHttpClient(statusCode: 200, body: successBody());
      final service = FrsApiService(config: config, client: client);
      final state = KioskState()..setCapturedImages(frames);
      await state.submitAutomaticIdentification(service);
      expect(client.callCount, 1);
      expect(state.status, KioskStatus.accepted);
      expect(state.lastIdentificationResult?.employeeId, 'EMP001');
      expect(state.matchedEmployeeName, 'Test Employee');
      expect(state.lastSimilarityScore, 0.91);
      state.dispose();
      client.close();
    });

    test('duplicate tap while request is in flight sends only one API request', () async {
      final client = StateHttpClient(
        statusCode: 200,
        body: successBody(),
        delay: const Duration(milliseconds: 100),
      );
      final service = FrsApiService(config: config, client: client);
      final state = KioskState()..setCapturedImages(frames);
      final first = state.submitAutomaticIdentification(service);
      final second = state.submitAutomaticIdentification(service);
      await Future.wait([first, second]);
      expect(client.callCount, 1);
      expect(state.status, KioskStatus.accepted);
      state.dispose();
      client.close();
    });

    test('uncertain biometric server outcome is not converted to acceptance', () async {
      final client = StateHttpClient(
        statusCode: 409,
        body: jsonEncode({
          'detail': {
            'message': 'The biometric evidence is ambiguous; no attendance was recorded.',
            'ambiguity_margin': 0.05,
            'first_candidate': 'person-a',
            'second_candidate': 'person-b',
          },
        }),
      );
      final service = FrsApiService(config: config, client: client);
      final state = KioskState()..setCapturedImages(frames);
      await state.submitAutomaticIdentification(service);
      expect(state.status, KioskStatus.ambiguous);
      expect(state.status, isNot(KioskStatus.accepted));
      expect(state.ambiguousCandidate1, 'person-a');
      state.dispose();
      client.close();
    });
  });
}
