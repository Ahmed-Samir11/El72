import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../l10n/app_localizations.dart';
import '../data/config.dart';
import '../core/format/error_message.dart';
import '../core/styles/app_theme.dart';
import '../data/providers.dart';
import '../data/repositories/tracked_items_repository.dart';
import 'subscription_screen.dart';

class CreateTrackerSheet extends ConsumerStatefulWidget {
  const CreateTrackerSheet({super.key});

  @override
  ConsumerState<CreateTrackerSheet> createState() => _CreateTrackerSheetState();
}

class _CreateTrackerSheetState extends ConsumerState<CreateTrackerSheet> {
  final _urlController = TextEditingController();
  final _targetController = TextEditingController();

  /// True when this build was compiled with the payment surface (`ENABLE_PAYMENTS`
  /// not set to false). A release build of the free product has it off, so the
  /// "Upgrade plan" route that navigates to [SubscriptionScreen] is compiled out
  /// of the flow rather than hidden at runtime.
  static const bool _paymentsEnabled = AppConfig.paymentsEnabled;

  /// The one error line every unhandled failure of the create shows. Extracted
  /// so a 402 in a payments-off build cannot become a silent no-op: the user
  /// must still be told the tracker was not created.
  void _showGenericError(BuildContext context, Object error) {
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          AppLocalizations.of(context).errorPrefix(errorMessage(error)),
        ),
        backgroundColor: context.appTokens.error,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom,
        left: 16,
        right: 16,
        top: 16,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            AppLocalizations.of(context).createPriceTracker,
            style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _urlController,
            decoration: InputDecoration(
              labelText: AppLocalizations.of(context).productUrlHint,
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _targetController,
            keyboardType: TextInputType.number,
            decoration: InputDecoration(
              labelText: AppLocalizations.of(context).targetPriceHint,
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          ElevatedButton(
            onPressed: () async {
              try {
                final url = _urlController.text.trim();
                final price = double.tryParse(_targetController.text) ?? 0.0;

                await ref
                    .read(trackedItemsRepositoryProvider)
                    .createFromUrl(url, targetPrice: price > 0 ? price : null);

                // Refresh the Trackers list so the new item appears immediately.
                ref.invalidate(trackedItemsProvider);

                // The creation may have changed the account state the Profile
                // tab shows: a fair-use build reports the tracker count and the
                // wait, a payment build the remaining credits. Invalidate both
                // so neither tile can go stale without an app restart.
                ref.invalidate(creditBalanceProvider);
                ref.invalidate(usageLimitsProvider);

                // Schedule a second refresh after the background price fetch
                // has had time to complete (~3.5s). Guard with mounted: if the
                // sheet is dismissed first, the state is disposed and `ref`
                // must not be touched.
                Future.delayed(const Duration(milliseconds: 3500), () {
                  if (!mounted) return;
                  ref.invalidate(trackedItemsProvider);
                });

                if (context.mounted) {
                  Navigator.pop(context); // Close the sheet
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text(
                        AppLocalizations.of(context).trackerCreated,
                      ),
                      backgroundColor: context.appTokens.success,
                      duration: const Duration(seconds: 3),
                    ),
                  );
                }
              } on InsufficientCreditsException {
                // Out of credits (HTTP 402): the legacy paid model.
                if (!context.mounted) return;
                if (!_paymentsEnabled) {
                  // A free build has no credit-packages screen to offer, so the
                  // refusal degrades to the generic error line - never a silent
                  // no-op, never an upgrade offer. The server's detail is NOT
                  // shown: it talks about credits, which a free product has none
                  // of, so the line stays neutral.
                  _showGenericError(
                    context,
                    const InsufficientCreditsException(null),
                  );
                  return;
                }
                final nav = Navigator.of(context);
                final l10n = AppLocalizations.of(context);
                showDialog<void>(
                  context: context,
                  builder: (dialogContext) => AlertDialog(
                    title: Text(l10n.reachedLimitTitle),
                    content: Text(l10n.reachedLimitBody),
                    actions: [
                      TextButton(
                        onPressed: () {
                          Navigator.pop(dialogContext);
                          nav.pop(); // dismiss the tracker sheet
                          nav.push(
                            MaterialPageRoute(
                              builder: (_) => const SubscriptionScreen(),
                            ),
                          );
                        },
                        child: Text(l10n.upgradePlan),
                      ),
                      TextButton(
                        onPressed: () => Navigator.pop(dialogContext),
                        child: Text(l10n.notNow),
                      ),
                    ],
                  ),
                );
              } on FairUseCapException catch (failure) {
                // The ceiling is the free product's main refusal: say what it
                // is and point at the way out (delete a tracker from the list).
                // A cap the server did not report as a number is not invented:
                // the dialog then carries the title alone.
                if (!context.mounted) return;
                final nav = Navigator.of(context);
                final l10n = AppLocalizations.of(context);
                final cap = failure.cap;
                showDialog<void>(
                  context: context,
                  builder: (dialogContext) => AlertDialog(
                    title: Text(l10n.reachedLimitTitle),
                    content: cap == null
                        ? null
                        : Text(l10n.fairUseCapBody(cap)),
                    actions: [
                      TextButton(
                        onPressed: () {
                          Navigator.pop(dialogContext);
                          nav.pop(); // back to the tracker list
                        },
                        child: Text(l10n.navTrackers),
                      ),
                      TextButton(
                        onPressed: () => Navigator.pop(dialogContext),
                        child: Text(l10n.notNow),
                      ),
                    ],
                  ),
                );
              } on RateLimitedException catch (failure) {
                // The creation window has not elapsed. The server rounds its
                // wait up, so rounding the countdown up again here can only make
                // the user wait a little longer, never get refused once more.
                // A wait of 0 means no usable countdown (an HTTP-date header).
                if (!context.mounted) return;
                final l10n = AppLocalizations.of(context);
                final seconds = failure.retryAfterSeconds.ceil();
                showDialog<void>(
                  context: context,
                  builder: (dialogContext) => AlertDialog(
                    title: Text(l10n.creationWaitTitle),
                    content: Text(
                      seconds > 0
                          ? l10n.creationWaitBody(seconds)
                          : l10n.creationWaitBodyNoCount,
                    ),
                    actions: [
                      TextButton(
                        onPressed: () => Navigator.pop(dialogContext),
                        child: Text(l10n.close),
                      ),
                    ],
                  ),
                );
              } catch (e) {
                if (context.mounted) _showGenericError(context, e);
              }
            },
            child: Text(AppLocalizations.of(context).startTracking),
          ),
          const SizedBox(height: 16),
        ],
      ),
    );
  }
}
