import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../services/api_client.dart';

class AuthRepository {
  final ApiClient _apiClient = ApiClient();
  final FlutterSecureStorage _storage = const FlutterSecureStorage();

  Future<bool> login(String phone, String password) async {
    try {
      final response = await _apiClient.dio.post(
        '/auth/login',
        data: {
          'phone': phone,
          'password': password,
        },
      );

      if (response.statusCode == 200) {
        final token = response.data['access_token'] as String;
        await _storage.write(key: 'access_token', value: token);
        return true;
      }
      return false;
    } catch (e) {
      return false;
    }
  }

  Future<bool> register(String phone, String password) async {
    print('Register attempt with phone: $phone');
    try {
      final response = await _apiClient.dio.post(
        '/auth/register',
        data: {
          'phone': phone,
          'password': password,
        },
      );
      print('Register response status: ${response.statusCode}');
      if (response.statusCode == 200) {
        // Assuming registration succeeds, but login to get token
        return await login(phone, password);
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