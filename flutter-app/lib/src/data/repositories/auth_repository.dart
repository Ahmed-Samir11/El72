import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../services/api_client.dart';

class AuthRepository {
  final ApiClient _apiClient = ApiClient();
  final FlutterSecureStorage _storage = const FlutterSecureStorage();

  /// Format phone number to ensure +20 prefix
  String _formatPhone(String phone) {
    // Remove any whitespace
    phone = phone.trim().replaceAll(' ', '');
    
    // If starts with +20, return as is
    if (phone.startsWith('+20')) {
      return phone;
    }
    
    // If starts with 20, add +
    if (phone.startsWith('20')) {
      return '+$phone';
    }
    
    // If starts with 0, replace with +20
    if (phone.startsWith('0')) {
      return '+2${phone.substring(1)}';
    }
    
    // Otherwise add +20
    return '+20$phone';
  }

  Future<bool> login(String phone, String password) async {
    try {
      final formattedPhone = _formatPhone(phone);
      print('🔐 Login - Original: $phone, Formatted: $formattedPhone');
      
      final response = await _apiClient.dio.post(
        '/auth/login',
        data: {
          'phone': formattedPhone,
          'password': password,
        },
      );

      print('📥 Login response: ${response.statusCode}');
      if (response.statusCode == 200) {
        final token = response.data['access_token'] as String;
        await _storage.write(key: 'access_token', value: token);
        print('✅ Token saved');
        return true;
      }
      return false;
    } on DioException catch (e) {
      print('❌ Login DioException: ${e.message}');
      print('Response: ${e.response?.data}');
      return false;
    } catch (e) {
      print('❌ Login error: $e');
      return false;
    }
  }

  Future<bool> register(String phone, String password) async {
    print('Register attempt with phone: $phone');
    try {
      final formattedPhone = _formatPhone(phone);
      print('Formatted phone: $formattedPhone');
      final response = await _apiClient.dio.post(
        '/auth/register',
        data: {
          'phone': formattedPhone,
          'password': password,
        },
      );
      print('Register response status: ${response.statusCode}');
      if (response.statusCode == 200) {
        // Assuming registration succeeds, but login to get token
        return await login(formattedPhone, password);
      }
      return false;
    } on DioException catch (e) {
      if (e.response != null) {
        final errorData = e.response?.data;
        if (errorData is Map && errorData['detail'] != null) {
          throw errorData['detail'];
        }
      }
      throw 'Registration failed: ${e.message}';
    } catch (e) {
      print('Register error: $e');
      throw 'Registration failed: $e';
    }
  }

  Future<void> logout() async {
    await _storage.delete(key: 'access_token');
  }

  Future<String?> getToken() async {
    return await _storage.read(key: 'access_token');
  }
}