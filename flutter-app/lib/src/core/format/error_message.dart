import 'package:dio/dio.dart';

/// Extracts a short, human-readable message from an exception for UI
/// display. Raw stack traces and internal exception objects must never be
/// shown to users.
String errorMessage(Object error) {
  if (error is DioException) {
    final message = error.message;
    if (message != null && message.trim().isNotEmpty) {
      return message.trim();
    }
    switch (error.type) {
      case DioExceptionType.connectionTimeout:
        return 'The connection timed out.';
      case DioExceptionType.connectionError:
        return 'Could not reach the server.';
      case DioExceptionType.badResponse:
        return 'The server returned an error.';
      case DioExceptionType.cancel:
        return 'The request was cancelled.';
      default:
        break;
    }
  }

  // Fallback: first line of the string form, truncated for display.
  final line = error.toString().split('\n').first.trim();
  if (line.isEmpty) return 'Something went wrong.';
  return line.length > 120 ? '${line.substring(0, 117)}...' : line;
}
