/// Health check response from GET /health.
class HealthStatus {
  final String status;
  final String environment;
  final String database;
  final String modelVersion;
  final double similarityThreshold;
  final String thresholdStatus;

  HealthStatus({
    required this.status,
    required this.environment,
    required this.database,
    required this.modelVersion,
    required this.similarityThreshold,
    required this.thresholdStatus,
  });

  factory HealthStatus.fromJson(Map<String, dynamic> json) {
    return HealthStatus(
      status: json['status'] as String? ?? 'unknown',
      environment: json['environment'] as String? ?? 'unknown',
      database: json['database'] as String? ?? 'unknown',
      modelVersion: json['model_version'] as String? ?? 'unknown',
      similarityThreshold: (json['similarity_threshold'] as num?)?.toDouble() ?? 0.363,
      thresholdStatus: json['threshold_status'] as String? ?? 'UNRECALIBRATED_BASELINE',
    );
  }

  bool get isHealthy => status == 'online' && database == 'healthy';
}
