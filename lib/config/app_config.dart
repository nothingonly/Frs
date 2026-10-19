/// Configuration settings for the FRS Kiosk client application.
class AppConfig {
  /// Base URL of the backend API.
  /// - Android Emulator: 'http://10.0.2.2:8000'
  /// - Localhost (Desktop): 'http://127.0.0.1:8000'
  /// - Local LAN Device: 'http://192.168.x.x:8000'
  final String apiBaseUrl;

  /// Pre-shared service authentication secret.
  ///
  /// CRITICAL SECURITY NOTICE:
  /// This shared-secret represents device/kiosk-level authentication and is
  /// strictly intended for DEVELOPMENT and TRUSTED-KIOSK pilots. It does NOT
  /// represent individual employee credentials. For production distributions,
  /// this secret must be provisioned via Android KeyStore / secure element attestation.
  final String apiKeySecret;

  /// Physical kiosk identifier reported in attendance audit records.
  final String clientDeviceId;

  /// Maximum image payload size (5 MB server limit).
  final int maxUploadSizeBytes;

  /// Image sharpness variance threshold calibrated on backend.
  final double minSharpnessThreshold;

  const AppConfig({
    this.apiBaseUrl = 'http://127.0.0.1:8000',
    this.apiKeySecret = 'dev_insecure_local_secret_key_32bytes_min',
    this.clientDeviceId = 'KIOSK_ANDROID_01',
    this.maxUploadSizeBytes = 5 * 1024 * 1024,
    this.minSharpnessThreshold = 25.0,
  });

  AppConfig copyWith({
    String? apiBaseUrl,
    String? apiKeySecret,
    String? clientDeviceId,
  }) {
    return AppConfig(
      apiBaseUrl: apiBaseUrl ?? this.apiBaseUrl,
      apiKeySecret: apiKeySecret ?? this.apiKeySecret,
      clientDeviceId: clientDeviceId ?? this.clientDeviceId,
      maxUploadSizeBytes: maxUploadSizeBytes,
      minSharpnessThreshold: minSharpnessThreshold,
    );
  }
}
