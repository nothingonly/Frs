import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Runtime settings for an FRS kiosk. Credentials are loaded from encrypted
/// platform secure storage, never compiled into the application.
class AppConfig {
  static const FlutterSecureStorage _secureStorage = FlutterSecureStorage();

  static const String _baseUrlKey = 'frs.api_base_url';
  static const String _deviceKey = 'frs.device_api_key';
  static const String _deviceIdKey = 'frs.device_id';

  final String apiBaseUrl;
  final String apiKeySecret;
  final String clientDeviceId;
  final int maxUploadSizeBytes;
  final double minSharpnessThreshold;
  final bool allowInsecureDevelopmentHttp;

  const AppConfig({
    this.apiBaseUrl = 'http://127.0.0.1:8000',
    this.apiKeySecret = '',
    this.clientDeviceId = 'KIOSK_ANDROID_01',
    this.maxUploadSizeBytes = 5 * 1024 * 1024,
    this.minSharpnessThreshold = 25.0,
    this.allowInsecureDevelopmentHttp = false,
  });

  static Future<AppConfig> loadFromSecureStorage() async {
    final values = await Future.wait([
      _secureStorage.read(key: _baseUrlKey),
      _secureStorage.read(key: _deviceKey),
      _secureStorage.read(key: _deviceIdKey),
    ]);
    return AppConfig(
      apiBaseUrl: values[0]?.trim().isNotEmpty == true
          ? values[0]!.trim()
          : 'http://127.0.0.1:8000',
      apiKeySecret: values[1] ?? '',
      clientDeviceId: values[2]?.trim().isNotEmpty == true
          ? values[2]!.trim()
          : 'KIOSK_ANDROID_01',
      allowInsecureDevelopmentHttp: false,
    );
  }

  Future<void> persistSecureSettings() async {
    await _secureStorage.write(key: _baseUrlKey, value: apiBaseUrl.trim());
    await _secureStorage.write(key: _deviceKey, value: apiKeySecret.trim());
    await _secureStorage.write(key: _deviceIdKey, value: clientDeviceId.trim());
  }

  AppConfig copyWith({
    String? apiBaseUrl,
    String? apiKeySecret,
    String? clientDeviceId,
    bool? allowInsecureDevelopmentHttp,
  }) {
    return AppConfig(
      apiBaseUrl: apiBaseUrl ?? this.apiBaseUrl,
      apiKeySecret: apiKeySecret ?? this.apiKeySecret,
      clientDeviceId: clientDeviceId ?? this.clientDeviceId,
      maxUploadSizeBytes: maxUploadSizeBytes,
      minSharpnessThreshold: minSharpnessThreshold,
      allowInsecureDevelopmentHttp:
          allowInsecureDevelopmentHttp ?? this.allowInsecureDevelopmentHttp,
    );
  }

  void validateTransport() {
    final uri = Uri.tryParse(apiBaseUrl.trim());
    if (uri == null || !uri.hasAuthority || uri.host.isEmpty) {
      throw const FormatException('Backend URL is not a valid absolute URL.');
    }
    if (uri.scheme != 'https') {
      final loopback = const {'127.0.0.1', 'localhost', '10.0.2.2', '::1'}
          .contains(uri.host);
      if (!allowInsecureDevelopmentHttp || !loopback) {
        throw const FormatException(
          'HTTPS is required. HTTP is permitted only for explicitly enabled local development endpoints.',
        );
      }
    }
  }
}
