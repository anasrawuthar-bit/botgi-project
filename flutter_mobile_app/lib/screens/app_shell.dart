import 'dart:async';
import 'package:flutter/material.dart';

import '../services/auth_service.dart';
import '../services/jobs_service.dart';
import '../services/management_service.dart';
import '../services/notification_service.dart';
import '../services/tasks_service.dart';
import 'dashboard_screen.dart';
import 'jobs_screen.dart';
import 'profile_screen.dart';
import 'task_detail_screen.dart';
import 'tasks_screen.dart';

class AppShell extends StatefulWidget {
  const AppShell({
    super.key,
    required this.authService,
    required this.jobsService,
    required this.managementService,
    required this.tasksService,
    required this.onLogout,
  });

  final AuthService authService;
  final JobsService jobsService;
  final ManagementService managementService;
  final TasksService tasksService;
  final Future<void> Function() onLogout;

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int _currentIndex = 0;
  Timer? _taskPollTimer;
  final Set<int> _knownTaskIds = <int>{};
  int _activeTaskCount = 0;

  @override
  void initState() {
    super.initState();
    _initNotifications();
    _checkNewTasks(initial: true);
    _taskPollTimer = Timer.periodic(
      const Duration(seconds: 25),
      (_) => _checkNewTasks(),
    );
  }

  @override
  void dispose() {
    _taskPollTimer?.cancel();
    super.dispose();
  }

  void _initNotifications() {
    NotificationService.instance.init();
    NotificationService.instance.onNotificationTap = (taskId) {
      if (!mounted) return;
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => TaskDetailScreen(
            taskId: taskId,
            tasksService: widget.tasksService,
            jobsService: widget.jobsService,
          ),
        ),
      );
    };
  }

  Future<void> _checkNewTasks({bool initial = false}) async {
    try {
      final tasks = await widget.tasksService.fetchTasks(
        mineOnly: true,
        status: 'active',
      );

      if (!mounted) return;

      if (initial) {
        _knownTaskIds.clear();
        for (final t in tasks) {
          _knownTaskIds.add(t.id);
        }
        setState(() {
          _activeTaskCount = tasks.length;
        });
      } else {
        final newTasks = tasks.where((t) => !_knownTaskIds.contains(t.id)).toList();
        for (final task in newTasks) {
          _knownTaskIds.add(task.id);
          // 1. Android native push notification
          NotificationService.instance.showTaskNotification(
            taskId: task.id,
            title: task.title,
            priority: task.priorityDisplay,
            description: task.description,
          );

          // 2. In-app interactive SnackBar
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Row(
                  children: [
                    const Icon(Icons.assignment_turned_in, color: Colors.white, size: 20),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'New Task: ${task.title}',
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontWeight: FontWeight.bold),
                      ),
                    ),
                  ],
                ),
                backgroundColor: const Color(0xFF0F172A),
                duration: const Duration(seconds: 6),
                action: SnackBarAction(
                  label: 'OPEN',
                  textColor: const Color(0xFF38BDF8),
                  onPressed: () {
                    Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => TaskDetailScreen(
                          taskId: task.id,
                          tasksService: widget.tasksService,
                          jobsService: widget.jobsService,
                        ),
                      ),
                    );
                  },
                ),
              ),
            );
          }
        }
        if (mounted) {
          setState(() {
            _activeTaskCount = tasks.length;
          });
        }
      }
    } catch (_) {
      // Ignore background poll errors silently
    }
  }

  @override
  Widget build(BuildContext context) {
    final pages = <Widget>[
      DashboardScreen(
        authService: widget.authService,
        jobsService: widget.jobsService,
        managementService: widget.managementService,
        tasksService: widget.tasksService,
        onNavigateToTasks: () {
          setState(() {
            _currentIndex = 2;
          });
        },
      ),
      JobsScreen(
        authService: widget.authService,
        jobsService: widget.jobsService,
      ),
      TasksScreen(
        tasksService: widget.tasksService,
        jobsService: widget.jobsService,
      ),
      ProfileScreen(authService: widget.authService, onLogout: widget.onLogout),
    ];

    return Scaffold(
      body: IndexedStack(index: _currentIndex, children: pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: (index) {
          setState(() {
            _currentIndex = index;
          });
        },
        destinations: [
          const NavigationDestination(
            icon: Icon(Icons.dashboard_outlined),
            selectedIcon: Icon(Icons.dashboard_rounded),
            label: 'Dashboard',
          ),
          const NavigationDestination(
            icon: Icon(Icons.receipt_long_outlined),
            selectedIcon: Icon(Icons.receipt_long),
            label: 'Jobs',
          ),
          NavigationDestination(
            icon: Badge(
              isLabelVisible: _activeTaskCount > 0,
              label: Text('$_activeTaskCount'),
              child: const Icon(Icons.task_alt_outlined),
            ),
            selectedIcon: Badge(
              isLabelVisible: _activeTaskCount > 0,
              label: Text('$_activeTaskCount'),
              child: const Icon(Icons.task_alt_rounded),
            ),
            label: 'Tasks',
          ),
          const NavigationDestination(
            icon: Icon(Icons.person_outline_rounded),
            selectedIcon: Icon(Icons.person_rounded),
            label: 'Profile',
          ),
        ],
      ),
    );
  }
}
