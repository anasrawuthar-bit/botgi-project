class JobDetail {
  JobDetail({
    required this.jobCode,
    required this.status,
    required this.statusDisplay,
    required this.customerName,
    required this.customerPhone,
    required this.deviceType,
    required this.deviceBrand,
    required this.deviceModel,
    required this.deviceSerial,
    required this.devicePassword,
    required this.rackLocation,
    required this.rackShort,
    required this.reportedIssue,
    required this.additionalItems,
    required this.technicianNotes,
    required this.isUnderWarranty,
    required this.estimatedAmount,
    required this.estimatedDelivery,
    required this.vyaparInvoiceNumber,
    required this.feedbackRating,
    required this.feedbackComment,
    required this.feedbackDate,
    required this.createdBy,
    required this.assignedTo,
    required this.updatedAt,
    required this.createdAt,
    required this.partTotal,
    required this.serviceTotal,
    required this.subtotal,
    required this.discountAmount,
    required this.grandTotal,
    required this.canEditNotes,
    required this.canManageServiceLogs,
    required this.canChangeStatus,
    required this.serviceLogs,
    required this.timeline,
    required this.availableActions,
    this.taskAssignment,
    required this.tasks,
    required this.checklistSchema,
    required this.checklistTitle,
    required this.checklistNotes,
    required this.checklistAnswers,
    this.receiptUrl = '',
    this.rackId,
    this.rackColumn,
    this.availableRacks = const [],
  });

  final String jobCode;
  final String status;
  final String statusDisplay;
  final String customerName;
  final String customerPhone;
  final String deviceType;
  final String deviceBrand;
  final String deviceModel;
  final String deviceSerial;
  final String devicePassword;
  final String rackLocation;
  final String rackShort;
  final int? rackId;
  final int? rackColumn;
  final List<DeviceRackOption> availableRacks;
  final String reportedIssue;
  final String additionalItems;
  final String technicianNotes;
  final bool isUnderWarranty;
  final String estimatedAmount;
  final String estimatedDelivery;
  final String vyaparInvoiceNumber;
  final int feedbackRating;
  final String feedbackComment;
  final String feedbackDate;
  final String createdBy;
  final String assignedTo;
  final String updatedAt;
  final String createdAt;
  final String partTotal;
  final String serviceTotal;
  final String subtotal;
  final String discountAmount;
  final String grandTotal;
  final bool canEditNotes;
  final bool canManageServiceLogs;
  final bool canChangeStatus;
  final List<JobServiceLine> serviceLogs;
  final List<JobTimelineEvent> timeline;
  final List<JobActionOption> availableActions;
  final TaskAssignmentDetail? taskAssignment;
  final List<LinkedTaskItem> tasks;
  final List<ChecklistFieldItem> checklistSchema;
  final String checklistTitle;
  final String checklistNotes;
  final Map<String, dynamic> checklistAnswers;
  final String receiptUrl;

  factory JobDetail.fromJson(Map<String, dynamic> json) {
    final job = json['job'] as Map<String, dynamic>? ?? {};
    final financials = json['financials'] as Map<String, dynamic>? ?? {};
    final permissions = json['permissions'] as Map<String, dynamic>? ?? {};
    final logsRaw = json['service_logs'];
    final timelineRaw = json['timeline'];
    final actionsRaw = json['available_actions'];
    final taskRaw = json['task_assignment'];
    final tasksRaw = json['tasks'];
    final checklistSchemaRaw = json['technician_checklist_schema'];
    final checklistAnswersRaw = job['technician_checklist'];

    return JobDetail(
      jobCode: (job['job_code'] ?? '').toString(),
      status: (job['status'] ?? '').toString(),
      statusDisplay: (job['status_display'] ?? '').toString(),
      customerName: (job['customer_name'] ?? '').toString(),
      customerPhone: (job['customer_phone'] ?? '').toString(),
      deviceType: (job['device_type'] ?? '').toString(),
      deviceBrand: (job['device_brand'] ?? '').toString(),
      deviceModel: (job['device_model'] ?? '').toString(),
      deviceSerial: (job['device_serial'] ?? '').toString(),
      devicePassword: (job['device_password'] ?? '').toString(),
      rackLocation: (job['rack_location'] ?? '').toString(),
      rackShort: (job['rack_short'] ?? '').toString(),
      reportedIssue: (job['reported_issue'] ?? '').toString(),
      additionalItems: (job['additional_items'] ?? '').toString(),
      technicianNotes: (job['technician_notes'] ?? '').toString(),
      isUnderWarranty: (job['is_under_warranty'] ?? false) == true,
      estimatedAmount: (job['estimated_amount'] ?? '').toString(),
      estimatedDelivery: (job['estimated_delivery'] ?? '').toString(),
      vyaparInvoiceNumber: (job['vyapar_invoice_number'] ?? '').toString(),
      feedbackRating: (job['feedback_rating'] is int)
          ? (job['feedback_rating'] as int)
          : int.tryParse('${job['feedback_rating']}') ?? 0,
      feedbackComment: (job['feedback_comment'] ?? '').toString(),
      feedbackDate: (job['feedback_date'] ?? '').toString(),
      createdBy: (job['created_by'] ?? '').toString(),
      assignedTo: (job['assigned_to'] ?? '').toString(),
      updatedAt: (job['updated_at'] ?? '').toString(),
      createdAt: (job['created_at'] ?? '').toString(),
      partTotal: (financials['part_total'] ?? '0.00').toString(),
      serviceTotal: (financials['service_total'] ?? '0.00').toString(),
      subtotal: (financials['subtotal'] ?? '0.00').toString(),
      discountAmount: (financials['discount_amount'] ?? '0.00').toString(),
      grandTotal: (financials['grand_total'] ?? '0.00').toString(),
      canEditNotes: (permissions['can_edit_notes'] ?? false) == true,
      canManageServiceLogs: (permissions['can_manage_service_logs'] ?? false) ==
          true,
      canChangeStatus: (permissions['can_change_status'] ??
              json['can_change_status'] ??
              false) ==
          true,
      serviceLogs: logsRaw is List
          ? logsRaw
                .whereType<Map<String, dynamic>>()
                .map(JobServiceLine.fromJson)
                .toList(growable: false)
          : const [],
      timeline: timelineRaw is List
          ? timelineRaw
                .whereType<Map<String, dynamic>>()
                .map(JobTimelineEvent.fromJson)
                .toList(growable: false)
          : const [],
      availableActions: actionsRaw is List
          ? actionsRaw
                .whereType<Map<String, dynamic>>()
                .map(JobActionOption.fromJson)
                .toList(growable: false)
          : const [],
      taskAssignment: taskRaw is Map<String, dynamic>
          ? TaskAssignmentDetail.fromJson(taskRaw)
          : null,
      tasks: tasksRaw is List
          ? tasksRaw
              .whereType<Map<String, dynamic>>()
              .map(LinkedTaskItem.fromJson)
              .toList(growable: false)
          : const [],
      checklistSchema: checklistSchemaRaw is List
          ? checklistSchemaRaw
              .whereType<Map<String, dynamic>>()
              .map(ChecklistFieldItem.fromJson)
              .toList(growable: false)
          : const [],
      checklistTitle: (json['technician_checklist_title'] ?? '').toString(),
      checklistNotes: (json['technician_checklist_notes'] ?? '').toString(),
      checklistAnswers: checklistAnswersRaw is Map<String, dynamic>
          ? Map<String, dynamic>.from(checklistAnswersRaw)
          : {},
      receiptUrl: (job['receipt_url'] ?? '').toString(),
      rackId: (job['rack_id'] is int)
          ? job['rack_id'] as int
          : int.tryParse('${job['rack_id']}'),
      rackColumn: (job['rack_column'] is int)
          ? job['rack_column'] as int
          : int.tryParse('${job['rack_column']}'),
      availableRacks: (json['available_racks'] is List)
          ? (json['available_racks'] as List)
              .whereType<Map<String, dynamic>>()
              .map(DeviceRackOption.fromJson)
              .toList(growable: false)
          : const [],
    );
  }
}

class TaskAttachmentItem {
  TaskAttachmentItem({
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

  factory TaskAttachmentItem.fromJson(Map<String, dynamic> json) {
    return TaskAttachmentItem(
      id: (json['id'] is int) ? json['id'] as int : int.tryParse('${json['id']}') ?? 0,
      fileName: (json['file_name'] ?? '').toString(),
      fileSize: (json['file_size'] is int) ? json['file_size'] as int : int.tryParse('${json['file_size']}') ?? 0,
      fileUrl: (json['file_url'] ?? '').toString(),
      uploadedAt: (json['uploaded_at'] ?? '').toString(),
      uploadedBy: (json['uploaded_by'] ?? '').toString(),
    );
  }
}

class TaskAssignmentDetail {
  TaskAssignmentDetail({
    required this.id,
    required this.status,
    required this.statusDisplay,
    required this.priority,
    required this.priorityDisplay,
    required this.dueDate,
    required this.instructions,
    required this.assignedBy,
    required this.assignedAt,
    required this.attachments,
  });

  final int id;
  final String status;
  final String statusDisplay;
  final String priority;
  final String priorityDisplay;
  final String dueDate;
  final String instructions;
  final String assignedBy;
  final String assignedAt;
  final List<TaskAttachmentItem> attachments;

  factory TaskAssignmentDetail.fromJson(Map<String, dynamic> json) {
    final attRaw = json['attachments'];
    return TaskAssignmentDetail(
      id: (json['id'] is int) ? json['id'] as int : int.tryParse('${json['id']}') ?? 0,
      status: (json['status'] ?? '').toString(),
      statusDisplay: (json['status_display'] ?? '').toString(),
      priority: (json['priority'] ?? 'medium').toString(),
      priorityDisplay: (json['priority_display'] ?? 'Medium').toString(),
      dueDate: (json['due_date'] ?? '').toString(),
      instructions: (json['instructions'] ?? '').toString(),
      assignedBy: (json['assigned_by'] ?? '').toString(),
      assignedAt: (json['assigned_at'] ?? '').toString(),
      attachments: attRaw is List
          ? attRaw
              .whereType<Map<String, dynamic>>()
              .map(TaskAttachmentItem.fromJson)
              .toList(growable: false)
          : const [],
    );
  }
}

class JobServiceLine {
  JobServiceLine({
    required this.id,
    required this.description,
    required this.partCost,
    required this.serviceCharge,
    required this.salesInvoiceNumber,
    required this.createdAt,
    required this.isProductSale,
    required this.productName,
    required this.productQuantity,
    required this.productUnitPrice,
    required this.productLineTotal,
  });

  final int id;
  final String description;
  final String partCost;
  final String serviceCharge;
  final String salesInvoiceNumber;
  final String createdAt;
  final bool isProductSale;
  final String productName;
  final int productQuantity;
  final String productUnitPrice;
  final String productLineTotal;

  factory JobServiceLine.fromJson(Map<String, dynamic> json) {
    return JobServiceLine(
      id: (json['id'] is int)
          ? json['id'] as int
          : int.tryParse('${json['id']}') ?? 0,
      description: (json['description'] ?? '').toString(),
      partCost: (json['part_cost'] ?? '0.00').toString(),
      serviceCharge: (json['service_charge'] ?? '0.00').toString(),
      salesInvoiceNumber: (json['sales_invoice_number'] ?? '').toString(),
      createdAt: (json['created_at'] ?? '').toString(),
      isProductSale: (json['is_product_sale'] ?? false) == true,
      productName: (json['product_name'] ?? '').toString(),
      productQuantity: (json['product_quantity'] is int)
          ? (json['product_quantity'] as int)
          : int.tryParse('${json['product_quantity']}') ?? 0,
      productUnitPrice: (json['product_unit_price'] ?? '0.00').toString(),
      productLineTotal: (json['product_line_total'] ?? '0.00').toString(),
    );
  }
}

class JobTimelineEvent {
  JobTimelineEvent({
    required this.action,
    required this.label,
    required this.details,
    required this.timestamp,
    required this.user,
  });

  final String action;
  final String label;
  final String details;
  final String timestamp;
  final String user;

  factory JobTimelineEvent.fromJson(Map<String, dynamic> json) {
    return JobTimelineEvent(
      action: (json['action'] ?? '').toString(),
      label: (json['label'] ?? '').toString(),
      details: (json['details'] ?? '').toString(),
      timestamp: (json['timestamp'] ?? '').toString(),
      user: (json['user'] ?? '').toString(),
    );
  }
}

class JobActionOption {
  JobActionOption({required this.key, required this.label});

  final String key;
  final String label;

  factory JobActionOption.fromJson(Map<String, dynamic> json) {
    return JobActionOption(
      key: (json['key'] ?? '').toString(),
      label: (json['label'] ?? '').toString(),
    );
  }
}

class ChecklistFieldItem {
  ChecklistFieldItem({
    required this.key,
    required this.label,
    required this.type,
    required this.required,
    required this.placeholder,
    required this.helpText,
    required this.options,
    required this.value,
  });

  final String key;
  final String label;
  final String type; // 'checkbox', 'select', 'text'
  final bool required;
  final String placeholder;
  final String helpText;
  final List<String> options;
  final dynamic value;

  factory ChecklistFieldItem.fromJson(Map<String, dynamic> json) {
    final opts = json['options'];
    return ChecklistFieldItem(
      key: (json['key'] ?? '').toString(),
      label: (json['label'] ?? '').toString(),
      type: (json['type'] ?? 'text').toString(),
      required: (json['required'] ?? false) == true,
      placeholder: (json['placeholder'] ?? '').toString(),
      helpText: (json['help_text'] ?? '').toString(),
      options: opts is List
          ? opts.map((e) => e.toString()).toList(growable: false)
          : const [],
      value: json['value'],
    );
  }
}

class LinkedTaskItem {
  LinkedTaskItem({
    required this.id,
    required this.title,
    required this.description,
    required this.priority,
    required this.priorityDisplay,
    required this.status,
    required this.statusDisplay,
    required this.dueDate,
    required this.assignedTo,
    required this.createdBy,
    required this.createdAt,
  });

  final int id;
  final String title;
  final String description;
  final String priority;
  final String priorityDisplay;
  final String status;
  final String statusDisplay;
  final String dueDate;
  final String assignedTo;
  final String createdBy;
  final String createdAt;

  factory LinkedTaskItem.fromJson(Map<String, dynamic> json) {
    return LinkedTaskItem(
      id: (json['id'] is int)
          ? json['id'] as int
          : int.tryParse('${json['id']}') ?? 0,
      title: (json['title'] ?? '').toString(),
      description: (json['description'] ?? '').toString(),
      priority: (json['priority'] ?? 'medium').toString(),
      priorityDisplay: (json['priority_display'] ?? 'Medium').toString(),
      status: (json['status'] ?? 'open').toString(),
      statusDisplay: (json['status_display'] ?? 'Open').toString(),
      dueDate: (json['due_date'] ?? '').toString(),
      assignedTo: (json['assigned_to'] ?? '').toString(),
      createdBy: (json['created_by'] ?? '').toString(),
      createdAt: (json['created_at'] ?? '').toString(),
    );
  }
}

class DeviceRackOption {
  const DeviceRackOption({
    required this.id,
    required this.name,
    required this.group,
    required this.totalColumns,
    this.occupied = const {},
    this.freeCount = 0,
    this.occupiedCount = 0,
    this.freeColumns = const [],
  });

  final int id;
  final String name;
  final String group;
  final int totalColumns;
  final Map<String, List<dynamic>> occupied;
  final int freeCount;
  final int occupiedCount;
  final List<int> freeColumns;

  String get displayName => group.isNotEmpty ? '$name ($group)' : name;

  List<dynamic> getOccupantsForColumn(int col) {
    final list = occupied[col.toString()];
    if (list != null && list.isNotEmpty) return list;
    return const [];
  }

  bool isColumnOccupied(int col) => getOccupantsForColumn(col).isNotEmpty;

  factory DeviceRackOption.fromJson(Map<String, dynamic> json) {
    final rawOccupied = json['occupied'];
    final Map<String, List<dynamic>> parsedOccupied = {};
    if (rawOccupied is Map) {
      for (final entry in rawOccupied.entries) {
        if (entry.value is List) {
          parsedOccupied[entry.key.toString()] = entry.value as List<dynamic>;
        }
      }
    }

    final totalCols = (json['total_columns'] is int)
        ? json['total_columns'] as int
        : int.tryParse('${json['total_columns']}') ?? 10;

    final rawFreeCols = json['free_columns'];
    final List<int> parsedFreeCols = [];
    if (rawFreeCols is List) {
      for (final item in rawFreeCols) {
        if (item is int) {
          parsedFreeCols.add(item);
        } else {
          final p = int.tryParse('$item');
          if (p != null) parsedFreeCols.add(p);
        }
      }
    }

    return DeviceRackOption(
      id: (json['id'] is int)
          ? json['id'] as int
          : int.tryParse('${json['id']}') ?? 0,
      name: (json['name'] ?? '').toString(),
      group: (json['group'] ?? '').toString(),
      totalColumns: totalCols,
      occupied: parsedOccupied,
      occupiedCount: (json['occupied_count'] is int)
          ? json['occupied_count'] as int
          : int.tryParse('${json['occupied_count']}') ?? 0,
      freeCount: (json['free_count'] is int)
          ? json['free_count'] as int
          : int.tryParse('${json['free_count']}') ?? totalCols,
      freeColumns: parsedFreeCols,
    );
  }
}
