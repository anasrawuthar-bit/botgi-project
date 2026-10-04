import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../config/app_config.dart';
import '../models/task_model.dart';
import 'auth_service.dart';

class TasksService {
  TasksService(this._authService);

  /// Converts exceptions and raw server responses into clear, human-friendly error messages.
  static String formatError(Object error) {
    if (error is SocketException) {
      return 'Unable to reach server. Please check your internet connection.';
    }
    if (error is TimeoutException) {
      return 'Server response timed out. Please try again.';
    }
    if (error is FormatException) {
      return 'Server response format was invalid.';
    }
    final str = error.toString().replaceFirst('Exception: ', '').trim();
    if (str.contains('SocketException') ||
        str.contains('Failed host lookup') ||
        str.contains('Network is unreachable')) {
      return 'Network connection lost. Please check your internet connection.';
    }
    if (str.contains('Connection refused') || str.contains('Connection timed out')) {
      return 'Server is temporarily unreachable. Please try again.';
    }
    return str.isNotEmpty ? str : 'An unexpected error occurred. Please try again.';
  }

  final AuthService _authService;
  AuthService get authService => _authService;

  TaskMetrics _cachedMetrics = TaskMetrics();
  TaskMetrics get cachedMetrics => _cachedMetrics;

  Future<TaskListResponse> fetchTasksWithMetrics({
    String status = 'active',
    String priority = '',
    String query = '',
    bool mineOnly = false,
    bool poolOnly = false,
  }) async {
    final queryParams = <String, String>{};
    if (status.isNotEmpty) queryParams['status'] = status;
    if (priority.isNotEmpty) queryParams['priority'] = priority;
    if (query.isNotEmpty) queryParams['q'] = query;
    if (mineOnly) queryParams['mine'] = '1';
    if (poolOnly) queryParams['pool'] = '1';

    final uri = Uri.parse('${AppConfig.baseUrl}/api/mobile/tasks/').replace(
      queryParameters: queryParams.isEmpty ? null : queryParams,
    );

    final response = await http.get(uri, headers: _authService.authHeaders());
    final body = _safeJsonDecode(response.body);

    if (response.statusCode == 401) {
      await _authService.logout();
      throw Exception(body['message'] ?? 'Session expired. Please login again.');
    }
    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Failed to load tasks.');
    }

    final tasksJson = body['tasks'];
    final metricsJson = body['metrics'];

    final tasks = (tasksJson is List)
        ? tasksJson.whereType<Map<String, dynamic>>().map(TaskModel.fromJson).toList(growable: false)
        : <TaskModel>[];

    final metrics = (metricsJson is Map<String, dynamic>)
        ? TaskMetrics.fromJson(metricsJson)
        : TaskMetrics(
            total: tasks.length,
            active: tasks.where((t) => t.status == 'open' || t.status == 'in_progress').length,
            urgent: tasks.where((t) => t.priority == 'urgent' && (t.status == 'open' || t.status == 'in_progress')).length,
            inProgress: tasks.where((t) => t.status == 'in_progress').length,
            open: tasks.where((t) => t.status == 'open').length,
            done: tasks.where((t) => t.status == 'done').length,
            pool: tasks.where((t) => t.isOpenToAll || t.assignedToId == null).length,
          );

    _cachedMetrics = metrics;

    return TaskListResponse(tasks: tasks, metrics: metrics);
  }

  Future<List<TaskModel>> fetchTasks({
    String status = 'active',
    String priority = '',
    String query = '',
    bool mineOnly = false,
    bool poolOnly = false,
  }) async {
    final response = await fetchTasksWithMetrics(
      status: status,
      priority: priority,
      query: query,
      mineOnly: mineOnly,
      poolOnly: poolOnly,
    );
    return response.tasks;
  }

  Future<TaskModel> fetchTaskDetail(int taskId) async {
    final uri = Uri.parse('${AppConfig.baseUrl}/api/mobile/tasks/$taskId/');
    final response = await http.get(uri, headers: _authService.authHeaders());
    final body = _safeJsonDecode(response.body);

    if (response.statusCode == 401) {
      await _authService.logout();
      throw Exception(body['message'] ?? 'Session expired. Please login again.');
    }
    if (response.statusCode == 403) {
      throw Exception(body['message'] ?? 'You do not have access to this task.');
    }
    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Failed to load task details.');
    }

    final taskJson = body['task'];
    if (taskJson is! Map<String, dynamic>) {
      throw Exception('Malformed task detail response.');
    }

    return TaskModel.fromJson(taskJson);
  }

  Future<TaskModel> acceptTask(int taskId) async {
    final uri = Uri.parse('${AppConfig.baseUrl}/api/mobile/tasks/$taskId/accept/');
    final response = await http.post(
      uri,
      headers: _authService.authHeaders(),
    );
    final body = _safeJsonDecode(response.body);

    if (response.statusCode == 401) {
      await _authService.logout();
      throw Exception(body['message'] ?? 'Session expired.');
    }
    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Failed to claim task.');
    }

    final taskJson = body['task'];
    if (taskJson is! Map<String, dynamic>) {
      throw Exception('Malformed task response from server.');
    }

    return TaskModel.fromJson(taskJson);
  }

  Future<TaskModel> createTask({
    required String title,
    String description = '',
    String priority = 'medium',
    String? dueDate,
    int? assignedToId,
    bool assignToMe = false,
    bool isOpenToAll = false,
    bool hasAlarm = false,
    String? alarmTime,
    int? jobReferenceId,
    String? jobCode,
    String? initialMessage,
  }) async {
    final uri = Uri.parse('${AppConfig.baseUrl}/api/mobile/tasks/');
    final payload = <String, dynamic>{
      'title': title,
      'description': description,
      'priority': priority,
    };
    if (dueDate != null && dueDate.isNotEmpty) payload['due_date'] = dueDate;
    if (isOpenToAll) {
      payload['is_open_to_all'] = true;
    } else if (assignedToId != null) {
      payload['assigned_to_id'] = assignedToId;
    } else if (assignToMe) {
      payload['assign_to_me'] = true;
    }
    if (hasAlarm) payload['has_alarm'] = true;
    if (alarmTime != null && alarmTime.isNotEmpty) payload['alarm_time'] = alarmTime;
    if (jobReferenceId != null) payload['job_reference_id'] = jobReferenceId;
    if (jobCode != null && jobCode.isNotEmpty) payload['job_code'] = jobCode;
    if (initialMessage != null && initialMessage.isNotEmpty) {
      payload['initial_message'] = initialMessage;
    }

    final response = await http.post(
      uri,
      headers: _authService.authHeaders(),
      body: jsonEncode(payload),
    );
    final body = _safeJsonDecode(response.body);

    if (response.statusCode == 401) {
      await _authService.logout();
      throw Exception(body['message'] ?? 'Session expired.');
    }
    if (response.statusCode != 201 && response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Failed to create task.');
    }

    final taskJson = body['task'];
    if (taskJson is! Map<String, dynamic>) {
      throw Exception('Malformed task response from server.');
    }

    return TaskModel.fromJson(taskJson);
  }

  Future<TaskModel> updateTask({
    required int taskId,
    String? title,
    String? description,
    String? priority,
    String? dueDate,
    int? assignedToId,
  }) async {
    final uri = Uri.parse('${AppConfig.baseUrl}/api/mobile/tasks/$taskId/');
    final payload = <String, dynamic>{};
    if (title != null) payload['title'] = title;
    if (description != null) payload['description'] = description;
    if (priority != null) payload['priority'] = priority;
    if (dueDate != null) payload['due_date'] = dueDate;
    if (assignedToId != null) payload['assigned_to_id'] = assignedToId;

    final response = await http.post(
      uri,
      headers: _authService.authHeaders(),
      body: jsonEncode(payload),
    );
    final body = _safeJsonDecode(response.body);

    if (response.statusCode == 401) {
      await _authService.logout();
      throw Exception(body['message'] ?? 'Session expired.');
    }
    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Failed to update task.');
    }

    final taskJson = body['task'];
    if (taskJson is! Map<String, dynamic>) {
      throw Exception('Malformed update response.');
    }

    return TaskModel.fromJson(taskJson);
  }

  Future<void> updateTaskStatus(int taskId, String status) async {
    final uri = Uri.parse('${AppConfig.baseUrl}/api/mobile/tasks/$taskId/status/');
    final response = await http.post(
      uri,
      headers: _authService.authHeaders(),
      body: jsonEncode({'status': status}),
    );
    final body = _safeJsonDecode(response.body);

    if (response.statusCode == 401) {
      await _authService.logout();
      throw Exception(body['message'] ?? 'Session expired.');
    }
    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Failed to update task status.');
    }
  }

  Future<TaskMessageModel> sendTaskMessage(int taskId, String bodyText) async {
    final uri = Uri.parse('${AppConfig.baseUrl}/api/mobile/tasks/$taskId/message/');
    final response = await http.post(
      uri,
      headers: _authService.authHeaders(),
      body: jsonEncode({'body': bodyText}),
    );
    final body = _safeJsonDecode(response.body);

    if (response.statusCode == 401) {
      await _authService.logout();
      throw Exception(body['message'] ?? 'Session expired.');
    }
    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Failed to send message.');
    }

    final msgJson = body['message'];
    if (msgJson is! Map<String, dynamic>) {
      throw Exception('Malformed message response.');
    }

    return TaskMessageModel.fromJson(msgJson);
  }

  Future<List<TaskMessageModel>> fetchTaskMessages(int taskId, {int? sinceId}) async {
    final queryParams = <String, String>{};
    if (sinceId != null) queryParams['since_id'] = sinceId.toString();

    final uri = Uri.parse('${AppConfig.baseUrl}/api/mobile/tasks/$taskId/messages/').replace(
      queryParameters: queryParams.isEmpty ? null : queryParams,
    );

    final response = await http.get(uri, headers: _authService.authHeaders());
    final body = _safeJsonDecode(response.body);

    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Failed to fetch messages.');
    }

    final messagesJson = body['messages'];
    if (messagesJson is! List) return [];

    return messagesJson
        .whereType<Map<String, dynamic>>()
        .map(TaskMessageModel.fromJson)
        .toList(growable: false);
  }

  Future<List<TechnicianItem>> fetchTechnicians() async {
    final uri = Uri.parse('${AppConfig.baseUrl}/api/mobile/technicians/');
    final response = await http.get(uri, headers: _authService.authHeaders());
    final body = _safeJsonDecode(response.body);

    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Failed to load technicians.');
    }

    final techsJson = body['technicians'];
    if (techsJson is! List) return [];

    return techsJson
        .whereType<Map<String, dynamic>>()
        .map(TechnicianItem.fromJson)
        .toList(growable: false);
  }

  Future<List<QuickJobItem>> fetchQuickJobs({String query = ''}) async {
    final queryParams = <String, String>{};
    if (query.isNotEmpty) queryParams['q'] = query;

    final uri = Uri.parse('${AppConfig.baseUrl}/api/mobile/jobs/quick-list/').replace(
      queryParameters: queryParams.isEmpty ? null : queryParams,
    );

    final response = await http.get(uri, headers: _authService.authHeaders());
    final body = _safeJsonDecode(response.body);

    if (response.statusCode != 200) {
      throw Exception(body['message'] ?? 'Failed to load jobs list.');
    }

    final jobsJson = body['jobs'];
    if (jobsJson is! List) return [];

    return jobsJson
        .whereType<Map<String, dynamic>>()
        .map(QuickJobItem.fromJson)
        .toList(growable: false);
  }

  Map<String, dynamic> _safeJsonDecode(String payload) {
    try {
      final decoded = jsonDecode(payload);
      if (decoded is Map<String, dynamic>) {
        return decoded;
      }
      return {'message': payload};
    } catch (_) {
      return {'message': payload};
    }
  }

  /// Connect to the real-time WebSocket room for a specific task with automatic reconnection.
  Stream<Map<String, dynamic>> connectToTaskChat(int taskId) async* {
    int backoff = 2;
    while (true) {
      final token = _authService.accessToken ?? '';
      if (token.isEmpty) break;

      final uri = Uri.parse('${AppConfig.wsBaseUrl}/ws/tasks/$taskId/').replace(
        queryParameters: {'token': token},
      );

      WebSocket? socket;
      try {
        socket = await WebSocket.connect(uri.toString());
        socket.pingInterval = const Duration(seconds: 15);
        backoff = 2; // Reset on successful connection

        await for (final data in socket) {
          if (data is String) {
            try {
              final decoded = jsonDecode(data);
              if (decoded is Map<String, dynamic>) {
                yield decoded;
              }
            } catch (_) {}
          }
        }
      } catch (_) {
        // Socket or network error; fall through to reconnect
      } finally {
        try {
          await socket?.close();
        } catch (_) {}
      }

      if (_authService.accessToken == null || _authService.accessToken!.isEmpty) {
        break;
      }

      await Future<void>.delayed(Duration(seconds: backoff));
      backoff = (backoff * 2).clamp(2, 30);
    }
  }

  /// Connect to the real-time WebSocket feed for technician tasks with automatic reconnection.
  Stream<Map<String, dynamic>> connectToTechTasks() async* {
    int backoff = 2;
    while (true) {
      final token = _authService.accessToken ?? '';
      if (token.isEmpty) break;

      final uri = Uri.parse('${AppConfig.wsBaseUrl}/ws/tech_tasks/').replace(
        queryParameters: {'token': token},
      );

      WebSocket? socket;
      try {
        socket = await WebSocket.connect(uri.toString());
        socket.pingInterval = const Duration(seconds: 15);
        backoff = 2; // Reset on successful connection

        await for (final data in socket) {
          if (data is String) {
            try {
              final decoded = jsonDecode(data);
              if (decoded is Map<String, dynamic>) {
                yield decoded;
              }
            } catch (_) {}
          }
        }
      } catch (_) {
        // Socket or network error; fall through to reconnect
      } finally {
        try {
          await socket?.close();
        } catch (_) {}
      }

      if (_authService.accessToken == null || _authService.accessToken!.isEmpty) {
        break;
      }

      await Future<void>.delayed(Duration(seconds: backoff));
      backoff = (backoff * 2).clamp(2, 30);
    }
  }
}
