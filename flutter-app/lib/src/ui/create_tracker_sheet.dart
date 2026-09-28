import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
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
          const Text(
            'Create Price Tracker',
            style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _urlController,
            decoration: const InputDecoration(
              labelText: 'Product URL (any supported store)',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _targetController,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              labelText: 'Target Price (Optional)',
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

                Navigator.pop(context); // Close the sheet

                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text(
                        '✅ Tracker created! You\'ll get a WhatsApp notification when we find a deal.',
                      ),
                      backgroundColor: Colors.green,
                      duration: Duration(seconds: 3),
                    ),
                  );
                }
              } catch (e) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text('Error: $e'),
                      backgroundColor: Colors.red,
                    ),
                  );
                }
              }
            },
            child: const Text('Start Tracking'),
          ),
          const SizedBox(height: 16),
        ],
      ),
    );
  }
}
