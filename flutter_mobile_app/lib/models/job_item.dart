class JobItem {
  JobItem({
    required this.jobCode,
    required this.customerName,
    required this.customerPhone,
    required this.device,
    required this.status,
    required this.updatedAt,
    required this.total,
    required this.partTotal,
    required this.serviceTotal,
    required this.discountAmount,
    required this.assignedTo,
    this.priority = 'medium',
    this.dueDate = '',
  });

  final String jobCode;
  final String customerName;
  final String customerPhone;
  final String device;
  final String status;
  final String updatedAt;
  final String total;
  final String partTotal;
  final String serviceTotal;
  final String discountAmount;
  final String assignedTo;
  final String priority;
  final String dueDate;

  factory JobItem.fromJson(Map<String, dynamic> json) {
    return JobItem(
      jobCode: (json['job_code'] ?? '').toString(),
      customerName: (json['customer_name'] ?? '').toString(),
      customerPhone: (json['customer_phone'] ?? '').toString(),
      device: (json['device'] ?? '').toString(),
      status: (json['status'] ?? '').toString(),
      updatedAt: (json['updated_at'] ?? '').toString(),
      total: (json['total'] ?? '0.00').toString(),
      partTotal: (json['part_total'] ?? '0.00').toString(),
      serviceTotal: (json['service_total'] ?? '0.00').toString(),
      discountAmount: (json['discount_amount'] ?? '0.00').toString(),
      assignedTo: (json['assigned_to'] ?? '').toString(),
      priority: (json['priority'] ?? 'medium').toString(),
      dueDate: (json['due_date'] ?? '').toString(),
    );
  }
}
