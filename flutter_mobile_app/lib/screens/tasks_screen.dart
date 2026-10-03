import 'dart:async';

import 'package:flutter/material.dart';

import '../models/task_model.dart';
import '../services/jobs_service.dart';
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
      _tasksFuture = widget.tasksService.fetchTasksWithMetrics(
        status: _statusFilter,
        priority: _priorityFilter,
        query: _searchController.text.trim(),
        mineOnly: _mineOnly,
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

  void _openCreateTaskModal() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => _CreateTaskSheet(
        tasksService: widget.tasksService,
        onCreated: () {
          _loadTasks();
        },
      ),
    );
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
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _openCreateTaskModal,
        icon: const Icon(Icons.add_task_rounded),
        label: const Text('New Directive'),
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

            // Status Filter Chips
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 2),
              child: Row(
                children: [
                  _filterChip('active', 'Active'),
                  const SizedBox(width: 6),
                  _filterChip('open', 'Open'),
                  const SizedBox(width: 6),
                  _filterChip('in_progress', 'In Progress'),
                  const SizedBox(width: 6),
                  _filterChip('done', 'Done'),
                  const SizedBox(width: 6),
                  _filterChip('all', 'All'),
                ],
              ),
            ),

            const SizedBox(height: 4),

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
        fontSize: 12,
        fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
        color: isSelected
            ? Theme.of(context).colorScheme.onPrimaryContainer
            : Theme.of(context).colorScheme.onSurface,
      ),
      visualDensity: VisualDensity.compact,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
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
                      if (task.isOverdue) ...[
                        const SizedBox(width: 6),
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
                  if (task.status == 'open')
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

class _CreateTaskSheet extends StatefulWidget {
  const _CreateTaskSheet({
    required this.tasksService,
    required this.onCreated,
  });

  final TasksService tasksService;
  final VoidCallback onCreated;

  @override
  State<_CreateTaskSheet> createState() => _CreateTaskSheetState();
}

class _CreateTaskSheetState extends State<_CreateTaskSheet> {
  final _formKey = GlobalKey<FormState>();
  final _titleController = TextEditingController();
  final _descController = TextEditingController();
  final _initialMsgController = TextEditingController();

  String _priority = 'medium';
  DateTime? _dueDate;
  TimeOfDay? _dueTime;

  bool _assignToMe = false;
  int? _selectedTechId;
  List<TechnicianItem> _technicians = [];

  QuickJobItem? _selectedJob;
  List<QuickJobItem> _jobs = [];

  bool _isLoadingLookups = true;
  bool _isSubmitting = false;

  @override
  void initState() {
    super.initState();
    _loadLookups();
  }

  @override
  void dispose() {
    _titleController.dispose();
    _descController.dispose();
    _initialMsgController.dispose();
    super.dispose();
  }

  Future<void> _loadLookups() async {
    try {
      final techs = await widget.tasksService.fetchTechnicians();
      final jobs = await widget.tasksService.fetchQuickJobs();
      if (!mounted) return;
      setState(() {
        _technicians = techs;
        _jobs = jobs;
        _isLoadingLookups = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _isLoadingLookups = false;
      });
    }
  }

  Future<void> _pickDueDate() async {
    final now = DateTime.now();
    final pickedDate = await showDatePicker(
      context: context,
      initialDate: _dueDate ?? now,
      firstDate: now.subtract(const Duration(days: 1)),
      lastDate: now.add(const Duration(days: 365)),
    );
    if (pickedDate == null || !mounted) return;

    final pickedTime = await showTimePicker(
      context: context,
      initialTime: _dueTime ?? const TimeOfDay(hour: 18, minute: 0),
    );
    if (!mounted) return;

    setState(() {
      _dueDate = pickedDate;
      _dueTime = pickedTime ?? const TimeOfDay(hour: 18, minute: 0);
    });
  }

  void _quickSetDueToday() {
    final now = DateTime.now();
    setState(() {
      _dueDate = DateTime(now.year, now.month, now.day);
      _dueTime = const TimeOfDay(hour: 18, minute: 0);
    });
  }

  void _quickSetDueTomorrow() {
    final tomorrow = DateTime.now().add(const Duration(days: 1));
    setState(() {
      _dueDate = DateTime(tomorrow.year, tomorrow.month, tomorrow.day);
      _dueTime = const TimeOfDay(hour: 18, minute: 0);
    });
  }

  String _formatPickedDue() {
    if (_dueDate == null) return 'No Due Date';
    final d = _dueDate!;
    final timeStr = _dueTime != null
        ? ' ${_dueTime!.hour.toString().padLeft(2, '0')}:${_dueTime!.minute.toString().padLeft(2, '0')}'
        : '';
    return '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}$timeStr';
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _isSubmitting = true;
    });

    try {
      final dueDateStr = _dueDate != null ? _formatPickedDue() : null;

      await widget.tasksService.createTask(
        title: _titleController.text.trim(),
        description: _descController.text.trim(),
        priority: _priority,
        dueDate: dueDateStr,
        assignedToId: _assignToMe ? null : _selectedTechId,
        assignToMe: _assignToMe,
        jobReferenceId: _selectedJob?.id,
        initialMessage: _initialMsgController.text.trim(),
      );

      if (!mounted) return;
      Navigator.of(context).pop();
      widget.onCreated();
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Task / Directive created successfully!'),
          backgroundColor: Color(0xFF16A34A),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(e.toString().replaceFirst('Exception: ', '')),
          backgroundColor: AppColors.warningFg,
        ),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isSubmitting = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      height: MediaQuery.of(context).size.height * 0.88,
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      child: Column(
        children: [
          // Header Bar
          Container(
            padding: const EdgeInsets.fromLTRB(20, 16, 16, 12),
            decoration: BoxDecoration(
              border: Border(bottom: BorderSide(color: Colors.grey.shade200)),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Row(
                  children: [
                    Icon(Icons.add_task_rounded, color: Color(0xFF2563EB)),
                    SizedBox(width: 8),
                    Text(
                      'New Directive / Task',
                      style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
                    ),
                  ],
                ),
                IconButton(
                  icon: const Icon(Icons.close),
                  onPressed: () => Navigator.of(context).pop(),
                ),
              ],
            ),
          ),

          // Form Body
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(20),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Title Field
                    const Text('Title *', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                    const SizedBox(height: 6),
                    TextFormField(
                      controller: _titleController,
                      decoration: InputDecoration(
                        hintText: 'e.g., Replace LCD screen on Dell Inspiron',
                        filled: true,
                        fillColor: Colors.grey.shade50,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(10),
                          borderSide: BorderSide(color: Colors.grey.shade300),
                        ),
                      ),
                      validator: (val) {
                        if (val == null || val.trim().isEmpty) {
                          return 'Please enter a title.';
                        }
                        return null;
                      },
                    ),

                    const SizedBox(height: 16),

                    // Priority Selector
                    const Text('Priority Level', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        _priorityChoice('urgent', '⚡ Urgent', const Color(0xFFDC2626)),
                        const SizedBox(width: 8),
                        _priorityChoice('high', '↑ High', const Color(0xFFEA580C)),
                        const SizedBox(width: 8),
                        _priorityChoice('medium', '● Medium', const Color(0xFF2563EB)),
                        const SizedBox(width: 8),
                        _priorityChoice('low', '↓ Low', Colors.grey.shade600),
                      ],
                    ),

                    const SizedBox(height: 16),

                    // Due Date
                    const Text('Due Date & Time', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton.icon(
                            style: OutlinedButton.styleFrom(
                              alignment: Alignment.centerLeft,
                              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                            ),
                            onPressed: _pickDueDate,
                            icon: const Icon(Icons.calendar_today_rounded, size: 16),
                            label: Text(_formatPickedDue(), style: const TextStyle(fontSize: 13)),
                          ),
                        ),
                        if (_dueDate != null) ...[
                          const SizedBox(width: 6),
                          IconButton(
                            icon: const Icon(Icons.clear, size: 18),
                            onPressed: () {
                              setState(() {
                                _dueDate = null;
                                _dueTime = null;
                              });
                            },
                          ),
                        ],
                      ],
                    ),
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        ActionChip(
                          label: const Text('Today (6 PM)', style: TextStyle(fontSize: 11)),
                          onPressed: _quickSetDueToday,
                          visualDensity: VisualDensity.compact,
                        ),
                        const SizedBox(width: 8),
                        ActionChip(
                          label: const Text('Tomorrow (6 PM)', style: TextStyle(fontSize: 11)),
                          onPressed: _quickSetDueTomorrow,
                          visualDensity: VisualDensity.compact,
                        ),
                      ],
                    ),

                    const SizedBox(height: 16),

                    // Assigned Technician
                    const Text('Assign To', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                    const SizedBox(height: 6),
                    SwitchListTile(
                      contentPadding: EdgeInsets.zero,
                      title: const Text('Assign to Myself', style: TextStyle(fontSize: 14)),
                      value: _assignToMe,
                      onChanged: (val) {
                        setState(() {
                          _assignToMe = val;
                          if (val) _selectedTechId = null;
                        });
                      },
                    ),
                    if (!_assignToMe) ...[
                      DropdownButtonFormField<int>(
                        initialValue: _selectedTechId,
                        decoration: InputDecoration(
                          hintText: _isLoadingLookups ? 'Loading technicians...' : 'Select Technician (or unassigned)',
                          filled: true,
                          fillColor: Colors.grey.shade50,
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(10),
                            borderSide: BorderSide(color: Colors.grey.shade300),
                          ),
                        ),
                        items: [
                          const DropdownMenuItem<int>(
                            value: null,
                            child: Text('Unassigned (Pool)'),
                          ),
                          ..._technicians.map((t) => DropdownMenuItem<int>(
                                value: t.id,
                                child: Text('${t.name} (${t.username})'),
                              )),
                        ],
                        onChanged: (val) {
                          setState(() {
                            _selectedTechId = val;
                          });
                        },
                      ),
                    ],

                    const SizedBox(height: 16),

                    // Link to Job Ticket
                    const Text('Link to Job Ticket (Optional)', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                    const SizedBox(height: 6),
                    DropdownButtonFormField<QuickJobItem>(
                      initialValue: _selectedJob,
                      isExpanded: true,
                      decoration: InputDecoration(
                        hintText: _isLoadingLookups ? 'Loading active jobs...' : 'Select related Job Ticket',
                        filled: true,
                        fillColor: Colors.grey.shade50,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(10),
                          borderSide: BorderSide(color: Colors.grey.shade300),
                        ),
                      ),
                      items: [
                        const DropdownMenuItem<QuickJobItem>(
                          value: null,
                          child: Text('None (General Task)'),
                        ),
                        ..._jobs.map((j) => DropdownMenuItem<QuickJobItem>(
                              value: j,
                              child: Text(
                                '${j.jobCode} • ${j.customerName} (${j.device})',
                                overflow: TextOverflow.ellipsis,
                              ),
                            )),
                      ],
                      onChanged: (val) {
                        setState(() {
                          _selectedJob = val;
                        });
                      },
                    ),

                    const SizedBox(height: 16),

                    // Instructions / Directives Description
                    const Text('Work Directives & Details', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                    const SizedBox(height: 6),
                    TextFormField(
                      controller: _descController,
                      maxLines: 3,
                      decoration: InputDecoration(
                        hintText: 'Detailed technical directives or diagnostic instructions...',
                        filled: true,
                        fillColor: Colors.grey.shade50,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(10),
                          borderSide: BorderSide(color: Colors.grey.shade300),
                        ),
                      ),
                    ),

                    const SizedBox(height: 16),

                    // Initial Chat Note
                    const Text('Initial Message to Thread (Optional)', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                    const SizedBox(height: 6),
                    TextFormField(
                      controller: _initialMsgController,
                      decoration: InputDecoration(
                        hintText: 'e.g., Please prioritize this before 3 PM.',
                        filled: true,
                        fillColor: Colors.grey.shade50,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(10),
                          borderSide: BorderSide(color: Colors.grey.shade300),
                        ),
                      ),
                    ),

                    const SizedBox(height: 24),

                    // Submit Button
                    SizedBox(
                      width: double.infinity,
                      height: 48,
                      child: FilledButton(
                        onPressed: _isSubmitting ? null : _submit,
                        style: FilledButton.styleFrom(
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                        ),
                        child: _isSubmitting
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                              )
                            : const Text('Create Task / Directive', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                      ),
                    ),
                    const SizedBox(height: 20),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _priorityChoice(String key, String label, Color color) {
    final isSelected = _priority == key;
    return Expanded(
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: () {
          setState(() {
            _priority = key;
          });
        },
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 8),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: isSelected ? color.withValues(alpha: 0.15) : Colors.grey.shade100,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(
              color: isSelected ? color : Colors.grey.shade300,
              width: isSelected ? 1.5 : 1,
            ),
          ),
          child: Text(
            label,
            style: TextStyle(
              fontSize: 11,
              fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
              color: isSelected ? color : Colors.grey.shade800,
            ),
          ),
        ),
      ),
    );
  }
}
