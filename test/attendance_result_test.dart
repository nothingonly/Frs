import 'package:kiosk_app/models/attendance_result.dart';

void main() {
  int passed = 0;
  int failed = 0;

  void test(String description, void Function() body) {
    try {
      body();
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

  print('Running AttendanceResult Tests:');

  test('Parses valid success verification JSON correctly', () {
    final sampleJson = {
      'status': 'success',
      'attendance_id': 'att_12345678-abcd-ef01-2345-6789abcdef01',
      'user_id': 'usr_abcdef01-2345-6789-abcd-ef0123456789',
      'employee_id': 'EMP001',
      'punch_type': 'CHECK_IN',
      'timestamp': '2026-10-10T13:00:00Z',
      'similarity_score': 0.8523,
      'threshold': 0.363,
      'message': 'Biometric verification successful.',
    };

    final result = AttendanceVerificationResult.fromJson(sampleJson);

    expect(result.status, 'success');
    expect(result.attendanceId, 'att_12345678-abcd-ef01-2345-6789abcdef01');
    expect(result.userId, 'usr_abcdef01-2345-6789-abcd-ef0123456789');
    expect(result.employeeId, 'EMP001');
    expect(result.punchType, 'CHECK_IN');
    expect(result.similarityScore, 0.8523);
    expect(result.threshold, 0.363);
    expect(result.message, 'Biometric verification successful.');
    expect(result.similarityPercentage, '85.2%');
  });

  test('Correctly converts UTC timestamp to local device timezone', () {
    final sampleJson = {
      'status': 'success',
      'attendance_id': 'att_1',
      'user_id': 'usr_1',
      'employee_id': 'EMP002',
      'punch_type': 'CHECK_OUT',
      'timestamp': '2026-10-10T12:30:45Z',
      'similarity_score': 0.9100,
      'threshold': 0.363,
      'message': 'Biometric verification successful.',
    };

    final result = AttendanceVerificationResult.fromJson(sampleJson);

    // Verify UTC time is exact
    expect(result.timestampUtc.isUtc, true);
    expect(result.timestampUtc.year, 2026);
    expect(result.timestampUtc.month, 10);
    expect(result.timestampUtc.day, 10);
    expect(result.timestampUtc.hour, 12);
    expect(result.timestampUtc.minute, 30);
    expect(result.timestampUtc.second, 45);

    // Verify local representation exists and format matches YYYY-MM-DD HH:mm:ss
    final localStr = result.toLocalFormattedTimestamp();
    expect(localStr.length, 19);
    expect(localStr.contains('2026-10-10'), true);
  });

  test('Handles integer similarity scores gracefully (num conversion)', () {
    final sampleJson = {
      'status': 'success',
      'attendance_id': 'att_2',
      'user_id': 'usr_2',
      'employee_id': 'EMP003',
      'punch_type': 'CHECK_IN',
      'timestamp': '2026-10-10T10:00:00Z',
      'similarity_score': 1, // integer 1
      'threshold': 0, // integer 0
      'message': 'Exact match',
    };

    final result = AttendanceVerificationResult.fromJson(sampleJson);
    expect(result.similarityScore, 1.0);
    expect(result.threshold, 0.0);
    expect(result.similarityPercentage, '100.0%');
  });

  print('AttendanceResult Tests: $passed passed, $failed failed.\n');
  if (failed > 0) throw Exception('AttendanceResult tests failed');
}
