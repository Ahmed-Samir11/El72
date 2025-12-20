import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../data/repositories/alerts_repository.dart';

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
              labelText: 'Target Price (Optional)',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          ElevatedButton(
            onPressed: () async {
              print("🔘 Add Button Pressed!");
              
              try {
                final url = _urlController.text;
                final price = double.tryParse(_targetController.text) ?? 0.0;
                
                print("📤 Sending: URL=$url, Price=$price");

                // Call your repository
                await ref.read(alertsRepositoryProvider).createAlert(url, price);
                
                print("✅ Success!");
                Navigator.pop(context); // Close the sheet
                
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('✅ Tracker created! You\'ll get a WhatsApp notification when we find a deal.'),
                      backgroundColor: Colors.green,
                      duration: Duration(seconds: 3),
                    ),
                  );
                }
              } catch (e, stack) {
                print("❌ ERROR: $e");
                print(stack);
                
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