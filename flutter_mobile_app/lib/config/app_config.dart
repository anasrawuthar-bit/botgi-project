import 'package:shared_preferences/shared_preferences.dart';

class AppConfig {
  AppConfig._();

  static const String devMode = 'dev';
  static const String prodMode = 'prod';
  static const String customMode = 'custom';

  // Android emulator: http://10.0.2.2:8000
  // iOS simulator: http://127.0.0.1:8000
  // Physical device: use your computer LAN IP.
  static const String devBaseUrl = 'http://192.168.1.6:8000';
  static const String prodBaseUrl = 'https://api.gihostings.com';

  static const String _modeKey = 'app_server_mode';
  static const String _customUrlKey = 'app_custom_base_url';

  static String _mode = devMode;
  static String _customBaseUrl = '';

  static String get mode => _mode;
  static String get customBaseUrl => _customBaseUrl;

  static String get baseUrl {
    if (_mode == customMode && _customBaseUrl.isNotEmpty) {
      return _customBaseUrl;
    }
    if (_mode == prodMode) {
      return prodBaseUrl;
    }
    return devBaseUrl;
  }

  static String get wsBaseUrl {
    final base = baseUrl;
    if (base.startsWith('https://')) {
      return base.replaceFirst('https://', 'wss://');
    }
    return base.replaceFirst('http://', 'ws://');
  }

  static Future<void> initialize() async {
    final prefs = await SharedPreferences.getInstance();
    _mode = prefs.getString(_modeKey) ?? devMode;
    _customBaseUrl = prefs.getString(_customUrlKey) ?? '';
  }

  static Future<void> setMode(String nextMode) async {
    _mode = nextMode;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_modeKey, _mode);
  }

  static Future<void> setCustomBaseUrl(String rawUrl) async {
    _customBaseUrl = normalizeBaseUrl(rawUrl);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_customUrlKey, _customBaseUrl);
  }

  static String normalizeBaseUrl(String rawUrl) {
    final trimmed = rawUrl.trim();
    if (trimmed.isEmpty) {
      return '';
    }
    if (trimmed.endsWith('/')) {
      return trimmed.substring(0, trimmed.length - 1);
    }
    return trimmed;
  }
}
