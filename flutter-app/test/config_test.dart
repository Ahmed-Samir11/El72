import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:elhaq_tracker/src/data/config.dart';

void main() {
  group('AppConfig', () {
    test(
      'demo mode defaults to live (false) when no preference is stored',
      () async {
        SharedPreferences.setMockInitialValues({});
        await AppConfig.initialize();
        expect(AppConfig.demoMode, isFalse);
      },
    );

    test(
      'isEmulatorDefaultUrl identifies only the dev-only loopback address',
      () {
        expect(AppConfig.isEmulatorDefaultUrl('http://10.0.2.2:8000'), isTrue);
        expect(
          AppConfig.isEmulatorDefaultUrl('https://api.example.com'),
          isFalse,
        );
        expect(
          AppConfig.isEmulatorDefaultUrl('http://192.168.1.106:8000'),
          isFalse,
        );
      },
    );

    test(
      'isProductionEndpoint requires HTTPS and rejects the emulator URL',
      () {
        expect(
          AppConfig.isProductionEndpoint('https://api.example.com'),
          isTrue,
        );
        expect(
          AppConfig.isProductionEndpoint('http://api.example.com'),
          isFalse,
        );
        expect(AppConfig.isProductionEndpoint('http://10.0.2.2:8000'), isFalse);
        expect(
          AppConfig.isProductionEndpoint('https://10.0.2.2:8000'),
          isFalse,
        );
      },
    );

    test(
      'initialize() completes in a non-release build with the default URL',
      () async {
        // Under `flutter test` kReleaseMode is false, so the release guard is a
        // no-op even though apiBaseUrl is the emulator default.
        SharedPreferences.setMockInitialValues({});
        await expectLater(AppConfig.initialize(), completes);
      },
    );
  });
}
