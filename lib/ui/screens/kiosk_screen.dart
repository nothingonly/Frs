import 'package:flutter/material.dart';

import '../../config/app_config.dart';
import '../../models/punch_type.dart';
import '../../services/api_service.dart';
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
  late final KioskState _state;
  bool _kioskCameraActive = true;
  final GlobalKey<CameraViewportState> _kioskCameraKey = GlobalKey<CameraViewportState>();

  @override
  void initState() {
    super.initState();
    _config = widget.initialConfig;
    _apiService = FrsApiService(config: _config);
    _state = KioskState();
    _state.addListener(_onStateChanged);
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
        // 1. Punch Type Toggle (CHECK_IN vs CHECK_OUT)
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
                '1. Look directly at the camera with face centered.\n'
                '2. Tap "Capture Face" on the camera preview.\n'
                '3. Tap the button below to automatically record attendance.',
                style: TextStyle(fontSize: 13, color: AppTheme.textSecondary, height: 1.4),
              ),
            ],
          ),
        ),
        const SizedBox(height: 20),

        // 3. Primary Action Button (Submit Automatic 1:N Punch)
        ElevatedButton(
          key: const ValueKey('submit_punch_button'),
          onPressed: _state.canSubmit
              ? () => _state.submitAutomaticIdentification(_apiService)
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
                  _state.capturedImage == null
                      ? 'Capture 3 Frames to Punch'
                      : (_state.punchType == PunchType.checkIn
                          ? 'Submit CHECK IN'
                          : 'Submit CHECK OUT'),
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                ),
        ),

        if (_state.capturedImage != null && !_state.isSubmitting) ...[
          const SizedBox(height: 10),
          OutlinedButton.icon(
            key: const ValueKey('retake_button'),
            onPressed: _state.clearCapturedImage,
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
