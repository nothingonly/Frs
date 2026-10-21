import 'package:flutter/material.dart';

/// Modern Material 3 Design System for the FRS Android Kiosk.
///
/// Designed with high-contrast surfaces, large touch targets (minimum 48dp),
/// clear typographic hierarchy, and unambiguous state feedback colors.
class AppTheme {
  // Brand & Semantic Palette
  static const Color primaryDark = Color(0xFF0F172A); // Slate 900
  static const Color primaryBlue = Color(0xFF2563EB); // Blue 600
  static const Color accentCyan = Color(0xFF0284C7);  // Sky 600

  static const Color successGreen = Color(0xFF059669); // Emerald 600
  static const Color successBg = Color(0xFFECFDF5);    // Emerald 50

  static const Color warningAmber = Color(0xFFD97706); // Amber 600
  static const Color warningBg = Color(0xFFFFFBEB);    // Amber 50

  static const Color errorRed = Color(0xFFDC2626);     // Red 600
  static const Color errorBg = Color(0xFFFEF2F2);       // Red 50

  static const Color surfaceBg = Color(0xFFF8FAFC);    // Slate 50
  static const Color cardBg = Color(0xFFFFFFFF);
  static const Color textPrimary = Color(0xFF0F172A);
  static const Color textSecondary = Color(0xFF64748B);
  static const Color borderSubtle = Color(0xFFE2E8F0);

  static ThemeData get lightTheme {
    return ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(
        seedColor: primaryBlue,
        brightness: Brightness.light,
        primary: primaryBlue,
        onPrimary: Colors.white,
        secondary: accentCyan,
        surface: surfaceBg,
        onSurface: textPrimary,
        error: errorRed,
      ),
      scaffoldBackgroundColor: surfaceBg,
      fontFamily: 'sans-serif',
      appBarTheme: const AppBarTheme(
        backgroundColor: primaryDark,
        foregroundColor: Colors.white,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          fontSize: 20,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.2,
          color: Colors.white,
        ),
      ),
      cardTheme: CardThemeData(
        color: cardBg,
        elevation: 1,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: borderSubtle, width: 1),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: primaryBlue,
          foregroundColor: Colors.white,
          minimumSize: const Size(64, 48),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
          textStyle: const TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w600,
            letterSpacing: 0.5,
          ),
          elevation: 2,
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size.fromHeight(52),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
          side: const BorderSide(color: borderSubtle, width: 1.5),
          textStyle: const TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}
