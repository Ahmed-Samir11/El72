import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/core/format/error_message.dart';

RequestOptions _options() => RequestOptions(path: '/test');

void main() {
  group('errorMessage', () {
    test('returns the DioException message when present', () {
      final e = DioException(requestOptions: _options(),
          message: 'Server not reachable');
      expect(errorMessage(e), 'Server not reachable');
    });

    test('maps connection timeouts to a friendly phrase', () {
      final e = DioException(
          requestOptions: _options(),
          type: DioExceptionType.connectionTimeout);
      expect(errorMessage(e), 'The connection timed out.');
    });

    test('maps bad responses to a friendly phrase', () {
      final e = DioException(
          requestOptions: _options(),
          type: DioExceptionType.badResponse,
          response: Response(requestOptions: _options(), statusCode: 500));
      expect(errorMessage(e), 'The server returned an error.');
    });

    test('truncates long raw messages for display', () {
      final long = 'x' * 200;
      final result = errorMessage(long);
      expect(result.length, lessThanOrEqualTo(120));
      expect(result, endsWith('...'));
    });

    test('falls back to a generic phrase for empty strings', () {
      expect(errorMessage(''), isNotEmpty);
    });
  });
}
