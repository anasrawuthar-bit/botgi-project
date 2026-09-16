class ProductRecord {
  ProductRecord({
    required this.id,
    required this.name,
    required this.sku,
    required this.category,
    required this.brand,
    required this.unitPrice,
    required this.costPrice,
    required this.stockQuantity,
    required this.description,
    required this.isActive,
    required this.updatedAt,
  });

  final int id;
  final String name;
  final String sku;
  final String category;
  final String brand;
  final String unitPrice;
  final String costPrice;
  final int stockQuantity;
  final String description;
  final bool isActive;
  final String updatedAt;

  factory ProductRecord.fromJson(Map<String, dynamic> json) {
    return ProductRecord(
      id: (json['id'] is int) ? json['id'] as int : int.tryParse('${json['id']}') ?? 0,
      name: (json['name'] ?? '').toString(),
      sku: (json['sku'] ?? '').toString(),
      category: (json['category'] ?? '').toString(),
      brand: (json['brand'] ?? '').toString(),
      unitPrice: (json['unit_price'] ?? '0.00').toString(),
      costPrice: (json['cost_price'] ?? '0.00').toString(),
      stockQuantity: (json['stock_quantity'] is int)
          ? json['stock_quantity'] as int
          : int.tryParse('${json['stock_quantity']}') ?? 0,
      description: (json['description'] ?? '').toString(),
      isActive: (json['is_active'] ?? false) == true,
      updatedAt: (json['updated_at'] ?? '').toString(),
    );
  }
}

class ClientRecord {
  ClientRecord({
    required this.id,
    required this.name,
    required this.phone,
    required this.email,
    required this.companyName,
    required this.address,
    required this.notes,
    required this.isActive,
    required this.updatedAt,
  });

  final int id;
  final String name;
  final String phone;
  final String email;
  final String companyName;
  final String address;
  final String notes;
  final bool isActive;
  final String updatedAt;

  factory ClientRecord.fromJson(Map<String, dynamic> json) {
    return ClientRecord(
      id: (json['id'] is int) ? json['id'] as int : int.tryParse('${json['id']}') ?? 0,
      name: (json['name'] ?? '').toString(),
      phone: (json['phone'] ?? '').toString(),
      email: (json['email'] ?? '').toString(),
      companyName: (json['company_name'] ?? '').toString(),
      address: (json['address'] ?? '').toString(),
      notes: (json['notes'] ?? '').toString(),
      isActive: (json['is_active'] ?? false) == true,
      updatedAt: (json['updated_at'] ?? '').toString(),
    );
  }
}

class PendingApprovalItem {
  PendingApprovalItem({
    required this.id,
    required this.jobCode,
    required this.jobStatus,
    required this.customerName,
    required this.customerPhone,
    required this.device,
    required this.technician,
    required this.createdAt,
    this.priority = 'medium',
    this.priorityDisplay = 'Medium',
    this.dueDate = '',
    this.instructions = '',
    this.attachmentsCount = 0,
  });

  final int id;
  final String jobCode;
  final String jobStatus;
  final String customerName;
  final String customerPhone;
  final String device;
  final String technician;
  final String createdAt;
  final String priority;
  final String priorityDisplay;
  final String dueDate;
  final String instructions;
  final int attachmentsCount;

  factory PendingApprovalItem.fromJson(Map<String, dynamic> json) {
    return PendingApprovalItem(
      id: (json['id'] is int) ? json['id'] as int : int.tryParse('${json['id']}') ?? 0,
      jobCode: (json['job_code'] ?? '').toString(),
      jobStatus: (json['job_status'] ?? '').toString(),
      customerName: (json['customer_name'] ?? '').toString(),
      customerPhone: (json['customer_phone'] ?? '').toString(),
      device: (json['device'] ?? '').toString(),
      technician: (json['technician'] ?? '').toString(),
      createdAt: (json['created_at'] ?? '').toString(),
      priority: (json['priority'] ?? 'medium').toString(),
      priorityDisplay: (json['priority_display'] ?? 'Medium').toString(),
      dueDate: (json['due_date'] ?? '').toString(),
      instructions: (json['instructions'] ?? '').toString(),
      attachmentsCount: (json['attachments_count'] is int)
          ? json['attachments_count'] as int
          : int.tryParse('${json['attachments_count']}') ?? 0,
    );
  }
}

class ProductListResponse {
  ProductListResponse({required this.canEdit, required this.products});

  final bool canEdit;
  final List<ProductRecord> products;
}

class ClientListResponse {
  ClientListResponse({required this.canEdit, required this.clients});

  final bool canEdit;
  final List<ClientRecord> clients;
}

class PendingApprovalsResponse {
  PendingApprovalsResponse({required this.canAct, required this.approvals});

  final bool canAct;
  final List<PendingApprovalItem> approvals;
}

class TopProductSummary {
  TopProductSummary({
    required this.productId,
    required this.name,
    required this.unitsSold,
    required this.revenue,
    required this.profit,
  });

  final int productId;
  final String name;
  final int unitsSold;
  final String revenue;
  final String profit;

  factory TopProductSummary.fromJson(Map<String, dynamic> json) {
    return TopProductSummary(
      productId: (json['product_id'] is int)
          ? json['product_id'] as int
          : int.tryParse('${json['product_id']}') ?? 0,
      name: (json['name'] ?? '').toString(),
      unitsSold: (json['units_sold'] is int)
          ? json['units_sold'] as int
          : int.tryParse('${json['units_sold']}') ?? 0,
      revenue: (json['revenue'] ?? '0.00').toString(),
      profit: (json['profit'] ?? '0.00').toString(),
    );
  }
}

class ReportsSummary {
  ReportsSummary({
    required this.startDate,
    required this.endDate,
    required this.preset,
    required this.jobsCreated,
    required this.jobsFinished,
    required this.jobsReturned,
    required this.vendorJobs,
    required this.overallRevenue,
    required this.overallExpense,
    required this.overallProfit,
    required this.overallMargin,
    required this.serviceRevenue,
    required this.serviceProfit,
    required this.stockSalesIncome,
    required this.stockSalesCogs,
    required this.stockSalesProfit,
    required this.stockSalesUnits,
    required this.stockProductsCount,
    required this.vendorRevenue,
    required this.vendorExpense,
    required this.vendorProfit,
    required this.topProducts,
  });

  final String startDate;
  final String endDate;
  final String preset;
  final int jobsCreated;
  final int jobsFinished;
  final int jobsReturned;
  final int vendorJobs;
  final String overallRevenue;
  final String overallExpense;
  final String overallProfit;
  final String overallMargin;
  final String serviceRevenue;
  final String serviceProfit;
  final String stockSalesIncome;
  final String stockSalesCogs;
  final String stockSalesProfit;
  final int stockSalesUnits;
  final int stockProductsCount;
  final String vendorRevenue;
  final String vendorExpense;
  final String vendorProfit;
  final List<TopProductSummary> topProducts;

  factory ReportsSummary.fromJson(Map<String, dynamic> json) {
    final period = json['period'] as Map<String, dynamic>? ?? {};
    final summary = json['summary'] as Map<String, dynamic>? ?? {};
    final topProductsRaw = json['top_products'];

    return ReportsSummary(
      startDate: (period['start_date'] ?? '').toString(),
      endDate: (period['end_date'] ?? '').toString(),
      preset: (period['preset'] ?? '').toString(),
      jobsCreated: (summary['jobs_created'] is int)
          ? summary['jobs_created'] as int
          : int.tryParse('${summary['jobs_created']}') ?? 0,
      jobsFinished: (summary['jobs_finished'] is int)
          ? summary['jobs_finished'] as int
          : int.tryParse('${summary['jobs_finished']}') ?? 0,
      jobsReturned: (summary['jobs_returned'] is int)
          ? summary['jobs_returned'] as int
          : int.tryParse('${summary['jobs_returned']}') ?? 0,
      vendorJobs: (summary['vendor_jobs'] is int)
          ? summary['vendor_jobs'] as int
          : int.tryParse('${summary['vendor_jobs']}') ?? 0,
      overallRevenue: (summary['overall_revenue'] ?? '0.00').toString(),
      overallExpense: (summary['overall_expense'] ?? '0.00').toString(),
      overallProfit: (summary['overall_profit'] ?? '0.00').toString(),
      overallMargin: (summary['overall_margin'] ?? '0.00').toString(),
      serviceRevenue: (summary['service_revenue'] ?? '0.00').toString(),
      serviceProfit: (summary['service_profit'] ?? '0.00').toString(),
      stockSalesIncome: (summary['stock_sales_income'] ?? '0.00').toString(),
      stockSalesCogs: (summary['stock_sales_cogs'] ?? '0.00').toString(),
      stockSalesProfit: (summary['stock_sales_profit'] ?? '0.00').toString(),
      stockSalesUnits: (summary['stock_sales_units'] is int)
          ? summary['stock_sales_units'] as int
          : int.tryParse('${summary['stock_sales_units']}') ?? 0,
      stockProductsCount: (summary['stock_products_count'] is int)
          ? summary['stock_products_count'] as int
          : int.tryParse('${summary['stock_products_count']}') ?? 0,
      vendorRevenue: (summary['vendor_revenue'] ?? '0.00').toString(),
      vendorExpense: (summary['vendor_expense'] ?? '0.00').toString(),
      vendorProfit: (summary['vendor_profit'] ?? '0.00').toString(),
      topProducts: topProductsRaw is List
          ? topProductsRaw
                .whereType<Map<String, dynamic>>()
                .map(TopProductSummary.fromJson)
                .toList(growable: false)
          : const [],
    );
  }
}
