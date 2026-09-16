import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../config/app_config.dart';
import '../models/task_model.dart';
import 'auth_service.dart';

class TasksService {
  TasksService(this._authService);

  final AuthService _authService;
  AuthService get authService => _authService;

  Future<List<TaskModel>> fetchTasks({
    String status = 'active',
    String priority = '',
    String query = '',
  }) async {
    final queryParams = <String, String>{};
    if (status.isNotEmpty) queryParams['status'] = status;
    if (priority.isNotEmpty) queryParams['priority'] = priority;
    if (query.isNotEmpty) queryParams['q'] = query;

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
    if (tasksJson is! List) {
      return [];
    }

    return tasksJson
        .whereType<Map<String, dynamic>>()
        .map(TaskModel.fromJson)
        .toList(growable: false);
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

  /// Connect to the real-time WebSocket room for a specific task.
  /// Yields parsed event maps (messages, status updates, priority updates).
  Stream<Map<String, dynamic>> connectToTaskChat(int taskId) async* {
    final token = _authService.accessToken ?? '';
    final uri = Uri.parse('${AppConfig.wsBaseUrl}/ws/tasks/$taskId/').replace(
      queryParameters: token.isNotEmpty ? {'token': token} : null,
    );

    WebSocket? socket;
    try {
      socket = await WebSocket.connect(uri.toString());
      socket.pingInterval = const Duration(seconds: 15);
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
      // Connection closed or failed
    } finally {
      await socket?.close();
    }
  }

  /// Connect to the real-time WebSocket feed for technician tasks.
  /// Yields parsed feed event maps (task_created, status_change, etc).
  Stream<Map<String, dynamic>> connectToTechTasks() async* {
    final token = _authService.accessToken ?? '';
    final uri = Uri.parse('${AppConfig.wsBaseUrl}/ws/tech_tasks/').replace(
      queryParameters: token.isNotEmpty ? {'token': token} : null,
    );

    WebSocket? socket;
    try {
      socket = await WebSocket.connect(uri.toString());
      socket.pingInterval = const Duration(seconds: 15);
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
      // Connection closed or failed
    } finally {
      await socket?.close();
    }
  }
}
