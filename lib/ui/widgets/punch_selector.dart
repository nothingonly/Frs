import 'package:flutter/material.dart';
import '../../models/punch_type.dart';
import '../theme/app_theme.dart';

/// Touch-friendly Segmented control for selecting CHECK_IN vs CHECK_OUT.
class PunchSelector extends StatelessWidget {
  final PunchType selectedType;
  final ValueChanged<PunchType> onChanged;
  final bool enabled;

  const PunchSelector({
    super.key,
    required this.selectedType,
    required this.onChanged,
    this.enabled = true,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFFF1F5F9),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.borderSubtle),
      ),
      padding: const EdgeInsets.all(4),
      child: Row(
        children: [
          Expanded(
            child: _PunchOption(
              label: 'CHECK IN',
              icon: Icons.login_rounded,
              isSelected: selectedType == PunchType.checkIn,
              activeColor: AppTheme.successGreen,
              onTap: enabled ? () => onChanged(PunchType.checkIn) : null,
            ),
          ),
          const SizedBox(width: 4),
          Expanded(
            child: _PunchOption(
              label: 'CHECK OUT',
              icon: Icons.logout_rounded,
              isSelected: selectedType == PunchType.checkOut,
              activeColor: AppTheme.warningAmber,
              onTap: enabled ? () => onChanged(PunchType.checkOut) : null,
            ),
          ),
        ],
      ),
    );
  }
}

class _PunchOption extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool isSelected;
  final Color activeColor;
  final VoidCallback? onTap;

  const _PunchOption({
    required this.label,
    required this.icon,
    required this.isSelected,
    required this.activeColor,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(10),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        curve: Curves.easeInOut,
        padding: const EdgeInsets.symmetric(vertical: 14),
        decoration: BoxDecoration(
          color: isSelected ? Colors.white : Colors.transparent,
          borderRadius: BorderRadius.circular(10),
          boxShadow: isSelected
              ? [
                  BoxShadow(
                    color: Colors.black.withOpacity(0.06),
                    blurRadius: 8,
                    offset: const Offset(0, 2),
                  ),
                ]
              : null,
          border: isSelected
              ? Border.all(color: activeColor.withOpacity(0.3), width: 1.5)
              : null,
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              icon,
              size: 20,
              color: isSelected ? activeColor : AppTheme.textSecondary,
            ),
            const SizedBox(width: 8),
            Text(
              label,
              style: TextStyle(
                fontSize: 15,
                fontWeight: isSelected ? FontWeight.w700 : FontWeight.w600,
                color: isSelected ? activeColor : AppTheme.textSecondary,
                letterSpacing: 0.5,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
