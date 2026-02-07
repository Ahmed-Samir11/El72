import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../routing/app_router.dart';
import '../common/top_box.dart';
import '../../data/providers.dart';
import '../../core/styles/app_colors.dart';

class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});

  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  final _phoneController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _isLoginPasswordVisible = false;
  bool _isLoading = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white, // Elhaq theme background
      appBar: const PreferredSize(
        preferredSize: Size.fromHeight(100), // fixed height
        child: TopBox(), // stays pinned at the top
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            const Text(
              'Log In',
              style: TextStyle(
                fontFamily: 'IBM Plex Sans',
                fontSize: 40,
                fontStyle: FontStyle.italic,
                color: AppColors.textPrimary,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 12),

            // Removed irrelevant asset
            const SizedBox(height: 30),

            // Form fields
            _buildForm(),

            const SizedBox(height: 12),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: () {
                  // TODO: forgot password action
                },
                child: const Text(
                  "Forgot Password?",
                  style: TextStyle(color: AppColors.primary),
                ),
              ),
            ),

            const SizedBox(height: 24),

            // Login & Cancel buttons
            Row(
              children: [
                Expanded(
                  child: ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppColors.secondary, // Orange
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      textStyle: const TextStyle(
                          fontSize: 18, fontWeight: FontWeight.bold),
                    ),
                    onPressed: _isLoading ? null : () async {
                      String phone = _phoneController.text.trim();
                      String password = _passwordController.text.trim();

                      if (phone.isEmpty || password.isEmpty) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(content: Text("Please fill all fields")),
                        );
                        return;
                      }

                      setState(() => _isLoading = true);
                      
                      try {
                        final authRepo = ref.read(authRepositoryProvider);
                        print('🔐 Attempting login with phone: $phone');
                        bool isValid = await authRepo.login(phone, password);
                        print('✅ Login result: $isValid');

                        if (isValid && mounted) {
                          print('📱 Navigating to dashboard');
                          Navigator.pushReplacementNamed(context, AppRoutes.dashboard);
                        } else if (mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(content: Text("Invalid credentials. Please try again.")),
                          );
                        }
                      } catch (e) {
                        print('❌ Login error: $e');
                        if (mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(content: Text("Login failed: $e"), backgroundColor: Colors.red),
                          );
                        }
                      } finally {
                        if (mounted) setState(() => _isLoading = false);
                      }
                    },
                    child: const Text("Log In"),
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppColors.primary, // Teal
                      side: BorderSide(color: AppColors.primary),
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      textStyle: const TextStyle(
                          fontSize: 18, fontWeight: FontWeight.bold),
                    ),
                    onPressed: () {
                      Navigator.pushReplacementNamed(context, '/welcome');
                    },
                    child: const Text("Cancel"),
                  ),
                ),
              ],
            )
          ],
        ),
      ),
    );
  }

  // Build form
  Widget _buildForm() {
    return Column(
      children: [
        TextField(
          controller: _phoneController,
          keyboardType: TextInputType.phone,
          style: const TextStyle(color: Colors.black),
          decoration: InputDecoration(
            labelText: 'Phone Number',
            labelStyle: TextStyle(color: AppColors.textPrimary),
            filled: true,
            fillColor: Colors.white,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: BorderSide.none,
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: BorderSide(color: AppColors.primary, width: 2),
            ),
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _passwordController,
          style: const TextStyle(color: Colors.black),
          obscureText: !_isLoginPasswordVisible,
          decoration: InputDecoration(
            labelText: 'Password',
            labelStyle: TextStyle(color: AppColors.textPrimary),
            filled: true,
            fillColor: Colors.white,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: BorderSide.none,
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: BorderSide(color: AppColors.primary, width: 2),
            ),
            suffixIcon: IconButton(
              icon: Icon(
                _isLoginPasswordVisible ? Icons.visibility : Icons.visibility_off,
                color: Colors.grey,
              ),
              onPressed: () {
                setState(() {
                  _isLoginPasswordVisible = !_isLoginPasswordVisible;
                });
              },
            ),
          ),
        ),
      ],
    );
  }
}
