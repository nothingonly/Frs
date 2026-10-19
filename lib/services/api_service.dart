import 'dart:convert';
import 'dart:typed_data';
import 'package:http/http.dart' as http;

import '../config/app_config.dart';
import '../exceptions/api_exceptions.dart';
import '../models/attendance_result.dart';
import '../models/health_status.dart';
import '../models/punch_type.dart';

/// Contract-exact API client communicating with the FastAPI FRS backend.
class FrsApiService {
  final AppConfig config;
  final http.Client _client;

  FrsApiService({
    required this.config,
    http.Client? client,
  }) : _client = client ?? http.Client();

  /// Checks server liveness and vision model loading state via GET /health.
  Future<HealthStatus> checkHealth() async {
    final uri = Uri.parse('${config.apiBaseUrl}/health');
    try {
      final response = await _client.get(uri);
      if (response.statusCode == 200) {
        final data = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
        return HealthStatus.fromJson(data);
      } else {
        throw ServerException('Healthcheck returned status ${response.statusCode}');
      }
    } catch (e) {
      if (e is FrsApiException) rethrow;
      throw NetworkException('Unable to reach backend at ${config.apiBaseUrl}: $e');
    }
  }

  /// One-to-one verification uses the same real burst/temporal policy as automatic identification.
  Future<AttendanceVerificationResult> verifyAttendance({
    required String employeeId,
    required List<Uint8List> imageFrames,
    required PunchType punchType,
    String? clientDeviceId,
  }) async {
    config.validateTransport();
    _requireDeviceCredential();
    _validateImageBurst(imageFrames);
    final uri = Uri.parse('${config.apiBaseUrl}/api/v1/attendance/verify');
    final request = http.MultipartRequest('POST', uri);
    request.headers['Authorization'] = 'Bearer ${config.apiKeySecret}';
    request.fields['employee_id'] = employeeId.trim();
    request.fields['punch_type'] = punchType.value;
    request.fields['client_device_id'] = clientDeviceId ?? config.clientDeviceId;
    _addImageBurst(request, imageFrames, 'kiosk_verify');

    final streamedResponse = await _send(request);
    final response = await http.Response.fromStream(streamedResponse);
    final responseBody = _parseJsonBody(response.bodyBytes);
    if (response.statusCode == 200) {
      return AttendanceVerificationResult.fromJson(responseBody);
    }
    _handleErrorStatus(response.statusCode, responseBody, response.body);
    throw ServerException('Unexpected verification response status ${response.statusCode}');
  }

  /// Automatic one-to-many identification sends each distinct hardware frame as an images part.
  Future<AttendanceIdentificationResult> identifyAttendance({
    required List<Uint8List> imageFrames,
    required PunchType punchType,
    String? clientDeviceId,
  }) async {
    config.validateTransport();
    _requireDeviceCredential();
    _validateImageBurst(imageFrames);
    final uri = Uri.parse('${config.apiBaseUrl}/api/v1/attendance/identify');
    final request = http.MultipartRequest('POST', uri);
    request.headers['Authorization'] = 'Bearer ${config.apiKeySecret}';
    request.fields['punch_type'] = punchType.value;
    request.fields['client_device_id'] = clientDeviceId ?? config.clientDeviceId;
    _addImageBurst(request, imageFrames, 'kiosk_identify');

    final streamedResponse = await _send(request);
    final response = await http.Response.fromStream(streamedResponse);
    final responseBody = _parseJsonBody(response.bodyBytes);
    if (response.statusCode == 200) {
      return AttendanceIdentificationResult.fromJson(responseBody);
    }
    _handleErrorStatus(response.statusCode, responseBody, response.body);
    throw ServerException('Unexpected identification response status ${response.statusCode}');
  }

  /// Administrator enrollment. The admin credential is supplied explicitly by the
  /// protected admin gate and is never re-used as the ordinary kiosk device key.
  Future<Map<String, dynamic>> adminEnroll({
    required String employeeId,
    required String fullName,
    String? department,
    required List<Uint8List> imageFrames,
    required String adminApiKey,
  }) async {
    config.validateTransport();
    if (adminApiKey.trim().isEmpty) {
      throw const AuthenticationException('Administrator API credential is required for enrollment.');
    }
    _validateImageBurst(imageFrames);
    final uri = Uri.parse('${config.apiBaseUrl}/api/v1/biometrics/enroll/admin');
    final request = http.MultipartRequest('POST', uri);
    request.headers['Authorization'] = 'Bearer ${adminApiKey.trim()}';
    request.fields['employee_id'] = employeeId.trim();
    request.fields['full_name'] = fullName.trim();
    if (department != null && department.trim().isNotEmpty) {
      request.fields['department'] = department.trim();
    }
    _addImageBurst(request, imageFrames, 'admin_enroll');

    final streamedResponse = await _send(request);
    final response = await http.Response.fromStream(streamedResponse);
    final responseBody = _parseJsonBody(response.bodyBytes);
    if (response.statusCode == 201) return responseBody;

    _handleErrorStatus(response.statusCode, responseBody, response.body);
    throw ServerException('Enrollment failed with status ${response.statusCode}');
  }

  Future<http.StreamedResponse> _send(http.BaseRequest request) async {
    try {
      return await _client.send(request);
    } catch (error) {
      throw NetworkException('Network transmission failure: $error');
    }
  }

  void _requireDeviceCredential() {
    if (config.apiKeySecret.trim().isEmpty) {
      throw const AuthenticationException(
        'Kiosk device credential is missing. Configure it in Settings before submitting attendance.',
      );
    }
  }

  void _validateImageBurst(List<Uint8List> imageFrames) {
    if (imageFrames.length < 3 || imageFrames.length > 8) {
      throw const BiometricQualityException(
        'Capture between three and eight distinct camera frames to submit biometric evidence.',
      );
    }
    if (imageFrames.any((frame) => frame.isEmpty)) {
      throw const BiometricQualityException('A captured frame is empty. Please recapture.');
    }
    if (imageFrames.any((frame) => frame.length > config.maxUploadSizeBytes)) {
      throw const PayloadTooLargeException(
        'One or more captured frames exceed the configured upload limit.',
      );
    }
    final totalBytes = imageFrames.fold<int>(0, (total, frame) => total + frame.length);
    if (totalBytes > config.maxUploadSizeBytes * 8) {
      throw const PayloadTooLargeException('The capture burst exceeds the total upload limit.');
    }
  }

  void _addImageBurst(
    http.MultipartRequest request,
    List<Uint8List> imageFrames,
    String filenamePrefix,
  ) {
    for (var index = 0; index < imageFrames.length; index++) {
      request.files.add(
        http.MultipartFile.fromBytes(
          'images',
          imageFrames[index],
          filename: '${filenamePrefix}_${(index + 1).toString().padLeft(2, '0')}.jpg',
        ),
      );
    }
  }

  Map<String, dynamic> _parseJsonBody(Uint8List bodyBytes) {
    try {
      final decoded = jsonDecode(utf8.decode(bodyBytes));
      if (decoded is Map<String, dynamic>) {
        return decoded;
      }
      return {'detail': decoded.toString()};
    } catch (_) {
      return {'detail': 'Invalid response payload from server'};
    }
  }

  void _handleErrorStatus(int statusCode, Map<String, dynamic> body, String rawBody) {
    final detail = body['detail'];

    if (statusCode == 401) {
      if (detail is Map<String, dynamic> && detail.containsKey('similarity_score')) {
        final msg = detail['message'] as String? ?? '';
        if (msg.toLowerCase().contains('unrecognized') || msg.toLowerCase().contains('no matching')) {
          throw UnrecognizedFaceException(
            similarityScore: (detail['similarity_score'] as num).toDouble(),
            requiredThreshold: (detail['required_threshold'] as num).toDouble(),
            message: msg,
          );
        }
        throw BiometricMismatchException(
          similarityScore: (detail['similarity_score'] as num).toDouble(),
          requiredThreshold: (detail['required_threshold'] as num).toDouble(),
          message: msg,
        );
      }
      final msg = detail is String ? detail : 'Invalid or missing API credentials.';
      throw AuthenticationException(msg);
    }

    if (statusCode == 409) {
      if (detail is Map<String, dynamic>) {
        if (detail.containsKey('first_candidate') ||
            (detail['message'] as String? ?? '').toLowerCase().contains('ambiguous')) {
          throw AmbiguousMatchException(
            firstCandidate: detail['first_candidate'] as String? ?? 'Candidate 1',
            firstSimilarity: (detail['first_similarity'] as num?)?.toDouble() ?? 0.0,
            secondCandidate: detail['second_candidate'] as String? ?? 'Candidate 2',
            secondSimilarity: (detail['second_similarity'] as num?)?.toDouble() ?? 0.0,
            margin: (detail['margin'] as num?)?.toDouble() ?? 0.0,
            message: detail['message'] as String?,
          );
        }
        if (detail.containsKey('remaining_seconds')) {
          throw CooldownException(
            remainingSeconds: detail['remaining_seconds'] as int,
            lastPunchTimeUtc: DateTime.parse(detail['last_punch_time'] as String).toUtc(),
            message: detail['message'] as String?,
          );
        }
      }
      throw CooldownException(
        remainingSeconds: 300,
        lastPunchTimeUtc: DateTime.now().toUtc(),
        message: detail is String ? detail : 'Duplicate punch cooldown active.',
      );
    }

    if (statusCode == 403) {
      final msg = detail is String ? detail : 'Employee is deactivated.';
      throw InactiveEmployeeException(msg);
    }

    if (statusCode == 404) {
      if (detail is Map<String, dynamic> && detail.containsKey('similarity_score')) {
        final msg = detail['message'] as String? ?? '';
        throw UnrecognizedFaceException(
          similarityScore: (detail['similarity_score'] as num).toDouble(),
          requiredThreshold: (detail['required_threshold'] as num).toDouble(),
          message: msg,
        );
      }
      final msg = detail is String ? detail : 'Not found.';
      if (msg.toLowerCase().contains('template')) {
        throw TemplateNotEnrolledException(msg);
      }
      throw EmployeeNotFoundException(msg);
    }

    if (statusCode == 413) {
      final msg = detail is String ? detail : 'Image upload size exceeded limit.';
      throw PayloadTooLargeException(msg);
    }

    if (statusCode == 422) {
      final msg = detail is String ? detail : detail.toString();
      final lower = msg.toLowerCase();
      if (lower.contains('multiple faces')) {
        throw MultipleFacesDetectedException(msg);
      }
      if (lower.contains('no face')) {
        throw NoFaceDetectedException(msg);
      }
      throw BiometricQualityException('Input validation failure: $msg');
    }

    if (statusCode == 400) {
      final msg = detail is String ? detail : detail.toString();
      final lower = msg.toLowerCase();
      if (lower.contains('incompatible')) {
        throw IncompatibleModelVersionException(msg);
      }
      throw BiometricQualityException(msg);
    }

    throw ServerException('Server error [$statusCode]: ${detail ?? rawBody}');
  }
}
