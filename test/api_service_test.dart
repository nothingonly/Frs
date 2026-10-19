import 'dart:convert';
import 'dart:typed_data';
import 'package:http/http.dart' as http;

import 'package:kiosk_app/config/app_config.dart';
import 'package:kiosk_app/exceptions/api_exceptions.dart';
import 'package:kiosk_app/models/punch_type.dart';
import 'package:kiosk_app/services/api_service.dart';

/// Test HTTP client that mocks server responses at the HTTP boundary.
class MockHttpClient extends http.BaseClient {
  int statusCode;
  String responseBody;
  http.BaseRequest? capturedRequest;
  bool shouldThrowNetworkError;

  MockHttpClient({
    this.statusCode = 200,
    this.responseBody = '{}',
    this.shouldThrowNetworkError = false,
  });

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    capturedRequest = request;
    if (shouldThrowNetworkError) {
      throw http.ClientException('Connection refused / SocketException');
    }

    final bytes = utf8.encode(responseBody);
    final stream = Stream<List<int>>.value(bytes);
    return http.StreamedResponse(
      stream,
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

  print('Running FrsApiService Boundary Tests:');

  const config = AppConfig(
    apiBaseUrl: 'http://localhost:8000',
    apiKeySecret: 'test_kiosk_secret_key_1234567890',
    clientDeviceId: 'TEST_KIOSK_01',
    allowInsecureDevelopmentHttp: true,
  );
  final probeBytes = Uint8List.fromList([1, 2, 3, 4, 5]);
  final probeFrames = <Uint8List>[
    Uint8List.fromList([1, 2, 3, 4, 5]),
    Uint8List.fromList([6, 7, 8, 9, 10]),
    Uint8List.fromList([11, 12, 13, 14, 15]),
  ];

  await test('GET /health parses health status correctly', () async {
    final mockClient = MockHttpClient(
      statusCode: 200,
      responseBody: jsonEncode({
        'status': 'online',
        'environment': 'development',
        'database': 'healthy',
        'model_version': 'arcface_r100_v1',
        'similarity_threshold': 0.363,
        'threshold_status': 'UNRECALIBRATED_BASELINE',
      }),
    );
    final service = FrsApiService(config: config, client: mockClient);
    final health = await service.checkHealth();
    expect(health.status, 'online');
    expect(health.database, 'healthy');
    expect(health.modelVersion, 'arcface_r100_v1');
    expect(health.similarityThreshold, 0.363);
    expect(health.isHealthy, true);
  });

  await test('POST /attendance/verify returns AttendanceVerificationResult on 200 OK', () async {
    final mockClient = MockHttpClient(
      statusCode: 200,
      responseBody: jsonEncode({
        'status': 'success',
        'attendance_id': 'att_abc',
        'user_id': 'usr_xyz',
        'employee_id': 'EMP100',
        'punch_type': 'CHECK_IN',
        'timestamp': '2026-10-10T14:00:00Z',
        'similarity_score': 0.825,
        'threshold': 0.363,
        'message': 'Biometric verification successful.',
      }),
    );
    final service = FrsApiService(config: config, client: mockClient);
    final res = await service.verifyAttendance(
      employeeId: 'EMP100',
      imageFrames: probeFrames,
      punchType: PunchType.checkIn,
    );

    expect(res.status, 'success');
    expect(res.employeeId, 'EMP100');
    expect(res.punchType, 'CHECK_IN');
    expect(res.similarityScore, 0.825);
    expect(mockClient.capturedRequest?.headers['Authorization'], 'Bearer test_kiosk_secret_key_1234567890');
  });

  await test('Throws BiometricMismatchException on 401 with similarity_score', () async {
    final mockClient = MockHttpClient(
      statusCode: 401,
      responseBody: jsonEncode({
        'detail': {
          'message': 'Face verification failed. Similarity score 0.2100 is below threshold 0.3630.',
          'similarity_score': 0.21,
          'required_threshold': 0.363,
        }
      }),
    );
    final service = FrsApiService(config: config, client: mockClient);

    bool thrown = false;
    try {
      await service.verifyAttendance(
        employeeId: 'EMP100',
        imageFrames: probeFrames,
        punchType: PunchType.checkIn,
      );
    } on BiometricMismatchException catch (e) {
      thrown = true;
      expect(e.similarityScore, 0.21);
      expect(e.requiredThreshold, 0.363);
    }
    expect(thrown, true, 'Should throw BiometricMismatchException');
  });

  await test('Throws AuthenticationException on 401 with invalid secret', () async {
    final mockClient = MockHttpClient(
      statusCode: 401,
      responseBody: jsonEncode({'detail': 'Invalid API key secret'}),
    );
    final service = FrsApiService(config: config, client: mockClient);

    bool thrown = false;
    try {
      await service.verifyAttendance(
        employeeId: 'EMP100',
        imageFrames: probeFrames,
        punchType: PunchType.checkIn,
      );
    } on AuthenticationException catch (e) {
      thrown = true;
      expect(e.message, 'Invalid API key secret');
    }
    expect(thrown, true, 'Should throw AuthenticationException');
  });

  await test('Throws CooldownException on 409 Conflict', () async {
    final mockClient = MockHttpClient(
      statusCode: 409,
      responseBody: jsonEncode({
        'detail': {
          'message': 'Attendance already recorded within cooldown window (remaining: 245s).',
          'remaining_seconds': 245,
          'last_punch_time': '2026-10-10T13:58:00Z',
        }
      }),
    );
    final service = FrsApiService(config: config, client: mockClient);

    bool thrown = false;
    try {
      await service.verifyAttendance(
        employeeId: 'EMP100',
        imageFrames: probeFrames,
        punchType: PunchType.checkIn,
      );
    } on CooldownException catch (e) {
      thrown = true;
      expect(e.remainingSeconds, 245);
    }
    expect(thrown, true, 'Should throw CooldownException');
  });

  await test('Throws BiometricQualityException on 400 sharpness blur rejection', () async {
    final mockClient = MockHttpClient(
      statusCode: 400,
      responseBody: jsonEncode({
        'detail': 'Image quality check failed: sharpness variance 18.4 is below required threshold 25.0'
      }),
    );
    final service = FrsApiService(config: config, client: mockClient);

    bool thrown = false;
    try {
      await service.verifyAttendance(
        employeeId: 'EMP100',
        imageFrames: probeFrames,
        punchType: PunchType.checkIn,
      );
    } on BiometricQualityException catch (e) {
      thrown = true;
      expect(e.message.contains('sharpness'), true);
    }
    expect(thrown, true, 'Should throw BiometricQualityException');
  });

  await test('Throws IncompatibleModelVersionException on 400 model version mismatch', () async {
    final mockClient = MockHttpClient(
      statusCode: 400,
      responseBody: jsonEncode({
        'detail': 'Biometric template was encoded with incompatible model version old_v1. Re-enrollment required.'
      }),
    );
    final service = FrsApiService(config: config, client: mockClient);

    bool thrown = false;
    try {
      await service.verifyAttendance(
        employeeId: 'EMP100',
        imageFrames: probeFrames,
        punchType: PunchType.checkIn,
      );
    } on IncompatibleModelVersionException catch (e) {
      thrown = true;
      expect(e.message.contains('incompatible model'), true);
    }
    expect(thrown, true, 'Should throw IncompatibleModelVersionException');
  });

  await test('Throws InactiveEmployeeException on 403 Forbidden', () async {
    final mockClient = MockHttpClient(
      statusCode: 403,
      responseBody: jsonEncode({'detail': 'Employee is inactive'}),
    );
    final service = FrsApiService(config: config, client: mockClient);

    bool thrown = false;
    try {
      await service.verifyAttendance(
        employeeId: 'EMP100',
        imageFrames: probeFrames,
        punchType: PunchType.checkIn,
      );
    } on InactiveEmployeeException catch (e) {
      thrown = true;
      expect(e.message, 'Employee is inactive');
    }
    expect(thrown, true, 'Should throw InactiveEmployeeException');
  });

  await test('Throws EmployeeNotFoundException on 404 Employee not found', () async {
    final mockClient = MockHttpClient(
      statusCode: 404,
      responseBody: jsonEncode({'detail': 'Employee not found'}),
    );
    final service = FrsApiService(config: config, client: mockClient);

    bool thrown = false;
    try {
      await service.verifyAttendance(
        employeeId: 'EMP999',
        imageFrames: probeFrames,
        punchType: PunchType.checkIn,
      );
    } on EmployeeNotFoundException catch (e) {
      thrown = true;
      expect(e.message, 'Employee not found');
    }
    expect(thrown, true, 'Should throw EmployeeNotFoundException');
  });

  await test('Throws TemplateNotEnrolledException on 404 template missing', () async {
    final mockClient = MockHttpClient(
      statusCode: 404,
      responseBody: jsonEncode({'detail': 'No biometric template enrolled for employee'}),
    );
    final service = FrsApiService(config: config, client: mockClient);

    bool thrown = false;
    try {
      await service.verifyAttendance(
        employeeId: 'EMP100',
        imageFrames: probeFrames,
        punchType: PunchType.checkIn,
      );
    } on TemplateNotEnrolledException catch (e) {
      thrown = true;
      expect(e.message.contains('No biometric template'), true);
    }
    expect(thrown, true, 'Should throw TemplateNotEnrolledException');
  });

  await test('Throws PayloadTooLargeException if payload exceeds 5MB', () async {
    final oversizedBytes = Uint8List(6 * 1024 * 1024); // 6MB
    final mockClient = MockHttpClient(statusCode: 200);
    final service = FrsApiService(config: config, client: mockClient);

    bool thrown = false;
    try {
      await service.verifyAttendance(
        employeeId: 'EMP100',
        imageFrames: <Uint8List>[oversizedBytes, probeFrames[1], probeFrames[2]],
        punchType: PunchType.checkIn,
      );
    } on PayloadTooLargeException catch (e) {
      thrown = true;
      expect(e.message.contains('exceeds limit'), true);
    }
    expect(thrown, true, 'Should throw PayloadTooLargeException client-side');
  });

  await test('Throws MultipleFacesDetectedException on 422 Multiple Faces', () async {
    final mockClient = MockHttpClient(
      statusCode: 422,
      responseBody: jsonEncode({'detail': 'Multiple faces detected (2 faces). Single face required.'}),
    );
    final service = FrsApiService(config: config, client: mockClient);

    bool thrown = false;
    try {
      await service.verifyAttendance(
        employeeId: 'EMP100',
        imageFrames: probeFrames,
        punchType: PunchType.checkIn,
      );
    } on MultipleFacesDetectedException catch (e) {
      thrown = true;
      expect(e.message.contains('Multiple faces'), true);
    }
    expect(thrown, true, 'Should throw MultipleFacesDetectedException');
  });

  await test('Throws NoFaceDetectedException on 422 No Face', () async {
    final mockClient = MockHttpClient(
      statusCode: 422,
      responseBody: jsonEncode({'detail': 'No face detected in probe image'}),
    );
    final service = FrsApiService(config: config, client: mockClient);

    bool thrown = false;
    try {
      await service.verifyAttendance(
        employeeId: 'EMP100',
        imageFrames: probeFrames,
        punchType: PunchType.checkIn,
      );
    } on NoFaceDetectedException catch (e) {
      thrown = true;
      expect(e.message.contains('No face'), true);
    }
    expect(thrown, true, 'Should throw NoFaceDetectedException');
  });

  await test('Throws NetworkException on connection failure', () async {
    final mockClient = MockHttpClient(shouldThrowNetworkError: true);
    final service = FrsApiService(config: config, client: mockClient);

    bool thrown = false;
    try {
      await service.verifyAttendance(
        employeeId: 'EMP100',
        imageFrames: probeFrames,
        punchType: PunchType.checkIn,
      );
    } on NetworkException catch (e) {
      thrown = true;
      expect(e.message.contains('Network transmission failure'), true);
    }
    expect(thrown, true, 'Should throw NetworkException');
  });

  print('FrsApiService Boundary Tests: $passed passed, $failed failed.\n');
  if (failed > 0) throw Exception('FrsApiService boundary tests failed');
}
