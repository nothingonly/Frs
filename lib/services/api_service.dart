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

  /// Submits probe image and employee ID for 1:1 biometric verification via POST /api/v1/attendance/verify.
  Future<AttendanceVerificationResult> verifyAttendance({
    required String employeeId,
    required Uint8List imageBytes,
    required PunchType punchType,
    String? clientDeviceId,
  }) async {
    // 1. Client-side sanity check on payload size
    if (imageBytes.length > config.maxUploadSizeBytes) {
      throw PayloadTooLargeException(
        'Captured image (${imageBytes.length} bytes) exceeds limit (${config.maxUploadSizeBytes} bytes).',
      );
    }

    final uri = Uri.parse('${config.apiBaseUrl}/api/v1/attendance/verify');
    final request = http.MultipartRequest('POST', uri);

    // 2. Authentication header (Bearer token)
    request.headers['Authorization'] = 'Bearer ${config.apiKeySecret}';

    // 3. Form parameters
    request.fields['employee_id'] = employeeId.trim();
    request.fields['punch_type'] = punchType.value;
    final deviceId = clientDeviceId ?? config.clientDeviceId;
    request.fields['client_device_id'] = deviceId;

    // 4. Attach image bytes
    request.files.add(
      http.MultipartFile.fromBytes(
        'image',
        imageBytes,
        filename: 'kiosk_probe.jpg',
      ),
    );

    // 5. Send multipart stream
    http.StreamedResponse streamedResponse;
    try {
      streamedResponse = await _client.send(request);
    } catch (e) {
      throw NetworkException('Network transmission failure: $e');
    }

    // 6. Decode response body
    final response = await http.Response.fromStream(streamedResponse);
    final responseBody = _parseJsonBody(response.bodyBytes);

    // 7. Status code dispatch
    final statusCode = response.statusCode;

    if (statusCode == 200) {
      return AttendanceVerificationResult.fromJson(responseBody);
    }

    _handleErrorStatus(statusCode, responseBody, response.body);
    throw ServerException('Unexpected response status $statusCode');
  }

  /// Submits probe image for automatic 1:N biometric identification via POST /api/v1/attendance/identify.
  Future<AttendanceIdentificationResult> identifyAttendance({
    required Uint8List imageBytes,
    required PunchType punchType,
    String? clientDeviceId,
  }) async {
    if (imageBytes.length > config.maxUploadSizeBytes) {
      throw PayloadTooLargeException(
        'Captured image (${imageBytes.length} bytes) exceeds limit (${config.maxUploadSizeBytes} bytes).',
      );
    }

    final uri = Uri.parse('${config.apiBaseUrl}/api/v1/attendance/identify');
    final request = http.MultipartRequest('POST', uri);

    request.headers['Authorization'] = 'Bearer ${config.apiKeySecret}';
    request.fields['punch_type'] = punchType.value;
    final deviceId = clientDeviceId ?? config.clientDeviceId;
    request.fields['client_device_id'] = deviceId;

    request.files.add(
      http.MultipartFile.fromBytes(
        'image',
        imageBytes,
        filename: 'kiosk_identify_probe.jpg',
      ),
    );

    http.StreamedResponse streamedResponse;
    try {
      streamedResponse = await _client.send(request);
    } catch (e) {
      throw NetworkException('Network transmission failure: $e');
    }

    final response = await http.Response.fromStream(streamedResponse);
    final responseBody = _parseJsonBody(response.bodyBytes);
    final statusCode = response.statusCode;

    if (statusCode == 200) {
      return AttendanceIdentificationResult.fromJson(responseBody);
    }

    _handleErrorStatus(statusCode, responseBody, response.body);
    throw ServerException('Unexpected response status $statusCode');
  }

  /// Admin workflow enrolling or updating an employee profile with facial template.
  Future<Map<String, dynamic>> adminEnroll({
    required String employeeId,
    required String fullName,
    String? department,
    required Uint8List imageBytes,
  }) async {
    if (imageBytes.length > config.maxUploadSizeBytes) {
      throw const PayloadTooLargeException('Enrollment image exceeds size limit.');
    }

    final uri = Uri.parse('${config.apiBaseUrl}/api/v1/biometrics/enroll/admin');
    final request = http.MultipartRequest('POST', uri);

    request.headers['Authorization'] = 'Bearer ${config.apiKeySecret}';
    request.fields['employee_id'] = employeeId.trim();
    request.fields['full_name'] = fullName.trim();
    if (department != null && department.trim().isNotEmpty) {
      request.fields['department'] = department.trim();
    }

    request.files.add(
      http.MultipartFile.fromBytes(
        'image',
        imageBytes,
        filename: 'admin_enroll.jpg',
      ),
    );

    http.StreamedResponse streamedResponse;
    try {
      streamedResponse = await _client.send(request);
    } catch (e) {
      throw NetworkException('Network transmission failure: $e');
    }

    final response = await http.Response.fromStream(streamedResponse);
    final responseBody = _parseJsonBody(response.bodyBytes);
    if (response.statusCode == 201) {
      return responseBody;
    }

    _handleErrorStatus(response.statusCode, responseBody, response.body);
    throw ServerException('Enrollment failed with status ${response.statusCode}');
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
