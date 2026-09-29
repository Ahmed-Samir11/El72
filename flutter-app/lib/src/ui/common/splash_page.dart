import 'package:flutter/material.dart';

import '../../core/styles/app_colors.dart';
import '../../data/repositories/auth_repository.dart';
import '../../routing/app_router.dart';
import '../../../l10n/app_localizations.dart';

class SplashPage extends StatefulWidget {
  const SplashPage({super.key});

  @override
  State<SplashPage> createState() => _SplashPageState();
}

class _SplashPageState extends State<SplashPage> {
  static const Duration _minDisplay = Duration(milliseconds: 800);

  @override
  void initState() {
    super.initState();
    _startLoading();
  }

  /// Real splash initialization: resolve the stored auth token. A minimum
  /// display time keeps the brand from flashing on fast devices; there is no
  /// fake status cycling padding the perceived load.
  Future<void> _startLoading() async {
    final stopwatch = Stopwatch()..start();
    // Route based on existing auth state: a stored token means the user is
    // already registered, so skip straight to the dashboard.
    final token = await AuthRepository().getToken();
    final elapsed = stopwatch.elapsed;
    if (elapsed < _minDisplay) {
      await Future.delayed(_minDisplay - elapsed);
    }
    if (!mounted) return;
    Navigator.pushReplacementNamed(
      context,
      token != null ? AppRoutes.dashboard : AppRoutes.welcome,
    );
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Image.asset('assets/logo.png', width: 223, height: 242),
            const SizedBox(height: 40),
            CircularProgressIndicator(color: AppColors.primary, strokeWidth: 3),
            const SizedBox(height: 16),
            Text(
              AppLocalizations.of(context).splashStatusOpening,
              style: TextStyle(
                fontFamily: 'IBM Plex Sans',
                fontSize: 20,
                color: colorScheme.onSurface,
                fontWeight: FontWeight.w500,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
