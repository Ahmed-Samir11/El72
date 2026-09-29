import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../l10n/app_localizations.dart';
import '../../core/format/error_message.dart';

/// Uniform async-state rendering for the app's screens.
///
/// Wraps an [AsyncValue] in the standard loading / error / data treatment so
/// every screen shares the same state design language: a themed spinner, a
/// centered themed error message, and the caller's data builder.
class AsyncStateView<T> extends StatelessWidget {
  final AsyncValue<T> value;
  final Widget Function(T data) builder;

  /// Optional custom loading indicator. Defaults to a centered themed
  /// [CircularProgressIndicator].
  final Widget? loading;

  /// Optional custom error view. Defaults to a centered themed message.
  final Widget Function(Object error, StackTrace stackTrace)? errorBuilder;

  const AsyncStateView({
    super.key,
    required this.value,
    required this.builder,
    this.loading,
    this.errorBuilder,
  });

  @override
  Widget build(BuildContext context) {
    return value.when(
      loading: () =>
          loading ?? const Center(child: CircularProgressIndicator()),
      error: (error, stackTrace) =>
          errorBuilder?.call(error, stackTrace) ??
          Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Text(
                AppLocalizations.of(
                  context,
                ).genericLoadError(errorMessage(error)),
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
            ),
          ),
      data: builder,
    );
  }
}
