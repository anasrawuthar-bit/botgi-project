import 'dart:async';

import 'package:flutter/material.dart';

import '../models/task_model.dart';
import '../services/jobs_service.dart';
import '../services/notification_service.dart';
import '../services/tasks_service.dart';
import '../theme/app_colors.dart';
import '../widgets/app_surface_card.dart';
import '../widgets/priority_badge.dart';
import 'job_detail_screen.dart';
import 'task_detail_screen.dart';

class TasksScreen extends StatefulWidget {
  const TasksScreen({
    super.key,
    required this.tasksService,
    this.jobsService,
  });

  final TasksService tasksService;
  final JobsService? jobsService;

  @override
  State<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends State<TasksScreen> {
  late Future<TaskListResponse> _tasksFuture;
  final TextEditingController _searchController = TextEditingController();
  StreamSubscription<Map<String, dynamic>>? _feedSubscription;

  String _statusFilter = 'active';
  String _priorityFilter = '';
  bool _mineOnly = false;
  bool _showPool = false;
  TaskMetrics _metrics = TaskMetrics();

  @override
  void initState() {
    super.initState();
    _loadTasks();
    _subscribeToFeed();
  }

  @override
  void dispose() {
    _feedSubscription?.cancel();
    _searchController.dispose();
    super.dispose();
  }

  void _subscribeToFeed() {
    _feedSubscription?.cancel();
    _feedSubscription = widget.tasksService.connectToTechTasks().listen(
      (event) {
        if (!mounted) return;
        final action = event['action'] as String?;
        final title = (event['task_title'] ?? event['title'] ?? 'Task').toString();
        final hasAlarm = event['has_alarm'] == true;
        final isPool = event['is_open_to_all'] == true;

        if (action == 'task_created') {
          if (hasAlarm) {
            NotificationService.instance.showAlarmNotification(
              taskId: event['task_id'] is int ? event['task_id'] : int.tryParse('${event['task_id']}') ?? 0,
              title: title,
              priority: (event['priority_display'] ?? event['priority'] ?? '').toString(),
              description: (event['description'] ?? '').toString(),
              isOpenPool: isPool,
            );
          }

          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Row(
                children: [
                  Icon(
                    hasAlarm ? Icons.alarm_rounded : (isPool ? Icons.groups_rounded : Icons.assignment_ind_rounded),
                    color: Colors.white,
                    size: 20,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      hasAlarm
                          ? '🚨 ALARM: $title'
                          : (isPool ? 'New Open Pool task available: $title' : 'New task assigned: $title'),
                    ),
                  ),
                ],
              ),
              backgroundColor: hasAlarm ? const Color(0xFFDC2626) : (isPool ? const Color(0xFF4F46E5) : const Color(0xFF1565C0)),
              duration: Duration(seconds: hasAlarm ? 8 : 4),
            ),
          );
          _loadTasks();
        } else if (action == 'task_accepted') {
          final techName = (event['assigned_to_name'] ?? 'A technician').toString();
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Task "$title" claimed by $techName.'),
              duration: const Duration(seconds: 3),
            ),
          );
          _loadTasks();
        } else if (action == 'status_change') {
          final newStatus = (event['status_display'] ?? event['new_status'] ?? '').toString();
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Task "$title" status updated: $newStatus'),
              duration: const Duration(seconds: 3),
            ),
          );
          _loadTasks();
        } else if (action == 'new_message') {
          final sender = (event['sender'] ?? 'Staff').toString();
          final preview = (event['preview'] ?? '').toString();
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('$sender on "$title": $preview'),
              duration: const Duration(seconds: 3),
            ),
          );
        }
      },
      onError: (_) {},
    );
  }

  void _loadTasks() {
    setState(() {
      _tasksFuture = widget.tasksService.fetchTasksWithMetrics(
        status: _statusFilter,
        priority: _priorityFilter,
        query: _searchController.text.trim(),
        mineOnly: _mineOnly,
        poolOnly: _showPool,
      ).then((res) {
        if (mounted) {
          setState(() {
            _metrics = res.metrics;
          });
        }
        return res;
      });
    });
  }

  Future<void> _acceptTask(TaskModel task) async {
    try {
      final updated = await widget.tasksService.acceptTask(task.id);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Claimed task: "${updated.title}" successfully!'),
          backgroundColor: const Color(0xFF16A34A),
        ),
      );
      _loadTasks();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Failed to claim task: ${TasksService.formatError(e)}'),
          backgroundColor: Colors.red,
        ),
      );
    }
  }

  Future<void> _updateStatus(TaskModel task, String newStatus) async {
    try {
      await widget.tasksService.updateTaskStatus(task.id, newStatus);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Task moved to ${_statusLabel(newStatus)}'),
          duration: const Duration(seconds: 2),
        ),
      );
      _loadTasks();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: AppColors.warningFg,
          content: Text(TasksService.formatError(e)),
        ),
      );
    }
  }

  String _statusLabel(String status) {
    switch (status) {
      case 'in_progress':
        return 'In Progress';
      case 'done':
        return 'Done';
      case 'cancelled':
        return 'Cancelled';
      default:
        return 'Open';
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Directives & Tasks', style: TextStyle(fontWeight: FontWeight.w700)),
        actions: [
          PopupMenuButton<String>(
            icon: Icon(
              Icons.filter_list_rounded,
              color: _priorityFilter.isNotEmpty ? Theme.of(context).colorScheme.primary : null,
            ),
            tooltip: 'Filter by Priority',
            initialValue: _priorityFilter,
            onSelected: (value) {
              setState(() {
                _priorityFilter = value;
              });
              _loadTasks();
            },
            itemBuilder: (context) => [
              const PopupMenuItem(value: '', child: Text('All Priorities')),
              const PopupMenuItem(value: 'urgent', child: Text('⚡ Urgent')),
              const PopupMenuItem(value: 'high', child: Text('↑ High')),
              const PopupMenuItem(value: 'medium', child: Text('● Medium')),
              const PopupMenuItem(value: 'low', child: Text('↓ Low')),
            ],
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'Refresh',
            onPressed: _loadTasks,
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            // KPI Summary Counters Bar
            _buildKpiMetricsBar(),

            // My Tasks vs Team Segmented Switcher & Search
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
              child: Row(
                children: [
                  Expanded(
                    child: SegmentedButton<bool>(
                      segments: const [
                        ButtonSegment(value: false, label: Text('All Tasks'), icon: Icon(Icons.groups_outlined, size: 18)),
                        ButtonSegment(value: true, label: Text('My Tasks'), icon: Icon(Icons.person_outline, size: 18)),
                      ],
                      selected: {_mineOnly},
                      onSelectionChanged: (set) {
                        setState(() {
                          _mineOnly = set.first;
                        });
                        _loadTasks();
                      },
                      style: const ButtonStyle(
                        visualDensity: VisualDensity.compact,
                        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      ),
                    ),
                  ),
                ],
              ),
            ),

            // Search Bar
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 6, 16, 6),
              child: TextField(
                controller: _searchController,
                decoration: InputDecoration(
                  hintText: 'Search tasks by title, job or device...',
                  prefixIcon: const Icon(Icons.search, size: 20),
                  suffixIcon: _searchController.text.isNotEmpty
                      ? IconButton(
                          icon: const Icon(Icons.clear, size: 18),
                          onPressed: () {
                            _searchController.clear();
                            _loadTasks();
                          },
                        )
                      : null,
                  filled: true,
                  fillColor: Colors.grey.shade100,
                  contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 0),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                    borderSide: BorderSide.none,
                  ),
                ),
                onSubmitted: (_) => _loadTasks(),
              ),
            ),


            // Task List
            Expanded(
              child: FutureBuilder<TaskListResponse>(
                future: _tasksFuture,
                builder: (context, snapshot) {
                  if (snapshot.connectionState == ConnectionState.waiting) {
                    return const Center(child: CircularProgressIndicator());
                  }

                  if (snapshot.hasError) {
                    return Center(
                      child: Padding(
                        padding: const EdgeInsets.all(24),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(Icons.error_outline, size: 48, color: AppColors.warningFg),
                            const SizedBox(height: 12),
                            Text(
                              TasksService.formatError(snapshot.error!),
                              textAlign: TextAlign.center,
                              style: const TextStyle(color: AppColors.warningFg),
                            ),
                            const SizedBox(height: 12),
                            FilledButton.tonal(
                              onPressed: _loadTasks,
                              child: const Text('Retry'),
                            ),
                          ],
                        ),
                      ),
                    );
                  }

                  final tasks = snapshot.data?.tasks ?? [];
                  if (tasks.isEmpty) {
                    return RefreshIndicator(
                      onRefresh: () async => _loadTasks(),
                      child: ListView(
                        physics: const AlwaysScrollableScrollPhysics(),
                        children: [
                          const SizedBox(height: 80),
                          Center(
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Icon(Icons.task_alt_rounded, size: 64, color: Colors.grey.shade400),
                                const SizedBox(height: 16),
                                Text(
                                  _mineOnly ? 'No tasks assigned to you.' : 'No tasks match your filter.',
                                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: Colors.grey.shade600),
                                ),
                                const SizedBox(height: 8),
                                Text(
                                  'Tap "+ New Directive" below to create one.',
                                  style: TextStyle(fontSize: 13, color: Colors.grey.shade500),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    );
                  }

                  return RefreshIndicator(
                    onRefresh: () async => _loadTasks(),
                    child: ListView.separated(
                      padding: const EdgeInsets.fromLTRB(16, 6, 16, 80),
                      itemCount: tasks.length,
                      separatorBuilder: (context, index) => const SizedBox(height: 10),
                      itemBuilder: (context, index) {
                        final task = tasks[index];
                        return _buildTaskCard(task);
                      },
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildKpiMetricsBar() {
    return Container(
      margin: const EdgeInsets.fromLTRB(16, 4, 16, 4),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.grey.shade200),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.03),
            blurRadius: 6,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Row(
        children: [
          Expanded(
            child: _kpiItem(
              label: 'Urgent',
              count: _metrics.urgent,
              icon: Icons.bolt_rounded,
              color: const Color(0xFFDC2626),
              bgColor: const Color(0xFFFEF2F2),
              onTap: () {
                setState(() {
                  _priorityFilter = _priorityFilter == 'urgent' ? '' : 'urgent';
                });
                _loadTasks();
              },
              isActive: _priorityFilter == 'urgent',
            ),
          ),
          Container(width: 1, height: 32, color: Colors.grey.shade200),
          Expanded(
            child: _kpiItem(
              label: 'In Progress',
              count: _metrics.inProgress,
              icon: Icons.timelapse_rounded,
              color: const Color(0xFFD97706),
              bgColor: const Color(0xFFFFFBEB),
              onTap: () {
                setState(() {
                  _statusFilter = _statusFilter == 'in_progress' ? 'active' : 'in_progress';
                });
                _loadTasks();
              },
              isActive: _statusFilter == 'in_progress',
            ),
          ),
          Container(width: 1, height: 32, color: Colors.grey.shade200),
          Expanded(
            child: _kpiItem(
              label: 'Open',
              count: _metrics.open,
              icon: Icons.pending_actions_rounded,
              color: const Color(0xFF2563EB),
              bgColor: const Color(0xFFEFF6FF),
              onTap: () {
                setState(() {
                  _statusFilter = _statusFilter == 'open' ? 'active' : 'open';
                });
                _loadTasks();
              },
              isActive: _statusFilter == 'open',
            ),
          ),
          Container(width: 1, height: 32, color: Colors.grey.shade200),
          Expanded(
            child: _kpiItem(
              label: 'Done',
              count: _metrics.done,
              icon: Icons.check_circle_outline_rounded,
              color: const Color(0xFF16A34A),
              bgColor: const Color(0xFFF0FDF4),
              onTap: () {
                setState(() {
                  _statusFilter = _statusFilter == 'done' ? 'active' : 'done';
                });
                _loadTasks();
              },
              isActive: _statusFilter == 'done',
            ),
          ),
          Container(width: 1, height: 32, color: Colors.grey.shade200),
          Expanded(
            child: _kpiItem(
              label: 'Pool',
              count: _metrics.pool,
              icon: Icons.groups_rounded,
              color: const Color(0xFF4F46E5),
              bgColor: const Color(0xFFEEF2FF),
              onTap: () {
                setState(() {
                  _showPool = !_showPool;
                });
                _loadTasks();
              },
              isActive: _showPool,
            ),
          ),
        ],
      ),
    );
  }

  Widget _kpiItem({
    required String label,
    required int count,
    required IconData icon,
    required Color color,
    required Color bgColor,
    required VoidCallback onTap,
    required bool isActive,
  }) {
    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 2),
        decoration: BoxDecoration(
          color: isActive ? bgColor : Colors.transparent,
          borderRadius: BorderRadius.circular(8),
          border: isActive ? Border.all(color: color.withValues(alpha: 0.5), width: 1.5) : null,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(icon, size: 14, color: color),
                const SizedBox(width: 3),
                Text(
                  '$count',
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w800,
                    color: color,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 1),
            Text(
              label,
              style: TextStyle(
                fontSize: 11,
                fontWeight: isActive ? FontWeight.w700 : FontWeight.w500,
                color: Colors.grey.shade700,
              ),
            ),
          ],
        ),
      ),
    );
  }


  Widget _buildTaskCard(TaskModel task) {
    Color leftBorderColor;
    switch (task.priority) {
      case 'urgent':
        leftBorderColor = const Color(0xFFDC2626);
        break;
      case 'high':
        leftBorderColor = const Color(0xFFEA580C);
        break;
      case 'low':
        leftBorderColor = Colors.grey.shade400;
        break;
      default:
        leftBorderColor = const Color(0xFF2563EB);
    }

    return AppSurfaceCard(
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () async {
          await Navigator.of(context).push(
            MaterialPageRoute(
              builder: (_) => TaskDetailScreen(
                taskId: task.id,
                tasksService: widget.tasksService,
                jobsService: widget.jobsService,
              ),
            ),
          );
          _loadTasks();
        },
        child: Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border(left: BorderSide(color: leftBorderColor, width: 4.5)),
          ),
          padding: const EdgeInsets.all(13),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Header: Priority + Overdue / Due Date
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Row(
                    children: [
                      PriorityBadge(
                        priority: task.priority,
                        label: task.priorityDisplay,
                      ),
                      if (task.hasAlarm) ...[
                        const SizedBox(width: 5),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
                          decoration: BoxDecoration(
                            color: const Color(0xFFFEF2F2),
                            borderRadius: BorderRadius.circular(4),
                            border: Border.all(color: const Color(0xFFEF4444), width: 0.8),
                          ),
                          child: const Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(Icons.alarm_rounded, size: 10, color: Color(0xFFDC2626)),
                              SizedBox(width: 2),
                              Text(
                                'ALARM',
                                style: TextStyle(
                                  fontSize: 9.5,
                                  fontWeight: FontWeight.w800,
                                  color: Color(0xFFDC2626),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                      if (task.isOpenToAll) ...[
                        const SizedBox(width: 5),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
                          decoration: BoxDecoration(
                            color: const Color(0xFFEEF2FF),
                            borderRadius: BorderRadius.circular(4),
                            border: Border.all(color: const Color(0xFF6366F1), width: 0.8),
                          ),
                          child: const Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(Icons.groups_rounded, size: 10, color: Color(0xFF4F46E5)),
                              SizedBox(width: 2),
                              Text(
                                'POOL',
                                style: TextStyle(
                                  fontSize: 9.5,
                                  fontWeight: FontWeight.w800,
                                  color: Color(0xFF4F46E5),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                      if (task.isOverdue) ...[
                        const SizedBox(width: 5),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(
                            color: const Color(0xFFFEF2F2),
                            borderRadius: BorderRadius.circular(4),
                            border: Border.all(color: const Color(0xFFDC2626), width: 0.8),
                          ),
                          child: const Text(
                            'OVERDUE',
                            style: TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.w800,
                              color: Color(0xFFDC2626),
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                  if (task.dueDate.isNotEmpty)
                    Row(
                      children: [
                        Icon(
                          Icons.schedule_rounded,
                          size: 13,
                          color: task.isOverdue ? const Color(0xFFDC2626) : Colors.blueGrey,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          task.dueDate,
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                            color: task.isOverdue ? const Color(0xFFDC2626) : Colors.blueGrey.shade700,
                          ),
                        ),
                      ],
                    ),
                ],
              ),

              const SizedBox(height: 7),

              // Title
              Text(
                task.title,
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                ),
              ),

              if (task.description.isNotEmpty) ...[
                const SizedBox(height: 3),
                Text(
                  task.description,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 12.5,
                    color: Colors.grey.shade700,
                  ),
                ),
              ],

              // Linked Job Ticket Badge (Clickable!)
              if (task.jobReference != null) ...[
                const SizedBox(height: 7),
                InkWell(
                  borderRadius: BorderRadius.circular(6),
                  onTap: () {
                    if (widget.jobsService != null) {
                      Navigator.of(context).push(
                        MaterialPageRoute(
                          builder: (_) => JobDetailScreen(
                            jobCode: task.jobReference!.jobCode,
                            jobsService: widget.jobsService!,
                          ),
                        ),
                      );
                    }
                  },
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: const Color(0xFFEEF2FF),
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(color: const Color(0xFFC7D2FE)),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.build_circle_outlined, size: 14, color: Color(0xFF4338CA)),
                        const SizedBox(width: 4),
                        Text(
                          'Job ${task.jobReference!.jobCode} • ${task.jobReference!.device}',
                          style: const TextStyle(
                            fontSize: 11.5,
                            fontWeight: FontWeight.w600,
                            color: Color(0xFF3730A3),
                          ),
                        ),
                        const SizedBox(width: 4),
                        const Icon(Icons.open_in_new_rounded, size: 12, color: Color(0xFF6366F1)),
                      ],
                    ),
                  ),
                ),
              ],

              const SizedBox(height: 9),

              // Footer: Status + Assignee + Messages count + Quick action button
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Row(
                    children: [
                      _statusChip(task.status, task.statusDisplay),
                      const SizedBox(width: 8),
                      // Assignee tag
                      if (task.assignedTo.isNotEmpty) ...[
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(
                            color: Colors.grey.shade100,
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(Icons.person_outline, size: 12, color: Colors.grey.shade700),
                              const SizedBox(width: 3),
                              Text(
                                task.assignedToName.isNotEmpty ? task.assignedToName : task.assignedTo,
                                style: TextStyle(fontSize: 11, color: Colors.grey.shade800, fontWeight: FontWeight.w500),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(width: 6),
                      ],
                      if (task.messagesCount > 0) ...[
                        const Icon(Icons.chat_bubble_outline_rounded, size: 13, color: Colors.blueGrey),
                        const SizedBox(width: 2),
                        Text(
                          '${task.messagesCount}',
                          style: const TextStyle(fontSize: 11, color: Colors.blueGrey, fontWeight: FontWeight.w600),
                        ),
                      ],
                    ],
                  ),

                  // Quick Action Button
                  if (task.canAccept)
                    FilledButton(
                      style: FilledButton.styleFrom(
                        backgroundColor: const Color(0xFF4F46E5),
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 2),
                        visualDensity: VisualDensity.compact,
                      ),
                      onPressed: () => _acceptTask(task),
                      child: const Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.assignment_turned_in_rounded, size: 15),
                          SizedBox(width: 3),
                          Text('Claim Task', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700)),
                        ],
                      ),
                    )
                  else if (task.status == 'open')
                    FilledButton.tonal(
                      style: FilledButton.styleFrom(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 2),
                        visualDensity: VisualDensity.compact,
                      ),
                      onPressed: () => _updateStatus(task, 'in_progress'),
                      child: const Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.play_arrow_rounded, size: 16),
                          SizedBox(width: 2),
                          Text('Start', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
                        ],
                      ),
                    )
                  else if (task.status == 'in_progress')
                    FilledButton(
                      style: FilledButton.styleFrom(
                        backgroundColor: const Color(0xFF16A34A),
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 2),
                        visualDensity: VisualDensity.compact,
                      ),
                      onPressed: () => _updateStatus(task, 'done'),
                      child: const Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.check_rounded, size: 16),
                          SizedBox(width: 2),
                          Text('Complete', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
                        ],
                      ),
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _statusChip(String status, String display) {
    Color bg;
    Color fg;
    switch (status) {
      case 'in_progress':
        bg = const Color(0xFFFFFBEB);
        fg = const Color(0xFFD97706);
        break;
      case 'done':
        bg = const Color(0xFFF0FDF4);
        fg = const Color(0xFF16A34A);
        break;
      case 'cancelled':
        bg = const Color(0xFFF1F5F9);
        fg = const Color(0xFF64748B);
        break;
      default:
        bg = const Color(0xFFEFF6FF);
        fg = const Color(0xFF2563EB);
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2.5),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        display,
        style: TextStyle(
          color: fg,
          fontSize: 10.5,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

