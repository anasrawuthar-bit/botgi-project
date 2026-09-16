import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config/app_config.dart';
import 'token_store.dart';

class AuthService {
  AuthService(this._tokenStore);

  final TokenStore _tokenStore;
  String? _accessToken;
  Map<String, dynamic>? _currentUser;

  Map<String, dynamic>? get currentUser => _currentUser;
  String? get accessToken => _accessToken;

  Future<bool> restoreSession() async {
    final token = await _tokenStore.readToken();
    if (token == null || token.isEmpty) {
      return false;
    }

    _accessToken = token;
    try {
      await fetchMe();
      return true;
    } catch (_) {
      await logout();
      return false;
    }
  }

  Future<void> login({
    required String username,
    required String password,
  }) async {
    final uri = Uri.parse('${AppConfig.baseUrl}/api/mobile/login/');
    final response = await http.post(
      uri,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'username': username, 'password': password}),
    );

    final body = _safeJsonDecode(response.body);
    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Login failed.');
    }

    final token = (body['access_token'] ?? '').toString();
    if (token.isEmpty) {
      throw Exception('Access token missing from login response.');
    }

    _accessToken = token;
    _currentUser = body['user'] is Map<String, dynamic>
        ? (body['user'] as Map<String, dynamic>)
        : null;
    await _tokenStore.saveToken(token);
  }

  Future<Map<String, dynamic>> fetchMe() async {
    final response = await http.get(
      Uri.parse('${AppConfig.baseUrl}/api/mobile/me/'),
      headers: _authHeaders(),
    );
    final body = _safeJsonDecode(response.body);

    if (response.statusCode == 401) {
      await logout();
      throw Exception(
        body['message'] ?? 'Session expired. Please login again.',
      );
    }
    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Failed to fetch profile.');
    }

    final user = body['user'];
    if (user is! Map<String, dynamic>) {
      throw Exception('Invalid user response from server.');
    }
    _currentUser = user;
    return user;
  }

  Future<void> logout() async {
    _accessToken = null;
    _currentUser = null;
    await _tokenStore.clearToken();
  }

  Map<String, String> authHeaders() => _authHeaders();

  Map<String, String> _authHeaders() {
    if (_accessToken == null || _accessToken!.isEmpty) {
      return {'Content-Type': 'application/json'};
    }
    return {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer $_accessToken',
    };
  }

  Map<String, dynamic> _safeJsonDecode(String rawBody) {
    if (rawBody.isEmpty) {
      return {};
    }
    try {
      final decoded = jsonDecode(rawBody);
      if (decoded is Map<String, dynamic>) {
        return decoded;
      }
    } catch (_) {
      // Ignore decode errors and return fallback object.
    }
    return {};
  }
}
