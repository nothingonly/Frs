import 'package:flutter/material.dart';
import '../../state/kiosk_state.dart';
import '../theme/app_theme.dart';

/// Renders the feedback status card based on current [KioskState].
class StatusBanner extends StatelessWidget {
  final KioskState state;
  final VoidCallback onDismiss;

  const StatusBanner({
    super.key,
    required this.state,
    required this.onDismiss,
  });

  @override
  Widget build(BuildContext context) {
    switch (state.status) {
      case KioskStatus.submitting:
        return _buildSubmittingCard();

      case KioskStatus.accepted:
        return _buildSuccessCard();

      case KioskStatus.unrecognized:
        return _buildUnrecognizedCard();

      case KioskStatus.ambiguous:
        return _buildAmbiguousCard();

      case KioskStatus.mismatch:
        return _buildMismatchCard();

      case KioskStatus.cooldown:
        return _buildCooldownCard();

      case KioskStatus.qualityError:
        return _buildQualityErrorCard();

      case KioskStatus.inactiveEmployee:
        return _buildInactiveEmployeeCard();

      case KioskStatus.notFound:
        return _buildNotFoundCard();

      case KioskStatus.networkError:
        return _buildNetworkErrorCard();

      case KioskStatus.serverError:
        return _buildServerErrorCard();

      case KioskStatus.idle:
      case KioskStatus.capturing:
      case KioskStatus.readyToSubmit:
        return const SizedBox.shrink();
    }
  }

  Widget _buildSubmittingCard() {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: const Color(0xFFEFF6FF), // Blue 50
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFBFDBFE)),
      ),
      child: const Row(
        children: [
          SizedBox(
            width: 24,
            height: 24,
            child: CircularProgressIndicator(
              strokeWidth: 2.5,
              valueColor: AlwaysStoppedAnimation<Color>(AppTheme.primaryBlue),
            ),
          ),
          SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  'Verifying Biometrics...',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: AppTheme.primaryBlue,
                  ),
                ),
                SizedBox(height: 4),
                Text(
                  'Extracting face embedding and checking server records',
                  style: TextStyle(
                    fontSize: 13,
                    color: AppTheme.textSecondary,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSuccessCard() {
    final result = state.lastSuccessResult;
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: state.isOfflineQueued ? const Color(0xFFEFF6FF) : AppTheme.successBg,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: state.isOfflineQueued
              ? const Color(0xFF60A5FA)
              : AppTheme.successGreen.withOpacity(0.4),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Icon(
                state.isOfflineQueued ? Icons.cloud_off_rounded : Icons.check_circle_rounded,
                color: state.isOfflineQueued ? AppTheme.primaryBlue : AppTheme.successGreen,
                size: 28,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  state.isOfflineQueued
                      ? 'Attendance Buffered Offline (Encrypted)'
                      : 'Attendance Recorded Successfully',
                  style: TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w700,
                    color: state.isOfflineQueued ? AppTheme.primaryBlue : AppTheme.successGreen,
                  ),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.close_rounded, size: 20),
                onPressed: onDismiss,
                color: AppTheme.textSecondary,
              ),
            ],
          ),
          const Divider(height: 24),
          if (state.isOfflineQueued) ...[
            _buildDetailRow('Storage Security', 'Hardware Keystore / Encrypted Buffer'),
            _buildDetailRow('Buffer Status', 'Saved locally; auto-syncs when online'),
            _buildDetailRow('Punch Type', state.punchType.label),
            _buildDetailRow('Fail-Closed TTL', '24 Hours (Purged if unsynced)'),
            if (state.matchedEmployeeId != null)
              _buildDetailRow('Batch Reference', state.matchedEmployeeId!),
          ] else if (state.lastIdentificationResult != null) ...[
            _buildDetailRow('Employee Name', state.lastIdentificationResult!.fullName),
            _buildDetailRow('Employee ID', state.lastIdentificationResult!.employeeId),
            if (state.lastIdentificationResult!.department != null)
              _buildDetailRow('Department', state.lastIdentificationResult!.department!),
            _buildDetailRow('Punch Type', state.lastIdentificationResult!.punchType),
            _buildDetailRow('Local Time', state.lastIdentificationResult!.toLocalFormattedTimestamp()),
            _buildDetailRow('Match Score', state.lastIdentificationResult!.similarityPercentage),
          ] else if (result != null) ...[
            _buildDetailRow('Employee ID', result.employeeId),
            _buildDetailRow('Punch Type', result.punchType),
            _buildDetailRow('Local Time', result.toLocalFormattedTimestamp()),
            _buildDetailRow('Match Score', result.similarityPercentage),
            _buildDetailRow('Record ID', result.attendanceId),
          ],
        ],
      ),
    );
  }

  Widget _buildUnrecognizedCard() {
    final score = state.lastSimilarityScore;
    final threshold = state.requiredThreshold ?? 0.363;
    return _buildAlertContainer(
      icon: Icons.person_search_rounded,
      iconColor: AppTheme.errorRed,
      bgColor: AppTheme.errorBg,
      borderColor: AppTheme.errorRed.withOpacity(0.3),
      title: 'Unrecognized Face',
      message: state.errorMessage ??
          'No matching enrolled employee found in records. Please contact an administrator to enroll.',
      extraDetails: score != null && score > 0
          ? 'Match Score: ${(score * 100).toStringAsFixed(1)}% (Required: ${(threshold * 100).toStringAsFixed(1)}%)'
          : null,
    );
  }

  Widget _buildAmbiguousCard() {
    final c1 = state.ambiguousCandidate1 ?? 'Candidate 1';
    final c2 = state.ambiguousCandidate2 ?? 'Candidate 2';
    return _buildAlertContainer(
      icon: Icons.people_outline_rounded,
      iconColor: AppTheme.warningAmber,
      bgColor: AppTheme.warningBg,
      borderColor: AppTheme.warningAmber.withOpacity(0.4),
      title: 'Ambiguous Biometric Match',
      message: 'Multiple candidate identities detected with similar confidence ($c1 and $c2). Please contact HR or use manual punch.',
    );
  }

  Widget _buildMismatchCard() {
    final score = state.lastSimilarityScore;
    final threshold = state.requiredThreshold ?? 0.363;
    return _buildAlertContainer(
      icon: Icons.person_off_rounded,
      iconColor: AppTheme.errorRed,
      bgColor: AppTheme.errorBg,
      borderColor: AppTheme.errorRed.withOpacity(0.3),
      title: 'Biometric Verification Failed',
      message: state.errorMessage ??
          'Face does not match the enrolled template for this employee ID.',
      extraDetails: score != null
          ? 'Similarity: ${(score * 100).toStringAsFixed(1)}% (Required: ${(threshold * 100).toStringAsFixed(1)}%)'
          : null,
    );
  }

  Widget _buildCooldownCard() {
    final seconds = state.cooldownRemainingSeconds ?? 300;
    return _buildAlertContainer(
      icon: Icons.hourglass_top_rounded,
      iconColor: AppTheme.warningAmber,
      bgColor: AppTheme.warningBg,
      borderColor: AppTheme.warningAmber.withOpacity(0.4),
      title: 'Attendance Cooldown Active',
      message: 'Attendance was already recorded recently. Please wait before punching again.',
      extraDetails: 'Remaining Cooldown: ${seconds}s',
    );
  }

  Widget _buildQualityErrorCard() {
    return _buildAlertContainer(
      icon: Icons.blur_on_rounded,
      iconColor: AppTheme.warningAmber,
      bgColor: AppTheme.warningBg,
      borderColor: AppTheme.warningAmber.withOpacity(0.4),
      title: 'Image Quality Rejection',
      message: state.errorMessage ??
          'The captured photo is too blurry or no clear face was detected. Please ensure good lighting and look directly into the camera.',
    );
  }

  Widget _buildInactiveEmployeeCard() {
    return _buildAlertContainer(
      icon: Icons.block_rounded,
      iconColor: AppTheme.errorRed,
      bgColor: AppTheme.errorBg,
      borderColor: AppTheme.errorRed.withOpacity(0.3),
      title: 'Employee Account Inactive',
      message: 'This employee account is deactivated. Please contact your HR administrator.',
    );
  }

  Widget _buildNotFoundCard() {
    return _buildAlertContainer(
      icon: Icons.search_off_rounded,
      iconColor: AppTheme.errorRed,
      bgColor: AppTheme.errorBg,
      borderColor: AppTheme.errorRed.withOpacity(0.3),
      title: 'Employee or Template Not Found',
      message: state.errorMessage ??
          'Employee ID is not registered, or no biometric template has been enrolled.',
    );
  }

  Widget _buildNetworkErrorCard() {
    return _buildAlertContainer(
      icon: Icons.wifi_off_rounded,
      iconColor: AppTheme.errorRed,
      bgColor: AppTheme.errorBg,
      borderColor: AppTheme.errorRed.withOpacity(0.3),
      title: 'Network Communication Error',
      message: state.errorMessage ??
          'Cannot reach the backend server. Verify network connectivity or server status.',
    );
  }

  Widget _buildServerErrorCard() {
    return _buildAlertContainer(
      icon: Icons.dns_rounded,
      iconColor: AppTheme.errorRed,
      bgColor: AppTheme.errorBg,
      borderColor: AppTheme.errorRed.withOpacity(0.3),
      title: 'Server Error',
      message: state.errorMessage ?? 'An internal server error occurred. Please try again.',
    );
  }

  Widget _buildAlertContainer({
    required IconData icon,
    required Color iconColor,
    required Color bgColor,
    required Color borderColor,
    required String title,
    required String message,
    String? extraDetails,
  }) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: borderColor),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Icon(icon, color: iconColor, size: 26),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  title,
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: iconColor,
                  ),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.close_rounded, size: 20),
                onPressed: onDismiss,
                color: AppTheme.textSecondary,
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            message,
            style: const TextStyle(
              fontSize: 14,
              color: AppTheme.textPrimary,
              height: 1.4,
            ),
          ),
          if (extraDetails != null) ...[
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: Colors.white.withOpacity(0.6),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                extraDetails,
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: iconColor,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildDetailRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            label,
            style: const TextStyle(
              fontSize: 14,
              color: AppTheme.textSecondary,
              fontWeight: FontWeight.w500,
            ),
          ),
          Text(
            value,
            style: const TextStyle(
              fontSize: 14,
              color: AppTheme.textPrimary,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}
