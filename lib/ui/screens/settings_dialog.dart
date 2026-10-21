import 'package:flutter/material.dart';
import '../../config/app_config.dart';
import '../../services/api_service.dart';
import '../../services/lock_task_service.dart';
import '../theme/app_theme.dart';

/// Configuration dialog allowing administrators to update the backend URL and test connection.
class SettingsDialog extends StatefulWidget {
  final AppConfig config;
  final ValueChanged<AppConfig> onConfigSaved;
  final FrsApiService apiService;
  final LockTaskService? lockTaskService;

  const SettingsDialog({
    super.key,
    required this.config,
    required this.onConfigSaved,
    required this.apiService,
    this.lockTaskService,
  });

  @override
  State<SettingsDialog> createState() => _SettingsDialogState();
}

class _SettingsDialogState extends State<SettingsDialog> {
  late final TextEditingController _urlController;
  late final TextEditingController _deviceIdController;
  late final TextEditingController _deviceApiKeyController;
  late final LockTaskService _lockTaskService;
  late bool _allowInsecureDevelopmentHttp;
  String? _saveError;
  bool _testingConnection = false;
  String? _testResult;
  bool _testSuccess = false;
  bool? _isDeviceOwner;
  bool? _isLockTaskPermitted;
  String? _lockTaskMessage;

  @override
  void initState() {
    super.initState();
    _lockTaskService = widget.lockTaskService ?? const LockTaskService();
    _allowInsecureDevelopmentHttp = widget.config.allowInsecureDevelopmentHttp;
    _urlController = TextEditingController(text: widget.config.apiBaseUrl);
    _deviceIdController = TextEditingController(text: widget.config.clientDeviceId);
    _deviceApiKeyController = TextEditingController(text: widget.config.apiKeySecret);
    _checkLockTaskStatus();
  }

  Future<void> _checkLockTaskStatus() async {
    final owner = await _lockTaskService.isDeviceOwner();
    final permitted = await _lockTaskService.isLockTaskPermitted();
    if (mounted) {
      setState(() {
        _isDeviceOwner = owner;
        _isLockTaskPermitted = permitted;
      });
    }
  }

  @override
  void dispose() {
    _urlController.dispose();
    _deviceIdController.dispose();
    _deviceApiKeyController.dispose();
    super.dispose();
  }

  Future<void> _runHealthCheck() async {
    setState(() {
      _testingConnection = true;
      _testResult = null;
    });

    final tempConfig = widget.config.copyWith(
      apiBaseUrl: _urlController.text.trim(),
      clientDeviceId: _deviceIdController.text.trim(),
      apiKeySecret: _deviceApiKeyController.text.trim(),
      allowInsecureDevelopmentHttp: _allowInsecureDevelopmentHttp,
    );
    final tempService = FrsApiService(config: tempConfig);

    try {
      final health = await tempService.checkHealth();
      if (!mounted) return;
      setState(() {
        _testingConnection = false;
        _testSuccess = true;
        _testResult = 'Connected: Status=${health.status}, DB=${health.database}, Model=${health.modelVersion}';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _testingConnection = false;
        _testSuccess = false;
        _testResult = 'Connection Failed: $e';
      });
    }
  }

  Future<void> _save() async {
    final updated = widget.config.copyWith(
      apiBaseUrl: _urlController.text.trim(),
      apiKeySecret: _deviceApiKeyController.text.trim(),
      clientDeviceId: _deviceIdController.text.trim(),
      allowInsecureDevelopmentHttp: _allowInsecureDevelopmentHttp,
    );
    try {
      updated.validateTransport();
      if (updated.apiKeySecret.trim().isEmpty) {
        throw const FormatException('The device API credential must be provisioned by the FRS administrator.');
      }
      await updated.persistSecureSettings();
      widget.onConfigSaved(updated);
      if (mounted) Navigator.of(context).pop();
    } catch (e) {
      if (mounted) setState(() => _saveError = e.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Row(
        children: [
          Icon(Icons.settings_rounded, color: AppTheme.primaryDark),
          SizedBox(width: 12),
          Text('Kiosk Configuration', style: TextStyle(fontWeight: FontWeight.w700)),
        ],
      ),
      content: SizedBox(
        width: 500,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Security Warning Box (Requirement 8)
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: AppTheme.warningBg,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: AppTheme.warningAmber.withOpacity(0.4)),
                ),
                child: const Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(Icons.security_rounded, color: AppTheme.warningAmber, size: 20),
                    SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'TRUSTED KIOSK / PILOT SECURITY NOTICE:\n'
                        'The pre-shared API secret authenticates the physical kiosk device only. '
                        'It does not grant or replace individual employee credentials.',
                        style: TextStyle(
                          fontSize: 12,
                          color: AppTheme.textPrimary,
                          fontWeight: FontWeight.w500,
                          height: 1.3,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),

              // Backend URL input
              const Text('Backend Base URL', style: TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 6),
              TextField(
                controller: _urlController,
                decoration: InputDecoration(
                  hintText: 'http://10.0.2.2:8000',
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                  helperText: 'Android Emulator: 10.0.2.2:8000 | Desktop: 127.0.0.1:8000',
                  prefixIcon: const Icon(Icons.link_rounded),
                ),
              ),
              const SizedBox(height: 16),

              // Device ID input
              const Text('Kiosk Device ID', style: TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 6),
              TextField(
                controller: _deviceIdController,
                decoration: InputDecoration(
                  hintText: 'KIOSK_ANDROID_01',
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                  prefixIcon: const Icon(Icons.tablet_android_rounded),
                ),
              ),
              const SizedBox(height: 16),

              const Text('Kiosk Device API Credential', style: TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 6),
              TextField(
                controller: _deviceApiKeyController,
                obscureText: true,
                autocorrect: false,
                enableSuggestions: false,
                decoration: InputDecoration(
                  labelText: 'Device bearer credential',
                  helperText: 'Stored encrypted by Android secure storage. Provision a separate admin credential for enrollment.',
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                  prefixIcon: const Icon(Icons.key_rounded),
                ),
              ),
              const SizedBox(height: 8),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: _allowInsecureDevelopmentHttp,
                onChanged: (value) => setState(() => _allowInsecureDevelopmentHttp = value ?? false),
                title: const Text('Allow loopback HTTP for local development only'),
                subtitle: const Text('Disabled by default. Production backend URLs must use HTTPS.'),
                controlAffinity: ListTileControlAffinity.leading,
              ),
              const SizedBox(height: 12),

              // Test Connection button
              Row(
                children: [
                  OutlinedButton.icon(
                    onPressed: _testingConnection ? null : _runHealthCheck,
                    icon: _testingConnection
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.network_check_rounded, size: 18),
                    label: const Text('Test Connection (GET /health)'),
                  ),
                ],
              ),
              if (_saveError != null) ...[
                const SizedBox(height: 8),
                Text(_saveError!, style: const TextStyle(fontSize: 12, color: AppTheme.errorRed)),
              ],
              if (_testResult != null) ...[
                const SizedBox(height: 8),
                Text(
                  _testResult!,
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: _testSuccess ? AppTheme.successGreen : AppTheme.errorRed,
                  ),
                ),
              ],
              const SizedBox(height: 16),
              const Divider(),
              const SizedBox(height: 8),
              const Text('Hardware Lock & Device Owner (Kiosk Mode)', style: TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 6),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: Colors.grey.shade100,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.grey.shade300),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Device Owner: ${_isDeviceOwner == null ? "Checking..." : (_isDeviceOwner! ? "ACTIVE (Provisioned)" : "NOT PROVISIONED")}',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: (_isDeviceOwner ?? false) ? AppTheme.successGreen : Colors.orange.shade800,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Lock Task Permitted: ${_isLockTaskPermitted == null ? "Checking..." : (_isLockTaskPermitted! ? "YES" : "NO")}',
                      style: TextStyle(
                        fontSize: 12,
                        color: (_isLockTaskPermitted ?? false) ? AppTheme.successGreen : Colors.grey.shade700,
                      ),
                    ),
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        ElevatedButton.icon(
                          onPressed: () async {
                            final success = await _lockTaskService.enableKioskMode();
                            if (mounted) {
                              setState(() {
                                _lockTaskMessage = success
                                    ? 'Kiosk Lock Task mode started.'
                                    : 'Failed to start Lock Task. Check Device Owner permissions.';
                              });
                              _checkLockTaskStatus();
                            }
                          },
                          icon: const Icon(Icons.lock_rounded, size: 16),
                          label: const Text('Start Lock Task'),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: AppTheme.primaryDark,
                            foregroundColor: Colors.white,
                            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                            textStyle: const TextStyle(fontSize: 12),
                          ),
                        ),
                        const SizedBox(width: 8),
                        OutlinedButton.icon(
                          onPressed: () async {
                            final success = await _lockTaskService.stopLockTask();
                            if (mounted) {
                              setState(() {
                                _lockTaskMessage = success
                                    ? 'Lock Task stopped.'
                                    : 'Failed to stop Lock Task.';
                              });
                              _checkLockTaskStatus();
                            }
                          },
                          icon: const Icon(Icons.lock_open_rounded, size: 16),
                          label: const Text('Stop Lock Task'),
                          style: OutlinedButton.styleFrom(
                            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                            textStyle: const TextStyle(fontSize: 12),
                          ),
                        ),
                      ],
                    ),
                    if (_lockTaskMessage != null) ...[
                      const SizedBox(height: 6),
                      Text(
                        _lockTaskMessage!,
                        style: const TextStyle(fontSize: 11, fontStyle: FontStyle.italic),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        ElevatedButton(
          onPressed: _save,
          style: ElevatedButton.styleFrom(minimumSize: const Size(100, 44)),
          child: const Text('Save Settings'),
        ),
      ],
    );
  }
}
