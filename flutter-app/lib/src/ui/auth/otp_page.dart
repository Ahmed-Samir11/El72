import 'package:flutter/material.dart';

import '../../routing/app_router.dart';
import '../../core/styles/app_colors.dart';

class OtpPage extends StatefulWidget {
  const OtpPage({super.key});

  @override
  State<OtpPage> createState() => _OtpPageState();
}

class _OtpPageState extends State<OtpPage> {
  final TextEditingController _otpCtrl = TextEditingController();
  String method = 'SMS';

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('OTP Verification'),
        backgroundColor: AppColors.primary,
        foregroundColor: Colors.white,
      ),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            DropdownButtonFormField<String>(
              initialValue: method,
              items: const [
                DropdownMenuItem(value: 'SMS', child: Text('SMS')),
                DropdownMenuItem(value: 'Email', child: Text('Email')),
              ],
              onChanged: (v) => setState(() => method = v ?? 'SMS'),
              decoration: InputDecoration(
                labelText: 'Delivery Method',
                labelStyle: TextStyle(color: AppColors.textPrimary),
                focusedBorder: OutlineInputBorder(
                  borderSide: BorderSide(color: AppColors.primary, width: 2),
                ),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _otpCtrl,
              decoration: InputDecoration(
                labelText: 'Enter OTP',
                labelStyle: TextStyle(color: AppColors.textPrimary),
                focusedBorder: OutlineInputBorder(
                  borderSide: BorderSide(color: AppColors.primary, width: 2),
                ),
              ),
              keyboardType: TextInputType.number,
            ),
            const SizedBox(height: 20),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.secondary,
                foregroundColor: Colors.white,
              ),
              onPressed: () {
                Navigator.pushReplacementNamed(context, AppRoutes.dashboard);
              },
              child: const Text('Verify'),
            ),
          ],
        ),
      ),
    );
  }
}


