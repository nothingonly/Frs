/// An open, persisted attendance session offered by the authenticated kiosk API.
class AttendanceSessionOption {
  final String sessionId;
  final String classGroupId;
  final String subjectName;
  final String? subjectCode;
  final String sessionType; // 'SPECIFIC', 'LAB', 'MIXED'
  final String? labName;
  final int? semester;
  final List<String> classGroupIds;
  final int expectedRosterCount;
  final DateTime startsAt;
  final String departmentCode;
  final int yearOfStudy;
  final String section;
  final String academicYear;

  const AttendanceSessionOption({
    required this.sessionId,
    required this.classGroupId,
    required this.subjectName,
    required this.subjectCode,
    this.sessionType = 'SPECIFIC',
    this.labName,
    this.semester,
    this.classGroupIds = const [],
    this.expectedRosterCount = 0,
    required this.startsAt,
    required this.departmentCode,
    required this.yearOfStudy,
    required this.section,
    required this.academicYear,
  });

  factory AttendanceSessionOption.fromJson(Map<String, dynamic> json) {
    final rawGroupIds = json['class_group_ids'];
    final List<String> groupIds = rawGroupIds is List
        ? rawGroupIds.map((e) => e.toString()).toList()
        : [json['class_group_id'] as String];

    return AttendanceSessionOption(
      sessionId: json['session_id'] as String,
      classGroupId: json['class_group_id'] as String,
      subjectName: json['subject_name'] as String,
      subjectCode: json['subject_code'] as String?,
      sessionType: json['session_type'] as String? ?? 'SPECIFIC',
      labName: json['lab_name'] as String?,
      semester: (json['semester'] as num?)?.toInt(),
      classGroupIds: groupIds,
      expectedRosterCount: (json['expected_roster_count'] as num?)?.toInt() ?? 0,
      startsAt: DateTime.parse(json['starts_at'] as String).toUtc(),
      departmentCode: json['department_code'] as String,
      yearOfStudy: (json['year_of_study'] as num).toInt(),
      section: json['section'] as String,
      academicYear: json['academic_year'] as String,
    );
  }

  bool get isLab => sessionType == 'LAB' || labName != null;
  bool get isMixed => sessionType == 'MIXED';

  String get typeBadge {
    if (isLab) return 'LAB';
    if (isMixed) return 'MIXED';
    return 'CLASS';
  }

  String get displayLabel {
    final prefix = isLab
        ? '[LAB] ${labName ?? subjectName}'
        : isMixed
            ? '[MIXED] $subjectName'
            : '$departmentCode · Yr $yearOfStudy-$section';
    final semText = semester != null ? ' · Sem $semester' : '';
    final countText = expectedRosterCount > 0 ? ' ($expectedRosterCount students)' : '';
    return '$prefix · $subjectName$semText$countText';
  }
}
