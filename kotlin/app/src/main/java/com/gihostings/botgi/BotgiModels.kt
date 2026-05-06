package com.gihostings.botgi

data class UserSession(
    val baseUrl: String,
    val token: String,
    val username: String,
    val role: String,
    val technicianId: String
)

data class JobSummary(
    val jobCode: String,
    val customerName: String,
    val customerPhone: String,
    val device: String,
    val status: String,
    val updatedAt: String,
    val total: String,
    val partTotal: String,
    val serviceTotal: String,
    val isNewAssignment: Boolean,
    val returnedFromVendor: Boolean
)

data class JobDetail(
    val jobCode: String,
    val status: String,
    val statusDisplay: String,
    val customerName: String,
    val customerPhone: String,
    val deviceType: String,
    val deviceBrand: String,
    val deviceModel: String,
    val deviceSerial: String,
    val reportedIssue: String,
    val additionalItems: String,
    val technicianNotes: String,
    val financials: Financials,
    val serviceLines: List<ServiceLine>,
    val timeline: List<TimelineEntry>,
    val actions: List<JobAction>,
    val permissions: JobPermissions,
    val statusChoices: List<StatusChoice>,
    val canChangeStatus: Boolean,
    val checklistRequiredForCompletion: Boolean,
    val specializedService: SpecializedServiceInfo,
    val checklistTitle: String,
    val checklistNotes: String,
    val checklistFields: List<ChecklistField>,
    val photos: List<JobPhoto>
)

data class Financials(
    val partTotal: String,
    val serviceTotal: String,
    val subtotal: String,
    val discountAmount: String,
    val grandTotal: String
)

data class ServiceLine(
    val id: Int,
    val description: String,
    val partCost: String,
    val serviceCharge: String,
    val createdAt: String,
    val isProductSale: Boolean
)

data class TimelineEntry(
    val label: String,
    val details: String,
    val timestamp: String,
    val user: String
)

data class JobAction(
    val key: String,
    val label: String
)

data class JobPermissions(
    val canEditNotes: Boolean,
    val canManageServiceLogs: Boolean,
    val canChangeStatus: Boolean,
    val canRequestSpecializedService: Boolean
)

data class StatusChoice(
    val value: String,
    val label: String
)

data class SpecializedServiceInfo(
    val exists: Boolean,
    val status: String,
    val statusDisplay: String,
    val vendorName: String,
    val notes: String
)

data class ChecklistField(
    val key: String,
    val label: String,
    val type: String,
    val required: Boolean,
    val placeholder: String,
    val helpText: String,
    val options: List<String>,
    val value: String
)

data class JobPhoto(
    val id: Int,
    val name: String,
    val contentType: String,
    val uploadedAt: String,
    val url: String
)
