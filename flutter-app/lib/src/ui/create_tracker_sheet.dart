import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../l10n/app_localizations.dart';
import '../core/styles/app_theme.dart';
import '../data/providers.dart';

class CreateTrackerSheet extends ConsumerStatefulWidget {
  const CreateTrackerSheet({super.key});

  @override
  ConsumerState<CreateTrackerSheet> createState() => _CreateTrackerSheetState();
}

class _CreateTrackerSheetState extends ConsumerState<CreateTrackerSheet> {
  final _urlController = TextEditingController();
  final _targetController = TextEditingController();

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
                      content: Text(AppLocalizations.of(context).trackerCreated),
                      backgroundColor: context.appTokens.success,
                      duration: const Duration(seconds: 3),
                    ),
                  );
                }
              } catch (e) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text(AppLocalizations.of(context).errorPrefix(e.toString())),
                      backgroundColor: context.appTokens.error,
                    ),
                  );
                }
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
