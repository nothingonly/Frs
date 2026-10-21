import 'dart:async';
import 'dart:typed_data';
import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

import '../../config/app_config.dart';
import '../../models/attendance_session.dart';
import '../../models/group_attendance_models.dart';
import '../../models/punch_type.dart';
import '../../services/api_service.dart';
import '../../services/offline_queue_service.dart';
import '../../state/kiosk_state.dart';
import '../theme/app_theme.dart';
import '../widgets/camera_viewport.dart';
import '../widgets/punch_selector.dart';
import '../widgets/status_banner.dart';
import 'admin_enrollment_dialog.dart';
import 'settings_dialog.dart';

/// Top-level operating modes for the FRS Kiosk.
enum KioskViewMode {
  groupPhoto,
  individualPunch,
}

/// Workflow steps for the College Group-Photo Attendance process.
enum GroupWorkflowStep {
  sessionSetup,
  capturePhotos,
  reviewRoster,
  finalized,
}

/// Redesigned Engineering-College Attendance Screen.
/// Supports multi-photo group capture covering 60-70 students per class across
/// 7 departments (CSE, CSD, MECH, CIVIL, IT, ECE, EEE), B.Tech years 1-4, semesters 1-8,
/// sections A-D, configured labs, and mixed cross-section classes.
class KioskScreen extends StatefulWidget {
  final AppConfig initialConfig;
  final KioskViewMode initialMode;

  const KioskScreen({
    super.key,
    required this.initialConfig,
    this.initialMode = KioskViewMode.groupPhoto,
  });

  @override
  State<KioskScreen> createState() => _KioskScreenState();
}

class _KioskScreenState extends State<KioskScreen> {
  late AppConfig _config;
  late FrsApiService _apiService;
  late final OfflineQueueService _offlineQueueService;
  late final KioskState _state;
  late KioskViewMode _viewMode;

  bool _kioskCameraActive = true;
  List<AttendanceSessionOption> _attendanceSessions = <AttendanceSessionOption>[];
  String? _selectedAttendanceSessionId;
  String? _sessionLoadError;
  bool _sessionsLoading = false;

  // Group Attendance Workflow state
  GroupWorkflowStep _groupStep = GroupWorkflowStep.sessionSetup;
  String _departmentFilter = 'ALL';
  String _sessionTypeFilter = 'ALL';
  SessionProvisionalState? _provisionalState;
  bool _loadingProvisional = false;
  bool _isUploadingGroupPhoto = false;
  GroupCaptureResult? _lastCaptureResult;
  final List<GroupCaptureResult> _captureHistory = [];
  String _rosterSearchQuery = '';
  String _rosterFilter = 'ALL'; // 'ALL', 'PRESENT', 'FLAGGED', 'ABSENT'
  bool _isFinalizing = false;
  FinalizeAttendanceResult? _finalizeResult;

  final GlobalKey<CameraViewportState> _kioskCameraKey = GlobalKey<CameraViewportState>();
  final TextEditingController _rosterSearchController = TextEditingController();

  static const List<String> _departments = [
    'ALL', 'CSE', 'CSD', 'MECH', 'CIVIL', 'IT', 'ECE', 'EEE'
  ];

  @override
  void initState() {
    super.initState();
    _config = widget.initialConfig;
    _viewMode = widget.initialMode;
    _apiService = FrsApiService(config: _config);
    _offlineQueueService = OfflineQueueService();
    _state = KioskState(offlineQueueService: _offlineQueueService);
    _state.addListener(_onStateChanged);
    unawaited(_refreshOpenSessions());
  }

  @override
  void dispose() {
    _rosterSearchController.dispose();
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

  AttendanceSessionOption? get _selectedSession {
    if (_selectedAttendanceSessionId == null) return null;
    for (final s in _attendanceSessions) {
      if (s.sessionId == _selectedAttendanceSessionId) return s;
    }
    return null;
  }

  List<AttendanceSessionOption> get _filteredSessions {
    return _attendanceSessions.where((session) {
      if (_departmentFilter != 'ALL' && session.departmentCode.toUpperCase() != _departmentFilter) {
        return false;
      }
      if (_sessionTypeFilter == 'CLASS' && (session.isLab || session.isMixed)) {
        return false;
      }
      if (_sessionTypeFilter == 'LAB' && !session.isLab) {
        return false;
      }
      if (_sessionTypeFilter == 'MIXED' && !session.isMixed) {
        return false;
      }
      return true;
    }).toList();
  }

  Future<void> _refreshOpenSessions() async {
    if (mounted) setState(() { _sessionsLoading = true; _sessionLoadError = null; });
    try {
      await _state.syncOfflineQueue(_apiService);
      final sessions = await _apiService.listOpenAttendanceSessions();
      if (!mounted) return;
      setState(() {
        _attendanceSessions = sessions;
        if (_selectedAttendanceSessionId == null ||
            !_attendanceSessions.any((item) => item.sessionId == _selectedAttendanceSessionId)) {
          _selectedAttendanceSessionId = _attendanceSessions.isEmpty ? null : _attendanceSessions.first.sessionId;
        }
      });
      if (_selectedAttendanceSessionId != null) {
        unawaited(_loadProvisionalState(_selectedAttendanceSessionId!));
      }
      await _state.refreshOfflineQueueCount();
    } catch (error) {
      if (mounted) setState(() => _sessionLoadError = error.toString());
    } finally {
      if (mounted) setState(() => _sessionsLoading = false);
    }
  }

  Future<void> _loadProvisionalState(String sessionId) async {
    if (_loadingProvisional) return;
    setState(() => _loadingProvisional = true);
    try {
      final state = await _apiService.getSessionProvisionalState(sessionId);
      if (mounted) {
        setState(() {
          _provisionalState = state;
          _loadingProvisional = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loadingProvisional = false);
    }
  }

  Future<void> _handleGroupPhotoCapture(Uint8List photoBytes) async {
    final sessionId = _selectedAttendanceSessionId;
    if (sessionId == null || _isUploadingGroupPhoto) return;

    setState(() => _isUploadingGroupPhoto = true);

    try {
      final result = await _apiService.uploadGroupPhoto(
        sessionId: sessionId,
        imageBytes: photoBytes,
      );

      if (!mounted) return;
      setState(() {
        _lastCaptureResult = result;
        _captureHistory.insert(0, result);
        _provisionalState = result.cumulativeState;
        _isUploadingGroupPhoto = false;
      });

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: AppTheme.successGreen,
          duration: const Duration(seconds: 4),
          content: Text(
            'Photo #${result.photoIndex} Processed: '
            '${result.facesDetectedCount} faces detected, '
            '${result.facesMatchedCount} recognized, '
            '${result.duplicatesIgnoredCount} duplicates ignored. '
            'Cumulative: ${result.cumulativeState.presentCount}/${result.cumulativeState.expectedCount} Present.',
          ),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() => _isUploadingGroupPhoto = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: AppTheme.errorRed,
          content: Text('Failed to process group photo: $e'),
        ),
      );
    }
  }

  Future<void> _toggleStudentStatus(RosterStudent student, String newStatus) async {
    final sessionId = _selectedAttendanceSessionId;
    if (sessionId == null) return;

    try {
      await _apiService.toggleProvisionalAttendance(
        sessionId: sessionId,
        studentId: student.studentId,
        newStatus: newStatus,
        notes: 'Faculty manual override in classroom',
      );
      await _loadProvisionalState(sessionId);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppTheme.primaryBlue,
            duration: const Duration(seconds: 2),
            content: Text('${student.fullName} marked as $newStatus'),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppTheme.errorRed,
            content: Text('Failed to update student status: $e'),
          ),
        );
      }
    }
  }

  Future<void> _confirmAndFinalizeAttendance() async {
    final sessionId = _selectedAttendanceSessionId;
    final prov = _provisionalState;
    if (sessionId == null || prov == null || _isFinalizing) return;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Row(
          children: [
            Icon(Icons.verified_rounded, color: AppTheme.primaryBlue),
            SizedBox(width: 10),
            Text('Confirm & Finalize Attendance'),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Finalizing will permanently commit official attendance records and close this session.',
              style: TextStyle(color: Colors.grey.shade700, fontSize: 13),
            ),
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFFF1F5F9),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                children: [
                  _buildSummaryRow('Total Expected Roster', '${prov.expectedCount}'),
                  const Divider(height: 12),
                  _buildSummaryRow('Confirmed Present', '${prov.presentCount} (${(prov.presentCount / (prov.expectedCount == 0 ? 1 : prov.expectedCount) * 100).toStringAsFixed(1)}%)', color: AppTheme.successGreen),
                  const Divider(height: 12),
                  _buildSummaryRow('Pending Review Items', '${prov.pendingReviewCount}', color: prov.pendingReviewCount > 0 ? AppTheme.warningAmber : Colors.black87),
                  const Divider(height: 12),
                  _buildSummaryRow('Absent', '${prov.unresolvedCount}', color: AppTheme.errorRed),
                ],
              ),
            ),
            if (prov.pendingReviewCount > 0) ...[
              const SizedBox(height: 12),
              const Row(
                children: [
                  Icon(Icons.warning_amber_rounded, size: 16, color: AppTheme.warningAmber),
                  SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      'Unresolved review items will be marked absent upon finalization.',
                      style: TextStyle(fontSize: 12, color: AppTheme.warningAmber, fontWeight: FontWeight.w600),
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: AppTheme.primaryBlue, foregroundColor: Colors.white),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Finalize Attendance'),
          ),
        ],
      ),
    );

    if (confirmed != true || !mounted) return;

    setState(() => _isFinalizing = true);

    try {
      final result = await _apiService.finalizeSessionAttendance(sessionId);
      if (!mounted) return;
      setState(() {
        _finalizeResult = result;
        _groupStep = GroupWorkflowStep.finalized;
        _isFinalizing = false;
      });
      unawaited(_refreshOpenSessions());
    } catch (e) {
      if (!mounted) return;
      setState(() => _isFinalizing = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(backgroundColor: AppTheme.errorRed, content: Text('Finalization failed: $e')),
      );
    }
  }

  Widget _buildSummaryRow(String label, String value, {Color? color}) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label, style: const TextStyle(fontSize: 13, color: AppTheme.textSecondary)),
        Text(value, style: TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: color ?? AppTheme.textPrimary)),
      ],
    );
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
              Text('Setup Required', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Colors.white)),
            ],
          ),
        ),
      );
    }
    if (_sessionsLoading) {
      return Container(
        margin: const EdgeInsets.symmetric(vertical: 12),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(8)),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(width: 10, height: 10, child: CircularProgressIndicator(strokeWidth: 1.5, color: Colors.white70)),
            SizedBox(width: 6),
            Text('Connecting...', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Colors.white)),
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
              Text('Offline (Retry)', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Colors.white)),
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
          Text('Online', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Colors.white)),
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
              'Enter administrator API credential issued for this college environment.',
              style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: credentialController,
              obscureText: true,
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

      if (!mounted || credential == null || credential.trim().isEmpty) return;
      await showDialog<void>(
        context: context,
        builder: (ctx) => AdminEnrollmentDialog(
          config: _config,
          apiService: _apiService,
          adminApiKey: credential.trim(),
        ),
      );
    } finally {
      credentialController.dispose();
      if (mounted) setState(() => _kioskCameraActive = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.school_rounded, size: 24, color: Colors.white),
            const SizedBox(width: 10),
            const Flexible(
              child: Text(
                'FRS Biometric Attendance Kiosk',
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontWeight: FontWeight.w700),
              ),
            ),
            const SizedBox(width: 12),
            // Mode Switcher Pill in AppBar
            Container(
              decoration: BoxDecoration(
                color: Colors.white.withOpacity(0.12),
                borderRadius: BorderRadius.circular(20),
              ),
              padding: const EdgeInsets.all(2),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _buildModePill(KioskViewMode.groupPhoto, 'Group Photo', Icons.groups_rounded),
                  _buildModePill(KioskViewMode.individualPunch, 'Kiosk Punch', Icons.person_rounded),
                ],
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
        child: _viewMode == KioskViewMode.groupPhoto
            ? _buildGroupPhotoAttendanceBody()
            : _buildLegacyKioskPunchBody(),
      ),
    );
  }

  Widget _buildModePill(KioskViewMode mode, String label, IconData icon) {
    final isSelected = _viewMode == mode;
    return InkWell(
      onTap: () => setState(() => _viewMode = mode),
      borderRadius: BorderRadius.circular(18),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: isSelected ? Colors.white : Colors.transparent,
          borderRadius: BorderRadius.circular(18),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              icon,
              size: 13,
              color: isSelected ? AppTheme.primaryDark : Colors.white70,
            ),
            const SizedBox(width: 4),
            Text(
              label,
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.bold,
                color: isSelected ? AppTheme.primaryDark : Colors.white70,
              ),
            ),
          ],
        ),
      ),
    );
  }

  // =========================================================================
  // GROUP PHOTO ATTENDANCE WORKFLOW (PRIMARY COLLEGE WORKFLOW)
  // =========================================================================

  Widget _buildGroupPhotoAttendanceBody() {
    return Column(
      children: [
        _buildWorkflowStepper(),
        Expanded(
          child: switch (_groupStep) {
            GroupWorkflowStep.sessionSetup => _buildSessionSelectionView(),
            GroupWorkflowStep.capturePhotos => _buildGroupCaptureView(),
            GroupWorkflowStep.reviewRoster => _buildRosterReviewView(),
            GroupWorkflowStep.finalized => _buildFinalizedSummaryView(),
          },
        ),
      ],
    );
  }

  Widget _buildWorkflowStepper() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border(bottom: BorderSide(color: Colors.grey.shade200)),
      ),
      child: Row(
        children: [
          _buildStepItem(GroupWorkflowStep.sessionSetup, '1. Class & Session', Icons.event_note_rounded),
          _buildStepDivider(),
          _buildStepItem(GroupWorkflowStep.capturePhotos, '2. Group Photos', Icons.camera_alt_rounded),
          _buildStepDivider(),
          _buildStepItem(GroupWorkflowStep.reviewRoster, '3. Roster Review', Icons.checklist_rounded),
          _buildStepDivider(),
          _buildStepItem(GroupWorkflowStep.finalized, '4. Finalize', Icons.verified_rounded),
        ],
      ),
    );
  }

  Widget _buildStepItem(GroupWorkflowStep step, String label, IconData icon) {
    final isActive = _groupStep == step;
    final isDone = _groupStep.index > step.index;
    final color = isActive ? AppTheme.primaryBlue : (isDone ? AppTheme.successGreen : Colors.grey.shade400);

    return InkWell(
      onTap: () {
        // Can always jump back to setup or review if session is selected
        if (_selectedAttendanceSessionId != null || step == GroupWorkflowStep.sessionSetup) {
          setState(() => _groupStep = step);
        }
      },
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(isDone ? Icons.check_circle_rounded : icon, size: 18, color: color),
            const SizedBox(width: 6),
            Text(
              label,
              style: TextStyle(
                fontSize: 13,
                fontWeight: isActive ? FontWeight.bold : FontWeight.w500,
                color: isActive ? AppTheme.primaryBlue : (isDone ? Colors.black87 : Colors.grey.shade500),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildStepDivider() {
    return Expanded(
      child: Container(
        height: 1,
        color: Colors.grey.shade300,
        margin: const EdgeInsets.symmetric(horizontal: 8),
      ),
    );
  }

  // -------------------------------------------------------------------------
  // Sub-view 1: Session Selection & Summary
  // -------------------------------------------------------------------------

  Widget _buildSessionSelectionView() {
    final session = _selectedSession;
    final filtered = _filteredSessions;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_config.apiKeySecret.isEmpty) _buildUnconfiguredBanner(),

          // Department Quick Filter Chips
          const Text('FILTER BY DEPARTMENT', style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: AppTheme.textSecondary, letterSpacing: 0.5)),
          const SizedBox(height: 8),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: _departments.map((dept) {
                final isSelected = _departmentFilter == dept;
                return Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: FilterChip(
                    label: Text(dept),
                    selected: isSelected,
                    onSelected: (val) => setState(() => _departmentFilter = dept),
                    selectedColor: AppTheme.primaryBlue.withOpacity(0.15),
                    checkmarkColor: AppTheme.primaryBlue,
                    labelStyle: TextStyle(
                      fontSize: 12,
                      fontWeight: isSelected ? FontWeight.bold : FontWeight.normal,
                      color: isSelected ? AppTheme.primaryBlue : AppTheme.textPrimary,
                    ),
                  ),
                );
              }).toList(),
            ),
          ),
          const SizedBox(height: 16),

          // Session Type Filter (All, Class, Lab, Mixed)
          const Text('SESSION TYPE', style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: AppTheme.textSecondary, letterSpacing: 0.5)),
          const SizedBox(height: 8),
          Row(
            children: [
              _buildTypeFilterChip('ALL', 'All Sessions'),
              const SizedBox(width: 8),
              _buildTypeFilterChip('CLASS', 'Theory Classes'),
              const SizedBox(width: 8),
              _buildTypeFilterChip('LAB', 'Laboratory'),
              const SizedBox(width: 8),
              _buildTypeFilterChip('MIXED', 'Mixed Classes'),
            ],
          ),
          const SizedBox(height: 20),

          // Open Attendance Session Dropdown
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  key: const ValueKey('select_session_dropdown'),
                  value: _selectedAttendanceSessionId,
                  isExpanded: true,
                  decoration: InputDecoration(
                    labelText: 'Open attendance session',
                    prefixIcon: const Icon(Icons.class_outlined),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                  items: filtered.map((s) => DropdownMenuItem<String>(
                    value: s.sessionId,
                    child: Text(s.displayLabel, overflow: TextOverflow.ellipsis),
                  )).toList(),
                  onChanged: (val) {
                    setState(() => _selectedAttendanceSessionId = val);
                    if (val != null) unawaited(_loadProvisionalState(val));
                  },
                ),
              ),
              const SizedBox(width: 8),
              IconButton(
                tooltip: 'Refresh open sessions',
                onPressed: _sessionsLoading ? null : () => unawaited(_refreshOpenSessions()),
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

          const SizedBox(height: 24),

          // Session Summary Card (if session selected)
          if (session != null) ...[
            _buildSessionSummaryCard(session),
            const SizedBox(height: 24),
            Row(
              children: [
                Expanded(
                  child: ElevatedButton.icon(
                    key: const ValueKey('begin_capture_button'),
                    onPressed: () => setState(() => _groupStep = GroupWorkflowStep.capturePhotos),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTheme.primaryBlue,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                    icon: const Icon(Icons.camera_alt_rounded),
                    label: const Text('Start Group Photo Capture', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                  ),
                ),
                const SizedBox(width: 12),
                OutlinedButton.icon(
                  onPressed: () => setState(() => _groupStep = GroupWorkflowStep.reviewRoster),
                  style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                  icon: const Icon(Icons.people_outline_rounded),
                  label: Text('View Roster (${session.expectedRosterCount})'),
                ),
              ],
            ),
          ] else if (!_sessionsLoading) ...[
            Container(
              padding: const EdgeInsets.all(32),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: Colors.grey.shade200),
              ),
              child: Column(
                children: [
                  Icon(Icons.event_busy_rounded, size: 48, color: Colors.grey.shade400),
                  const SizedBox(height: 12),
                  const Text('No Open Attendance Sessions', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 6),
                  const Text(
                    'No open sessions match your filter. Create a class/lab session in the Admin Console or select another department.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildTypeFilterChip(String type, String label) {
    final isSelected = _sessionTypeFilter == type;
    return FilterChip(
      label: Text(label),
      selected: isSelected,
      onSelected: (_) => setState(() => _sessionTypeFilter = type),
      selectedColor: AppTheme.primaryBlue.withOpacity(0.15),
      checkmarkColor: AppTheme.primaryBlue,
      labelStyle: TextStyle(
        fontSize: 11,
        fontWeight: isSelected ? FontWeight.bold : FontWeight.normal,
        color: isSelected ? AppTheme.primaryBlue : AppTheme.textPrimary,
      ),
    );
  }

  Widget _buildSessionSummaryCard(AttendanceSessionOption session) {
    final prov = _provisionalState;
    final total = session.expectedRosterCount;
    final present = prov?.presentCount ?? 0;
    final pct = total > 0 ? (present / total * 100).toStringAsFixed(1) : '0.0';

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.grey.shade200),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.04),
            blurRadius: 10,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: session.isLab
                      ? const Color(0xFF6B21A8).withOpacity(0.12)
                      : (session.isMixed
                          ? const Color(0xFF0F766E).withOpacity(0.12)
                          : const Color(0xFF1E3A8A).withOpacity(0.12)),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  session.typeBadge,
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                    color: session.isLab
                        ? const Color(0xFF6B21A8)
                        : (session.isMixed ? const Color(0xFF0F766E) : const Color(0xFF1E3A8A)),
                  ),
                ),
              ),
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: AppTheme.successGreen.withOpacity(0.12),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.circle, size: 8, color: AppTheme.successGreen),
                    SizedBox(width: 4),
                    Text('SESSION ACTIVE', style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: AppTheme.successGreen)),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            session.displayLabel,
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: AppTheme.textPrimary),
          ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 16,
            runSpacing: 8,
            children: [
              _buildInfoPill(Icons.account_balance_outlined, 'Dept: ${session.departmentCode}'),
              _buildInfoPill(Icons.calendar_today_outlined, 'Year ${session.yearOfStudy} • Sec ${session.section}'),
              if (session.semester != null)
                _buildInfoPill(Icons.timeline_rounded, 'Semester ${session.semester}'),
              if (session.labName != null)
                _buildInfoPill(Icons.science_outlined, 'Lab: ${session.labName}'),
              _buildInfoPill(Icons.groups_rounded, '$total Students Expected'),
            ],
          ),
          if (prov != null && prov.photosCapturedCount > 0) ...[
            const SizedBox(height: 16),
            const Divider(),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('PROVISIONAL ATTENDANCE: $present / $total ($pct%)', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: AppTheme.textSecondary)),
                      const SizedBox(height: 6),
                      ClipRRect(
                        borderRadius: BorderRadius.circular(4),
                        child: LinearProgressIndicator(
                          value: total > 0 ? (present / total).clamp(0.0, 1.0) : 0.0,
                          minHeight: 8,
                          backgroundColor: Colors.grey.shade200,
                          valueColor: const AlwaysStoppedAnimation<Color>(AppTheme.successGreen),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 16),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(
                    color: const Color(0xFFF1F5F9),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    '${prov.photosCapturedCount} Photos Captured',
                    style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: AppTheme.textPrimary),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildInfoPill(IconData icon, String text) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 14, color: AppTheme.textSecondary),
        const SizedBox(width: 4),
        Text(text, style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary, fontWeight: FontWeight.w500)),
      ],
    );
  }

  // -------------------------------------------------------------------------
  // Sub-view 2: Multi-Photo Group Capture View
  // -------------------------------------------------------------------------

  Widget _buildGroupCaptureView() {
    final session = _selectedSession;
    if (session == null) {
      return Center(
        child: ElevatedButton(
          onPressed: () => setState(() => _groupStep = GroupWorkflowStep.sessionSetup),
          child: const Text('Please select an open session first'),
        ),
      );
    }

    final prov = _provisionalState;
    final total = session.expectedRosterCount;
    final present = prov?.presentCount ?? 0;
    final flagged = prov?.pendingReviewCount ?? 0;
    final absent = prov?.unresolvedCount ?? (total - present);
    final pct = total > 0 ? (present / total * 100).toStringAsFixed(1) : '0.0';

    return LayoutBuilder(
      builder: (context, constraints) {
        final isWide = constraints.maxWidth >= 840;

        final cameraWidget = CameraViewport(
          key: _kioskCameraKey,
          capturedImages: null,
          onRetakePressed: () {},
          onSingleImageCaptured: _handleGroupPhotoCapture,
          isGroupMode: true,
          initialLensDirection: CameraLensDirection.back,
          allowCameraSwitch: true,
          captureButtonLabel: 'Capture Group Photo',
          statusMessage: 'Frame Classroom Rows — Rear Camera Default',
          isSubmitting: _isUploadingGroupPhoto,
        );

        final metricsWidget = SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Session Info Strip
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: Colors.grey.shade200),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.school, size: 18, color: AppTheme.primaryBlue),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        session.displayLabel,
                        style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: AppTheme.primaryBlue.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        'Total: $total',
                        style: const TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: AppTheme.primaryBlue),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),

              // Cumulative Metrics Card
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.grey.shade200),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('SESSION ATTENDANCE PROGRESS', style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: AppTheme.textSecondary, letterSpacing: 0.5)),
                    const SizedBox(height: 8),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.baseline,
                      textBaseline: TextBaseline.alphabetic,
                      children: [
                        Text('$present', style: const TextStyle(fontSize: 32, fontWeight: FontWeight.bold, color: AppTheme.successGreen)),
                        Text(' / $total', style: const TextStyle(fontSize: 18, color: AppTheme.textSecondary)),
                        const Spacer(),
                        Text('$pct%', style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: AppTheme.textPrimary)),
                      ],
                    ),
                    const SizedBox(height: 8),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(4),
                      child: LinearProgressIndicator(
                        value: total > 0 ? (present / total).clamp(0.0, 1.0) : 0.0,
                        minHeight: 10,
                        backgroundColor: Colors.grey.shade200,
                        valueColor: const AlwaysStoppedAnimation<Color>(AppTheme.successGreen),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        _buildMetricChip('Present', '$present', AppTheme.successGreen),
                        const SizedBox(width: 8),
                        _buildMetricChip('Pending Review', '$flagged', AppTheme.warningAmber),
                        const SizedBox(width: 8),
                        _buildMetricChip('Absent', '$absent', AppTheme.errorRed),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),

              // Last Capture Result Banner (if exists)
              if (_lastCaptureResult != null) ...[
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: const Color(0xFFF0FDF4),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: const Color(0xFFBBF7D0)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          const Icon(Icons.check_circle_rounded, size: 16, color: AppTheme.successGreen),
                          const SizedBox(width: 6),
                          Text('Photo #${_lastCaptureResult!.photoIndex} Processed', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Color(0xFF166534))),
                        ],
                      ),
                      const SizedBox(height: 6),
                      Text(
                        '${_lastCaptureResult!.facesDetectedCount} faces detected: '
                        '${_lastCaptureResult!.facesMatchedCount} recognized, '
                        '${_lastCaptureResult!.facesUncertainCount} flagged for review, '
                        '${_lastCaptureResult!.duplicatesIgnoredCount} cross-photo duplicates ignored.',
                        style: const TextStyle(fontSize: 12, color: Color(0xFF15803D), height: 1.3),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
              ],

              // Multi-Photo Classroom Tip
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFFF8FAFC),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: const Color(0xFFE2E8F0)),
                ),
                child: const Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(Icons.tips_and_updates_outlined, size: 18, color: AppTheme.primaryBlue),
                    SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Take several photos covering different rows, left wing, and right wing of the classroom. '
                        'The system aggregates all students into this session and deduplicates records.',
                        style: TextStyle(fontSize: 12, color: AppTheme.textSecondary, height: 1.3),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),

              // Action Buttons
              ElevatedButton.icon(
                key: const ValueKey('goto_review_button'),
                onPressed: () => setState(() => _groupStep = GroupWorkflowStep.reviewRoster),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppTheme.primaryBlue,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
                icon: const Icon(Icons.checklist_rounded),
                label: Text('Review Roster & Finalize ($present Present)', style: const TextStyle(fontWeight: FontWeight.bold)),
              ),
              const SizedBox(height: 8),
              TextButton(
                onPressed: () => setState(() => _groupStep = GroupWorkflowStep.sessionSetup),
                child: const Text('Back to Session Selection'),
              ),
            ],
          ),
        );

        if (isWide) {
          return Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(flex: 6, child: Padding(padding: const EdgeInsets.all(16), child: cameraWidget)),
              Expanded(flex: 5, child: metricsWidget),
            ],
          );
        } else {
          return SingleChildScrollView(
            child: Column(
              children: [
                SizedBox(height: 380, child: cameraWidget),
                metricsWidget,
              ],
            ),
          );
        }
      },
    );
  }

  Widget _buildMetricChip(String label, String value, Color color) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 8),
        decoration: BoxDecoration(
          color: color.withOpacity(0.08),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          children: [
            Text(value, style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: color)),
            const SizedBox(height: 2),
            Text(label, style: const TextStyle(fontSize: 10, color: AppTheme.textSecondary, fontWeight: FontWeight.w600), overflow: TextOverflow.ellipsis),
          ],
        ),
      ),
    );
  }

  // -------------------------------------------------------------------------
  // Sub-view 3: Faculty Roster Review & Override View
  // -------------------------------------------------------------------------

  Widget _buildRosterReviewView() {
    final session = _selectedSession;
    final prov = _provisionalState;

    if (session == null || prov == null) {
      return Center(
        child: ElevatedButton(
          onPressed: () => setState(() => _groupStep = GroupWorkflowStep.sessionSetup),
          child: const Text('Select a session first'),
        ),
      );
    }

    final query = _rosterSearchQuery.toLowerCase().trim();
    final filteredRoster = prov.roster.where((student) {
      // Filter by status tab
      if (_rosterFilter == 'PRESENT' && !student.isPresent) return false;
      if (_rosterFilter == 'FLAGGED' && !student.isPendingReview) return false;
      if (_rosterFilter == 'ABSENT' && (student.isPresent || student.isPendingReview)) return false;

      // Filter by search query
      if (query.isNotEmpty) {
        final matchesNumber = student.studentNumber.toLowerCase().contains(query);
        final matchesName = student.fullName.toLowerCase().contains(query);
        if (!matchesNumber && !matchesName) return false;
      }
      return true;
    }).toList();

    return Column(
      children: [
        // Roster Summary Header Bar
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
          color: Colors.white,
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(session.displayLabel, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
                    Text(
                      '${prov.presentCount} Present • ${prov.pendingReviewCount} Pending Review • ${prov.unresolvedCount} Absent of ${prov.expectedCount}',
                      style: const TextStyle(color: AppTheme.textSecondary, fontSize: 12),
                    ),
                  ],
                ),
              ),
              ElevatedButton.icon(
                key: const ValueKey('finalize_attendance_button'),
                onPressed: _confirmAndFinalizeAttendance,
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppTheme.successGreen,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
                icon: const Icon(Icons.check_rounded, size: 18),
                label: const Text('Confirm & Finalize', style: TextStyle(fontWeight: FontWeight.bold)),
              ),
            ],
          ),
        ),

        // Search and Status Filters
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
          decoration: BoxDecoration(
            color: const Color(0xFFF8FAFC),
            border: Border(
              top: BorderSide(color: Colors.grey.shade200),
              bottom: BorderSide(color: Colors.grey.shade200),
            ),
          ),
          child: Row(
            children: [
              // Search Field
              Expanded(
                flex: 4,
                child: TextField(
                  controller: _rosterSearchController,
                  decoration: InputDecoration(
                    hintText: 'Search by student name or roll number...',
                    prefixIcon: const Icon(Icons.search, size: 20),
                    suffixIcon: _rosterSearchQuery.isNotEmpty
                        ? IconButton(
                            icon: const Icon(Icons.clear, size: 18),
                            onPressed: () {
                              _rosterSearchController.clear();
                              setState(() => _rosterSearchQuery = '');
                            },
                          )
                        : null,
                    isDense: true,
                    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                    fillColor: Colors.white,
                    filled: true,
                  ),
                  onChanged: (val) => setState(() => _rosterSearchQuery = val),
                ),
              ),
              const SizedBox(width: 12),
              // Segmented Filter
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _buildRosterFilterTab('ALL', 'All (${prov.roster.length})'),
                  _buildRosterFilterTab('PRESENT', 'Present (${prov.presentCount})', color: AppTheme.successGreen),
                  _buildRosterFilterTab('FLAGGED', 'Review (${prov.pendingReviewCount})', color: AppTheme.warningAmber),
                  _buildRosterFilterTab('ABSENT', 'Absent (${prov.unresolvedCount})', color: AppTheme.errorRed),
                ],
              ),
            ],
          ),
        ),

        // Non-Roster Faces Notice (if unknown faces detected)
        if (prov.unknownFacesCount > 0)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
            color: const Color(0xFFFEF3C7),
            child: Row(
              children: [
                const Icon(Icons.info_outline_rounded, size: 16, color: Color(0xFFD97706)),
                const SizedBox(width: 8),
                Text(
                  '${prov.unknownFacesCount} face(s) detected in captures were not found in this session\'s roster (non-enrolled students/visitors).',
                  style: const TextStyle(fontSize: 12, color: Color(0xFF92400E)),
                ),
              ],
            ),
          ),

        // Student List View
        Expanded(
          child: filteredRoster.isEmpty
              ? Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.person_search_rounded, size: 40, color: Colors.grey.shade400),
                      const SizedBox(height: 8),
                      Text('No students match "$_rosterSearchQuery"', style: const TextStyle(color: AppTheme.textSecondary)),
                    ],
                  ),
                )
              : ListView.separated(
                  padding: const EdgeInsets.all(16),
                  itemCount: filteredRoster.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 8),
                  itemBuilder: (context, index) {
                    final student = filteredRoster[index];
                    return _buildStudentCard(student);
                  },
                ),
        ),

        // Bottom Actions Bar
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
          decoration: BoxDecoration(
            color: Colors.white,
            border: Border(top: BorderSide(color: Colors.grey.shade200)),
          ),
          child: Row(
            children: [
              OutlinedButton.icon(
                onPressed: () => setState(() => _groupStep = GroupWorkflowStep.capturePhotos),
                icon: const Icon(Icons.camera_alt_outlined),
                label: const Text('Capture More Photos'),
              ),
              const Spacer(),
              ElevatedButton.icon(
                onPressed: _confirmAndFinalizeAttendance,
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppTheme.primaryBlue,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
                icon: const Icon(Icons.done_all_rounded),
                label: const Text('Confirm & Finalize Session', style: TextStyle(fontWeight: FontWeight.bold)),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildRosterFilterTab(String code, String label, {Color? color}) {
    final isSelected = _rosterFilter == code;
    return Padding(
      padding: const EdgeInsets.only(left: 6),
      child: ChoiceChip(
        label: Text(label),
        selected: isSelected,
        onSelected: (_) => setState(() => _rosterFilter = code),
        selectedColor: (color ?? AppTheme.primaryBlue).withOpacity(0.18),
        labelStyle: TextStyle(
          fontSize: 11,
          fontWeight: isSelected ? FontWeight.bold : FontWeight.w500,
          color: isSelected ? (color ?? AppTheme.primaryBlue) : AppTheme.textPrimary,
        ),
      ),
    );
  }

  Widget _buildStudentCard(RosterStudent student) {
    Color statusBg;
    Color statusFg;
    String statusText;

    if (student.isPresent) {
      statusBg = const Color(0xFFDCFCE7);
      statusFg = const Color(0xFF15803D);
      final scorePct = (student.similarityScore * 100).toStringAsFixed(1);
      statusText = 'PRESENT ($scorePct% match)';
    } else if (student.isPendingReview) {
      statusBg = const Color(0xFFFEF3C7);
      statusFg = const Color(0xFFB45309);
      final scorePct = (student.similarityScore * 100).toStringAsFixed(1);
      statusText = 'REVIEW ($scorePct%)';
    } else {
      statusBg = const Color(0xFFF1F5F9);
      statusFg = const Color(0xFF64748B);
      statusText = 'ABSENT';
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: student.isPendingReview ? const Color(0xFFF59E0B) : Colors.grey.shade200,
          width: student.isPendingReview ? 1.5 : 1.0,
        ),
      ),
      child: Row(
        children: [
          CircleAvatar(
            backgroundColor: AppTheme.primaryBlue.withOpacity(0.1),
            child: Text(
              student.fullName.isNotEmpty ? student.fullName[0].toUpperCase() : '?',
              style: const TextStyle(color: AppTheme.primaryBlue, fontWeight: FontWeight.bold),
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      student.studentNumber,
                      style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13, fontFamily: 'monospace'),
                    ),
                    const SizedBox(width: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: statusBg,
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        statusText,
                        style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: statusFg),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(student.fullName, style: const TextStyle(fontSize: 14, color: AppTheme.textPrimary)),
                if (student.notes != null)
                  Text(student.notes!, style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary, fontStyle: FontStyle.italic)),
              ],
            ),
          ),
          // Action Buttons: Mark Present / Mark Absent
          if (student.isPresent)
            OutlinedButton(
              onPressed: () => _toggleStudentStatus(student, 'MARKED_ABSENT'),
              style: OutlinedButton.styleFrom(
                foregroundColor: AppTheme.errorRed,
                side: const BorderSide(color: Color(0xFFFCA5A5)),
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                minimumSize: Size.zero,
              ),
              child: const Text('Mark Absent', style: TextStyle(fontSize: 11)),
            )
          else if (student.isPendingReview)
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                ElevatedButton(
                  onPressed: () => _toggleStudentStatus(student, 'PRESENT'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppTheme.successGreen,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    minimumSize: Size.zero,
                  ),
                  child: const Text('Confirm', style: TextStyle(fontSize: 11)),
                ),
                const SizedBox(width: 6),
                OutlinedButton(
                  onPressed: () => _toggleStudentStatus(student, 'MARKED_ABSENT'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppTheme.errorRed,
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                    minimumSize: Size.zero,
                  ),
                  child: const Text('Reject', style: TextStyle(fontSize: 11)),
                ),
              ],
            )
          else
            ElevatedButton(
              onPressed: () => _toggleStudentStatus(student, 'PRESENT'),
              style: ElevatedButton.styleFrom(
                backgroundColor: AppTheme.primaryBlue,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                minimumSize: Size.zero,
              ),
              child: const Text('Mark Present', style: TextStyle(fontSize: 11)),
            ),
        ],
      ),
    );
  }

  // -------------------------------------------------------------------------
  // Sub-view 4: Finalized Summary Receipt
  // -------------------------------------------------------------------------

  Widget _buildFinalizedSummaryView() {
    final result = _finalizeResult;
    final session = _selectedSession;

    return Center(
      child: Container(
        constraints: const BoxConstraints(maxWidth: 540),
        padding: const EdgeInsets.all(32),
        margin: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(20),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(0.06),
              blurRadius: 16,
              offset: const Offset(0, 6),
            ),
          ],
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: AppTheme.successGreen.withOpacity(0.12),
                shape: BoxShape.circle,
              ),
              child: const Icon(Icons.verified_rounded, size: 48, color: AppTheme.successGreen),
            ),
            const SizedBox(height: 16),
            const Text('Attendance Session Finalized', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
            const SizedBox(height: 6),
            Text(
              session?.displayLabel ?? 'Class Session',
              style: const TextStyle(color: AppTheme.textSecondary, fontSize: 13),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 24),

            if (result != null)
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: const Color(0xFFF8FAFC),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.grey.shade200),
                ),
                child: Column(
                  children: [
                    _buildSummaryRow('Total Enrolled Students', '${result.totalExpected}'),
                    const Divider(height: 14),
                    _buildSummaryRow('Present & Recorded', '${result.presentCount}', color: AppTheme.successGreen),
                    const Divider(height: 14),
                    _buildSummaryRow('Absent', '${result.absentCount}', color: AppTheme.errorRed),
                    const Divider(height: 14),
                    _buildSummaryRow('Attendance Rate', '${result.attendanceRatePct.toStringAsFixed(1)}%', color: AppTheme.primaryBlue),
                  ],
                ),
              ),

            const SizedBox(height: 24),
            Row(
              children: [
                Expanded(
                  child: ElevatedButton(
                    onPressed: () {
                      setState(() {
                        _selectedAttendanceSessionId = null;
                        _provisionalState = null;
                        _lastCaptureResult = null;
                        _finalizeResult = null;
                        _groupStep = GroupWorkflowStep.sessionSetup;
                      });
                      unawaited(_refreshOpenSessions());
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTheme.primaryBlue,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                    ),
                    child: const Text('Start Next Class Session', style: TextStyle(fontWeight: FontWeight.bold)),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  // =========================================================================
  // LEGACY KIOSK PUNCH MODE (DUAL-PANE AUTOMATIC 1:N IDENTIFICATION)
  // =========================================================================

  Widget _buildLegacyKioskPunchBody() {
    return LayoutBuilder(
      builder: (context, constraints) {
        final isWide = constraints.maxWidth >= 800;

        if (isWide) {
          return Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
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
                    isGroupMode: false,
                  ),
                ),
              ),
              Expanded(
                flex: 6,
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(20.0),
                  child: _buildLegacyInteractionColumn(),
                ),
              ),
            ],
          );
        } else {
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
                    isGroupMode: false,
                  ),
                ),
                const SizedBox(height: 16),
                _buildLegacyInteractionColumn(),
              ],
            ),
          );
        }
      },
    );
  }

  Widget _buildLegacyInteractionColumn() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (_config.apiKeySecret.isEmpty) _buildUnconfiguredBanner(),

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

        PunchSelector(
          selectedType: _state.punchType,
          onChanged: _state.setPunchType,
          enabled: !_state.isSubmitting,
        ),
        const SizedBox(height: 16),

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
                  Text('Automatic Face Identification', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
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

        ElevatedButton(
          key: const ValueKey('submit_punch_button'),
          onPressed: _state.canSubmit && _selectedAttendanceSessionId != null
              ? () => _state.submitSessionAttendance(_apiService, _selectedAttendanceSessionId!)
              : null,
          style: ElevatedButton.styleFrom(
            backgroundColor: _state.punchType == PunchType.checkIn ? AppTheme.successGreen : AppTheme.warningAmber,
            disabledBackgroundColor: const Color(0xFFCBD5E1),
            minimumSize: const Size.fromHeight(56),
          ),
          child: _state.isSubmitting
              ? const Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, valueColor: AlwaysStoppedAnimation<Color>(Colors.white))),
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
        StatusBanner(state: _state, onDismiss: _state.reset),
      ],
    );
  }

  Widget _buildUnconfiguredBanner() {
    return Container(
      key: const ValueKey('kiosk_unconfigured_banner'),
      margin: const EdgeInsets.only(bottom: 16),
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
    );
  }
}
