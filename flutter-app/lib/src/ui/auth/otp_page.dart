import 'package:flutter/material.dart';

import '../../../l10n/app_localizations.dart';
import '../../routing/app_router.dart';

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
      appBar: AppBar(title: Text(AppLocalizations.of(context).otpVerification)),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            DropdownButtonFormField<String>(
              initialValue: method,
              items: [
                DropdownMenuItem(
                  value: 'SMS',
                  child: Text(AppLocalizations.of(context).sms),
                ),
                DropdownMenuItem(
                  value: 'Email',
                  child: Text(AppLocalizations.of(context).email),
                ),
              ],
              onChanged: (v) => setState(() => method = v ?? 'SMS'),
              decoration: InputDecoration(
                labelText: AppLocalizations.of(context).deliveryMethod,
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _otpCtrl,
              decoration: InputDecoration(
                labelText: AppLocalizations.of(context).enterOtp,
              ),
              keyboardType: TextInputType.number,
            ),
            const SizedBox(height: 20),
            ElevatedButton(
              onPressed: () {
                Navigator.pushReplacementNamed(context, AppRoutes.dashboard);
              },
              child: Text(AppLocalizations.of(context).verify),
            ),
          ],
        ),
      ),
    );
  }
}
