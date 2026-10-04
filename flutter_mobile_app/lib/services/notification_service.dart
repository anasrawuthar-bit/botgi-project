import 'dart:typed_data';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

class NotificationService {
  NotificationService._();
  static final NotificationService instance = NotificationService._();

  final FlutterLocalNotificationsPlugin _notificationsPlugin =
      FlutterLocalNotificationsPlugin();

  bool _initialized = false;
  void Function(int taskId)? onNotificationTap;
  void Function(String jobCode)? onJobNotificationTap;

  Future<void> init() async {
    if (_initialized) return;

    const androidSettings = AndroidInitializationSettings('@mipmap/ic_launcher');
    const initSettings = InitializationSettings(android: androidSettings);

    await _notificationsPlugin.initialize(
      settings: initSettings,
      onDidReceiveNotificationResponse: (response) {
        final payload = response.payload;
        if (payload != null) {
          if (payload.startsWith('job:') && onJobNotificationTap != null) {
            onJobNotificationTap!(payload.substring(4));
          } else if (onNotificationTap != null) {
            final id = int.tryParse(payload);
            if (id != null) {
              onNotificationTap!(id);
            }
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

  Future<void> showAlarmNotification({
    required int taskId,
    required String title,
    required String priority,
    String? description,
    bool isOpenPool = false,
  }) async {
    await init();

    final androidDetails = AndroidNotificationDetails(
      'task_alarms',
      'Task Alarms & Urgent Alerts',
      channelDescription: 'High priority sound & vibration alarm alerts for urgent directives and open pool tasks',
      importance: Importance.max,
      priority: Priority.max,
      enableVibration: true,
      vibrationPattern: Int64List.fromList([0, 1000, 500, 1000, 500, 1000]),
      showWhen: true,
      icon: '@mipmap/ic_launcher',
    );

    final notificationDetails = NotificationDetails(android: androidDetails);

    final cleanDesc = (description ?? '').trim();
    final prefix = isOpenPool ? '🚨 [OPEN POOL ALARM]' : '🚨 [TASK ALARM]';
    final body = cleanDesc.isNotEmpty ? cleanDesc : 'Audible alarm directive requiring immediate attention.';

    await _notificationsPlugin.show(
      id: taskId + 90000,
      title: '$prefix $title',
      body: body,
      notificationDetails: notificationDetails,
      payload: taskId.toString(),
    );
  }

  Future<void> showJobNotification({
    required String jobCode,
    required String customerName,
    required String device,
  }) async {
    await init();

    const androidDetails = AndroidNotificationDetails(
      'job_assignments',
      'Job Assignments',
      channelDescription: 'Notifications when new repair jobs are assigned to you',
      importance: Importance.max,
      priority: Priority.high,
      showWhen: true,
      icon: '@mipmap/ic_launcher',
    );

    const notificationDetails = NotificationDetails(android: androidDetails);

    final cleanDevice = device.trim();
    final cleanCustomer = customerName.trim();
    final body = cleanDevice.isNotEmpty
        ? '$cleanDevice${cleanCustomer.isNotEmpty ? ' • $cleanCustomer' : ''}'
        : cleanCustomer;

    await _notificationsPlugin.show(
      id: jobCode.hashCode,
      title: 'New Job Assigned: $jobCode',
      body: body.isEmpty ? 'A new repair job has been assigned to you.' : body,
      notificationDetails: notificationDetails,
      payload: 'job:$jobCode',
    );
  }
}
