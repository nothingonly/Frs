import 'package:intl/intl.dart';

String _requireSuccessfulStatus(Map<String, dynamic> json) {
  final status = json['status'];
  if (status is! String || status.toLowerCase() != 'success') {
    throw const FormatException('Backend response is not an accepted attendance result.');
  }
  return status;
}

/// Typed verification and attendance record response from POST /api/v1/attendance/verify.
class AttendanceVerificationResult {
  final String status;
  final String attendanceId;
  final String userId;
  final String employeeId;
  final String punchType;
  final DateTime timestampUtc;
  final double similarityScore;
  final double threshold;
  final String message;

  AttendanceVerificationResult({
    required this.status,
    required this.attendanceId,
    required this.userId,
    required this.employeeId,
    required this.punchType,
    required this.timestampUtc,
    required this.similarityScore,
    required this.threshold,
    required this.message,
  });

  factory AttendanceVerificationResult.fromJson(Map<String, dynamic> json) {
    return AttendanceVerificationResult(
      status: _requireSuccessfulStatus(json),
      attendanceId: json['attendance_id'] as String,
      userId: json['user_id'] as String,
      employeeId: json['employee_id'] as String,
      punchType: json['punch_type'] as String,
      timestampUtc: DateTime.parse(json['timestamp'] as String).toUtc(),
      similarityScore: (json['similarity_score'] as num).toDouble(),
      threshold: (json['threshold'] as num).toDouble(),
      message: json['message'] as String? ?? 'Biometric verification successful.',
    );
  }

  /// Converts the server's UTC timestamp to the kiosk's local timezone.
  DateTime get timestampLocal => timestampUtc.toLocal();

  /// Formatted representation in local device time (e.g., '2026-10-10 18:30:15').
  String toLocalFormattedTimestamp() {
    return DateFormat('yyyy-MM-dd HH:mm:ss').format(timestampLocal);
  }

  /// Human-friendly match percentage display.
  String get similarityPercentage => '${(similarityScore * 100).toStringAsFixed(1)}%';
}

/// Typed automatic 1:N identification result from POST /api/v1/attendance/identify.
class AttendanceIdentificationResult {
  final String status;
  final String attendanceId;
  final String userId;
  final String employeeId;
  final String fullName;
  final String? department;
  final String punchType;
  final DateTime timestampUtc;
  final double similarityScore;
  final double threshold;
  final String message;

  AttendanceIdentificationResult({
    required this.status,
    required this.attendanceId,
    required this.userId,
    required this.employeeId,
    required this.fullName,
    this.department,
    required this.punchType,
    required this.timestampUtc,
    required this.similarityScore,
    required this.threshold,
    required this.message,
  });

  factory AttendanceIdentificationResult.fromJson(Map<String, dynamic> json) {
    return AttendanceIdentificationResult(
      status: _requireSuccessfulStatus(json),
      attendanceId: json['attendance_id'] as String,
      userId: json['user_id'] as String,
      employeeId: json['employee_id'] as String,
      fullName: json['full_name'] as String? ?? 'Enrolled Employee',
      department: json['department'] as String?,
      punchType: json['punch_type'] as String,
      timestampUtc: DateTime.parse(json['timestamp'] as String).toUtc(),
      similarityScore: (json['similarity_score'] as num).toDouble(),
      threshold: (json['threshold'] as num).toDouble(),
      message: json['message'] as String? ?? 'Automatic biometric attendance verified.',
    );
  }

  DateTime get timestampLocal => timestampUtc.toLocal();

  String toLocalFormattedTimestamp() {
    return DateFormat('yyyy-MM-dd HH:mm:ss').format(timestampLocal);
  }

  String get similarityPercentage => '${(similarityScore * 100).toStringAsFixed(1)}%';
}
