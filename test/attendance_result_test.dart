import 'package:flutter_test/flutter_test.dart';
import 'package:kiosk_app/models/attendance_result.dart';

void main() {
  group('Attendance result contracts', () {
    test('verification parses UTC timestamp and similarity fields', () {
      final result = AttendanceVerificationResult.fromJson({
        'status': 'success',
        'attendance_id': 'att-1',
        'user_id': 'person-1',
        'employee_id': 'EMP-001',
        'punch_type': 'CHECK_IN',
        'timestamp': '2026-10-19T10:00:00Z',
        'similarity_score': 0.86,
        'threshold': 0.75,
        'message': 'accepted',
      });
      expect(result.employeeId, 'EMP-001');
      expect(result.timestampUtc.isUtc, isTrue);
      expect(result.similarityScore, 0.86);
      expect(result.similarityPercentage, '86.0%');
    });

    test('identification keeps backend identity and optional department', () {
      final result = AttendanceIdentificationResult.fromJson({
        'status': 'success',
        'attendance_id': 'att-2',
        'user_id': 'person-2',
        'employee_id': 'EMP-002',
        'full_name': 'Example Person',
        'department': 'Engineering',
        'punch_type': 'CHECK_OUT',
        'timestamp': '2026-10-19T10:00:00+00:00',
        'similarity_score': 0.9,
        'threshold': 0.72,
      });
      expect(result.fullName, 'Example Person');
      expect(result.department, 'Engineering');
      expect(result.timestampUtc.isUtc, isTrue);
      expect(result.status, 'success');
    });

    test('malformed required fields throw instead of creating a false success result', () {
      expect(
        () => AttendanceVerificationResult.fromJson({
          'status': 'success',
          'attendance_id': 'att-3',
        }),
        throwsA(anything),
      );
    });
  });
}
