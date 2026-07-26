import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../../core/styles/app_colors.dart';
import '../../routing/app_router.dart';
import 'el72_brand_mark.dart';

class SplashPage extends StatefulWidget {
  const SplashPage({Key? key}) : super(key: key);

  @override
  State<SplashPage> createState() => _SplashPageState();
}

class _SplashPageState extends State<SplashPage> {
  final List<String> statuses = [
    'Scanning live offers...',
    'Loading Black Friday deals...',
    'Syncing category feeds...',
    'Almost ready...'
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
      if (!mounted) {
        return;
      }
      setState(() {
        _statusIndex = i;
        _progress = (i + 1) / statuses.length;
      });
    }
    if (mounted) {
      Navigator.pushReplacementNamed(context, AppRoutes.dashboard);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            colors: [Color(0xFFFFFBF4), Color(0xFFFFEDD5)],
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
          ),
        ),
        child: SafeArea(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const El72BrandMark(size: 148, alignCenter: true),
                  const SizedBox(height: 36),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(999),
                    child: SizedBox(
                      width: 240,
                      child: LinearProgressIndicator(
                        value: _progress,
                        backgroundColor: const Color(0x33FF8A00),
                        color: AppColors.primary,
                        minHeight: 10,
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Text(
                    statuses[_statusIndex],
                    style: GoogleFonts.ubuntu(
                      fontSize: 18,
                      color: AppColors.textPrimary,
                      fontWeight: FontWeight.w600,
                    ),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 14),
                  if (_statusIndex < statuses.length - 1)
                    const CircularProgressIndicator(
                      color: AppColors.primary,
                      strokeWidth: 3,
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
