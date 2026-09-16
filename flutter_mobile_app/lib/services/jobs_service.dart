import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config/app_config.dart';
import '../models/job_detail.dart';
import '../models/job_item.dart';
import 'auth_service.dart';

class JobsService {
  JobsService(this._authService);

  final AuthService _authService;

  Future<List<JobItem>> fetchJobs() async {
    final response = await http.get(
      Uri.parse('${AppConfig.baseUrl}/api/mobile/jobs/'),
      headers: _authService.authHeaders(),
    );

    final body = _safeJsonDecode(response.body);
    if (response.statusCode == 401) {
      await _authService.logout();
      throw Exception(
        body['message'] ?? 'Session expired. Please login again.',
      );
    }
    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Failed to load jobs.');
    }

    final jobsJson = body['jobs'];
    if (jobsJson is! List) {
      return [];
    }

    return jobsJson
        .whereType<Map<String, dynamic>>()
        .map(JobItem.fromJson)
        .toList(growable: false);
  }

  Future<JobDetail> fetchJobDetail(String jobCode) async {
    final response = await http.get(
      Uri.parse('${AppConfig.baseUrl}/api/mobile/jobs/$jobCode/'),
      headers: _authService.authHeaders(),
    );

    final body = _safeJsonDecode(response.body);
    if (response.statusCode == 401) {
      await _authService.logout();
      throw Exception(
        body['message'] ?? 'Session expired. Please login again.',
      );
    }
    if (response.statusCode == 403) {
      throw Exception(
        body['message'] ?? 'You are not allowed to access this job.',
      );
    }
    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Failed to load job detail.');
    }

    return JobDetail.fromJson(body);
  }

  Future<String> performJobAction({
    required String jobCode,
    required String action,
  }) async {
    final response = await http.post(
      Uri.parse('${AppConfig.baseUrl}/api/mobile/jobs/$jobCode/action/'),
      headers: _authService.authHeaders(),
      body: jsonEncode({'action': action}),
    );

    final body = _safeJsonDecode(response.body);
    if (response.statusCode == 401) {
      await _authService.logout();
      throw Exception(
        body['message'] ?? 'Session expired. Please login again.',
      );
    }
    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Unable to perform action.');
    }

    return (body['message'] ?? 'Action completed.').toString();
  }

  Future<String> updateJobNotes({
    required String jobCode,
    required String technicianNotes,
  }) async {
    final response = await http.post(
      Uri.parse('${AppConfig.baseUrl}/api/mobile/jobs/$jobCode/notes/'),
      headers: _authService.authHeaders(),
      body: jsonEncode({'technician_notes': technicianNotes}),
    );

    final body = _safeJsonDecode(response.body);
    if (response.statusCode == 401) {
      await _authService.logout();
      throw Exception(
        body['message'] ?? 'Session expired. Please login again.',
      );
    }
    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Unable to update notes.');
    }

    return (body['message'] ?? 'Notes saved.').toString();
  }

  Future<String> addServiceLine({
    required String jobCode,
    required String description,
    required String partCost,
    required String serviceCharge,
    String salesInvoiceNumber = '',
  }) async {
    final response = await http.post(
      Uri.parse('${AppConfig.baseUrl}/api/mobile/jobs/$jobCode/service-lines/'),
      headers: _authService.authHeaders(),
      body: jsonEncode({
        'description': description,
        'part_cost': partCost,
        'service_charge': serviceCharge,
        'sales_invoice_number': salesInvoiceNumber,
      }),
    );

    final body = _safeJsonDecode(response.body);
    if (response.statusCode == 401) {
      await _authService.logout();
      throw Exception(
        body['message'] ?? 'Session expired. Please login again.',
      );
    }
    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Unable to add service line.');
    }

    return (body['message'] ?? 'Service line added.').toString();
  }

  Future<String> updateServiceLine({
    required String jobCode,
    required int lineId,
    required String description,
    required String partCost,
    required String serviceCharge,
    String salesInvoiceNumber = '',
  }) async {
    final response = await http.post(
      Uri.parse(
        '${AppConfig.baseUrl}/api/mobile/jobs/$jobCode/service-lines/$lineId/update/',
      ),
      headers: _authService.authHeaders(),
      body: jsonEncode({
        'description': description,
        'part_cost': partCost,
        'service_charge': serviceCharge,
        'sales_invoice_number': salesInvoiceNumber,
      }),
    );

    final body = _safeJsonDecode(response.body);
    if (response.statusCode == 401) {
      await _authService.logout();
      throw Exception(
        body['message'] ?? 'Session expired. Please login again.',
      );
    }
    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Unable to update service line.');
    }

    return (body['message'] ?? 'Service line updated.').toString();
  }

  Future<String> deleteServiceLine({
    required String jobCode,
    required int lineId,
  }) async {
    final response = await http.post(
      Uri.parse(
        '${AppConfig.baseUrl}/api/mobile/jobs/$jobCode/service-lines/$lineId/delete/',
      ),
      headers: _authService.authHeaders(),
    );

    final body = _safeJsonDecode(response.body);
    if (response.statusCode == 401) {
      await _authService.logout();
      throw Exception(
        body['message'] ?? 'Session expired. Please login again.',
      );
    }
    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Unable to delete service line.');
    }

    return (body['message'] ?? 'Service line deleted.').toString();
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
