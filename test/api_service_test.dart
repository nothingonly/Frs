import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:kiosk_app/config/app_config.dart';
import 'package:kiosk_app/exceptions/api_exceptions.dart';
import 'package:kiosk_app/models/punch_type.dart';
import 'package:kiosk_app/services/api_service.dart';

class BoundaryHttpClient extends http.BaseClient {
  BoundaryHttpClient({required this.statusCode, required this.body});
  final int statusCode;
  final String body;
  http.BaseRequest? lastRequest;
  int requests = 0;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    requests++;
    lastRequest = request;
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
  clientDeviceId: 'TEST_KIOSK_01',
  allowInsecureDevelopmentHttp: true,
);
final frames = <Uint8List>[
  Uint8List.fromList([1, 2, 3, 4, 5]),
  Uint8List.fromList([6, 7, 8, 9, 10]),
  Uint8List.fromList([11, 12, 13, 14, 15]),
];

void main() {
  group('FrsApiService contracts', () {
    test('GET /health parses backend health contract', () async {
      final client = BoundaryHttpClient(
        statusCode: 200,
        body: jsonEncode({
          'status': 'online', 'environment': 'development', 'database': 'healthy',
          'model_version': 'frs-v5:scrfd:arcface', 'similarity_threshold': 0.72,
          'threshold_status': 'CALIBRATED', 'model_components': {'detection_primary': 'READY'},
          'liveness_required': true, 'ready_for_attendance': true,
        }),
      );
      final result = await FrsApiService(config: config, client: client).checkHealth();
      expect(result.status, 'online');
      expect(result.database, 'healthy');
      expect(result.modelVersion, 'frs-v5:scrfd:arcface');
      expect(result.similarityThreshold, 0.72);
      expect(result.isHealthy, isTrue);
    });

    test('verification sends three repeated images parts', () async {
      final client = BoundaryHttpClient(
        statusCode: 200,
        body: jsonEncode({
          'status': 'success', 'attendance_id': 'att_test', 'user_id': 'person_test',
          'employee_id': 'EMP100', 'punch_type': 'CHECK_IN',
          'timestamp': '2026-10-19T14:00:00Z', 'similarity_score': 0.84,
          'threshold': 0.72, 'message': 'Biometric verification successful.',
        }),
      );
      final result = await FrsApiService(config: config, client: client).verifyAttendance(
        employeeId: 'EMP100', imageFrames: frames, punchType: PunchType.checkIn,
      );
      expect(result.employeeId, 'EMP100');
      expect(result.similarityScore, 0.84);
      final request = client.lastRequest! as http.MultipartRequest;
      expect(request.url.path, '/api/v1/attendance/verify');
      expect(request.headers['Authorization'], 'Bearer ${config.apiKeySecret}');
      expect(request.fields['employee_id'], 'EMP100');
      expect(request.files, hasLength(3));
      expect(request.files.every((part) => part.field == 'images'), isTrue);
      expect(request.files.map((part) => part.filename).toSet(), hasLength(3));
    });

    test('automatic identification parses identity response', () async {
      final client = BoundaryHttpClient(
        statusCode: 200,
        body: jsonEncode({
          'status': 'success', 'attendance_id': 'att_id', 'user_id': 'person_a',
          'employee_id': 'EMP002', 'full_name': 'Example Employee', 'department': 'Engineering',
          'punch_type': 'CHECK_OUT', 'timestamp': '2026-10-19T14:02:00Z',
          'similarity_score': 0.88, 'threshold': 0.74, 'message': 'Attendance recorded.',
        }),
      );
      final result = await FrsApiService(config: config, client: client).identifyAttendance(
        imageFrames: frames, punchType: PunchType.checkOut,
      );
      expect(result.employeeId, 'EMP002');
      expect(result.fullName, 'Example Employee');
      final request = client.lastRequest! as http.MultipartRequest;
      expect(request.url.path, '/api/v1/attendance/identify');
      expect(request.fields['punch_type'], 'CHECK_OUT');
      expect(request.files, hasLength(3));
    });

    test('open-session endpoint returns persisted session metadata', () async {
      final client = BoundaryHttpClient(
        statusCode: 200,
        body: jsonEncode({
          'items': [
            {
              'session_id': 'session-1', 'class_group_id': 'group-1',
              'subject_name': 'Operating Systems', 'subject_code': 'CS401',
              'starts_at': '2026-10-20T04:00:00Z', 'department_code': 'CSE',
              'year_of_study': 3, 'section': 'A', 'academic_year': '2026-2027',
            },
          ],
        }),
      );
      final sessions = await FrsApiService(config: config, client: client).listOpenAttendanceSessions();
      expect(sessions, hasLength(1));
      expect(sessions.single.sessionId, 'session-1');
      expect(sessions.single.classGroupId, 'group-1');
      expect(sessions.single.displayLabel, contains('Operating Systems'));
      expect(client.lastRequest!.url.path, '/api/v1/attendance/sessions/open');
      expect(client.lastRequest!.headers['Authorization'], 'Bearer ${config.apiKeySecret}');
    });

    test('session capture queue sends frames with stable idempotency key', () async {
      final client = BoundaryHttpClient(
        statusCode: 202,
        body: jsonEncode({
          'batch_id': 'batch-1', 'attendance_session_id': 'session-1',
          'class_group_id': 'group-1', 'status': 'QUEUED', 'frame_count': 3,
          'attempts': 0, 'max_attempts': 3, 'created_at': '2026-10-20T04:00:00Z',
          'updated_at': '2026-10-20T04:00:00Z', 'result': null, 'error': null,
        }),
      );
      final job = await FrsApiService(config: config, client: client).enqueueCaptureBatch(
        attendanceSessionId: 'session-1',
        idempotencyKey: 'stable-request-key-001',
        imageFrames: frames,
        punchType: PunchType.checkIn,
      );
      expect(job.batchId, 'batch-1');
      expect(job.status, 'QUEUED');
      final request = client.lastRequest! as http.MultipartRequest;
      expect(request.url.path, '/api/v1/attendance/sessions/session-1/batches');
      expect(request.headers['Authorization'], 'Bearer ${config.apiKeySecret}');
      expect(request.fields['idempotency_key'], 'stable-request-key-001');
      expect(request.fields['punch_type'], 'CHECK_IN');
      expect(request.files, hasLength(3));
      expect(request.files.every((part) => part.field == 'images'), isTrue);
    });

    test('capture batch status parses real server-persisted success result', () async {
      final client = BoundaryHttpClient(
        statusCode: 200,
        body: jsonEncode({
          'batch_id': 'batch-1', 'attendance_session_id': 'session-1',
          'class_group_id': 'group-1', 'status': 'SUCCEEDED', 'frame_count': 3,
          'attempts': 1, 'max_attempts': 3, 'created_at': '2026-10-20T04:00:00Z',
          'updated_at': '2026-10-20T04:00:05Z', 'completed_at': '2026-10-20T04:00:05Z',
          'error': null,
          'result': {
            'status': 'success', 'attendance_id': 'att-1', 'user_id': 'person-1',
            'employee_id': 'CSE-001', 'full_name': 'Enrolled Student', 'department': 'CSE',
            'punch_type': 'CHECK_IN', 'timestamp': '2026-10-20T04:00:05Z',
            'similarity_score': 0.91, 'threshold': 0.76, 'message': 'Recorded',
          },
        }),
      );
      final job = await FrsApiService(config: config, client: client).getCaptureBatch('batch-1');
      expect(job.status, 'SUCCEEDED');
      expect(job.result?['attendance_id'], 'att-1');
      expect(client.lastRequest!.url.path, '/api/v1/attendance/batches/batch-1');
    });
    test('admin enrollment uses distinct admin credential', () async {
      const adminKey = 'independent-admin-api-credential-32-chars-min';
      final client = BoundaryHttpClient(
        statusCode: 201,
        body: jsonEncode({'status': 'success', 'employee_id': 'EMP003', 'enrollment_version': 1}),
      );
      final result = await FrsApiService(config: config, client: client).adminEnroll(
        employeeId: 'EMP003', fullName: 'Example Employee', department: 'Operations',
        imageFrames: frames, adminApiKey: adminKey,
      );
      expect(result['enrollment_version'], 1);
      final request = client.lastRequest! as http.MultipartRequest;
      expect(request.url.path, '/api/v1/biometrics/enroll/admin');
      expect(request.headers['Authorization'], 'Bearer $adminKey');
      expect(request.headers['Authorization'], isNot('Bearer ${config.apiKeySecret}'));
      expect(request.files, hasLength(3));
      expect(request.files.every((part) => part.field == 'images'), isTrue);
    });

    test('single image is rejected before network transmission', () async {
      final client = BoundaryHttpClient(statusCode: 200, body: '{}');
      await expectLater(
        FrsApiService(config: config, client: client).identifyAttendance(
          imageFrames: [frames.first], punchType: PunchType.checkIn,
        ),
        throwsA(isA<BiometricQualityException>()),
      );
      expect(client.requests, 0);
    });

    test('oversized frame is rejected before network transmission', () async {
      final client = BoundaryHttpClient(statusCode: 200, body: '{}');
      await expectLater(
        FrsApiService(config: config, client: client).identifyAttendance(
          imageFrames: [Uint8List(config.maxUploadSizeBytes + 1), frames[1], frames[2]],
          punchType: PunchType.checkIn,
        ),
        throwsA(isA<PayloadTooLargeException>()),
      );
      expect(client.requests, 0);
    });

    test('unauthenticated backend response is surfaced as authentication failure', () async {
      final client = BoundaryHttpClient(
        statusCode: 401,
        body: jsonEncode({'detail': 'Valid kiosk device bearer credentials are required.'}),
      );
      await expectLater(
        FrsApiService(config: config, client: client).identifyAttendance(
          imageFrames: frames, punchType: PunchType.checkIn,
        ),
        throwsA(isA<AuthenticationException>()),
      );
    });

    test('non-loopback plain HTTP is refused even with development toggle', () async {
      const insecureConfig = AppConfig(
        apiBaseUrl: 'http://192.168.1.50:8000',
        apiKeySecret: 'test-kiosk-device-credential-32chars-min',
        clientDeviceId: 'TEST_KIOSK_01',
        allowInsecureDevelopmentHttp: true,
      );
      final client = BoundaryHttpClient(statusCode: 200, body: '{}');
      await expectLater(
        FrsApiService(config: insecureConfig, client: client).checkHealth(),
        throwsA(isA<FormatException>()),
      );
      expect(client.requests, 0);
    });
  });
}
