import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config/app_config.dart';
import '../models/job_detail.dart';
import '../models/job_item.dart';
import 'auth_service.dart';

class JobsSummary {
  const JobsSummary({
    this.count = 0,
    this.partsTotal = '0.00',
    this.serviceTotal = '0.00',
    this.grandTotal = '0.00',
  });

  final int count;
  final String partsTotal;
  final String serviceTotal;
  final String grandTotal;

  factory JobsSummary.fromJson(Map<String, dynamic> json) {
    return JobsSummary(
      count: (json['count'] is num)
          ? (json['count'] as num).toInt()
          : int.tryParse((json['count'] ?? '').toString()) ?? 0,
      partsTotal: (json['parts_total'] ?? '0.00').toString(),
      serviceTotal: (json['service_total'] ?? '0.00').toString(),
      grandTotal: (json['grand_total'] ?? '0.00').toString(),
    );
  }
}

class JobsResponse {
  const JobsResponse({
    required this.jobs,
    required this.summary,
  });

  final List<JobItem> jobs;
  final JobsSummary summary;
}

class JobsService {
  JobsService(this._authService);

  final AuthService _authService;
  AuthService get authService => _authService;

  Future<List<JobItem>> fetchJobs({
    String? preset,
    String? reportMonth,
    String? scope,
    int limit = 300,
  }) async {
    final res = await fetchJobsWithSummary(
      preset: preset,
      reportMonth: reportMonth,
      scope: scope,
      limit: limit,
    );
    return res.jobs;
  }

  Future<JobsResponse> fetchJobsWithSummary({
    String? preset,
    String? reportMonth,
    String? scope,
    int limit = 300,
  }) async {
    final queryParams = <String, String>{};
    if (preset != null && preset.trim().isNotEmpty) {
      queryParams['preset'] = preset.trim();
    }
    if (reportMonth != null && reportMonth.trim().isNotEmpty) {
      queryParams['report_month'] = reportMonth.trim();
    }
    if (scope != null && scope.trim().isNotEmpty) {
      queryParams['scope'] = scope.trim();
    }
    queryParams['limit'] = limit.toString();

    final uri = Uri.parse('${AppConfig.baseUrl}/api/mobile/jobs/')
        .replace(queryParameters: queryParams.isEmpty ? null : queryParams);

    final response = await http.get(
      uri,
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
    final jobs = jobsJson is List
        ? jobsJson
            .whereType<Map<String, dynamic>>()
            .map(JobItem.fromJson)
            .toList(growable: false)
        : <JobItem>[];

    final summaryJson = body['summary'];
    final summary = summaryJson is Map<String, dynamic>
        ? JobsSummary.fromJson(summaryJson)
        : JobsSummary(count: jobs.length);

    return JobsResponse(jobs: jobs, summary: summary);
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
    Map<String, dynamic>? answers,
  }) async {
    final payload = <String, dynamic>{'action': action};
    if (answers != null) {
      payload['answers'] = answers;
    }
    final response = await http.post(
      Uri.parse('${AppConfig.baseUrl}/api/mobile/jobs/$jobCode/action/'),
      headers: _authService.authHeaders(),
      body: jsonEncode(payload),
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

  Future<String> updateJobRack({
    required String jobCode,
    int? rackId,
    int? rackColumn,
  }) async {
    final payload = <String, dynamic>{
      'rack_id': rackId,
      'rack_column': rackColumn,
    };
    final response = await http.post(
      Uri.parse('${AppConfig.baseUrl}/api/mobile/jobs/$jobCode/rack/'),
      headers: _authService.authHeaders(),
      body: jsonEncode(payload),
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
        body['message'] ?? 'You do not have permission to update rack.',
      );
    }
    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Failed to update rack location.');
    }

    return (body['message'] ?? 'Rack updated successfully.').toString();
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

  Future<String> saveJobChecklist({
    required String jobCode,
    required Map<String, dynamic> answers,
  }) async {
    final response = await http.post(
      Uri.parse('${AppConfig.baseUrl}/api/mobile/jobs/$jobCode/checklist/'),
      headers: _authService.authHeaders(),
      body: jsonEncode({'answers': answers}),
    );

    final body = _safeJsonDecode(response.body);
    if (response.statusCode == 401) {
      await _authService.logout();
      throw Exception(
        body['message'] ?? 'Session expired. Please login again.',
      );
    }
    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Unable to save checklist.');
    }

    return (body['message'] ?? 'Checklist saved successfully.').toString();
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
