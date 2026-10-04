class TaskModel {
  TaskModel({
    required this.id,
    required this.title,
    required this.description,
    required this.priority,
    required this.priorityDisplay,
    required this.status,
    required this.statusDisplay,
    required this.dueDate,
    required this.createdAt,
    required this.completedAt,
    required this.createdBy,
    required this.assignedTo,
    this.assignedToId,
    this.assignedToName = '',
    this.isOverdue = false,
    this.isMine = false,
    this.isOpenToAll = false,
    this.hasAlarm = false,
    this.alarmTime = '',
    this.isClaimable = false,
    this.canAccept = false,
    this.jobReference,
    this.attachmentsCount = 0,
    this.messagesCount = 0,
    this.attachments = const [],
    this.messages = const [],
  });

  final int id;
  final String title;
  final String description;
  final String priority;
  final String priorityDisplay;
  final String status;
  final String statusDisplay;
  final String dueDate;
  final String createdAt;
  final String completedAt;
  final String createdBy;
  final String assignedTo;
  final int? assignedToId;
  final String assignedToName;
  final bool isOverdue;
  final bool isMine;
  final bool isOpenToAll;
  final bool hasAlarm;
  final String alarmTime;
  final bool isClaimable;
  final bool canAccept;
  final TaskJobReference? jobReference;
  final int attachmentsCount;
  final int messagesCount;
  final List<TaskAttachmentModel> attachments;
  final List<TaskMessageModel> messages;

  factory TaskModel.fromJson(Map<String, dynamic> json) {
    return TaskModel(
      id: (json['id'] is int) ? json['id'] as int : int.tryParse('${json['id']}') ?? 0,
      title: (json['title'] ?? '').toString(),
      description: (json['description'] ?? '').toString(),
      priority: (json['priority'] ?? 'medium').toString(),
      priorityDisplay: (json['priority_display'] ?? 'Medium').toString(),
      status: (json['status'] ?? 'open').toString(),
      statusDisplay: (json['status_display'] ?? 'Open').toString(),
      dueDate: (json['due_date'] ?? '').toString(),
      createdAt: (json['created_at'] ?? '').toString(),
      completedAt: (json['completed_at'] ?? '').toString(),
      createdBy: (json['created_by'] ?? '').toString(),
      assignedTo: (json['assigned_to'] ?? '').toString(),
      assignedToId: (json['assigned_to_id'] is int)
          ? json['assigned_to_id'] as int
          : int.tryParse('${json['assigned_to_id']}'),
      assignedToName: (json['assigned_to_name'] ?? '').toString(),
      isOverdue: json['is_overdue'] == true,
      isMine: json['is_mine'] == true,
      isOpenToAll: json['is_open_to_all'] == true,
      hasAlarm: json['has_alarm'] == true,
      alarmTime: (json['alarm_time'] ?? '').toString(),
      isClaimable: json['is_claimable'] == true,
      canAccept: json['can_accept'] == true,
      jobReference: json['job_reference'] is Map<String, dynamic>
          ? TaskJobReference.fromJson(json['job_reference'] as Map<String, dynamic>)
          : null,
      attachmentsCount: (json['attachments_count'] is int)
          ? json['attachments_count'] as int
          : int.tryParse('${json['attachments_count']}') ?? 0,
      messagesCount: (json['messages_count'] is int)
          ? json['messages_count'] as int
          : int.tryParse('${json['messages_count']}') ?? 0,
      attachments: (json['attachments'] is List)
          ? (json['attachments'] as List)
              .whereType<Map<String, dynamic>>()
              .map(TaskAttachmentModel.fromJson)
              .toList()
          : const [],
      messages: (json['messages'] is List)
          ? (json['messages'] as List)
              .whereType<Map<String, dynamic>>()
              .map(TaskMessageModel.fromJson)
              .toList()
          : const [],
    );
  }

  TaskModel copyWith({
    int? id,
    String? title,
    String? description,
    String? priority,
    String? priorityDisplay,
    String? status,
    String? statusDisplay,
    String? dueDate,
    String? createdAt,
    String? completedAt,
    String? createdBy,
    String? assignedTo,
    int? assignedToId,
    String? assignedToName,
    bool? isOverdue,
    bool? isMine,
    bool? isOpenToAll,
    bool? hasAlarm,
    String? alarmTime,
    bool? isClaimable,
    bool? canAccept,
    TaskJobReference? jobReference,
    int? attachmentsCount,
    int? messagesCount,
    List<TaskAttachmentModel>? attachments,
    List<TaskMessageModel>? messages,
  }) {
    return TaskModel(
      id: id ?? this.id,
      title: title ?? this.title,
      description: description ?? this.description,
      priority: priority ?? this.priority,
      priorityDisplay: priorityDisplay ?? this.priorityDisplay,
      status: status ?? this.status,
      statusDisplay: statusDisplay ?? this.statusDisplay,
      dueDate: dueDate ?? this.dueDate,
      createdAt: createdAt ?? this.createdAt,
      completedAt: completedAt ?? this.completedAt,
      createdBy: createdBy ?? this.createdBy,
      assignedTo: assignedTo ?? this.assignedTo,
      assignedToId: assignedToId ?? this.assignedToId,
      assignedToName: assignedToName ?? this.assignedToName,
      isOverdue: isOverdue ?? this.isOverdue,
      isMine: isMine ?? this.isMine,
      isOpenToAll: isOpenToAll ?? this.isOpenToAll,
      hasAlarm: hasAlarm ?? this.hasAlarm,
      alarmTime: alarmTime ?? this.alarmTime,
      isClaimable: isClaimable ?? this.isClaimable,
      canAccept: canAccept ?? this.canAccept,
      jobReference: jobReference ?? this.jobReference,
      attachmentsCount: attachmentsCount ?? this.attachmentsCount,
      messagesCount: messagesCount ?? this.messagesCount,
      attachments: attachments ?? this.attachments,
      messages: messages ?? this.messages,
    );
  }
}

class TaskMetrics {
  TaskMetrics({
    this.total = 0,
    this.active = 0,
    this.urgent = 0,
    this.inProgress = 0,
    this.open = 0,
    this.done = 0,
    this.pool = 0,
  });

  final int total;
  final int active;
  final int urgent;
  final int inProgress;
  final int open;
  final int done;
  final int pool;

  factory TaskMetrics.fromJson(Map<String, dynamic> json) {
    return TaskMetrics(
      total: (json['total'] is int) ? json['total'] as int : int.tryParse('${json['total']}') ?? 0,
      active: (json['active'] is int) ? json['active'] as int : int.tryParse('${json['active']}') ?? 0,
      urgent: (json['urgent'] is int) ? json['urgent'] as int : int.tryParse('${json['urgent']}') ?? 0,
      inProgress: (json['in_progress'] is int) ? json['in_progress'] as int : int.tryParse('${json['in_progress']}') ?? 0,
      open: (json['open'] is int) ? json['open'] as int : int.tryParse('${json['open']}') ?? 0,
      done: (json['done'] is int) ? json['done'] as int : int.tryParse('${json['done']}') ?? 0,
      pool: (json['pool'] is int) ? json['pool'] as int : int.tryParse('${json['pool']}') ?? 0,
    );
  }
}

class TaskListResponse {
  TaskListResponse({
    required this.tasks,
    required this.metrics,
  });

  final List<TaskModel> tasks;
  final TaskMetrics metrics;
}

class TechnicianItem {
  TechnicianItem({
    required this.id,
    required this.uniqueId,
    required this.name,
    required this.username,
    required this.isMe,
  });

  final int id;
  final String uniqueId;
  final String name;
  final String username;
  final bool isMe;

  factory TechnicianItem.fromJson(Map<String, dynamic> json) {
    return TechnicianItem(
      id: (json['id'] is int) ? json['id'] as int : int.tryParse('${json['id']}') ?? 0,
      uniqueId: (json['unique_id'] ?? '').toString(),
      name: (json['name'] ?? json['username'] ?? '').toString(),
      username: (json['username'] ?? '').toString(),
      isMe: json['is_me'] == true,
    );
  }
}

class QuickJobItem {
  QuickJobItem({
    required this.id,
    required this.jobCode,
    required this.customerName,
    required this.device,
    required this.status,
  });

  final int id;
  final String jobCode;
  final String customerName;
  final String device;
  final String status;

  factory QuickJobItem.fromJson(Map<String, dynamic> json) {
    return QuickJobItem(
      id: (json['id'] is int) ? json['id'] as int : int.tryParse('${json['id']}') ?? 0,
      jobCode: (json['job_code'] ?? '').toString(),
      customerName: (json['customer_name'] ?? '').toString(),
      device: (json['device'] ?? '').toString(),
      status: (json['status'] ?? '').toString(),
    );
  }
}

class TaskJobReference {
  TaskJobReference({
    required this.id,
    required this.jobCode,
    required this.status,
    required this.customerName,
    required this.device,
  });

  final int id;
  final String jobCode;
  final String status;
  final String customerName;
  final String device;

  factory TaskJobReference.fromJson(Map<String, dynamic> json) {
    return TaskJobReference(
      id: (json['id'] is int) ? json['id'] as int : int.tryParse('${json['id']}') ?? 0,
      jobCode: (json['job_code'] ?? '').toString(),
      status: (json['status'] ?? '').toString(),
      customerName: (json['customer_name'] ?? '').toString(),
      device: (json['device'] ?? '').toString(),
    );
  }
}

class TaskAttachmentModel {
  TaskAttachmentModel({
    required this.id,
    required this.fileName,
    required this.fileSize,
    required this.fileUrl,
    required this.uploadedAt,
    required this.uploadedBy,
  });

  final int id;
  final String fileName;
  final int fileSize;
  final String fileUrl;
  final String uploadedAt;
  final String uploadedBy;

  factory TaskAttachmentModel.fromJson(Map<String, dynamic> json) {
    return TaskAttachmentModel(
      id: (json['id'] is int) ? json['id'] as int : int.tryParse('${json['id']}') ?? 0,
      fileName: (json['file_name'] ?? '').toString(),
      fileSize: (json['file_size'] is int) ? json['file_size'] as int : int.tryParse('${json['file_size']}') ?? 0,
      fileUrl: (json['file_url'] ?? '').toString(),
      uploadedAt: (json['uploaded_at'] ?? '').toString(),
      uploadedBy: (json['uploaded_by'] ?? '').toString(),
    );
  }
}

class TaskMessageModel {
  TaskMessageModel({
    required this.id,
    required this.sender,
    required this.senderIsSelf,
    required this.body,
    required this.sentAt,
    this.isPending = false,
  });

  final int id;
  final String sender;
  final bool senderIsSelf;
  final String body;
  final String sentAt;
  final bool isPending;

  factory TaskMessageModel.fromJson(Map<String, dynamic> json, {String? currentUsername}) {
    final rawId = json['id'] ?? json['message_id'];
    final id = (rawId is int) ? rawId : int.tryParse('$rawId') ?? 0;
    final sender = (json['sender'] ?? '').toString();
    final bool isSelf = (json['sender_is_self'] == true) ||
        (currentUsername != null && currentUsername.isNotEmpty && sender.toLowerCase() == currentUsername.toLowerCase());

    return TaskMessageModel(
      id: id,
      sender: sender,
      senderIsSelf: isSelf,
      body: (json['body'] ?? '').toString(),
      sentAt: (json['sent_at'] ?? '').toString(),
      isPending: false,
    );
  }
}
