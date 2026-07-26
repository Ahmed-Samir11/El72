import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../data/repositories/alerts_repository.dart';
import '../data/providers/tracking_status_provider.dart';

class CreateTrackerSheet extends ConsumerStatefulWidget {
  const CreateTrackerSheet({super.key});

  @override
  ConsumerState<CreateTrackerSheet> createState() => _CreateTrackerSheetState();
}

class _CreateTrackerSheetState extends ConsumerState<CreateTrackerSheet> {
  final _urlController = TextEditingController();
  final _targetController = TextEditingController();
  bool _isSubmitting = false;

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
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _urlController,
            decoration: const InputDecoration(
              labelText: 'Product URL (Amazon/Noon)',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _targetController,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              labelText: 'Target Price (Required)',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          ElevatedButton(
            onPressed: _isSubmitting ? null : () async {
              print("🔘 Add Button Pressed!");

              try {
                final url = _urlController.text.trim();
                final price = double.tryParse(_targetController.text.trim()) ?? 0.0;

                if (url.isEmpty || !url.startsWith('http')) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('Please enter a valid product URL.'),
                      backgroundColor: Colors.red,
                    ),
                  );
                  return;
                }

                if (price <= 0) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('Please enter a target price above zero.'),
                      backgroundColor: Colors.red,
                    ),
                  );
                  return;
                }

                print("📤 Sending: URL=$url, Price=$price");
                setState(() => _isSubmitting = true);

                ref.read(trackingStatusProvider.notifier).startTracking(url, price);

                // Call your repository
                await ref.read(alertsRepositoryProvider).createAlert(url, price);
                
                print("✅ Success!");
                ref.read(trackingStatusProvider.notifier).complete();

                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('✅ Tracker created! You\'ll get a WhatsApp notification when we find a deal.'),
                      backgroundColor: Colors.green,
                      duration: Duration(seconds: 3),
                    ),
                  );
                  Navigator.pop(context);
                }
              } catch (e, stack) {
                print("❌ ERROR: $e");
                print(stack);
                ref.read(trackingStatusProvider.notifier).error(e.toString());
                
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text('Error: $e'),
                      backgroundColor: Colors.red,
                    ),
                  );
                }
              } finally {
                if (mounted) {
                  setState(() => _isSubmitting = false);
                }
              }
            },
            child: _isSubmitting
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2.4),
                  )
                : const Text('Start Tracking'),
          ),
          const SizedBox(height: 16),
        ],
      ),
    );
  }
}