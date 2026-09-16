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
      jobReference: jobReference ?? this.jobReference,
      attachmentsCount: attachmentsCount ?? this.attachmentsCount,
      messagesCount: messagesCount ?? this.messagesCount,
      attachments: attachments ?? this.attachments,
      messages: messages ?? this.messages,
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
