import 'dart:async';

import 'package:flutter/material.dart';

import '../models/task_model.dart';
import '../services/tasks_service.dart';
import '../theme/app_colors.dart';
import '../widgets/app_surface_card.dart';
import '../widgets/priority_badge.dart';
import 'task_detail_screen.dart';

class TasksScreen extends StatefulWidget {
  const TasksScreen({
    super.key,
    required this.tasksService,
  });

  final TasksService tasksService;

  @override
  State<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends State<TasksScreen> {
  late Future<List<TaskModel>> _tasksFuture;
  final TextEditingController _searchController = TextEditingController();
  StreamSubscription<Map<String, dynamic>>? _feedSubscription;
  String _statusFilter = 'active';
  String _priorityFilter = '';

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
        final title = (event['task_title'] ?? 'Task').toString();

        if (action == 'task_created') {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Row(
                children: [
                  const Icon(Icons.assignment_ind_rounded, color: Colors.white, size: 20),
                  const SizedBox(width: 8),
                  Expanded(child: Text('New task assigned: $title')),
                ],
              ),
              backgroundColor: const Color(0xFF1565C0),
              duration: const Duration(seconds: 4),
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
      _tasksFuture = widget.tasksService.fetchTasks(
        status: _statusFilter,
        priority: _priorityFilter,
        query: _searchController.text.trim(),
      );
    });
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
          content: Text(e.toString().replaceFirst('Exception: ', '')),
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
        title: const Text('Directives & Tasks'),
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
            // Search Bar
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
              child: TextField(
                controller: _searchController,
                decoration: InputDecoration(
                  hintText: 'Search tasks by title or job...',
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: _searchController.text.isNotEmpty
                      ? IconButton(
                          icon: const Icon(Icons.clear),
                          onPressed: () {
                            _searchController.clear();
                            _loadTasks();
                          },
                        )
                      : null,
                  filled: true,
                  fillColor: Colors.grey.shade100,
                  contentPadding: const EdgeInsets.symmetric(horizontal: 16),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide.none,
                  ),
                ),
                onSubmitted: (_) => _loadTasks(),
              ),
            ),

            // Status Filter Chips
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
              child: Row(
                children: [
                  _filterChip('active', 'Active'),
                  const SizedBox(width: 8),
                  _filterChip('open', 'Open'),
                  const SizedBox(width: 8),
                  _filterChip('in_progress', 'In Progress'),
                  const SizedBox(width: 8),
                  _filterChip('done', 'Done'),
                  const SizedBox(width: 8),
                  _filterChip('all', 'All'),
                ],
              ),
            ),

            const SizedBox(height: 8),

            // Task List
            Expanded(
              child: FutureBuilder<List<TaskModel>>(
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
                              snapshot.error.toString().replaceFirst('Exception: ', ''),
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

                  final tasks = snapshot.data ?? [];
                  if (tasks.isEmpty) {
                    return RefreshIndicator(
                      onRefresh: () async => _loadTasks(),
                      child: ListView(
                        physics: const AlwaysScrollableScrollPhysics(),
                        children: const [
                          SizedBox(height: 120),
                          Center(
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Icon(Icons.task_alt_rounded, size: 64, color: Colors.grey),
                                SizedBox(height: 16),
                                Text(
                                  'No tasks found.',
                                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: Colors.grey),
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
                      padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                      itemCount: tasks.length,
                      separatorBuilder: (_, index) => const SizedBox(height: 10),
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

  Widget _filterChip(String key, String label) {
    final isSelected = _statusFilter == key;
    return FilterChip(
      label: Text(label),
      selected: isSelected,
      onSelected: (selected) {
        if (selected) {
          setState(() {
            _statusFilter = key;
          });
          _loadTasks();
        }
      },
      selectedColor: Theme.of(context).colorScheme.primaryContainer,
      labelStyle: TextStyle(
        fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
        color: isSelected
            ? Theme.of(context).colorScheme.onPrimaryContainer
            : Theme.of(context).colorScheme.onSurface,
      ),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
    );
  }

  Widget _buildTaskCard(TaskModel task) {
    final isUrgent = task.priority == 'urgent';

    return AppSurfaceCard(
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () async {
          await Navigator.of(context).push(
            MaterialPageRoute(
              builder: (_) => TaskDetailScreen(
                taskId: task.id,
                tasksService: widget.tasksService,
              ),
            ),
          );
          _loadTasks();
        },
        child: Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: isUrgent
                ? Border(left: BorderSide(color: Colors.red.shade600, width: 4))
                : null,
          ),
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Header: Priority + Due Date
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  PriorityBadge(
                    priority: task.priority,
                    label: task.priorityDisplay,
                  ),
                  if (task.dueDate.isNotEmpty)
                    Row(
                      children: [
                        Icon(Icons.schedule, size: 13, color: isUrgent ? Colors.red.shade700 : Colors.blueGrey),
                        const SizedBox(width: 4),
                        Text(
                          task.dueDate,
                          style: TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                            color: isUrgent ? Colors.red.shade700 : Colors.blueGrey,
                          ),
                        ),
                      ],
                    ),
                ],
              ),

              const SizedBox(height: 8),

              // Title
              Text(
                task.title,
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                ),
              ),

              if (task.description.isNotEmpty) ...[
                const SizedBox(height: 4),
                Text(
                  task.description,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 13,
                    color: Colors.grey.shade700,
                  ),
                ),
              ],

              if (task.jobReference != null) ...[
                const SizedBox(height: 8),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: Colors.grey.shade100,
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: Colors.grey.shade300),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.build_circle_outlined, size: 14, color: Colors.indigo),
                      const SizedBox(width: 4),
                      Text(
                        'Job ${task.jobReference!.jobCode} • ${task.jobReference!.device}',
                        style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
                      ),
                    ],
                  ),
                ),
              ],

              const SizedBox(height: 10),

              // Footer: Status + Message/Attachment counts + Quick action
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Row(
                    children: [
                      _statusChip(task.status, task.statusDisplay),
                      const SizedBox(width: 8),
                      if (task.attachmentsCount > 0) ...[
                        const Icon(Icons.attach_file, size: 14, color: Colors.blueGrey),
                        Text(
                          '${task.attachmentsCount}',
                          style: const TextStyle(fontSize: 12, color: Colors.blueGrey),
                        ),
                        const SizedBox(width: 6),
                      ],
                      if (task.messagesCount > 0) ...[
                        const Icon(Icons.chat_bubble_outline, size: 13, color: Colors.blueGrey),
                        const SizedBox(width: 2),
                        Text(
                          '${task.messagesCount}',
                          style: const TextStyle(fontSize: 12, color: Colors.blueGrey),
                        ),
                      ],
                    ],
                  ),

                  // Quick Action Button
                  if (task.status == 'open')
                    FilledButton.tonal(
                      style: FilledButton.styleFrom(
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                        visualDensity: VisualDensity.compact,
                      ),
                      onPressed: () => _updateStatus(task, 'in_progress'),
                      child: const Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.play_arrow_rounded, size: 16),
                          SizedBox(width: 2),
                          Text('Start', style: TextStyle(fontSize: 12)),
                        ],
                      ),
                    )
                  else if (task.status == 'in_progress')
                    FilledButton(
                      style: FilledButton.styleFrom(
                        backgroundColor: Colors.teal.shade700,
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                        visualDensity: VisualDensity.compact,
                      ),
                      onPressed: () => _updateStatus(task, 'done'),
                      child: const Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.check_rounded, size: 16),
                          SizedBox(width: 2),
                          Text('Complete', style: TextStyle(fontSize: 12)),
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
        bg = const Color(0xFFFFF8E1);
        fg = const Color(0xFFF57F17);
        break;
      case 'done':
        bg = const Color(0xFFE8F5E9);
        fg = const Color(0xFF2E7D32);
        break;
      case 'cancelled':
        bg = const Color(0xFFECEFF1);
        fg = const Color(0xFF546E7A);
        break;
      default:
        bg = const Color(0xFFE3F2FD);
        fg = const Color(0xFF1565C0);
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        display,
        style: TextStyle(
          color: fg,
          fontSize: 11,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}
