/// Persisted state of an encrypted attendance capture batch.
class CaptureBatchJob {
  final String batchId;
  final String attendanceSessionId;
  final String classGroupId;
  final String status;
  final int frameCount;
  final int attempts;
  final Map<String, dynamic>? result;
  final Map<String, dynamic>? error;

  const CaptureBatchJob({
    required this.batchId,
    required this.attendanceSessionId,
    required this.classGroupId,
    required this.status,
    required this.frameCount,
    required this.attempts,
    this.result,
    this.error,
  });

  factory CaptureBatchJob.fromJson(Map<String, dynamic> json) => CaptureBatchJob(
        batchId: json['batch_id'] as String,
        attendanceSessionId: json['attendance_session_id'] as String,
        classGroupId: json['class_group_id'] as String,
        status: (json['status'] as String).toUpperCase(),
        frameCount: (json['frame_count'] as num).toInt(),
        attempts: (json['attempts'] as num).toInt(),
        result: json['result'] is Map<String, dynamic>
            ? Map<String, dynamic>.from(json['result'] as Map<String, dynamic>)
            : null,
        error: json['error'] is Map<String, dynamic>
            ? Map<String, dynamic>.from(json['error'] as Map<String, dynamic>)
            : null,
      );

  String get errorMessage {
    final detail = error?['detail'];
    if (detail is Map<String, dynamic>) {
      return detail['message'] as String? ?? detail.toString();
    }
    return detail?.toString() ?? 'Attendance batch $status.';
  }
}
