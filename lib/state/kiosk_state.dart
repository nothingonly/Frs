import 'dart:async';
import 'dart:typed_data';

import '../exceptions/api_exceptions.dart';
import '../models/attendance_result.dart';
import '../models/punch_type.dart';
import '../services/api_service.dart';

/// The distinct UI lifecycle states for the kiosk app.
enum KioskStatus {
  idle,
  capturing,
  readyToSubmit,
  submitting,
  accepted,
  unrecognized,
  ambiguous,
  mismatch,
  qualityError,
  cooldown,
  inactiveEmployee,
  notFound,
  networkError,
  serverError,
}

/// Core state holder and automatic 1:N submission coordinator for the FRS Kiosk.
class KioskState {
  final List<void Function()> _listeners = [];

  KioskStatus _status = KioskStatus.idle;
  String _employeeId = '';
  PunchType _punchType = PunchType.checkIn;
  List<Uint8List> _capturedImages = <Uint8List>[];
  bool _isSubmitting = false;

  AttendanceVerificationResult? _lastSuccessResult;
  AttendanceIdentificationResult? _lastIdentificationResult;

  String? _matchedEmployeeName;
  String? _matchedEmployeeId;
  String? _matchedDepartment;
  String? _ambiguousCandidate1;
  String? _ambiguousCandidate2;

  String? _errorMessage;
  double? _lastSimilarityScore;
  double? _requiredThreshold;
  int? _cooldownRemainingSeconds;
  DateTime? _cooldownLastPunchTime;
  Timer? _countdownTimer;
  Timer? _autoResetTimer;

  // Getters
  KioskStatus get status => _status;
  String get employeeId => _employeeId;
  PunchType get punchType => _punchType;
  Uint8List? get capturedImage => _capturedImages.isEmpty ? null : _capturedImages.first;
  List<Uint8List> get capturedImages => List<Uint8List>.unmodifiable(_capturedImages);
  bool get hasUsableBurst => _capturedImages.length >= 3 && _capturedImages.every((frame) => frame.isNotEmpty);
  bool get isSubmitting => _isSubmitting;
  AttendanceVerificationResult? get lastSuccessResult => _lastSuccessResult;
  AttendanceIdentificationResult? get lastIdentificationResult => _lastIdentificationResult;

  String? get matchedEmployeeName => _matchedEmployeeName;
  String? get matchedEmployeeId => _matchedEmployeeId;
  String? get matchedDepartment => _matchedDepartment;
  String? get ambiguousCandidate1 => _ambiguousCandidate1;
  String? get ambiguousCandidate2 => _ambiguousCandidate2;

  String? get errorMessage => _errorMessage;
  double? get lastSimilarityScore => _lastSimilarityScore;
  double? get requiredThreshold => _requiredThreshold;
  int? get cooldownRemainingSeconds => _cooldownRemainingSeconds;
  DateTime? get cooldownLastPunchTime => _cooldownLastPunchTime;

  /// For automatic 1:N identification: submission requires only a captured photo.
  bool get canSubmit => !_isSubmitting && hasUsableBurst;

  /// For optional 1:1 legacy verification: requires both employee ID and photo.
  bool get canSubmit1To1 =>
      !_isSubmitting && _employeeId.trim().isNotEmpty && hasUsableBurst;

  void addListener(void Function() listener) {
    _listeners.add(listener);
  }

  void removeListener(void Function() listener) {
    _listeners.remove(listener);
  }

  void notifyListeners() {
    for (final listener in List.of(_listeners)) {
      listener();
    }
  }

  void setEmployeeId(String id) {
    _employeeId = id.trim();
    _updateReadyStatus();
    notifyListeners();
  }

  void appendDigit(String digit) {
    if (_employeeId.length < 20) {
      _employeeId += digit;
      _updateReadyStatus();
      notifyListeners();
    }
  }

  void backspaceDigit() {
    if (_employeeId.isNotEmpty) {
      _employeeId = _employeeId.substring(0, _employeeId.length - 1);
      _updateReadyStatus();
      notifyListeners();
    }
  }

  void clearEmployeeId() {
    _employeeId = '';
    _updateReadyStatus();
    notifyListeners();
  }

  void setPunchType(PunchType type) {
    _punchType = type;
    notifyListeners();
  }

  void setCapturedImages(List<Uint8List> imageFrames) {
    _capturedImages = imageFrames
        .where((frame) => frame.isNotEmpty)
        .map((frame) => Uint8List.fromList(frame))
        .toList(growable: false);
    _updateReadyStatus();
    notifyListeners();
  }

  /// A single legacy image is not sufficient to submit temporal attendance evidence.
  void setCapturedImage(Uint8List imageBytes) => setCapturedImages([imageBytes]);

  void clearCapturedImage() {
    _capturedImages = <Uint8List>[];
    _updateReadyStatus();
    notifyListeners();
  }

  void setStatus(KioskStatus newStatus) {
    _status = newStatus;
    notifyListeners();
  }

  void setSuccessResult(AttendanceVerificationResult result) {
    _status = KioskStatus.accepted;
    _lastSuccessResult = result;
    _matchedEmployeeId = result.employeeId;
    _lastSimilarityScore = result.similarityScore;
    _requiredThreshold = result.threshold;
    _errorMessage = null;
    notifyListeners();
  }

  void setIdentificationResult(AttendanceIdentificationResult result) {
    _status = KioskStatus.accepted;
    _lastIdentificationResult = result;
    _matchedEmployeeName = result.fullName;
    _matchedEmployeeId = result.employeeId;
    _matchedDepartment = result.department;
    _lastSimilarityScore = result.similarityScore;
    _requiredThreshold = result.threshold;
    _errorMessage = null;
    notifyListeners();
  }

  void _updateReadyStatus() {
    if (_status == KioskStatus.submitting) return;
    if (_capturedImages.isNotEmpty) {
      _status = KioskStatus.readyToSubmit;
    } else if (_status != KioskStatus.accepted &&
               _status != KioskStatus.unrecognized &&
               _status != KioskStatus.ambiguous &&
               _status != KioskStatus.mismatch &&
               _status != KioskStatus.cooldown &&
               _status != KioskStatus.inactiveEmployee &&
               _status != KioskStatus.notFound &&
               _status != KioskStatus.qualityError &&
               _status != KioskStatus.networkError) {
      _status = KioskStatus.idle;
    }
  }

  /// Primary 1:N automatic biometric attendance punch (No employee ID entered).
  Future<void> submitAutomaticIdentification(FrsApiService apiService) async {
    if (_isSubmitting) return;

    if (!hasUsableBurst) {
      _status = KioskStatus.idle;
      _errorMessage = 'Capture at least three separate camera frames before submitting.';
      notifyListeners();
      return;
    }

    _isSubmitting = true;
    _status = KioskStatus.submitting;
    _errorMessage = null;
    _cancelCooldownTimer();
    _cancelAutoResetTimer();
    notifyListeners();

    try {
      final result = await apiService.identifyAttendance(
        imageFrames: _capturedImages,
        punchType: _punchType,
      );

      _status = KioskStatus.accepted;
      _lastIdentificationResult = result;
      _matchedEmployeeName = result.fullName;
      _matchedEmployeeId = result.employeeId;
      _matchedDepartment = result.department;
      _lastSimilarityScore = result.similarityScore;
      _requiredThreshold = result.threshold;
      _errorMessage = null;
      _startAutoResetTimer(durationSeconds: 5);
    } on UnrecognizedFaceException catch (e) {
      _status = KioskStatus.unrecognized;
      _lastSimilarityScore = e.similarityScore;
      _requiredThreshold = e.requiredThreshold;
      _errorMessage = e.message;
      _startAutoResetTimer(durationSeconds: 6);
    } on AmbiguousMatchException catch (e) {
      _status = KioskStatus.ambiguous;
      _ambiguousCandidate1 = e.firstCandidate;
      _ambiguousCandidate2 = e.secondCandidate;
      _errorMessage = e.message;
      _startAutoResetTimer(durationSeconds: 6);
    } on CooldownException catch (e) {
      _status = KioskStatus.cooldown;
      _cooldownRemainingSeconds = e.remainingSeconds;
      _cooldownLastPunchTime = e.lastPunchTimeUtc;
      _errorMessage = e.message;
      _startCooldownTimer();
      _startAutoResetTimer(durationSeconds: 6);
    } on BiometricQualityException catch (e) {
      _status = KioskStatus.qualityError;
      _errorMessage = e.message;
      _startAutoResetTimer(durationSeconds: 5);
    } on InactiveEmployeeException catch (e) {
      _status = KioskStatus.inactiveEmployee;
      _errorMessage = e.message;
      _startAutoResetTimer(durationSeconds: 5);
    } on NetworkException catch (e) {
      _status = KioskStatus.networkError;
      _errorMessage = e.message;
      _startAutoResetTimer(durationSeconds: 6);
    } on FrsApiException catch (e) {
      _status = KioskStatus.serverError;
      _errorMessage = e.message;
      _startAutoResetTimer(durationSeconds: 5);
    } catch (e) {
      _status = KioskStatus.serverError;
      _errorMessage = 'Unexpected client error: $e';
      _startAutoResetTimer(durationSeconds: 5);
    } finally {
      _isSubmitting = false;
      notifyListeners();
    }
  }

  /// Legacy 1:1 facial verification method.
  Future<void> submitAttendance(FrsApiService apiService) async {
    if (_isSubmitting) return;

    if (_employeeId.trim().isEmpty) {
      _status = KioskStatus.idle;
      _errorMessage = 'Please enter an Employee ID.';
      notifyListeners();
      return;
    }

    if (!hasUsableBurst) {
      _status = KioskStatus.idle;
      _errorMessage = 'Please capture a face photo before submitting.';
      notifyListeners();
      return;
    }

    _isSubmitting = true;
    _status = KioskStatus.submitting;
    _errorMessage = null;
    _cancelCooldownTimer();
    _cancelAutoResetTimer();
    notifyListeners();

    try {
      final result = await apiService.verifyAttendance(
        employeeId: _employeeId.trim(),
        imageFrames: _capturedImages,
        punchType: _punchType,
      );

      _status = KioskStatus.accepted;
      _lastSuccessResult = result;
      _matchedEmployeeId = result.employeeId;
      _lastSimilarityScore = result.similarityScore;
      _requiredThreshold = result.threshold;
      _errorMessage = null;
    } on BiometricMismatchException catch (e) {
      _status = KioskStatus.mismatch;
      _lastSimilarityScore = e.similarityScore;
      _requiredThreshold = e.requiredThreshold;
      _errorMessage = e.message;
    } on CooldownException catch (e) {
      _status = KioskStatus.cooldown;
      _cooldownRemainingSeconds = e.remainingSeconds;
      _cooldownLastPunchTime = e.lastPunchTimeUtc;
      _errorMessage = e.message;
      _startCooldownTimer();
    } on BiometricQualityException catch (e) {
      _status = KioskStatus.qualityError;
      _errorMessage = e.message;
    } on InactiveEmployeeException catch (e) {
      _status = KioskStatus.inactiveEmployee;
      _errorMessage = e.message;
    } on EmployeeNotFoundException catch (e) {
      _status = KioskStatus.notFound;
      _errorMessage = e.message;
    } on TemplateNotEnrolledException catch (e) {
      _status = KioskStatus.notFound;
      _errorMessage = e.message;
    } on NetworkException catch (e) {
      _status = KioskStatus.networkError;
      _errorMessage = e.message;
    } on FrsApiException catch (e) {
      _status = KioskStatus.serverError;
      _errorMessage = e.message;
    } catch (e) {
      _status = KioskStatus.serverError;
      _errorMessage = 'Unexpected client error: $e';
    } finally {
      _isSubmitting = false;
      notifyListeners();
    }
  }

  void _startCooldownTimer() {
    _cancelCooldownTimer();
    if (_cooldownRemainingSeconds != null && _cooldownRemainingSeconds! > 0) {
      _countdownTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
        if (_cooldownRemainingSeconds != null && _cooldownRemainingSeconds! > 1) {
          _cooldownRemainingSeconds = _cooldownRemainingSeconds! - 1;
          notifyListeners();
        } else {
          _cooldownRemainingSeconds = 0;
          _cancelCooldownTimer();
          notifyListeners();
        }
      });
    }
  }

  void _cancelCooldownTimer() {
    _countdownTimer?.cancel();
    _countdownTimer = null;
  }

  void _startAutoResetTimer({int durationSeconds = 5}) {
    _cancelAutoResetTimer();
    _autoResetTimer = Timer(Duration(seconds: durationSeconds), () {
      reset();
    });
  }

  void _cancelAutoResetTimer() {
    _autoResetTimer?.cancel();
    _autoResetTimer = null;
  }

  /// Resets the kiosk state for the next person.
  void reset() {
    _cancelCooldownTimer();
    _cancelAutoResetTimer();
    _status = KioskStatus.idle;
    _employeeId = '';
    _punchType = PunchType.checkIn;
    _capturedImages = <Uint8List>[];
    _isSubmitting = false;
    _lastSuccessResult = null;
    _lastIdentificationResult = null;
    _matchedEmployeeName = null;
    _matchedEmployeeId = null;
    _matchedDepartment = null;
    _ambiguousCandidate1 = null;
    _ambiguousCandidate2 = null;
    _errorMessage = null;
    _lastSimilarityScore = null;
    _requiredThreshold = null;
    _cooldownRemainingSeconds = null;
    _cooldownLastPunchTime = null;
    notifyListeners();
  }

  void dispose() {
    _cancelCooldownTimer();
    _cancelAutoResetTimer();
    _listeners.clear();
  }
}
