import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../routing/app_router.dart';
import '../common/top_box.dart';
import '../../data/providers.dart';

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
                color: Colors.black87,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 12),

            // Elhaq logo
            SizedBox(
              height: 80,
              child: Image.asset(
                'assets/logo.png',
                fit: BoxFit.contain,
              ),
            ),
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
                  style: TextStyle(color: Color(0xFF26667f)),
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
                      backgroundColor: Colors.purple, // Elhaq purple theme
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
                      foregroundColor: Colors.purple, // Elhaq purple theme
                      side: const BorderSide(color: Colors.purple),
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
            labelStyle: const TextStyle(color: Colors.black54),
            filled: true,
            fillColor: Colors.white,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: BorderSide.none,
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
            filled: true,
            fillColor: Colors.white,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: BorderSide.none,
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
