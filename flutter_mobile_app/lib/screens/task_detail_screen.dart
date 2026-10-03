import 'dart:async';
import 'package:flutter/material.dart';

import '../models/task_model.dart';
import '../services/jobs_service.dart';
import '../services/tasks_service.dart';
import '../theme/app_colors.dart';
import '../widgets/priority_badge.dart';
import 'job_detail_screen.dart';

class TaskDetailScreen extends StatefulWidget {
  const TaskDetailScreen({
    super.key,
    required this.taskId,
    required this.tasksService,
    this.jobsService,
  });

  final int taskId;
  final TasksService tasksService;
  final JobsService? jobsService;

  @override
  State<TaskDetailScreen> createState() => _TaskDetailScreenState();
}

class _TaskDetailScreenState extends State<TaskDetailScreen> {
  TaskModel? _task;
  List<TaskMessageModel> _messages = [];
  bool _isLoading = true;
  String? _errorMessage;

  final TextEditingController _messageController = TextEditingController();
  final ScrollController _chatScrollController = ScrollController();
  StreamSubscription<Map<String, dynamic>>? _chatSubscription;
  bool _isSending = false;
  bool _isUpdatingStatus = false;

  @override
  void initState() {
    super.initState();
    _loadTask();
    _subscribeToChat();
  }

  @override
  void dispose() {
    _chatSubscription?.cancel();
    _messageController.dispose();
    _chatScrollController.dispose();
    super.dispose();
  }

  void _subscribeToChat() {
    _chatSubscription?.cancel();
    _chatSubscription = widget.tasksService.connectToTaskChat(widget.taskId).listen(
      _handleSocketEvent,
      onError: (_) {},
    );
  }

  void _handleSocketEvent(Map<String, dynamic> event) {
    if (!mounted) return;
    final type = event['type'] as String?;
    final currentUsername = widget.tasksService.authService.currentUser?['username'] ?? '';

    if (type == 'task_message_event') {
      final msg = TaskMessageModel.fromJson(event, currentUsername: currentUsername);
      setState(() {
        final existingIdx = _messages.indexWhere((m) => m.id == msg.id);
        if (existingIdx != -1) {
          _messages[existingIdx] = msg;
        } else {
          final pendingIdx = _messages.indexWhere(
            (m) => m.isPending && m.body.trim() == msg.body.trim() && m.senderIsSelf,
          );
          if (pendingIdx != -1) {
            _messages[pendingIdx] = msg;
          } else {
            _messages.add(msg);
          }
        }
        if (_task != null) {
          _task = _task!.copyWith(
            messagesCount: _messages.length,
            messages: _messages,
          );
        }
      });
      _scrollToBottom();
    } else if (type == 'task_status_event') {
      final newStatus = (event['new_status'] ?? '').toString();
      final newDisplay = (event['status_display'] ?? '').toString();
      if (newStatus.isNotEmpty && _task != null) {
        setState(() {
          _task = _task!.copyWith(
            status: newStatus,
            statusDisplay: newDisplay.isNotEmpty ? newDisplay : _statusLabel(newStatus),
          );
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Task status updated to ${newDisplay.isNotEmpty ? newDisplay : _statusLabel(newStatus)}'),
            duration: const Duration(seconds: 2),
          ),
        );
      }
    } else if (type == 'task_priority_event') {
      final priority = (event['priority'] ?? '').toString();
      final priorityDisplay = (event['priority_display'] ?? '').toString();
      if (priority.isNotEmpty && _task != null) {
        setState(() {
          _task = _task!.copyWith(
            priority: priority,
            priorityDisplay: priorityDisplay.isNotEmpty ? priorityDisplay : _task!.priorityDisplay,
          );
        });
      }
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_chatScrollController.hasClients) {
        _chatScrollController.animateTo(
          _chatScrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _loadTask() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final task = await widget.tasksService.fetchTaskDetail(widget.taskId);
      if (!mounted) return;
      setState(() {
        _task = task;
        _messages = List.from(task.messages);
        _isLoading = false;
      });
      _scrollToBottom();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = e.toString().replaceFirst('Exception: ', '');
        _isLoading = false;
      });
    }
  }

  Future<void> _updateStatus(String status) async {
    setState(() {
      _isUpdatingStatus = true;
    });
    try {
      await widget.tasksService.updateTaskStatus(widget.taskId, status);
      if (!mounted) return;
      setState(() {
        if (_task != null) {
          _task = _task!.copyWith(
            status: status,
            statusDisplay: _statusLabel(status),
          );
        }
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Status updated to ${_statusLabel(status)}'),
          duration: const Duration(seconds: 2),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: AppColors.warningFg,
          content: Text(e.toString().replaceFirst('Exception: ', '')),
        ),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isUpdatingStatus = false;
        });
      }
    }
  }

  Future<void> _sendMessage([String? quickText]) async {
    final text = (quickText ?? _messageController.text).trim();
    if (text.isEmpty || _isSending) return;

    final currentUsername = widget.tasksService.authService.currentUser?['username'] ?? 'Me';
    final tempId = -DateTime.now().millisecondsSinceEpoch;
    final optimisticMsg = TaskMessageModel(
      id: tempId,
      sender: currentUsername,
      senderIsSelf: true,
      body: text,
      sentAt: 'Sending...',
      isPending: true,
    );

    setState(() {
      _messages.add(optimisticMsg);
      if (_task != null) {
        _task = _task!.copyWith(
          messagesCount: _messages.length,
          messages: _messages,
        );
      }
      _isSending = true;
    });

    if (quickText == null) {
      _messageController.clear();
    }
    _scrollToBottom();

    try {
      final serverMsg = await widget.tasksService.sendTaskMessage(widget.taskId, text);
      if (!mounted) return;
      setState(() {
        final pendingIdx = _messages.indexWhere((m) => m.id == tempId);
        if (pendingIdx != -1) {
          if (_messages.any((m) => m.id == serverMsg.id)) {
            _messages.removeAt(pendingIdx);
          } else {
            _messages[pendingIdx] = serverMsg;
          }
        } else if (!_messages.any((m) => m.id == serverMsg.id)) {
          _messages.add(serverMsg);
        }
        if (_task != null) {
          _task = _task!.copyWith(
            messagesCount: _messages.length,
            messages: _messages,
          );
        }
      });
      _scrollToBottom();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _messages.removeWhere((m) => m.id == tempId);
        if (_task != null) {
          _task = _task!.copyWith(
            messagesCount: _messages.length,
            messages: _messages,
          );
        }
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: AppColors.warningFg,
          content: Text(e.toString().replaceFirst('Exception: ', '')),
        ),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isSending = false;
        });
      }
    }
  }

  void _openEditTaskSheet() {
    if (_task == null) return;
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => _EditTaskSheet(
        task: _task!,
        tasksService: widget.tasksService,
        onUpdated: (updatedTask) {
          setState(() {
            _task = updatedTask;
          });
        },
      ),
    );
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

  Color _statusColor(String status) {
    switch (status) {
      case 'in_progress':
        return const Color(0xFFD97706);
      case 'done':
        return const Color(0xFF16A34A);
      case 'cancelled':
        return const Color(0xFF64748B);
      default:
        return const Color(0xFF2563EB);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Task & Directives', style: TextStyle(fontWeight: FontWeight.w700)),
        actions: [
          if (_task != null)
            IconButton(
              icon: const Icon(Icons.edit_outlined),
              tooltip: 'Edit Task',
              onPressed: _openEditTaskSheet,
            ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () {
              _loadTask();
              _subscribeToChat();
            },
            tooltip: 'Refresh',
          ),
        ],
      ),
      body: SafeArea(
        child: _isLoading && _task == null
            ? const Center(child: CircularProgressIndicator())
            : _errorMessage != null && _task == null
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(Icons.error_outline, size: 48, color: AppColors.warningFg),
                          const SizedBox(height: 12),
                          Text(
                            _errorMessage!,
                            textAlign: TextAlign.center,
                            style: const TextStyle(color: AppColors.warningFg),
                          ),
                          const SizedBox(height: 12),
                          FilledButton.tonal(
                            onPressed: () {
                              _loadTask();
                              _subscribeToChat();
                            },
                            child: const Text('Retry'),
                          ),
                        ],
                      ),
                    ),
                  )
                : _task == null
                    ? const Center(child: Text('Task not found.'))
                    : Column(
                        children: [
                          Expanded(
                            child: ListView(
                              controller: _chatScrollController,
                              padding: const EdgeInsets.all(16),
                              children: [
                                _buildHeaderCard(_task!),
                                const SizedBox(height: 12),
                                if (_task!.jobReference != null) ...[
                                  _buildLinkedJobBanner(_task!),
                                  const SizedBox(height: 12),
                                ],
                                _buildDirectivesCard(_task!),
                                const SizedBox(height: 12),
                                if (_task!.attachments.isNotEmpty) ...[
                                  _buildAttachmentsCard(_task!),
                                  const SizedBox(height: 12),
                                ],
                                _buildDiscussionSection(_task!),
                              ],
                            ),
                          ),
                          _buildQuickResponseChips(),
                          _buildMessageComposer(),
                        ],
                      ),
      ),
    );
  }

  Widget _buildHeaderCard(TaskModel task) {
    final isUrgent = task.priority == 'urgent';

    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(
          color: isUrgent ? const Color(0xFFDC2626) : Colors.grey.shade300,
          width: isUrgent ? 1.8 : 1,
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
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
                      const SizedBox(width: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: const Color(0xFFFEF2F2),
                          borderRadius: BorderRadius.circular(4),
                          border: Border.all(color: const Color(0xFFDC2626)),
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
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: _statusColor(task.status).withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    task.statusDisplay,
                    style: TextStyle(
                      color: _statusColor(task.status),
                      fontWeight: FontWeight.w700,
                      fontSize: 12,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              task.title,
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 10),

            // Due Date & Assigned Info
            if (task.dueDate.isNotEmpty) ...[
              Row(
                children: [
                  Icon(
                    Icons.schedule_rounded,
                    size: 16,
                    color: task.isOverdue ? const Color(0xFFDC2626) : Colors.blueGrey,
                  ),
                  const SizedBox(width: 6),
                  Text(
                    'Due: ${task.dueDate}',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: task.isOverdue ? const Color(0xFFDC2626) : Colors.blueGrey.shade800,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
            ],

            Row(
              children: [
                Icon(Icons.person_pin_rounded, size: 16, color: Colors.blue.shade700),
                const SizedBox(width: 6),
                Text(
                  task.assignedTo.isNotEmpty
                      ? 'Assigned to: ${task.assignedToName.isNotEmpty ? task.assignedToName : task.assignedTo}'
                      : 'Assigned to: Unassigned (Pool)',
                  style: TextStyle(fontSize: 12.5, color: Colors.grey.shade800, fontWeight: FontWeight.w600),
                ),
              ],
            ),
            const SizedBox(height: 4),

            Row(
              children: [
                const Icon(Icons.account_circle_outlined, size: 15, color: Colors.grey),
                const SizedBox(width: 6),
                Text(
                  'Created by: ${task.createdBy} • ${task.createdAt}',
                  style: const TextStyle(fontSize: 11.5, color: Colors.grey),
                ),
              ],
            ),

            const SizedBox(height: 16),

            // Status Progression Stepper / Action Buttons
            Row(
              children: [
                if (task.status == 'open')
                  Expanded(
                    child: FilledButton.icon(
                      style: FilledButton.styleFrom(
                        backgroundColor: const Color(0xFFD97706),
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                      ),
                      onPressed: _isUpdatingStatus ? null : () => _updateStatus('in_progress'),
                      icon: const Icon(Icons.play_arrow_rounded),
                      label: const Text('Start Work (In Progress)', style: TextStyle(fontWeight: FontWeight.w700)),
                    ),
                  )
                else if (task.status == 'in_progress') ...[
                  Expanded(
                    child: FilledButton.icon(
                      style: FilledButton.styleFrom(
                        backgroundColor: const Color(0xFF16A34A),
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                      ),
                      onPressed: _isUpdatingStatus ? null : () => _updateStatus('done'),
                      icon: const Icon(Icons.check_circle_rounded),
                      label: const Text('Mark Completed', style: TextStyle(fontWeight: FontWeight.w700)),
                    ),
                  ),
                ] else if (task.status == 'done')
                  Expanded(
                    child: OutlinedButton.icon(
                      style: OutlinedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                      ),
                      onPressed: _isUpdatingStatus ? null : () => _updateStatus('in_progress'),
                      icon: const Icon(Icons.replay_rounded),
                      label: const Text('Reopen Task', style: TextStyle(fontWeight: FontWeight.w700)),
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildLinkedJobBanner(TaskModel task) {
    final job = task.jobReference!;
    return Card(
      elevation: 0,
      color: const Color(0xFFEEF2FF),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: Color(0xFFC7D2FE)),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () {
          if (widget.jobsService != null) {
            Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => JobDetailScreen(
                  jobCode: job.jobCode,
                  jobsService: widget.jobsService!,
                ),
              ),
            );
          }
        },
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: const Color(0xFF4338CA).withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Icon(Icons.build_circle_rounded, color: Color(0xFF4338CA), size: 22),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(
                          'Job Ticket: ${job.jobCode}',
                          style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14, color: Color(0xFF312E81)),
                        ),
                        const SizedBox(width: 6),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1.5),
                          decoration: BoxDecoration(
                            color: Colors.white,
                            borderRadius: BorderRadius.circular(4),
                            border: Border.all(color: const Color(0xFFA5B4FC)),
                          ),
                          child: Text(
                            job.status,
                            style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: Color(0xFF4338CA)),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${job.customerName} • ${job.device}',
                      style: TextStyle(fontSize: 12.5, color: Colors.indigo.shade900),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.arrow_forward_ios_rounded, size: 14, color: Color(0xFF6366F1)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildDirectivesCard(TaskModel task) {
    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: Colors.grey.shade300),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Row(
              children: [
                Icon(Icons.notes_rounded, size: 18, color: Colors.blueGrey),
                SizedBox(width: 6),
                Text(
                  'Work Directives & Instructions',
                  style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.grey.shade50,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.grey.shade200),
              ),
              child: Text(
                task.description.isEmpty ? 'No detailed technical directives provided.' : task.description,
                style: TextStyle(
                  fontSize: 13.5,
                  height: 1.45,
                  color: task.description.isEmpty ? Colors.grey : Colors.black87,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildAttachmentsCard(TaskModel task) {
    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: Colors.grey.shade300),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.attach_file_rounded, size: 18, color: Colors.blueGrey),
                const SizedBox(width: 6),
                Text(
                  'Attachments (${task.attachments.length})',
                  style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold),
                ),
              ],
            ),
            const SizedBox(height: 10),
            ...task.attachments.map((att) => Container(
                  margin: const EdgeInsets.only(bottom: 8),
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: Colors.grey.shade50,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: Colors.grey.shade200),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.insert_drive_file_outlined, size: 20, color: Colors.indigo),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              att.fileName,
                              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
                              overflow: TextOverflow.ellipsis,
                            ),
                            Text(
                              'Uploaded by ${att.uploadedBy} • ${att.uploadedAt}',
                              style: const TextStyle(fontSize: 11, color: Colors.grey),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                )),
          ],
        ),
      ),
    );
  }

  Widget _buildDiscussionSection(TaskModel task) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
          child: Row(
            children: [
              const Icon(Icons.forum_outlined, size: 18, color: Colors.blueGrey),
              const SizedBox(width: 6),
              Text(
                'Task Discussion & Thread (${_messages.length})',
                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold),
              ),
            ],
          ),
        ),
        if (_messages.isEmpty)
          Container(
            padding: const EdgeInsets.all(24),
            alignment: Alignment.center,
            child: Text(
              'No messages on this task yet.\nSend directives or technical updates below.',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.grey.shade500, fontSize: 13),
            ),
          )
        else
          ..._messages.map(_buildMessageBubble),
      ],
    );
  }

  Widget _buildMessageBubble(TaskMessageModel msg) {
    final isSelf = msg.senderIsSelf;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Align(
        alignment: isSelf ? Alignment.centerRight : Alignment.centerLeft,
        child: Container(
          constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.78),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: isSelf ? const Color(0xFF2563EB) : Colors.grey.shade100,
            borderRadius: BorderRadius.only(
              topLeft: const Radius.circular(14),
              topRight: const Radius.circular(14),
              bottomLeft: isSelf ? const Radius.circular(14) : const Radius.circular(2),
              bottomRight: isSelf ? const Radius.circular(2) : const Radius.circular(14),
            ),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.03),
                blurRadius: 3,
                offset: const Offset(0, 1),
              ),
            ],
          ),
          child: Column(
            crossAxisAlignment: isSelf ? CrossAxisAlignment.end : CrossAxisAlignment.start,
            children: [
              if (!isSelf)
                Text(
                  msg.sender,
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    color: Colors.blue.shade900,
                  ),
                ),
              Text(
                msg.body,
                style: TextStyle(
                  fontSize: 13.5,
                  color: isSelf ? Colors.white : Colors.black87,
                ),
              ),
              const SizedBox(height: 3),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    msg.sentAt,
                    style: TextStyle(
                      fontSize: 10,
                      color: isSelf ? Colors.white70 : Colors.grey.shade500,
                    ),
                  ),
                  if (msg.isPending) ...[
                    const SizedBox(width: 4),
                    const Icon(Icons.access_time_rounded, size: 10, color: Colors.white70),
                  ],
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildQuickResponseChips() {
    final quickResponses = [
      'Started work on bench',
      'Waiting for parts approval',
      'Inspection complete, testing now',
      'Completed and ready for review',
    ];

    return Container(
      height: 34,
      margin: const EdgeInsets.only(bottom: 6),
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        itemCount: quickResponses.length,
        separatorBuilder: (context, index) => const SizedBox(width: 6),
        itemBuilder: (context, index) {
          final reply = quickResponses[index];
          return ActionChip(
            label: Text(reply, style: const TextStyle(fontSize: 11)),
            visualDensity: VisualDensity.compact,
            padding: const EdgeInsets.symmetric(horizontal: 6),
            onPressed: () => _sendMessage(reply),
          );
        },
      ),
    );
  }

  Widget _buildMessageComposer() {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: Colors.grey.shade200)),
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _messageController,
              minLines: 1,
              maxLines: 4,
              decoration: InputDecoration(
                hintText: 'Type a message or directive update...',
                filled: true,
                fillColor: Colors.grey.shade100,
                contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(20),
                  borderSide: BorderSide.none,
                ),
              ),
              onSubmitted: (_) => _sendMessage(),
            ),
          ),
          const SizedBox(width: 8),
          IconButton.filled(
            onPressed: _isSending ? null : () => _sendMessage(),
            icon: _isSending
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                  )
                : const Icon(Icons.send_rounded, size: 18),
          ),
        ],
      ),
    );
  }
}

class _EditTaskSheet extends StatefulWidget {
  const _EditTaskSheet({
    required this.task,
    required this.tasksService,
    required this.onUpdated,
  });

  final TaskModel task;
  final TasksService tasksService;
  final ValueChanged<TaskModel> onUpdated;

  @override
  State<_EditTaskSheet> createState() => _EditTaskSheetState();
}

class _EditTaskSheetState extends State<_EditTaskSheet> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _titleController;
  late final TextEditingController _descController;
  late String _priority;
  int? _assignedToId;
  List<TechnicianItem> _technicians = [];
  bool _isLoadingTechs = true;
  bool _isSaving = false;

  @override
  void initState() {
    super.initState();
    _titleController = TextEditingController(text: widget.task.title);
    _descController = TextEditingController(text: widget.task.description);
    _priority = widget.task.priority;
    _assignedToId = widget.task.assignedToId;
    _loadTechs();
  }

  @override
  void dispose() {
    _titleController.dispose();
    _descController.dispose();
    super.dispose();
  }

  Future<void> _loadTechs() async {
    try {
      final list = await widget.tasksService.fetchTechnicians();
      if (!mounted) return;
      setState(() {
        _technicians = list;
        _isLoadingTechs = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _isLoadingTechs = false;
      });
    }
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _isSaving = true;
    });

    try {
      final updated = await widget.tasksService.updateTask(
        taskId: widget.task.id,
        title: _titleController.text.trim(),
        description: _descController.text.trim(),
        priority: _priority,
        assignedToId: _assignedToId,
      );

      if (!mounted) return;
      Navigator.of(context).pop();
      widget.onUpdated(updated);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Task updated successfully!')),
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
          _isSaving = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      height: MediaQuery.of(context).size.height * 0.75,
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      child: Column(
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(20, 16, 16, 12),
            decoration: BoxDecoration(
              border: Border(bottom: BorderSide(color: Colors.grey.shade200)),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('Edit Directive / Task', style: TextStyle(fontSize: 17, fontWeight: FontWeight.bold)),
                IconButton(
                  icon: const Icon(Icons.close),
                  onPressed: () => Navigator.of(context).pop(),
                ),
              ],
            ),
          ),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(20),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Title *', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                    const SizedBox(height: 6),
                    TextFormField(
                      controller: _titleController,
                      validator: (val) => val == null || val.trim().isEmpty ? 'Title is required' : null,
                      decoration: InputDecoration(
                        filled: true,
                        fillColor: Colors.grey.shade50,
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                      ),
                    ),
                    const SizedBox(height: 16),
                    const Text('Priority Level', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        _priorityChip('urgent', '⚡ Urgent', const Color(0xFFDC2626)),
                        const SizedBox(width: 8),
                        _priorityChip('high', '↑ High', const Color(0xFFEA580C)),
                        const SizedBox(width: 8),
                        _priorityChip('medium', '● Medium', const Color(0xFF2563EB)),
                        const SizedBox(width: 8),
                        _priorityChip('low', '↓ Low', Colors.grey.shade600),
                      ],
                    ),
                    const SizedBox(height: 16),
                    const Text('Assignee', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                    const SizedBox(height: 6),
                    DropdownButtonFormField<int>(
                      initialValue: _assignedToId,
                      decoration: InputDecoration(
                        hintText: _isLoadingTechs ? 'Loading technicians...' : 'Select Technician (or unassigned)',
                        filled: true,
                        fillColor: Colors.grey.shade50,
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                      ),
                      items: [
                        const DropdownMenuItem<int>(
                          value: null,
                          child: Text('Unassigned'),
                        ),
                        ..._technicians.map((t) => DropdownMenuItem<int>(
                              value: t.id,
                              child: Text('${t.name} (${t.username})'),
                            )),
                      ],
                      onChanged: (val) {
                        setState(() {
                          _assignedToId = val;
                        });
                      },
                    ),
                    const SizedBox(height: 16),
                    const Text('Directives & Instructions', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                    const SizedBox(height: 6),
                    TextFormField(
                      controller: _descController,
                      maxLines: 3,
                      decoration: InputDecoration(
                        filled: true,
                        fillColor: Colors.grey.shade50,
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                      ),
                    ),
                    const SizedBox(height: 24),
                    SizedBox(
                      width: double.infinity,
                      height: 48,
                      child: FilledButton(
                        onPressed: _isSaving ? null : _save,
                        child: _isSaving
                            ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                            : const Text('Save Changes'),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _priorityChip(String key, String label, Color color) {
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
