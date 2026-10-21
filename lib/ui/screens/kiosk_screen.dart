import 'dart:async';
import 'package:flutter/material.dart';

import '../../config/app_config.dart';
import '../../models/punch_type.dart';
import '../../models/attendance_session.dart';
import '../../services/api_service.dart';
import '../../services/offline_queue_service.dart';
import '../../state/kiosk_state.dart';
import '../theme/app_theme.dart';
import '../widgets/camera_viewport.dart';
import '../widgets/punch_selector.dart';
import '../widgets/status_banner.dart';
import 'admin_enrollment_dialog.dart';
import 'settings_dialog.dart';

/// Main dual-pane screen for the FRS Android Kiosk.
/// Redesigned for automatic 1:N biometric identification (no daily employee ID entry).
class KioskScreen extends StatefulWidget {
  final AppConfig initialConfig;

  const KioskScreen({
    super.key,
    required this.initialConfig,
  });

  @override
  State<KioskScreen> createState() => _KioskScreenState();
}

class _KioskScreenState extends State<KioskScreen> {
  late AppConfig _config;
  late FrsApiService _apiService;
  late final OfflineQueueService _offlineQueueService;
  late final KioskState _state;
  bool _kioskCameraActive = true;
  List<AttendanceSessionOption> _attendanceSessions = <AttendanceSessionOption>[];
  String? _selectedAttendanceSessionId;
  String? _sessionLoadError;
  bool _sessionsLoading = false;
  final GlobalKey<CameraViewportState> _kioskCameraKey = GlobalKey<CameraViewportState>();

  @override
  void initState() {
    super.initState();
    _config = widget.initialConfig;
    _apiService = FrsApiService(config: _config);
    _offlineQueueService = OfflineQueueService();
    _state = KioskState(offlineQueueService: _offlineQueueService);
    _state.addListener(_onStateChanged);
    unawaited(_refreshOpenSessions());
  }

  @override
  void dispose() {
    _state.removeListener(_onStateChanged);
    _state.dispose();
    super.dispose();
  }

  void _onStateChanged() {
    if (mounted) setState(() {});
  }

  void _updateConfig(AppConfig newConfig) {
    setState(() {
      _config = newConfig;
      _apiService = FrsApiService(config: _config);
    });
    unawaited(_refreshOpenSessions());
  }

  Future<void> _refreshOpenSessions() async {
    if (mounted) setState(() { _sessionsLoading = true; _sessionLoadError = null; });
    try {
      await _state.syncOfflineQueue(_apiService);
      final sessions = await _apiService.listOpenAttendanceSessions();
      if (!mounted) return;
      setState(() {
        final priorIndex = _attendanceSessions.indexWhere((item) => item.sessionId == _selectedAttendanceSessionId);
        final priorSelection = priorIndex >= 0 ? _attendanceSessions[priorIndex] : null;
        _attendanceSessions = sessions;
        if (_state.hasPendingSessionBatch && _selectedAttendanceSessionId != null &&
            !_attendanceSessions.any((item) => item.sessionId == _selectedAttendanceSessionId) && priorSelection != null) {
          _attendanceSessions = [..._attendanceSessions, priorSelection];
        }
        if (!_state.hasPendingSessionBatch &&
            !_attendanceSessions.any((item) => item.sessionId == _selectedAttendanceSessionId)) {
          _selectedAttendanceSessionId = _attendanceSessions.isEmpty ? null : _attendanceSessions.first.sessionId;
        }
      });
      await _state.refreshOfflineQueueCount();
    } catch (error) {
      if (mounted) setState(() => _sessionLoadError = error.toString());
    } finally {
      if (mounted) setState(() => _sessionsLoading = false);
    }
  }

  Widget _buildOfflineQueueBadge() {
    if (_state.offlineQueueCount <= 0) return const SizedBox.shrink();
    return Tooltip(
      message: 'Pending attendance batches buffered in encrypted offline queue',
      child: Container(
        margin: const EdgeInsets.symmetric(horizontal: 4, vertical: 12),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: const Color(0xFF1E3A8A).withOpacity(0.3),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0xFF60A5FA)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off_rounded, size: 14, color: Color(0xFF93C5FD)),
            const SizedBox(width: 4),
            Text(
              'Offline: ${_state.offlineQueueCount}',
              style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Color(0xFFDBEAFE)),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildConnectionBadge() {
    if (_config.apiKeySecret.isEmpty) {
      return InkWell(
        key: const ValueKey('connection_badge_setup'),
        onTap: _openSettings,
        borderRadius: BorderRadius.circular(8),
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 12),
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          decoration: BoxDecoration(
            color: AppTheme.warningAmber.withValues(alpha: 0.2),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: AppTheme.warningAmber.withValues(alpha: 0.5)),
          ),
          child: const Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.warning_amber_rounded, size: 14, color: AppTheme.warningAmber),
              SizedBox(width: 4),
              Text(
                'Setup Required',
                style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Colors.white),
              ),
            ],
          ),
        ),
      );
    }
    if (_sessionsLoading) {
      return Container(
        margin: const EdgeInsets.symmetric(vertical: 12),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(8),
        ),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 10,
              height: 10,
              child: CircularProgressIndicator(strokeWidth: 1.5, color: Colors.white70),
            ),
            SizedBox(width: 6),
            Text(
              'Connecting...',
              style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Colors.white),
            ),
          ],
        ),
      );
    }
    if (_sessionLoadError != null) {
      return InkWell(
        key: const ValueKey('connection_badge_offline'),
        onTap: () => unawaited(_refreshOpenSessions()),
        borderRadius: BorderRadius.circular(8),
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 12),
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          decoration: BoxDecoration(
            color: AppTheme.errorRed.withValues(alpha: 0.2),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: AppTheme.errorRed.withValues(alpha: 0.5)),
          ),
          child: const Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.cloud_off, size: 14, color: Colors.white70),
              SizedBox(width: 4),
              Text(
                'Offline (Retry)',
                style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Colors.white),
              ),
            ],
          ),
        ),
      );
    }
    return Container(
      key: const ValueKey('connection_badge_online'),
      margin: const EdgeInsets.symmetric(vertical: 12),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: AppTheme.successGreen.withValues(alpha: 0.2),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppTheme.successGreen.withValues(alpha: 0.5)),
      ),
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.cloud_done, size: 14, color: Colors.greenAccent),
          SizedBox(width: 4),
          Text(
            'Online',
            style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Colors.white),
          ),
        ],
      ),
    );
  }

  Future<void> _openSettings() async {
    try {
      await _kioskCameraKey.currentState?.pauseCamera();
      if (!mounted) return;
      setState(() => _kioskCameraActive = false);
      await showDialog<void>(
        context: context,
        builder: (ctx) => SettingsDialog(
          config: _config,
          onConfigSaved: _updateConfig,
          apiService: _apiService,
        ),
      );
    } finally {
      if (mounted) setState(() => _kioskCameraActive = true);
    }
  }

  Future<void> _authenticateAndOpenAdmin() async {
    final credentialController = TextEditingController();
    try {
      await _kioskCameraKey.currentState?.pauseCamera();
      if (!mounted) return;
      setState(() => _kioskCameraActive = false);
      final credential = await showDialog<String>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Row(children: [
            Icon(Icons.admin_panel_settings, color: AppTheme.primaryBlue),
            SizedBox(width: 10),
            Text('Admin Authentication', style: TextStyle(fontWeight: FontWeight.bold)),
          ]),
          content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text(
              'Enter the administrator API credential issued for this kiosk environment. It is sent only to the configured FRS backend.',
              style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: credentialController,
              obscureText: true,
              autocorrect: false,
              enableSuggestions: false,
              autofocus: true,
              decoration: const InputDecoration(
                labelText: 'Administrator API Credential',
                border: OutlineInputBorder(),
                prefixIcon: Icon(Icons.lock_outline),
              ),
              onSubmitted: (_) => Navigator.of(dialogContext).pop(credentialController.text.trim()),
            ),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.of(dialogContext).pop(), child: const Text('Cancel')),
            ElevatedButton(
              onPressed: () => Navigator.of(dialogContext).pop(credentialController.text.trim()),
              child: const Text('Continue'),
            ),
          ],
        ),
      );

      if (!mounted || credential == null) return;
      if (credential.trim().isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Administrator API credential is required.'),
            backgroundColor: AppTheme.errorRed,
          ),
        );
        return;
      }
      await showDialog<void>(
        context: context,
        builder: (ctx) => AdminEnrollmentDialog(
          config: _config,
          apiService: _apiService,
          adminApiKey: credential.trim(),
        ),
      );
    } finally {
      credentialController.clear();
      credentialController.dispose();
      if (mounted) setState(() => _kioskCameraActive = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.badge_rounded, size: 22, color: Colors.white),
            SizedBox(width: 8),
            Flexible(
              child: Text(
                'FRS Biometric Attendance Kiosk',
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        ),
        actions: [
          _buildOfflineQueueBadge(),
          _buildConnectionBadge(),
          const SizedBox(width: 6),
          Container(
            margin: const EdgeInsets.symmetric(vertical: 12),
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.smartphone, size: 14, color: Colors.white70),
                const SizedBox(width: 4),
                Text(
                  _config.clientDeviceId,
                  style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600),
                ),
              ],
            ),
          ),
          IconButton(
            icon: const Icon(Icons.person_add_alt_1),
            tooltip: 'Administrator Enrollment',
            onPressed: () => _authenticateAndOpenAdmin(),
          ),
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            tooltip: 'Kiosk Settings',
            onPressed: () => _openSettings(),
          ),
        ],
      ),
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) {
            // Adaptive layout: 2 columns on tablet/landscape, 1 column on narrow portrait
            final isWide = constraints.maxWidth >= 800;

            if (isWide) {
              return Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // Left Pane: Real Camera Stream & Biometric Alignment Reticle
                  Expanded(
                    flex: 5,
                    child: Padding(
                      padding: const EdgeInsets.all(20.0),
                      child: CameraViewport(
                         key: _kioskCameraKey,
                        capturedImages: _state.capturedImages,
                        onImagesCaptured: _state.setCapturedImages,
                         isActive: _kioskCameraActive,
                        onRetakePressed: _state.clearCapturedImage,
                        isSubmitting: _state.isSubmitting,
                        canRetake: !_state.hasPendingSessionBatch,
                      ),
                    ),
                  ),

                  // Right Pane: Punch Mode, Automatic 1:N Submission & Feedback
                  Expanded(
                    flex: 6,
                    child: SingleChildScrollView(
                      padding: const EdgeInsets.all(20.0),
                      child: _buildInteractionColumn(),
                    ),
                  ),
                ],
              );
            } else {
              // Narrow/Portrait fallback
              return SingleChildScrollView(
                padding: const EdgeInsets.all(16.0),
                child: Column(
                  children: [
                    SizedBox(
                      height: 340,
                      child: CameraViewport(
                         key: _kioskCameraKey,
                        capturedImages: _state.capturedImages,
                        onImagesCaptured: _state.setCapturedImages,
                         isActive: _kioskCameraActive,
                        onRetakePressed: _state.clearCapturedImage,
                        isSubmitting: _state.isSubmitting,
                        canRetake: !_state.hasPendingSessionBatch,
                      ),
                    ),
                    const SizedBox(height: 16),
                    _buildInteractionColumn(),
                  ],
                ),
              );
            }
          },
        ),
      ),
    );
  }

  Widget _buildInteractionColumn() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (_config.apiKeySecret.isEmpty) ...[
          Container(
            key: const ValueKey('kiosk_unconfigured_banner'),
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: AppTheme.warningBg,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppTheme.warningAmber.withValues(alpha: 0.4)),
            ),
            child: Row(
              children: [
                const Icon(Icons.settings_suggest_rounded, color: AppTheme.warningAmber, size: 28),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Kiosk Device Unconfigured',
                        style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14, color: AppTheme.textPrimary),
                      ),
                      const SizedBox(height: 4),
                      const Text(
                        'This kiosk has not been provisioned with a backend URL or API key secret.',
                        style: TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                      ),
                      const SizedBox(height: 8),
                      ElevatedButton.icon(
                        key: const ValueKey('configure_kiosk_button'),
                        onPressed: _openSettings,
                        icon: const Icon(Icons.settings, size: 16),
                        label: const Text('Configure Device Settings'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppTheme.warningAmber,
                          foregroundColor: Colors.white,
                          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                          textStyle: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
        ],

        // Choose a persisted OPEN class attendance session before submitting.
        Row(
          children: [
            Expanded(
              child: DropdownButtonFormField<String>(
                value: _selectedAttendanceSessionId,
                isExpanded: true,
                decoration: const InputDecoration(
                  labelText: 'Open attendance session',
                  prefixIcon: Icon(Icons.class_outlined),
                  border: OutlineInputBorder(),
                ),
                items: _attendanceSessions.map((session) => DropdownMenuItem<String>(
                  value: session.sessionId,
                  child: Text(session.displayLabel, overflow: TextOverflow.ellipsis),
                )).toList(),
                onChanged: (_state.isSubmitting || _state.hasPendingSessionBatch || _sessionsLoading)
                    ? null
                    : (value) => setState(() => _selectedAttendanceSessionId = value),
              ),
            ),
            const SizedBox(width: 8),
            IconButton(
              tooltip: 'Refresh open sessions',
              onPressed: _sessionsLoading || _state.isSubmitting ? null : () => unawaited(_refreshOpenSessions()),
              icon: _sessionsLoading
                  ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.refresh),
            ),
          ],
        ),
        if (_sessionLoadError != null) ...[
          const SizedBox(height: 6),
          Text(_sessionLoadError!, style: const TextStyle(color: AppTheme.errorRed, fontSize: 12)),
        ],
        if (!_sessionsLoading && _attendanceSessions.isEmpty) ...[
          const SizedBox(height: 6),
          const Text('No open attendance sessions are available. Create and open a class session in the admin console.',
            style: TextStyle(color: AppTheme.textSecondary, fontSize: 12)),
        ],
        const SizedBox(height: 16),

        // Punch type is scoped to the selected attendance session.
        PunchSelector(
          selectedType: _state.punchType,
          onChanged: _state.setPunchType,
          enabled: !_state.isSubmitting,
        ),
        const SizedBox(height: 16),

        // 2. Clear instructions card
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: AppTheme.cardBg,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: const Color(0xFFE2E8F0)),
          ),
          child: const Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(Icons.face_retouching_natural, color: AppTheme.primaryBlue, size: 20),
                  SizedBox(width: 8),
                  Text(
                    'Automatic Face Identification',
                    style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
                  ),
                ],
              ),
              SizedBox(height: 8),
              Text(
                '1. Select the correct open class/session.\n'
                '2. Look at the camera and capture three separate frames.\n'
                '3. Submit once; the server queues, recognizes and confirms attendance.',
                style: TextStyle(fontSize: 13, color: AppTheme.textSecondary, height: 1.4),
              ),
            ],
          ),
        ),
        const SizedBox(height: 20),

        // 3. Primary Action Button (Submit Automatic 1:N Punch)
        ElevatedButton(
          key: const ValueKey('submit_punch_button'),
          onPressed: _state.canSubmit && _selectedAttendanceSessionId != null
              ? () => _state.submitSessionAttendance(_apiService, _selectedAttendanceSessionId!)
              : null,
          style: ElevatedButton.styleFrom(
            backgroundColor: _state.punchType == PunchType.checkIn
                ? AppTheme.successGreen
                : AppTheme.warningAmber,
            disabledBackgroundColor: const Color(0xFFCBD5E1),
            minimumSize: const Size.fromHeight(56),
          ),
          child: _state.isSubmitting
              ? const Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                      ),
                    ),
                    SizedBox(width: 12),
                    Text('Identifying Face in Database...'),
                  ],
                )
              : Text(
                  _selectedAttendanceSessionId == null
                      ? 'Select an open session'
                      : (_state.hasPendingSessionBatch
                          ? 'Resume attendance confirmation'
                          : (_state.capturedImage == null
                              ? 'Capture 3 Frames to Punch'
                              : (_state.punchType == PunchType.checkIn
                                  ? 'Submit CHECK IN to Session'
                                  : 'Submit CHECK OUT to Session'))),
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                ),
        ),

        if (_state.capturedImage != null && !_state.isSubmitting) ...[
          const SizedBox(height: 10),
          OutlinedButton.icon(
            key: const ValueKey('retake_button'),
            onPressed: _state.hasPendingSessionBatch ? null : _state.clearCapturedImage,
            icon: const Icon(Icons.refresh, size: 18),
            label: const Text('Clear / Retake Photo'),
            style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(44)),
          ),
        ],

        const SizedBox(height: 16),

        // 4. Status Banner & Verification Result
        StatusBanner(
          state: _state,
          onDismiss: _state.reset,
        ),
      ],
    );
  }
}
