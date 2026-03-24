import re
from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as DjangoGroupAdmin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.db.models import Count, DecimalField, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from .admin_roles import ROLE_READ_ONLY, ROLE_STAFF_ADMIN, ROLE_SUPER_ADMIN
from .models import (
    Assignment,
    Client,
    CompanyProfile,
    DailyJobCodeSequence,
    DeviceChecklistField,
    DeviceChecklistTemplate,
    InventoryEntry,
    InventoryParty,
    JobFieldPreset,
    JobTicket,
    JobTicketLog,
    PlatformSettings,
    ProductSale,
    Product,
    ServiceLog,
    SpecializedService,
    TechnicianProfile,
    UserSessionActivity,
    Vendor,
    WhatsAppIntegrationSettings,
    WhatsAppNotificationLog,
)

PROTECTED_JOB_DELETE_STATUSES = {'Completed', 'Ready for Pickup', 'Closed'}
LOCKED_JOB_STATUSES = {'Ready for Pickup', 'Closed'}


def _has_group(user, group_name):
    return user.groups.filter(name=group_name).exists()


def is_super_admin_user(user):
    return user.is_superuser or _has_group(user, ROLE_SUPER_ADMIN)


def is_staff_admin_user(user):
    return _has_group(user, ROLE_STAFF_ADMIN)


def is_read_only_user(user):
    return _has_group(user, ROLE_READ_ONLY)


def is_allowed_admin_user(user):
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        return False
    return is_super_admin_user(user) or is_staff_admin_user(user) or is_read_only_user(user)


def is_job_locked(job):
    return job.status in LOCKED_JOB_STATUSES or bool(job.vyapar_invoice_number)


def is_job_delete_protected(job):
    return (
        bool(job.vyapar_invoice_number)
        or job.status in PROTECTED_JOB_DELETE_STATUSES
        or job.service_logs.exists()
    )


class RoleBasedAdminMixin:
    """Role control for Django admin models."""

    staff_can_add = True
    staff_can_change = True
    staff_can_delete = False

    class Media:
        css = {'all': ('admin/css/custom_admin.css',)}

    def has_module_permission(self, request):
        return is_allowed_admin_user(request.user)

    def has_view_permission(self, request, obj=None):
        return is_allowed_admin_user(request.user)

    def has_add_permission(self, request):
        user = request.user
        if is_super_admin_user(user):
            return True
        if is_staff_admin_user(user):
            return self.staff_can_add
        return False

    def has_change_permission(self, request, obj=None):
        user = request.user
        if is_super_admin_user(user):
            return True
        if is_staff_admin_user(user):
            return self.staff_can_change
        return False

    def has_delete_permission(self, request, obj=None):
        user = request.user
        if is_super_admin_user(user):
            return True
        if is_staff_admin_user(user):
            return self.staff_can_delete
        return False


class SuperAdminOnlyMixin(RoleBasedAdminMixin):
    """Only super admins can access this admin model."""

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_staff and is_super_admin_user(request.user)

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff and is_super_admin_user(request.user)

    def has_add_permission(self, request):
        return request.user.is_active and request.user.is_staff and is_super_admin_user(request.user)

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff and is_super_admin_user(request.user)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff and is_super_admin_user(request.user)


class ImmutableAuditAdminMixin(RoleBasedAdminMixin):
    """Read-only admin for audit models."""

    staff_can_add = False
    staff_can_change = False
    staff_can_delete = False
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ClientAdminForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = '__all__'

    def clean_phone(self):
        raw_phone = (self.cleaned_data.get('phone') or '').strip()
        normalized_phone = re.sub(r'\s+', '', raw_phone)

        if not re.fullmatch(r'^\+?\d{8,15}$', normalized_phone):
            raise ValidationError("Phone must contain 8 to 15 digits (optional '+' prefix).")

        duplicate_qs = Client.objects.filter(phone=normalized_phone)
        if self.instance.pk:
            duplicate_qs = duplicate_qs.exclude(pk=self.instance.pk)
        if duplicate_qs.exists():
            raise ValidationError("A client with this phone already exists.")

        return normalized_phone


class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = '__all__'

    def clean_unit_price(self):
        unit_price = self.cleaned_data.get('unit_price')
        if unit_price is not None and unit_price < 0:
            raise ValidationError("Unit price cannot be negative.")
        return unit_price

    def clean_cost_price(self):
        cost_price = self.cleaned_data.get('cost_price')
        if cost_price is not None and cost_price < 0:
            raise ValidationError("Cost price cannot be negative.")
        return cost_price


class JobTicketAdminForm(forms.ModelForm):
    class Meta:
        model = JobTicket
        fields = '__all__'

    def clean_discount_amount(self):
        discount = self.cleaned_data.get('discount_amount')
        if discount is not None and discount < 0:
            raise ValidationError("Discount cannot be negative.")
        return discount

    def clean_estimated_amount(self):
        amount = self.cleaned_data.get('estimated_amount')
        if amount is not None and amount < 0:
            raise ValidationError("Estimated amount cannot be negative.")
        return amount


@admin.register(JobTicket)
class JobTicketAdmin(RoleBasedAdminMixin, admin.ModelAdmin):
    form = JobTicketAdminForm
    list_display = (
        'job_code',
        'customer_name',
        'customer_phone',
        'device_type',
        'status',
        'assigned_technician',
        'invoice_number',
        'parts_total',
        'service_total',
        'grand_total',
        'updated_at',
    )
    list_filter = (
        'status',
        'is_under_warranty',
        'assigned_to',
        'created_at',
        'updated_at',
    )
    search_fields = (
        'job_code',
        'customer_name',
        'customer_phone',
        'device_type',
        'device_brand',
        'device_model',
        'device_serial',
        'vyapar_invoice_number',
    )
    date_hierarchy = 'created_at'
    list_per_page = 50
    raw_id_fields = ('assigned_to', 'created_by', 'original_job_ticket')
    readonly_fields = (
        'job_code',
        'parts_total',
        'service_total',
        'grand_total',
        'billing_lock_status',
        'created_at',
        'updated_at',
    )
    fieldsets = (
        ("Ticket Identity", {'fields': ('job_code', 'status', 'billing_lock_status')}),
        ("Client", {'fields': ('customer_name', 'customer_phone')}),
        (
            "Device",
            {'fields': (
                'device_type',
                'device_brand',
                'device_model',
                'device_serial',
                'reported_issue',
                'additional_items',
            )},
        ),
        (
            "Operations",
            {'fields': (
                'assigned_to',
                'is_under_warranty',
                'estimated_amount',
                'estimated_delivery',
                'discount_amount',
                'vyapar_invoice_number',
            )},
        ),
        (
            "Reference",
            {'fields': ('original_job_ticket', 'created_by', 'customer_group_id', 'technician_notes')},
        ),
        ("Audit", {'fields': ('parts_total', 'service_total', 'grand_total', 'created_at', 'updated_at')}),
    )
    actions = ('mark_selected_ready_for_pickup', 'mark_selected_closed', 'reopen_selected_jobs')

    def get_queryset(self, request):
        money_field = DecimalField(max_digits=12, decimal_places=2)
        return (
            super()
            .get_queryset(request)
            .select_related('assigned_to__user', 'created_by')
            .annotate(
                parts_total_sum=Coalesce(
                    Sum('service_logs__part_cost', output_field=money_field),
                    Value(Decimal('0.00'), output_field=money_field),
                    output_field=money_field,
                ),
                service_total_sum=Coalesce(
                    Sum('service_logs__service_charge', output_field=money_field),
                    Value(Decimal('0.00'), output_field=money_field),
                    output_field=money_field,
                ),
            )
        )

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is None:
            readonly = [field for field in readonly if field not in {'parts_total', 'service_total', 'grand_total', 'billing_lock_status'}]
        if obj and is_job_locked(obj):
            readonly.extend(
                [
                    'customer_name',
                    'customer_phone',
                    'device_type',
                    'device_brand',
                    'device_model',
                    'device_serial',
                    'reported_issue',
                    'additional_items',
                    'assigned_to',
                    'estimated_amount',
                    'estimated_delivery',
                    'discount_amount',
                    'is_under_warranty',
                    'original_job_ticket',
                    'technician_notes',
                ]
            )
        return tuple(dict.fromkeys(readonly))

    @admin.display(description="Technician", ordering='assigned_to__user__username')
    def assigned_technician(self, obj):
        if obj.assigned_to and obj.assigned_to.user:
            return obj.assigned_to.user.username
        return "-"

    @admin.display(description="Invoice No")
    def invoice_number(self, obj):
        return obj.vyapar_invoice_number or "-"

    @admin.display(description="Parts Total (Rs)", ordering='parts_total_sum')
    def parts_total(self, obj):
        value = getattr(obj, 'parts_total_sum', Decimal('0.00')) or Decimal('0.00')
        return f"{value:.2f}"

    @admin.display(description="Service Total (Rs)", ordering='service_total_sum')
    def service_total(self, obj):
        value = getattr(obj, 'service_total_sum', Decimal('0.00')) or Decimal('0.00')
        return f"{value:.2f}"

    @admin.display(description="Grand Total (Rs)")
    def grand_total(self, obj):
        if obj is None:
            return "0.00"
        parts = getattr(obj, 'parts_total_sum', Decimal('0.00')) or Decimal('0.00')
        service = getattr(obj, 'service_total_sum', Decimal('0.00')) or Decimal('0.00')
        return f"{(parts + service - (obj.discount_amount or Decimal('0.00'))):.2f}"

    @admin.display(description="Billing Lock")
    def billing_lock_status(self, obj):
        if obj is None:
            return "Open"
        if not obj.pk:
            return "Open"
        if obj.vyapar_invoice_number:
            return f"Locked - Invoice: {obj.vyapar_invoice_number}"
        if obj.status in LOCKED_JOB_STATUSES:
            return f"Locked - Status: {obj.status}"
        return "Open"

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        if obj and is_job_delete_protected(obj):
            return False
        return super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions

    def delete_queryset(self, request, queryset):
        protected = []
        deletable_ids = []
        for job in queryset:
            if is_job_delete_protected(job):
                protected.append(job.job_code)
            else:
                deletable_ids.append(job.id)

        if deletable_ids:
            super().delete_queryset(request, queryset.filter(id__in=deletable_ids))
        if protected:
            self.message_user(
                request,
                f"Skipped protected jobs: {', '.join(protected)}",
                level=messages.ERROR,
            )

    @admin.action(description="Mark selected jobs as Ready for Pickup")
    def mark_selected_ready_for_pickup(self, request, queryset):
        updated = 0
        skipped = 0
        for job in queryset:
            if job.status == 'Completed':
                job.status = 'Ready for Pickup'
                job.save(update_fields=['status', 'updated_at'])
                updated += 1
            else:
                skipped += 1
        if updated:
            self.message_user(request, f"{updated} job(s) moved to Ready for Pickup.", level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f"{skipped} job(s) skipped due to status mismatch.", level=messages.WARNING)

    @admin.action(description="Mark selected jobs as Closed")
    def mark_selected_closed(self, request, queryset):
        updated = 0
        skipped = 0
        for job in queryset:
            if job.status in {'Ready for Pickup', 'Returned'}:
                job.status = 'Closed'
                job.save(update_fields=['status', 'updated_at'])
                updated += 1
            else:
                skipped += 1
        if updated:
            self.message_user(request, f"{updated} job(s) marked as Closed.", level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f"{skipped} job(s) skipped due to status mismatch.", level=messages.WARNING)

    @admin.action(description="Reopen selected jobs to Pending")
    def reopen_selected_jobs(self, request, queryset):
        updated = 0
        skipped = 0
        for job in queryset:
            if job.status in {'Pending', 'Under Inspection', 'Repairing', 'Specialized Service'}:
                skipped += 1
                continue
            if job.vyapar_invoice_number:
                skipped += 1
                continue
            job.status = 'Pending'
            job.save(update_fields=['status', 'updated_at'])
            updated += 1
        if updated:
            self.message_user(request, f"{updated} job(s) reopened to Pending.", level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f"{skipped} job(s) skipped (already active or billed).", level=messages.WARNING)


@admin.register(ServiceLog)
class ServiceLogAdmin(RoleBasedAdminMixin, admin.ModelAdmin):
    staff_can_add = False
    staff_can_change = False
    staff_can_delete = False

    list_display = (
        'job_code',
        'description',
        'part_cost',
        'service_charge',
        'sales_invoice_number',
        'created_at',
    )
    search_fields = (
        'job_ticket__job_code',
        'job_ticket__customer_phone',
        'description',
        'sales_invoice_number',
    )
    list_filter = ('created_at',)
    raw_id_fields = ('job_ticket',)
    readonly_fields = ('created_at',)
    list_select_related = ('job_ticket',)
    list_per_page = 75

    @admin.display(description="Job Code", ordering='job_ticket__job_code')
    def job_code(self, obj):
        return obj.job_ticket.job_code

    def has_change_permission(self, request, obj=None):
        if obj and is_job_locked(obj.job_ticket):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and is_job_locked(obj.job_ticket):
            return False
        return super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions


@admin.register(Client)
class ClientAdmin(RoleBasedAdminMixin, admin.ModelAdmin):
    form = ClientAdminForm
    list_display = ('phone', 'name', 'jobs_count', 'latest_device', 'created_at', 'updated_at')
    search_fields = ('phone', 'name', 'address', 'notes')
    ordering = ('phone',)
    list_filter = ('created_at', 'updated_at')
    readonly_fields = ('created_at', 'updated_at', 'jobs_count', 'latest_device')
    list_per_page = 75

    def get_queryset(self, request):
        jobs_count_subquery = (
            JobTicket.objects.filter(customer_phone=OuterRef('phone'))
            .values('customer_phone')
            .annotate(total=Count('id'))
            .values('total')[:1]
        )
        latest_device_subquery = (
            JobTicket.objects.filter(customer_phone=OuterRef('phone'))
            .order_by('-created_at')
            .values('device_type')[:1]
        )
        return super().get_queryset(request).annotate(
            jobs_count_value=Coalesce(
                Subquery(jobs_count_subquery, output_field=IntegerField()),
                Value(0),
                output_field=IntegerField(),
            ),
            latest_device_value=Coalesce(
                Subquery(latest_device_subquery),
                Value('-'),
            ),
        )

    @admin.display(description="Jobs", ordering='jobs_count_value')
    def jobs_count(self, obj):
        return getattr(obj, 'jobs_count_value', 0)

    @admin.display(description="Latest Device", ordering='latest_device_value')
    def latest_device(self, obj):
        return getattr(obj, 'latest_device_value', '-') or '-'

    def has_delete_permission(self, request, obj=None):
        if obj and JobTicket.objects.filter(customer_phone=obj.phone).exists():
            return False
        return super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions

    def delete_queryset(self, request, queryset):
        protected_phones = []
        deletable_ids = []
        for client in queryset:
            if JobTicket.objects.filter(customer_phone=client.phone).exists():
                protected_phones.append(client.phone)
            else:
                deletable_ids.append(client.id)

        if deletable_ids:
            super().delete_queryset(request, queryset.filter(id__in=deletable_ids))
        if protected_phones:
            self.message_user(
                request,
                f"Skipped clients with service history: {', '.join(protected_phones)}",
                level=messages.ERROR,
            )


@admin.register(JobFieldPreset)
class JobFieldPresetAdmin(RoleBasedAdminMixin, admin.ModelAdmin):
    list_display = ('field_name', 'value', 'sort_order', 'is_active', 'updated_at')
    list_filter = ('field_name', 'is_active')
    search_fields = ('value',)
    ordering = ('field_name', 'sort_order', 'value')
    list_per_page = 100


class DeviceChecklistFieldInline(admin.TabularInline):
    model = DeviceChecklistField
    extra = 1
    fields = (
        'sort_order',
        'field_key',
        'label',
        'field_type',
        'is_required',
        'placeholder',
        'help_text',
        'options',
        'is_active',
    )
    ordering = ('sort_order', 'label')


@admin.register(DeviceChecklistTemplate)
class DeviceChecklistTemplateAdmin(RoleBasedAdminMixin, admin.ModelAdmin):
    list_display = ('device_type', 'name', 'is_active', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('device_type', 'name', 'notes')
    ordering = ('device_type',)
    inlines = [DeviceChecklistFieldInline]
    list_per_page = 100


@admin.register(Product)
class ProductAdmin(RoleBasedAdminMixin, admin.ModelAdmin):
    form = ProductAdminForm
    list_display = (
        'name',
        'sku',
        'category',
        'brand',
        'unit_price',
        'cost_price',
        'stock_quantity',
        'stock_status',
        'updated_at',
    )
    search_fields = ('name', 'sku', 'category', 'brand', 'description')
    list_filter = ('category', 'brand', 'updated_at')
    ordering = ('name',)
    readonly_fields = ('created_at', 'updated_at')
    list_per_page = 75

    @admin.display(description="Stock Status")
    def stock_status(self, obj):
        if obj.stock_quantity <= 0:
            return "Out of Stock"
        if obj.stock_quantity <= 5:
            return "Low Stock"
        return "In Stock"

    def _has_sales_history(self, product):
        return ProductSale.objects.filter(product=product).exists()

    def has_delete_permission(self, request, obj=None):
        if obj and (obj.stock_quantity > 0 or self._has_sales_history(obj)):
            return False
        return super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions

    def delete_queryset(self, request, queryset):
        blocked = []
        deletable_ids = []
        for product in queryset:
            if product.stock_quantity > 0 or self._has_sales_history(product):
                blocked.append(product.name)
            else:
                deletable_ids.append(product.id)

        if deletable_ids:
            super().delete_queryset(request, queryset.filter(id__in=deletable_ids))
        if blocked:
            self.message_user(
                request,
                f"Skipped products with stock or sales history: {', '.join(blocked)}",
                level=messages.ERROR,
            )


@admin.register(ProductSale)
class ProductSaleAdmin(ImmutableAuditAdminMixin, admin.ModelAdmin):
    list_display = (
        'job_code',
        'product',
        'quantity',
        'unit_price',
        'cost_price',
        'line_total',
        'line_cost',
        'line_profit',
        'sold_at',
        'sold_by',
    )
    search_fields = (
        'job_ticket__job_code',
        'job_ticket__customer_phone',
        'product__name',
        'product__sku',
    )
    list_filter = ('sold_at', 'product__category')
    raw_id_fields = ('job_ticket', 'product', 'service_log', 'sold_by')
    readonly_fields = (
        'job_ticket',
        'product',
        'service_log',
        'quantity',
        'unit_price',
        'cost_price',
        'line_total',
        'line_cost',
        'line_profit',
        'sold_at',
        'sold_by',
    )
    list_select_related = ('job_ticket', 'product', 'sold_by')
    list_per_page = 100

    @admin.display(description='Job Code', ordering='job_ticket__job_code')
    def job_code(self, obj):
        return obj.job_ticket.job_code


@admin.register(Vendor)
class VendorAdmin(RoleBasedAdminMixin, admin.ModelAdmin):
    list_display = ('company_name', 'name', 'phone', 'email', 'active_jobs_count', 'created_at')
    search_fields = ('company_name', 'name', 'phone', 'email', 'specialties')
    list_filter = ('created_at',)
    ordering = ('company_name',)
    readonly_fields = ('created_at', 'active_jobs_count')
    list_per_page = 75

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            active_jobs_count_value=Count('services', filter=Q(services__status='Sent to Vendor'))
        )

    @admin.display(description="Active Jobs", ordering='active_jobs_count_value')
    def active_jobs_count(self, obj):
        return getattr(obj, 'active_jobs_count_value', 0)

    def has_delete_permission(self, request, obj=None):
        if obj and SpecializedService.objects.filter(vendor=obj, status='Sent to Vendor').exists():
            return False
        return super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions


@admin.register(SpecializedService)
class SpecializedServiceAdmin(RoleBasedAdminMixin, admin.ModelAdmin):
    staff_can_delete = False

    list_display = (
        'job_ticket',
        'vendor',
        'status',
        'vendor_cost',
        'client_charge',
        'sent_date',
        'returned_date',
    )
    list_filter = ('status', 'vendor', 'sent_date', 'returned_date')
    search_fields = ('job_ticket__job_code', 'job_ticket__customer_phone', 'vendor__company_name')
    raw_id_fields = ('job_ticket', 'vendor')
    readonly_fields = ('sent_date', 'returned_date')
    list_select_related = ('job_ticket', 'vendor')
    list_per_page = 75

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions


@admin.register(Assignment)
class AssignmentAdmin(RoleBasedAdminMixin, admin.ModelAdmin):
    staff_can_add = False
    staff_can_change = False
    staff_can_delete = False

    list_display = ('job', 'technician', 'status', 'created_at', 'responded_at')
    list_filter = ('status', 'created_at', 'responded_at')
    search_fields = ('job__job_code', 'technician__user__username', 'response_note')
    raw_id_fields = ('job', 'technician')
    readonly_fields = ('created_at', 'responded_at')
    list_select_related = ('job', 'technician__user')
    list_per_page = 75

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions


@admin.register(TechnicianProfile)
class TechnicianProfileAdmin(SuperAdminOnlyMixin, admin.ModelAdmin):
    list_display = ('user', 'unique_id')
    search_fields = ('user__username', 'unique_id')
    list_select_related = ('user',)
    list_per_page = 75

    def has_delete_permission(self, request, obj=None):
        if obj and (JobTicket.objects.filter(assigned_to=obj).exists() or Assignment.objects.filter(technician=obj).exists()):
            return False
        return super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions


@admin.register(JobTicketLog)
class JobTicketLogAdmin(ImmutableAuditAdminMixin, admin.ModelAdmin):
    list_display = ('job_ticket', 'action', 'user', 'timestamp', 'details')
    search_fields = ('job_ticket__job_code', 'action', 'details', 'user__username')
    list_filter = ('action', 'timestamp')
    raw_id_fields = ('job_ticket', 'user')
    readonly_fields = ('job_ticket', 'action', 'user', 'timestamp', 'details')
    list_select_related = ('job_ticket', 'user')
    list_per_page = 100


@admin.register(DailyJobCodeSequence)
class DailyJobCodeSequenceAdmin(ImmutableAuditAdminMixin, admin.ModelAdmin):
    list_display = ('date', 'last_counter')
    ordering = ('-date',)
    readonly_fields = ('date', 'last_counter')
    list_per_page = 100


@admin.register(CompanyProfile)
class CompanyProfileAdmin(RoleBasedAdminMixin, admin.ModelAdmin):
    staff_can_add = False
    staff_can_delete = False

    list_display = ('company_name', 'tagline', 'phone1', 'website', 'enable_gst')
    search_fields = ('company_name', 'phone1', 'email', 'website')
    fieldsets = (
        ("Brand", {'fields': ('company_name', 'tagline', 'logo', 'logo_url')}),
        (
            "Contact",
            {'fields': ('address', 'city', 'state', 'pincode', 'phone1', 'phone2', 'email', 'website')},
        ),
        (
            "Tax & Banking",
            {'fields': ('gstin', 'pan', 'bank_name', 'account_number', 'ifsc_code', 'branch', 'upi_id')},
        ),
        ("Invoice", {'fields': ('job_code_prefix', 'sales_invoice_next_number', 'enable_gst', 'gst_rate')}),
        ("Policy", {'fields': ('terms_conditions', 'warranty_policy')}),
    )

    def has_add_permission(self, request):
        if CompanyProfile.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions


@admin.register(PlatformSettings)
class PlatformSettingsAdmin(RoleBasedAdminMixin, admin.ModelAdmin):
    staff_can_add = False
    staff_can_delete = False

    list_display = ('billing_author_name', 'support_phone', 'whatsapp_number', 'website')
    search_fields = ('billing_author_name', 'support_phone', 'whatsapp_number', 'website')
    fieldsets = (
        (
            "Footer Branding",
            {'fields': ('billing_author_name',)},
        ),
        (
            "Support Channels",
            {'fields': ('support_phone', 'whatsapp_number', 'website')},
        ),
    )

    def has_add_permission(self, request):
        if PlatformSettings.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions


@admin.register(WhatsAppIntegrationSettings)
class WhatsAppIntegrationSettingsAdmin(RoleBasedAdminMixin, admin.ModelAdmin):
    staff_can_add = False
    staff_can_delete = False

    list_display = (
        'is_enabled',
        'bridge_base_url',
        'public_site_url',
        'default_country_code',
        'notify_on_created',
        'notify_on_completed',
        'notify_on_delivered',
        'updated_at',
    )
    fieldsets = (
        ("Connection", {'fields': ('is_enabled', 'bridge_base_url', 'public_site_url', 'default_country_code')}),
        ("Events", {'fields': ('notify_on_created', 'notify_on_completed', 'notify_on_delivered')}),
        ("Templates", {'fields': ('created_template', 'completed_template', 'delivered_template')}),
    )

    def has_add_permission(self, request):
        if WhatsAppIntegrationSettings.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions


@admin.register(WhatsAppNotificationLog)
class WhatsAppNotificationLogAdmin(ImmutableAuditAdminMixin, admin.ModelAdmin):
    list_display = ('job_ticket', 'event_type', 'target_phone', 'was_successful', 'created_at')
    list_filter = ('event_type', 'was_successful', 'created_at')
    search_fields = ('job_ticket__job_code', 'target_phone', 'message', 'response_text')
    raw_id_fields = ('job_ticket',)
    readonly_fields = ('job_ticket', 'event_type', 'target_phone', 'message', 'was_successful', 'response_text', 'created_at')
    list_select_related = ('job_ticket',)
    list_per_page = 100


@admin.register(InventoryParty)
class InventoryPartyAdmin(RoleBasedAdminMixin, admin.ModelAdmin):
    staff_can_delete = False

    list_display = ('name', 'party_type', 'phone', 'gstin', 'is_active', 'updated_at')
    list_filter = ('party_type', 'is_active', 'state')
    search_fields = ('name', 'phone', 'gstin', 'pan', 'city')
    ordering = ('name',)
    list_per_page = 100

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions


@admin.register(InventoryEntry)
class InventoryEntryAdmin(ImmutableAuditAdminMixin, admin.ModelAdmin):
    list_display = (
        'entry_number',
        'invoice_number',
        'entry_date',
        'entry_type',
        'party',
        'product',
        'quantity',
        'total_amount',
        'stock_before',
        'stock_after',
    )
    list_filter = ('entry_type', 'entry_date')
    search_fields = ('entry_number', 'invoice_number', 'party__name', 'product__name', 'notes')
    raw_id_fields = ('party', 'product', 'created_by')
    readonly_fields = (
        'entry_number',
        'invoice_number',
        'entry_type',
        'entry_date',
        'party',
        'product',
        'quantity',
        'unit_price',
        'discount_amount',
        'gst_rate',
        'taxable_amount',
        'gst_amount',
        'total_amount',
        'stock_before',
        'stock_after',
        'notes',
        'created_by',
        'created_at',
    )
    list_select_related = ('party', 'product', 'created_by')
    list_per_page = 100


@admin.register(UserSessionActivity)
class UserSessionActivityAdmin(ImmutableAuditAdminMixin, admin.ModelAdmin):
    list_display = ('user', 'channel', 'device_label', 'status', 'ip_address', 'login_at', 'last_activity_at', 'logout_at')
    list_filter = ('channel', 'status', 'login_at')
    search_fields = ('user__username', 'session_key', 'ip_address', 'user_agent', 'last_activity_path')
    raw_id_fields = ('user',)
    readonly_fields = (
        'user',
        'session_key',
        'channel',
        'device_label',
        'status',
        'ip_address',
        'user_agent',
        'login_at',
        'last_activity_at',
        'last_activity_path',
        'expires_at',
        'logout_at',
        'logout_reason',
    )
    list_select_related = ('user',)
    list_per_page = 100

    @admin.display(description='Device')
    def device_label(self, obj):
        return obj.device_label


class SecureUserAdmin(SuperAdminOnlyMixin, DjangoUserAdmin):
    pass


class SecureGroupAdmin(SuperAdminOnlyMixin, DjangoGroupAdmin):
    pass


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

try:
    admin.site.unregister(Group)
except admin.sites.NotRegistered:
    pass

admin.site.register(User, SecureUserAdmin)
admin.site.register(Group, SecureGroupAdmin)

admin.site.site_header = "GI Hostings | Service Billing Administration"
admin.site.site_title = "GI Hostings Admin"
admin.site.index_title = "Operations Control Panel"
admin.site.site_url = "/"
admin.site.disable_action('delete_selected')
