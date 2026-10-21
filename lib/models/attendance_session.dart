/// An open, persisted attendance session offered by the authenticated kiosk API.
class AttendanceSessionOption {
  final String sessionId;
  final String classGroupId;
  final String subjectName;
  final String? subjectCode;
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
    required this.startsAt,
    required this.departmentCode,
    required this.yearOfStudy,
    required this.section,
    required this.academicYear,
  });

  factory AttendanceSessionOption.fromJson(Map<String, dynamic> json) => AttendanceSessionOption(
        sessionId: json['session_id'] as String,
        classGroupId: json['class_group_id'] as String,
        subjectName: json['subject_name'] as String,
        subjectCode: json['subject_code'] as String?,
        startsAt: DateTime.parse(json['starts_at'] as String).toUtc(),
        departmentCode: json['department_code'] as String,
        yearOfStudy: (json['year_of_study'] as num).toInt(),
        section: json['section'] as String,
        academicYear: json['academic_year'] as String,
      );

  String get displayLabel =>
      '$departmentCode · Year $yearOfStudy-$section · $subjectName · $academicYear';
}
