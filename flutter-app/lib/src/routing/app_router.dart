import 'package:flutter/material.dart';

import '../ui/auth/login_page.dart';
import '../ui/auth/register_page.dart';
import '../ui/auth/otp_page.dart';
import '../ui/common/splash_page.dart';
import '../ui/auth/welcome_page.dart';
import '../ui/dashboard/dashboard_page.dart';

class AppRoutes {
  static const String splash = '/';
  static const String login = '/login';
  static const String register = '/register';
  static const String otp = '/otp';
  static const String dashboard = '/dashboard';
  static const String welcome = '/welcome';
}

class AppRouter {
  static Map<String, WidgetBuilder> get routes => {
        AppRoutes.splash: (context) => const SplashPage(),
        AppRoutes.login: (context) => const LoginPage(),
        AppRoutes.register: (context) => const RegisterPage(),
        AppRoutes.otp: (context) => const OtpPage(),
        AppRoutes.dashboard: (context) => const DashboardPage(),
        AppRoutes.welcome: (context) => const WelcomePage(),
      };
}


