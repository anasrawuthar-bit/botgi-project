import 'dart:async';
import 'package:flutter/material.dart';

import '../models/task_model.dart';
import '../services/tasks_service.dart';
import '../theme/app_colors.dart';
import '../widgets/priority_badge.dart';

class TaskDetailScreen extends StatefulWidget {
  const TaskDetailScreen({
    super.key,
    required this.taskId,
    required this.tasksService,
  });

  final int taskId;
  final TasksService tasksService;

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
      onError: (_) {
        // Socket closed or reconnect pending
      },
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
          // If there is an optimistic pending message with matching body & sender, replace it
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

  Future<void> _sendMessage() async {
    final text = _messageController.text.trim();
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

    _messageController.clear();
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Task Details'),
        actions: [
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
                          _buildMessageComposer(),
                        ],
                      ),
      ),
    );
  }

  Widget _buildHeaderCard(TaskModel task) {
    final isUrgent = task.priority == 'urgent';

    return Card(
      elevation: 1,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: isUrgent ? BorderSide(color: Colors.red.shade400, width: 1.5) : BorderSide.none,
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                PriorityBadge(
                  priority: task.priority,
                  label: task.priorityDisplay,
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
            if (task.dueDate.isNotEmpty) ...[
              Row(
                children: [
                  const Icon(Icons.schedule, size: 16, color: Colors.blueGrey),
                  const SizedBox(width: 6),
                  Text(
                    'Due: ${task.dueDate}',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: isUrgent ? Colors.red.shade700 : Colors.blueGrey.shade800,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
            ],
            if (task.jobReference != null) ...[
              Row(
                children: [
                  const Icon(Icons.build_circle, size: 16, color: Colors.indigo),
                  const SizedBox(width: 6),
                  Text(
                    'Linked Job: ${task.jobReference!.jobCode} (${task.jobReference!.device})',
                    style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: Colors.indigo),
                  ),
                ],
              ),
              const SizedBox(height: 6),
            ],
            Row(
              children: [
                const Icon(Icons.person, size: 16, color: Colors.grey),
                const SizedBox(width: 6),
                Text(
                  'Created by: ${task.createdBy} • ${task.createdAt}',
                  style: const TextStyle(fontSize: 12, color: Colors.grey),
                ),
              ],
            ),
            const SizedBox(height: 16),
            // Action Buttons
            Row(
              children: [
                if (task.status == 'open')
                  Expanded(
                    child: FilledButton.icon(
                      style: FilledButton.styleFrom(backgroundColor: const Color(0xFFF57F17)),
                      onPressed: _isUpdatingStatus ? null : () => _updateStatus('in_progress'),
                      icon: const Icon(Icons.play_arrow_rounded),
                      label: const Text('Start Task'),
                    ),
                  )
                else if (task.status == 'in_progress')
                  Expanded(
                    child: FilledButton.icon(
                      style: FilledButton.styleFrom(backgroundColor: const Color(0xFF2E7D32)),
                      onPressed: _isUpdatingStatus ? null : () => _updateStatus('done'),
                      icon: const Icon(Icons.check_circle_outline),
                      label: const Text('Mark Complete'),
                    ),
                  )
                else if (task.status == 'done')
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: _isUpdatingStatus ? null : () => _updateStatus('in_progress'),
                      icon: const Icon(Icons.replay_rounded),
                      label: const Text('Reopen Task'),
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildDirectivesCard(TaskModel task) {
    return Card(
      elevation: 1,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Row(
              children: [
                Icon(Icons.notes, size: 18, color: Colors.blueGrey),
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
                task.description.isEmpty ? 'No detailed description provided.' : task.description,
                style: TextStyle(
                  fontSize: 14,
                  height: 1.4,
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
      elevation: 1,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.attach_file, size: 18, color: Colors.blueGrey),
                const SizedBox(width: 6),
                Text(
                  'Reference Files (${task.attachments.length})',
                  style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold),
                ),
              ],
            ),
            const SizedBox(height: 8),
            ...task.attachments.map((att) {
              return ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.insert_drive_file, color: Colors.indigo),
                title: Text(att.fileName, style: const TextStyle(fontWeight: FontWeight.w600)),
                subtitle: Text(
                  '${att.fileSize > 0 ? '${(att.fileSize / 1024).toStringAsFixed(1)} KB • ' : ''}Uploaded ${att.uploadedAt}',
                  style: const TextStyle(fontSize: 11),
                ),
              );
            }),
          ],
        ),
      ),
    );
  }

  Widget _buildDiscussionSection(TaskModel task) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.chat_bubble_outline, size: 18, color: Colors.blueGrey),
            const SizedBox(width: 6),
            Text(
              'Discussion (${_messages.length})',
              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold),
            ),
          ],
        ),
        const SizedBox(height: 8),
        if (_messages.isEmpty)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: Colors.grey.shade50,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.grey.shade200),
            ),
            child: const Center(
              child: Text(
                'No messages yet. Send a query or update below.',
                style: TextStyle(fontSize: 13, color: Colors.grey),
              ),
            ),
          )
        else
          ..._messages.map((msg) {
            final isSelf = msg.senderIsSelf;
            return Align(
              alignment: isSelf ? Alignment.centerRight : Alignment.centerLeft,
              child: Opacity(
                opacity: msg.isPending ? 0.65 : 1.0,
                child: Container(
                  margin: const EdgeInsets.symmetric(vertical: 4),
                  constraints: BoxConstraints(
                    maxWidth: MediaQuery.of(context).size.width * 0.75,
                  ),
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  decoration: BoxDecoration(
                    color: isSelf
                        ? Theme.of(context).colorScheme.primary
                        : Colors.grey.shade200,
                    borderRadius: BorderRadius.circular(12).copyWith(
                      bottomRight: isSelf ? const Radius.circular(0) : const Radius.circular(12),
                      bottomLeft: !isSelf ? const Radius.circular(0) : const Radius.circular(12),
                    ),
                  ),
                  child: Column(
                    crossAxisAlignment: isSelf ? CrossAxisAlignment.end : CrossAxisAlignment.start,
                    children: [
                      Text(
                        msg.body,
                        style: TextStyle(
                          fontSize: 14,
                          color: isSelf ? Colors.white : Colors.black87,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            '${msg.sender} • ${msg.sentAt}',
                            style: TextStyle(
                              fontSize: 10,
                              color: isSelf ? Colors.white70 : Colors.black54,
                            ),
                          ),
                          if (msg.isPending) ...[
                            const SizedBox(width: 4),
                            const SizedBox(
                              width: 10,
                              height: 10,
                              child: CircularProgressIndicator(
                                strokeWidth: 1.5,
                                color: Colors.white70,
                              ),
                            ),
                          ],
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            );
          }),
      ],
    );
  }

  Widget _buildMessageComposer() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.05),
            blurRadius: 4,
            offset: const Offset(0, -2),
          ),
        ],
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _messageController,
              decoration: InputDecoration(
                hintText: 'Type a message to staff...',
                contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(24),
                  borderSide: BorderSide(color: Colors.grey.shade300),
                ),
                filled: true,
                fillColor: Colors.grey.shade100,
              ),
              textCapitalization: TextCapitalization.sentences,
              maxLines: null,
            ),
          ),
          const SizedBox(width: 8),
          IconButton.filled(
            onPressed: _isSending ? null : _sendMessage,
            icon: _isSending
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                  )
                : const Icon(Icons.send_rounded, size: 20),
          ),
        ],
      ),
    );
  }

  Color _statusColor(String status) {
    switch (status) {
      case 'in_progress':
        return const Color(0xFFF57F17);
      case 'done':
        return const Color(0xFF2E7D32);
      case 'cancelled':
        return const Color(0xFF546E7A);
      default:
        return const Color(0xFF1565C0);
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
}
