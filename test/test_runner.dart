import 'api_service_test.dart' as api_service_test;
import 'attendance_result_test.dart' as attendance_result_test;
import 'kiosk_state_test.dart' as kiosk_state_test;

void main() async {
  print('====================================================');
  print('FRS Kiosk App — Unit & Boundary Test Suite Execution');
  print('====================================================\n');

  try {
    print('[SUITE 1/3] Testing AttendanceResult & Timezone Conversions...');
    attendance_result_test.main();

    print('[SUITE 2/3] Testing FrsApiService Boundary & Status Handling...');
    await api_service_test.main();

    print('[SUITE 3/3] Testing KioskState Machine & In-Flight Lock...');
    await kiosk_state_test.main();

    print('====================================================');
    print('ALL KIOSK UNIT & BOUNDARY TESTS PASSED SUCCESSFULLY!');
    print('====================================================');
  } catch (e, st) {
    print('\nTEST SUITE FAILED: $e\n$st');
  }
}
