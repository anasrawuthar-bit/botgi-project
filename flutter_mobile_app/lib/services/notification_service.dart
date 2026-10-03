import 'package:flutter_local_notifications/flutter_local_notifications.dart';

class NotificationService {
  NotificationService._();
  static final NotificationService instance = NotificationService._();

  final FlutterLocalNotificationsPlugin _notificationsPlugin =
      FlutterLocalNotificationsPlugin();

  bool _initialized = false;
  void Function(int taskId)? onNotificationTap;

  Future<void> init() async {
    if (_initialized) return;

    const androidSettings = AndroidInitializationSettings('@mipmap/ic_launcher');
    const initSettings = InitializationSettings(android: androidSettings);

    await _notificationsPlugin.initialize(
      settings: initSettings,
      onDidReceiveNotificationResponse: (response) {
        final payload = response.payload;
        if (payload != null && onNotificationTap != null) {
          final id = int.tryParse(payload);
          if (id != null) {
            onNotificationTap!(id);
          }
        }
      },
    );

    // Request Android 13+ notification permissions
    final androidPlugin = _notificationsPlugin.resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin>();
    if (androidPlugin != null) {
      await androidPlugin.requestNotificationsPermission();
    }

    _initialized = true;
  }

  Future<void> showTaskNotification({
    required int taskId,
    required String title,
    required String priority,
    String? description,
  }) async {
    await init();

    const androidDetails = AndroidNotificationDetails(
      'task_assignments',
      'Task Assignments',
      channelDescription: 'Notifications when tasks are assigned to you',
      importance: Importance.max,
      priority: Priority.high,
      showWhen: true,
      icon: '@mipmap/ic_launcher',
    );

    const notificationDetails = NotificationDetails(android: androidDetails);

    final cleanDesc = (description ?? '').trim();
    final body = priority.isNotEmpty
        ? 'Priority: $priority${cleanDesc.isNotEmpty ? ' • $cleanDesc' : ''}'
        : cleanDesc;

    await _notificationsPlugin.show(
      id: taskId,
      title: 'New Task Assigned: $title',
      body: body.isEmpty ? 'You have a new task assigned.' : body,
      notificationDetails: notificationDetails,
      payload: taskId.toString(),
    );
  }
}
