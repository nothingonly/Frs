import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:kiosk_app/config/app_config.dart';
import 'package:kiosk_app/main.dart';
import 'package:kiosk_app/models/attendance_result.dart';
import 'package:kiosk_app/state/kiosk_state.dart';
import 'package:kiosk_app/ui/widgets/status_banner.dart';

void main() {
  const testConfig = AppConfig(
    apiBaseUrl: 'http://127.0.0.1:8000',
    apiKeySecret: 'test_dev_secret',
    clientDeviceId: 'TEST_KIOSK_01',
  );

  testWidgets('Renders all essential automatic kiosk UI elements in idle state', (WidgetTester tester) async {
    // Provide a large enough surface to render tablet layout
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(const FRSKioskApp(config: testConfig));
    await tester.pump();

    // Verify AppBar and Device badge
    expect(find.text('FRS Biometric Attendance Kiosk'), findsOneWidget);
    expect(find.text('TEST_KIOSK_01'), findsOneWidget);

    // Verify Admin enrollment action button exists in AppBar
    expect(find.byIcon(Icons.person_add_alt_1), findsOneWidget);

    // Verify Punch selector buttons
    expect(find.text('CHECK IN'), findsOneWidget);
    expect(find.text('CHECK OUT'), findsOneWidget);

    // Verify Guidance card
    expect(find.text('Automatic Face Identification'), findsOneWidget);

    // Verify Keypad is NOT present (eliminated for automatic 1:N attendance)
    expect(find.text('Tap digits to enter Employee ID'), findsNothing);
    expect(find.text('CLR'), findsNothing);
    expect(find.text('DEL'), findsNothing);

    // Verify Primary submission button is disabled when face has not been captured
    final submitFinder = find.byKey(const ValueKey('submit_punch_button'));
    expect(submitFinder, findsOneWidget);
    final submitButton = tester.widget<ElevatedButton>(submitFinder);
    expect(submitButton.onPressed, isNull, reason: 'Submit button must be disabled when no photo captured');
    expect(find.text('Capture 3 Frames to Punch'), findsOneWidget);
  });

  testWidgets('Punch selector toggles punch type between CHECK_IN and CHECK_OUT', (WidgetTester tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(const FRSKioskApp(config: testConfig));
    await tester.pump();

    // Switch to CHECK OUT
    await tester.tap(find.text('CHECK OUT'));
    await tester.pump();

    // Switch back to CHECK IN
    await tester.tap(find.text('CHECK IN'));
    await tester.pump();
  });

  testWidgets('StatusBanner renders 1:N accepted card with database-matched identity', (WidgetTester tester) async {
    final state = KioskState();
    final sampleResult = AttendanceIdentificationResult(
      status: 'success',
      attendanceId: 'att_9999',
      userId: 'usr_8888',
      employeeId: 'EMP_MATCHED',
      fullName: 'Alice Walker',
      department: 'Robotics Lab',
      punchType: 'CHECK_IN',
      timestampUtc: DateTime.utc(2026, 10, 10, 13, 30, 0),
      similarityScore: 0.88,
      threshold: 0.363,
      message: 'Automatic face attendance recorded successfully.',
    );

    // Set 1:N identification result
    state.setIdentificationResult(sampleResult);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: StatusBanner(
            state: state,
            onDismiss: () {},
          ),
        ),
      ),
    );
    await tester.pump();

    // Verify database-matched full name and employee ID are rendered!
    expect(find.text('Attendance Recorded Successfully'), findsOneWidget);
    expect(find.text('Alice Walker'), findsOneWidget);
    expect(find.text('EMP_MATCHED'), findsOneWidget);
    expect(find.text('Robotics Lab'), findsOneWidget);
  });

  testWidgets('StatusBanner renders unrecognized face warning card', (WidgetTester tester) async {
    final state = KioskState();
    state.setStatus(KioskStatus.unrecognized);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: StatusBanner(
            state: state,
            onDismiss: () {},
          ),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('Unrecognized Face'), findsOneWidget);
  });

  testWidgets('StatusBanner renders ambiguous match security warning card', (WidgetTester tester) async {
    final state = KioskState();
    state.setStatus(KioskStatus.ambiguous);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: StatusBanner(
            state: state,
            onDismiss: () {},
          ),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('Ambiguous Biometric Match'), findsOneWidget);
  });

  testWidgets('StatusBanner renders cooldown warning card', (WidgetTester tester) async {
    final state = KioskState();
    state.setStatus(KioskStatus.cooldown);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: StatusBanner(
            state: state,
            onDismiss: () {},
          ),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('Attendance Cooldown Active'), findsOneWidget);
  });
}
