import 'package:flutter/material.dart';

class TopBox extends StatelessWidget {
  const TopBox({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      color: const Color(0xFFF2841A), // El72 Falcon Orange
      height: 80,
      width: double.infinity,
      child: Center(
        child: Image.asset(
          'assets/logo.png', // El72 framed logo
          height: 56,
          width: 56,
          fit: BoxFit.contain,
        ),
      ),
    );
  }
}
