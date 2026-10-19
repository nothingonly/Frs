import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'config/app_config.dart';
import 'ui/screens/kiosk_screen.dart';
import 'ui/theme/app_theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp,
    DeviceOrientation.portraitDown,
  ]);

  // In production Android kiosk deployment, configuration can be loaded from
  // Android Managed Configurations (MDM) or SharedPreferences.
  const config = AppConfig();

  runApp(const FRSKioskApp(config: config));
}

class FRSKioskApp extends StatelessWidget {
  final AppConfig config;

  const FRSKioskApp({
    super.key,
    required this.config,
  });

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'FRS Attendance Kiosk',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.lightTheme,
      home: KioskScreen(initialConfig: config),
    );
  }
}
