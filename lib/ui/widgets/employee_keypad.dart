import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Touch-screen numeric keypad for rapid Employee ID entry on kiosk tablets.
class EmployeeKeypad extends StatelessWidget {
  final String currentId;
  final ValueChanged<String> onDigitPressed;
  final VoidCallback onBackspacePressed;
  final VoidCallback onClearPressed;
  final bool enabled;

  const EmployeeKeypad({
    super.key,
    required this.currentId,
    required this.onDigitPressed,
    required this.onBackspacePressed,
    required this.onClearPressed,
    this.enabled = true,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        // Display header
        Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: currentId.isNotEmpty ? AppTheme.primaryBlue : AppTheme.borderSubtle,
              width: currentId.isNotEmpty ? 2 : 1,
            ),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Expanded(
                child: Text(
                  currentId.isEmpty ? 'Tap digits to enter Employee ID' : currentId,
                  style: TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 2.0,
                    color: currentId.isEmpty ? AppTheme.textSecondary : AppTheme.textPrimary,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (currentId.isNotEmpty && enabled)
                IconButton(
                  icon: const Icon(Icons.clear_rounded, color: AppTheme.textSecondary),
                  onPressed: onClearPressed,
                  tooltip: 'Clear ID',
                ),
            ],
          ),
        ),
        const SizedBox(height: 12),

        // 3x4 Grid of keypad buttons
        Table(
          children: [
            TableRow(
              children: [
                _buildDigitCell('1'),
                _buildDigitCell('2'),
                _buildDigitCell('3'),
              ],
            ),
            TableRow(
              children: [
                _buildDigitCell('4'),
                _buildDigitCell('5'),
                _buildDigitCell('6'),
              ],
            ),
            TableRow(
              children: [
                _buildDigitCell('7'),
                _buildDigitCell('8'),
                _buildDigitCell('9'),
              ],
            ),
            TableRow(
              children: [
                _buildActionCell(
                  icon: Icons.clear_all_rounded,
                  label: 'CLR',
                  onTap: enabled && currentId.isNotEmpty ? onClearPressed : null,
                ),
                _buildDigitCell('0'),
                _buildActionCell(
                  icon: Icons.backspace_outlined,
                  label: 'DEL',
                  onTap: enabled && currentId.isNotEmpty ? onBackspacePressed : null,
                ),
              ],
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildDigitCell(String digit) {
    return Padding(
      padding: const EdgeInsets.all(4.0),
      child: Material(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        elevation: 1,
        child: InkWell(
          onTap: enabled ? () => onDigitPressed(digit) : null,
          borderRadius: BorderRadius.circular(12),
          child: Container(
            height: 58,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppTheme.borderSubtle),
            ),
            child: Text(
              digit,
              style: TextStyle(
                fontSize: 24,
                fontWeight: FontWeight.w700,
                color: enabled ? AppTheme.textPrimary : AppTheme.textSecondary.withOpacity(0.5),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildActionCell({
    required IconData icon,
    required String label,
    required VoidCallback? onTap,
  }) {
    return Padding(
      padding: const EdgeInsets.all(4.0),
      child: Material(
        key: ValueKey('keypad_$label'),
        color: const Color(0xFFF1F5F9),
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(12),
          child: Container(
            height: 58,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppTheme.borderSubtle),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  icon,
                  size: 18,
                  color: onTap != null ? AppTheme.textPrimary : AppTheme.textSecondary.withOpacity(0.4),
                ),
                const SizedBox(width: 4),
                Text(
                  label,
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: onTap != null ? AppTheme.textPrimary : AppTheme.textSecondary.withOpacity(0.4),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
