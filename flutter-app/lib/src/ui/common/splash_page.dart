import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../../core/styles/app_colors.dart';
import '../../data/repositories/auth_repository.dart';
import '../../routing/app_router.dart';

class SplashPage extends StatefulWidget {
  const SplashPage({Key? key}) : super(key: key);

  @override
  State<SplashPage> createState() => _SplashPageState();
}

class _SplashPageState extends State<SplashPage> {
  final List<String> statuses = [
    "Opening application...",
    "Connecting to cloud...",
    "Loading user data...",
    "Almost ready..."
  ];
  int _statusIndex = 0;
  double _progress = 0.0;

  @override
  void initState() {
    super.initState();
    _startLoading();
  }

  void _startLoading() async {
    for (int i = 0; i < statuses.length; i++) {
      await Future.delayed(const Duration(seconds: 1));
      setState(() {
        _statusIndex = i;
        _progress = (i + 1) / statuses.length;
      });
    }
    // Route based on existing auth state: a stored token means the user is
    // already registered, so skip straight to the dashboard.
    final token = await AuthRepository().getToken();
    if (!mounted) return;
    Navigator.pushReplacementNamed(
      context,
      token != null ? AppRoutes.dashboard : AppRoutes.welcome,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            // ✅ Bigger logo
            Image.asset(
              'assets/logo.png',
              width: 223,
              height: 242,
            ),
            const SizedBox(height: 40),
            // ✅ Rounded progress bar
            ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: SizedBox(
                width: 250,
                child: LinearProgressIndicator(
                  value: _progress,
                  backgroundColor: const Color(0xFFE8D9B0), // light tan
                  color: AppColors.primary, // Falcon Orange
                  minHeight: 12,
                ),
              ),
            ),
            const SizedBox(height: 16),
            Text(
              statuses[_statusIndex],
              style: GoogleFonts.ubuntu( 
                fontSize: 20,
                color: Colors.black87,
                fontWeight: FontWeight.w500,
              ),
            ),
            const SizedBox(height: 16),
            if (_statusIndex < statuses.length - 1)
              CircularProgressIndicator(
                color: AppColors.primary,
                strokeWidth: 3,
              ),
          ],
        ),
      ),
    );
  }
}
