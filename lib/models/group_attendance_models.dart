class RosterStudent {
  final String studentId;
  final String studentNumber;
  final String fullName;
  final String? email;
  final String? personId;
  final String departmentCode;
  final int yearOfStudy;
  final String section;
  final String academicYear;
  final String status; // 'PRESENT', 'PENDING_REVIEW', 'UNRESOLVED', 'MARKED_ABSENT'
  final double similarityScore;
  final String? notes;

  const RosterStudent({
    required this.studentId,
    required this.studentNumber,
    required this.fullName,
    this.email,
    this.personId,
    required this.departmentCode,
    required this.yearOfStudy,
    required this.section,
    required this.academicYear,
    required this.status,
    required this.similarityScore,
    this.notes,
  });

  factory RosterStudent.fromJson(Map<String, dynamic> json) => RosterStudent(
        studentId: json['student_id'] as String,
        studentNumber: json['student_number'] as String,
        fullName: json['full_name'] as String,
        email: json['email'] as String?,
        personId: json['person_id'] as String?,
        departmentCode: json['department_code'] as String? ?? 'N/A',
        yearOfStudy: (json['year_of_study'] as num?)?.toInt() ?? 1,
        section: json['section'] as String? ?? 'A',
        academicYear: json['academic_year'] as String? ?? '',
        status: json['status'] as String? ?? 'UNRESOLVED',
        similarityScore: (json['similarity_score'] as num?)?.toDouble() ?? 0.0,
        notes: json['notes'] as String?,
      );

  RosterStudent copyWith({
    String? status,
    double? similarityScore,
    String? notes,
  }) =>
      RosterStudent(
        studentId: studentId,
        studentNumber: studentNumber,
        fullName: fullName,
        email: email,
        personId: personId,
        departmentCode: departmentCode,
        yearOfStudy: yearOfStudy,
        section: section,
        academicYear: academicYear,
        status: status ?? this.status,
        similarityScore: similarityScore ?? this.similarityScore,
        notes: notes ?? this.notes,
      );

  bool get isPresent => status == 'PRESENT';
  bool get isPendingReview => status == 'PENDING_REVIEW';
  bool get isAbsent => status == 'MARKED_ABSENT';
  bool get isUnresolved => status == 'UNRESOLVED';
}

class DetectedFaceItem {
  final int faceIndex;
  final List<double> bbox;
  final String status;
  final String? studentId;
  final String? studentNumber;
  final String? fullName;
  final double similarityScore;

  const DetectedFaceItem({
    required this.faceIndex,
    required this.bbox,
    required this.status,
    this.studentId,
    this.studentNumber,
    this.fullName,
    required this.similarityScore,
  });

  factory DetectedFaceItem.fromJson(Map<String, dynamic> json) {
    final rawBbox = json['bbox'] as List?;
    final bbox = rawBbox != null
        ? rawBbox.map((e) => (e as num).toDouble()).toList()
        : <double>[0, 0, 0, 0];
    return DetectedFaceItem(
      faceIndex: (json['face_index'] as num?)?.toInt() ?? 0,
      bbox: bbox,
      status: json['status'] as String? ?? 'UNKNOWN_FACE',
      studentId: json['student_id'] as String?,
      studentNumber: json['student_number'] as String?,
      fullName: json['full_name'] as String?,
      similarityScore: (json['similarity_score'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class GroupCaptureItem {
  final String captureId;
  final int photoIndex;
  final DateTime capturedAt;
  final int facesDetected;
  final int facesMatched;
  final int facesUncertain;
  final int facesUnknown;
  final int duplicatesIgnored;

  const GroupCaptureItem({
    required this.captureId,
    required this.photoIndex,
    required this.capturedAt,
    required this.facesDetected,
    required this.facesMatched,
    required this.facesUncertain,
    required this.facesUnknown,
    required this.duplicatesIgnored,
  });

  factory GroupCaptureItem.fromJson(Map<String, dynamic> json) => GroupCaptureItem(
        captureId: json['capture_id'] as String,
        photoIndex: (json['photo_index'] as num).toInt(),
        capturedAt: DateTime.parse(json['captured_at'] as String).toUtc(),
        facesDetected: (json['faces_detected'] as num).toInt(),
        facesMatched: (json['faces_matched'] as num).toInt(),
        facesUncertain: (json['faces_uncertain'] as num).toInt(),
        facesUnknown: (json['faces_unknown'] as num).toInt(),
        duplicatesIgnored: (json['duplicates_ignored'] as num).toInt(),
      );
}

class SessionProvisionalState {
  final String sessionId;
  final String status;
  final int expectedCount;
  final int presentCount;
  final int pendingReviewCount;
  final int unresolvedCount;
  final int unknownFacesCount;
  final int photosCapturedCount;
  final List<RosterStudent> roster;
  final List<GroupCaptureItem> captures;

  const SessionProvisionalState({
    required this.sessionId,
    required this.status,
    required this.expectedCount,
    required this.presentCount,
    required this.pendingReviewCount,
    required this.unresolvedCount,
    required this.unknownFacesCount,
    required this.photosCapturedCount,
    required this.roster,
    required this.captures,
  });

  factory SessionProvisionalState.fromJson(Map<String, dynamic> json) {
    final rawRoster = json['roster'] as List? ?? [];
    final rawCaptures = json['captures'] as List? ?? [];
    return SessionProvisionalState(
      sessionId: json['session_id'] as String,
      status: json['status'] as String? ?? 'OPEN',
      expectedCount: (json['expected_count'] as num?)?.toInt() ?? 0,
      presentCount: (json['present_count'] as num?)?.toInt() ?? 0,
      pendingReviewCount: (json['pending_review_count'] as num?)?.toInt() ?? 0,
      unresolvedCount: (json['unresolved_count'] as num?)?.toInt() ?? 0,
      unknownFacesCount: (json['unknown_faces_count'] as num?)?.toInt() ?? 0,
      photosCapturedCount: (json['photos_captured_count'] as num?)?.toInt() ?? 0,
      roster: rawRoster
          .whereType<Map<String, dynamic>>()
          .map(RosterStudent.fromJson)
          .toList(),
      captures: rawCaptures
          .whereType<Map<String, dynamic>>()
          .map(GroupCaptureItem.fromJson)
          .toList(),
    );
  }
}

class GroupCaptureResult {
  final String captureId;
  final int photoIndex;
  final int facesDetectedCount;
  final int facesMatchedCount;
  final int facesUncertainCount;
  final int facesUnknownCount;
  final int duplicatesIgnoredCount;
  final List<DetectedFaceItem> detectedFaces;
  final String summaryMessage;
  final SessionProvisionalState cumulativeState;

  const GroupCaptureResult({
    required this.captureId,
    required this.photoIndex,
    required this.facesDetectedCount,
    required this.facesMatchedCount,
    required this.facesUncertainCount,
    required this.facesUnknownCount,
    required this.duplicatesIgnoredCount,
    required this.detectedFaces,
    required this.summaryMessage,
    required this.cumulativeState,
  });

  factory GroupCaptureResult.fromJson(Map<String, dynamic> json) {
    final rawFaces = json['detected_faces'] as List? ?? [];
    final rawCum = json['cumulative_state'] as Map<String, dynamic>? ??
        json['session_cumulative'] as Map<String, dynamic>? ??
        {};
    return GroupCaptureResult(
      captureId: json['capture_id'] as String,
      photoIndex: (json['photo_index'] as num?)?.toInt() ?? 1,
      facesDetectedCount: (json['faces_detected_count'] as num?)?.toInt() ?? 0,
      facesMatchedCount: (json['faces_matched_count'] as num?)?.toInt() ?? 0,
      facesUncertainCount: (json['faces_uncertain_count'] as num?)?.toInt() ?? 0,
      facesUnknownCount: (json['faces_unknown_count'] as num?)?.toInt() ?? 0,
      duplicatesIgnoredCount: (json['duplicates_ignored_count'] as num?)?.toInt() ?? 0,
      detectedFaces: rawFaces
          .whereType<Map<String, dynamic>>()
          .map(DetectedFaceItem.fromJson)
          .toList(),
      summaryMessage: json['summary_message'] as String? ?? 'Capture processed.',
      cumulativeState: SessionProvisionalState.fromJson(rawCum),
    );
  }
}

class FinalizeAttendanceResult {
  final String status;
  final String sessionId;
  final String state;
  final int totalExpected;
  final int presentCount;
  final int absentCount;
  final double attendanceRatePct;
  final DateTime finalizedAt;

  const FinalizeAttendanceResult({
    required this.status,
    required this.sessionId,
    required this.state,
    required this.totalExpected,
    required this.presentCount,
    required this.absentCount,
    required this.attendanceRatePct,
    required this.finalizedAt,
  });

  factory FinalizeAttendanceResult.fromJson(Map<String, dynamic> json) => FinalizeAttendanceResult(
        status: json['status'] as String,
        sessionId: json['session_id'] as String,
        state: json['state'] as String? ?? 'CLOSED',
        totalExpected: (json['total_expected'] as num?)?.toInt() ?? 0,
        presentCount: (json['present_count'] as num?)?.toInt() ?? 0,
        absentCount: (json['absent_count'] as num?)?.toInt() ?? 0,
        attendanceRatePct: (json['attendance_rate_pct'] as num?)?.toDouble() ?? 0.0,
        finalizedAt: DateTime.tryParse(json['finalized_at'] as String? ?? '')?.toUtc() ?? DateTime.now().toUtc(),
      );
}
