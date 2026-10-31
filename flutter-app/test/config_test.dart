import 'dart:io';

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

    test('isProductionEndpoint rejects malformed HTTPS URLs with no host', () {
      expect(AppConfig.isProductionEndpoint('https://'), isFalse);
      expect(AppConfig.isProductionEndpoint('https:/'), isFalse);
      expect(AppConfig.isProductionEndpoint('not a url at all'), isFalse);
    });

    group('validateApiBaseUrlForRelease', () {
      test('throws in release mode for the emulator default URL', () {
        expect(
          () => AppConfig.validateApiBaseUrlForRelease(
            'http://10.0.2.2:8000',
            isRelease: true,
          ),
          throwsA(
            isA<StateError>().having(
              (e) => e.message,
              'message',
              contains('emulator API base URL'),
            ),
          ),
        );
      });

      test('throws in release mode for a cleartext http URL', () {
        expect(
          () => AppConfig.validateApiBaseUrlForRelease(
            'http://api.example.com',
            isRelease: true,
          ),
          throwsA(isA<StateError>()),
        );
      });

      test('throws in release mode for a malformed HTTPS URL (empty host)', () {
        expect(
          () => AppConfig.validateApiBaseUrlForRelease(
            'https://',
            isRelease: true,
          ),
          throwsA(isA<StateError>()),
        );
      });

      test('passes in release mode for a valid production HTTPS URL', () {
        expect(
          () => AppConfig.validateApiBaseUrlForRelease(
            'https://api.example.com',
            isRelease: true,
          ),
          returnsNormally,
        );
      });

      test(
        'accepts an uppercase HTTPS scheme (schemes are case-insensitive)',
        () {
          expect(
            () => AppConfig.validateApiBaseUrlForRelease(
              'HTTPS://API.Example.com',
              isRelease: true,
            ),
            returnsNormally,
          );
          expect(
            AppConfig.isProductionEndpoint('HTTPS://API.Example.com'),
            isTrue,
          );
        },
      );

      test('never throws in debug/profile mode, even for the emulator URL', () {
        expect(
          () => AppConfig.validateApiBaseUrlForRelease(
            'http://10.0.2.2:8000',
            isRelease: false,
          ),
          returnsNormally,
        );
        expect(
          () => AppConfig.validateApiBaseUrlForRelease(
            'https://',
            isRelease: false,
          ),
          returnsNormally,
        );
      });
    });

    test(
      'initialize() completes in a non-release build with the default URL',
      () async {
        // Under `flutter test` kReleaseMode is false, so the release guard is a
        // no-op even though apiBaseUrl is the emulator default.
        SharedPreferences.setMockInitialValues({});
        await expectLater(AppConfig.initialize(), completes);
      },
    );

    test('the release build is compiled without the payment surface', () {
      // `AppConfig.paymentsEnabled` is a compile-time constant, so no runtime
      // test can prove which posture a store artifact uses - the artifact's
      // own build command can. Read the workflow and require the define there
      // (same file-reading precedent as `l10n_coverage_test.dart`).
      final workflow = File('../.github/workflows/ci.yml').readAsStringSync();

      expect(
        workflow,
        contains('--dart-define=ENABLE_PAYMENTS=false'),
        reason:
            'a release AAB built without the define would ship the credit-'
            'packages screen the free product promises not to have',
      );
      // The suite must also RUN under that define, so the off posture is
      // compiled and exercised rather than merely assumed.
      expect(
        workflow,
        contains('flutter test --dart-define=ENABLE_PAYMENTS=false'),
      );
    });
  });
}
