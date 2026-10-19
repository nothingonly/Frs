import 'dart:convert';
import 'dart:typed_data';
import 'package:http/http.dart' as http;

import 'package:kiosk_app/config/app_config.dart';
import 'package:kiosk_app/models/punch_type.dart';
import 'package:kiosk_app/services/api_service.dart';
import 'package:kiosk_app/state/kiosk_state.dart';

class DelayedMockHttpClient extends http.BaseClient {
  final int statusCode;
  final String responseBody;
  final Duration delay;
  int callCount = 0;

  DelayedMockHttpClient({
    this.statusCode = 200,
    this.responseBody = '{}',
    this.delay = const Duration(milliseconds: 50),
  });

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    callCount++;
    await Future.delayed(delay);
    final bytes = utf8.encode(responseBody);
    return http.StreamedResponse(
      Stream<List<int>>.value(bytes),
      statusCode,
      headers: {'content-type': 'application/json'},
    );
  }
}

Future<void> main() async {
  int passed = 0;
  int failed = 0;

  Future<void> test(String description, Future<void> Function() body) async {
    try {
      await body();
      passed++;
      print('  ✓ $description');
    } catch (e, st) {
      failed++;
      print('  ✗ $description');
      print('    Error: $e');
      print('    $st');
    }
  }

  void expect(dynamic actual, dynamic expected, [String? reason]) {
    if (actual != expected) {
      throw Exception('Expected <$expected> but got <$actual>${reason != null ? " ($reason)" : ""}');
    }
  }

  print('Running KioskState Tests:');

  const config = AppConfig(
    apiBaseUrl: 'http://localhost:8000',
    apiKeySecret: 'test-kiosk-device-key-that-is-long-enough',
    allowInsecureDevelopmentHttp: true,
  );
  final testImage = Uint8List.fromList([10, 20, 30, 40]);
  final testFrames = <Uint8List>[
    Uint8List.fromList([10, 20, 30, 40]),
    Uint8List.fromList([40, 30, 20, 10]),
    Uint8List.fromList([12, 22, 32, 42]),
  ];

  await test('Initial state is idle and cannot submit', () async {
    final state = KioskState();
    expect(state.status, KioskStatus.idle);
    expect(state.employeeId, '');
    expect(state.punchType, PunchType.checkIn);
    expect(state.capturedImage, null);
    expect(state.isSubmitting, false);
    expect(state.canSubmit, false);
  });

  await test('Punch type switching works correctly', () async {
    final state = KioskState();
    expect(state.punchType, PunchType.checkIn);

    state.setPunchType(PunchType.checkOut);
    expect(state.punchType, PunchType.checkOut);

    state.setPunchType(PunchType.checkIn);
    expect(state.punchType, PunchType.checkIn);
  });

  await test('1:N canSubmit requires only captured image (NO employee ID needed)', () async {
    final state = KioskState();
    expect(state.canSubmit, false);

    // A single frame is not temporal evidence and must never be submitted.
    state.setCapturedImage(testImage);
    expect(state.canSubmit, false);

    // Kiosk captures three distinct camera exposures WITHOUT entering an employee ID.
    state.setCapturedImages(testFrames);
    expect(state.canSubmit, true, '1:N requires three actual frames, not an employee ID');
    expect(state.status, KioskStatus.readyToSubmit);

    state.clearCapturedImage();
    expect(state.canSubmit, false);
  });

  await test('1:1 canSubmit1To1 still requires both employee ID and captured image', () async {
    final state = KioskState();
    expect(state.canSubmit1To1, false);

    state.setCapturedImages(testFrames);
    expect(state.canSubmit1To1, false);

    state.setEmployeeId('EMP001');
    expect(state.canSubmit1To1, true);
  });

  await test('In-flight lock: Prevents duplicate submissions while 1:N request is pending', () async {
    final mockClient = DelayedMockHttpClient(
      statusCode: 200,
      responseBody: jsonEncode({
        'status': 'success',
        'attendance_id': 'att_test',
        'user_id': 'usr_test',
        'employee_id': 'EMP001',
        'full_name': 'Jane Doe',
        'department': 'Engineering',
        'punch_type': 'CHECK_IN',
        'timestamp': '2026-10-10T14:30:00Z',
        'similarity_score': 0.88,
        'threshold': 0.363,
        'message': 'Automatic face attendance recorded successfully.',
      }),
      delay: const Duration(milliseconds: 100),
    );
    final service = FrsApiService(config: config, client: mockClient);

    final state = KioskState();
    state.setCapturedImages(testFrames);

    // Launch first 1:N identification (takes 100ms)
    final future1 = state.submitAutomaticIdentification(service);
    expect(state.isSubmitting, true);
    expect(state.canSubmit, false); // Locked!

    // Attempt second submission immediately while first is in-flight
    final future2 = state.submitAutomaticIdentification(service);

    await Future.wait([future1, future2]);

    expect(state.isSubmitting, false);
    expect(state.status, KioskStatus.accepted);
    expect(state.matchedEmployeeName, 'Jane Doe');
    expect(state.matchedEmployeeId, 'EMP001');
    expect(state.matchedDepartment, 'Engineering');
    // CRITICAL: Ensure only ONE HTTP request was dispatched!
    expect(mockClient.callCount, 1, 'Duplicate submission was prevented by in-flight lock');
    state.dispose();
  });

  await test('Handles unrecognized face state transition on 1:N identification', () async {
    final mockClient = DelayedMockHttpClient(
      statusCode: 404,
      responseBody: jsonEncode({
        'detail': {
          'message': 'No matching active employee template found for the submitted face.',
          'similarity_score': 0.22,
          'required_threshold': 0.363,
        }
      }),
    );
    final service = FrsApiService(config: config, client: mockClient);

    final state = KioskState();
    state.setCapturedImages(testFrames);

    await state.submitAutomaticIdentification(service);

    expect(state.status, KioskStatus.unrecognized);
    expect(state.lastSimilarityScore, 0.22);
    expect(state.requiredThreshold, 0.363);
    expect(state.isSubmitting, false);
    state.dispose();
  });

  await test('Handles ambiguous biometric match state transition on 1:N identification', () async {
    final mockClient = DelayedMockHttpClient(
      statusCode: 409,
      responseBody: jsonEncode({
        'detail': {
          'message': 'Ambiguous biometric match: multiple candidates exceed threshold within margin 0.0500.',
          'ambiguity_margin': 0.05,
          'first_candidate': 'EMP001 (score: 0.7500)',
          'second_candidate': 'EMP002 (score: 0.7400)',
        }
      }),
    );
    final service = FrsApiService(config: config, client: mockClient);

    final state = KioskState();
    state.setCapturedImages(testFrames);

    await state.submitAutomaticIdentification(service);

    expect(state.status, KioskStatus.ambiguous);
    expect(state.ambiguousCandidate1, 'EMP001 (score: 0.7500)');
    expect(state.ambiguousCandidate2, 'EMP002 (score: 0.7400)');
    expect(state.isSubmitting, false);
    state.dispose();
  });

  await test('Handles cooldown state transition on 1:N identification', () async {
    final mockClient = DelayedMockHttpClient(
      statusCode: 409,
      responseBody: jsonEncode({
        'detail': {
          'message': 'Attendance already recorded within cooldown window.',
          'remaining_seconds': 180,
          'last_punch_time': '2026-10-10T14:00:00Z',
        }
      }),
    );
    final service = FrsApiService(config: config, client: mockClient);

    final state = KioskState();
    state.setCapturedImages(testFrames);

    await state.submitAutomaticIdentification(service);

    expect(state.status, KioskStatus.cooldown);
    expect(state.cooldownRemainingSeconds, 180);
    expect(state.isSubmitting, false);
    state.dispose();
  });

  await test('Reset restores all fields back to idle', () async {
    final state = KioskState();
    state.setCapturedImages(testFrames);
    state.setPunchType(PunchType.checkOut);

    state.reset();

    expect(state.status, KioskStatus.idle);
    expect(state.employeeId, '');
    expect(state.punchType, PunchType.checkIn);
    expect(state.capturedImage, null);
    expect(state.canSubmit, false);
    state.dispose();
  });

  print('KioskState Tests: $passed passed, $failed failed.\n');
  if (failed > 0) throw Exception('KioskState tests failed');
}
