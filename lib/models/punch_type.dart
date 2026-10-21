/// Attendance punch type directions supported by the FRS backend.
enum PunchType {
  checkIn('CHECK_IN', 'Check In'),
  checkOut('CHECK_OUT', 'Check Out');

  final String value;
  final String label;

  const PunchType(this.value, this.label);

  static PunchType fromValue(String value) {
    return PunchType.values.firstWhere(
      (e) => e.value == value,
      orElse: () => PunchType.checkIn,
    );
  }
}
