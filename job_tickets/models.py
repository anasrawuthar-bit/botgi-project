# job_tickets/models.py
from decimal import Decimal

from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.text import slugify
from django.urls import reverse

from .gst_utils import (
    validate_gstin,
    validate_hsn_sac_code,
    validate_pan,
    validate_state_code,
)

# A user profile to link to the technician
class CompanyWorkspace(models.Model):
    STATUS_TRIAL = 'trial'
    STATUS_ACTIVE = 'active'
    STATUS_SUSPENDED = 'suspended'
    STATUS_CHOICES = [
        (STATUS_TRIAL, 'Trial'),
        (STATUS_ACTIVE, 'Active'),
        (STATUS_SUSPENDED, 'Suspended'),
    ]

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name='owned_workspaces')
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_TRIAL, db_index=True)
    plan_name = models.CharField(max_length=80, default='Starter')
    timezone_name = models.CharField(max_length=80, default='Asia/Kolkata')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or 'workspace'
            slug = base_slug
            counter = 2
            while CompanyWorkspace.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)


class CompanyUserMembership(models.Model):
    ROLE_OWNER = 'owner'
    ROLE_ADMIN = 'admin'
    ROLE_STAFF = 'staff'
    ROLE_TECHNICIAN = 'technician'
    ROLE_INVENTORY = 'inventory'
    ROLE_VIEWER = 'viewer'
    ROLE_CHOICES = [
        (ROLE_OWNER, 'Owner'),
        (ROLE_ADMIN, 'Admin'),
        (ROLE_STAFF, 'Staff'),
        (ROLE_TECHNICIAN, 'Technician'),
        (ROLE_INVENTORY, 'Inventory'),
        (ROLE_VIEWER, 'Viewer'),
    ]

    workspace = models.ForeignKey(CompanyWorkspace, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='workspace_memberships')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_STAFF)
    is_active = models.BooleanField(default=True, db_index=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('workspace', 'user')
        ordering = ['workspace__name', 'user__username']

    def __str__(self):
        return f'{self.user.username} - {self.workspace.name} ({self.get_role_display()})'


class TechnicianProfile(models.Model):
    workspace = models.ForeignKey(
        CompanyWorkspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='technicians',
        db_index=True,
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='technician_profile')
    unique_id = models.CharField(max_length=10, unique=True)

    def __str__(self):
        return self.user.username


class Client(models.Model):
    workspace = models.ForeignKey(
        CompanyWorkspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='clients',
        db_index=True,
    )
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    company_name = models.CharField(max_length=200, blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['workspace', 'phone'], name='unique_client_phone_per_workspace'),
        ]

    def __str__(self):
        return f"{self.name} ({self.phone})"


class JobFieldPreset(models.Model):
    FIELD_CHOICES = [
        ('device_type', 'Device Type'),
        ('device_brand', 'Device Brand'),
        ('reported_issue', 'Reported Issue'),
        ('additional_items', 'Additional Items'),
    ]

    workspace = models.ForeignKey(
        CompanyWorkspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='job_field_presets',
        db_index=True,
    )
    field_name = models.CharField(max_length=32, choices=FIELD_CHOICES, db_index=True)
    value = models.CharField(max_length=255)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['field_name', 'sort_order', 'value']
        constraints = [
            models.UniqueConstraint(fields=['workspace', 'field_name', 'value'], name='unique_job_preset_per_workspace'),
        ]

    def __str__(self):
        return f"{self.get_field_name_display()}: {self.value}"


class DeviceChecklistTemplate(models.Model):
    workspace = models.ForeignKey(
        CompanyWorkspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='device_checklist_templates',
        db_index=True,
    )
    device_type = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Device type this checklist applies to (example: Laptop, Desktop, Printer).",
    )
    name = models.CharField(
        max_length=120,
        blank=True,
        help_text="Optional internal name shown in admin.",
    )
    notes = models.TextField(
        blank=True,
        help_text="Optional guidance shown to technicians.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['device_type']
        constraints = [
            models.UniqueConstraint(fields=['workspace', 'device_type'], name='unique_checklist_template_per_workspace'),
        ]

    def __str__(self):
        return (self.name or self.device_type).strip()


class DeviceChecklistField(models.Model):
    FIELD_TYPE_CHOICES = [
        ('text', 'Single Line Text'),
        ('textarea', 'Multi Line Text'),
        ('number', 'Number'),
        ('select', 'Dropdown Select'),
        ('checkbox', 'Checkbox'),
    ]

    template = models.ForeignKey(
        DeviceChecklistTemplate,
        on_delete=models.CASCADE,
        related_name='fields',
    )
    field_key = models.SlugField(
        max_length=64,
        help_text="Stable key used to store this answer (example: battery_health).",
    )
    label = models.CharField(max_length=120)
    field_type = models.CharField(max_length=20, choices=FIELD_TYPE_CHOICES, default='text')
    is_required = models.BooleanField(default=True)
    placeholder = models.CharField(max_length=150, blank=True)
    help_text = models.CharField(max_length=255, blank=True)
    options = models.TextField(
        blank=True,
        help_text="For dropdown fields, enter one option per line.",
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ['sort_order', 'label']
        unique_together = ('template', 'field_key')

    def __str__(self):
        return f"{self.template.device_type}: {self.label}"

    def get_option_list(self):
        return [line.strip() for line in (self.options or '').splitlines() if line.strip()]


PRODUCT_ITEM_TYPE_CHOICES = [
    ('goods', 'Goods'),
    ('service', 'Service'),
]


PRODUCT_TAX_CATEGORY_CHOICES = [
    ('taxable', 'Taxable'),
    ('exempt', 'Exempt'),
    ('nil_rated', 'Nil Rated'),
    ('non_gst', 'Non-GST'),
]


PARTY_GST_REGISTRATION_TYPE_CHOICES = [
    ('registered', 'Registered'),
    ('unregistered', 'Unregistered'),
    ('composition', 'Composition'),
    ('consumer', 'Consumer'),
    ('sez', 'SEZ'),
    ('overseas', 'Overseas'),
]


COMPANY_REGISTRATION_TYPE_CHOICES = [
    ('regular', 'Regular'),
    ('composition', 'Composition'),
    ('unregistered', 'Unregistered'),
]


FILING_FREQUENCY_CHOICES = [
    ('monthly', 'Monthly'),
    ('quarterly', 'Quarterly'),
]


ANNUAL_TURNOVER_BAND_CHOICES = [
    ('up_to_5cr', 'Up to Rs. 5 Cr'),
    ('5_to_10cr', 'Rs. 5 Cr to 10 Cr'),
    ('above_10cr', 'Above Rs. 10 Cr'),
]


class Product(models.Model):
    workspace = models.ForeignKey(
        CompanyWorkspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
        db_index=True,
    )
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=50, null=True, blank=True)
    category = models.CharField(max_length=120, blank=True)
    brand = models.CharField(max_length=120, blank=True)
    item_type = models.CharField(max_length=20, choices=PRODUCT_ITEM_TYPE_CHOICES, default='goods')
    hsn_sac_code = models.CharField(
        max_length=8,
        blank=True,
        validators=[validate_hsn_sac_code],
        help_text="HSN for goods or SAC for services.",
    )
    uqc = models.CharField(
        max_length=20,
        blank=True,
        help_text="Unit Quantity Code used in GST summaries, for example NOS or KGS.",
    )
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cost_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Internal purchase/stock cost per unit for profit calculations.",
    )
    gst_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=18,
        help_text="Default GST rate for this product or service.",
    )
    cess_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Default cess rate, if applicable.",
    )
    tax_category = models.CharField(
        max_length=20,
        choices=PRODUCT_TAX_CATEGORY_CHOICES,
        default='taxable',
    )
    is_tax_inclusive_default = models.BooleanField(
        default=False,
        help_text="Treat entered prices as tax-inclusive by default for this item.",
    )
    stock_quantity = models.IntegerField(default=0)
    reserved_stock = models.PositiveIntegerField(
        default=0,
        help_text="Minimum quantity to keep in stock for essential/reserved items.",
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['workspace', 'sku'], name='unique_product_sku_per_workspace'),
        ]

    def __str__(self):
        return self.name

    @property
    def effective_gst_rate(self):
        if self.tax_category != 'taxable':
            return Decimal('0.00')
        return self.gst_rate or Decimal('0.00')


class InventoryParty(models.Model):
    PARTY_TYPE_CHOICES = [
        ('supplier', 'Supplier'),
        ('customer', 'Customer'),
        ('both', 'Both'),
    ]

    workspace = models.ForeignKey(
        CompanyWorkspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_parties',
        db_index=True,
    )
    name = models.CharField(max_length=200)
    legal_name = models.CharField(max_length=200, blank=True)
    contact_person = models.CharField(max_length=120, blank=True)
    party_type = models.CharField(max_length=20, choices=PARTY_TYPE_CHOICES, default='both')
    gst_registration_type = models.CharField(
        max_length=20,
        choices=PARTY_GST_REGISTRATION_TYPE_CHOICES,
        default='unregistered',
    )
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    gstin = models.CharField(
        max_length=15,
        blank=True,
        validators=[validate_gstin],
        help_text="GSTIN for B2B transactions.",
    )
    pan = models.CharField(max_length=10, blank=True, validators=[validate_pan])
    state_code = models.CharField(
        max_length=2,
        blank=True,
        validators=[validate_state_code],
        help_text="2-digit GST state code.",
    )
    default_place_of_supply_state = models.CharField(
        max_length=2,
        blank=True,
        validators=[validate_state_code],
        help_text="Optional default place of supply state code for billing.",
    )
    country = models.CharField(max_length=100, blank=True, default='India')
    address = models.TextField(blank=True)
    shipping_address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    pincode = models.CharField(max_length=10, blank=True)
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


INVENTORY_ENTRY_TYPE_CHOICES = [
    ('purchase', 'Purchase'),
    ('purchase_return', 'Purchase Return'),
    ('sale', 'Sales'),
    ('sale_return', 'Sales Return'),
]


class InventoryBill(models.Model):
    workspace = models.ForeignKey(
        CompanyWorkspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_bills',
        db_index=True,
    )
    bill_number = models.CharField(max_length=40, unique=True)
    entry_type = models.CharField(max_length=20, choices=INVENTORY_ENTRY_TYPE_CHOICES)
    entry_date = models.DateField(default=timezone.localdate)
    invoice_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Supplier/customer invoice number for reference.",
    )
    invoice_date = models.DateField(
        null=True,
        blank=True,
        help_text="Original supplier/customer invoice date when different from entry date.",
    )
    job_ticket = models.ForeignKey(
        'JobTicket',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_bills',
        help_text="Linked job ticket when this bill is generated from service billing.",
    )
    party = models.ForeignKey(InventoryParty, on_delete=models.PROTECT, related_name='inventory_bills')
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_bills',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-entry_date', '-id']

    def __str__(self):
        return f"{self.get_entry_type_display()} {self.bill_number}"


class InventoryEntry(models.Model):
    ENTRY_TYPE_CHOICES = INVENTORY_ENTRY_TYPE_CHOICES

    workspace = models.ForeignKey(
        CompanyWorkspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_entries',
        db_index=True,
    )
    entry_number = models.CharField(max_length=40, unique=True)
    entry_type = models.CharField(max_length=20, choices=ENTRY_TYPE_CHOICES)
    entry_date = models.DateField(default=timezone.localdate)
    bill = models.ForeignKey('InventoryBill', on_delete=models.CASCADE, related_name='lines')
    invoice_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Supplier/customer invoice number for reference.",
    )
    job_ticket = models.ForeignKey(
        'JobTicket',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_entries',
        help_text="Linked job ticket when this sale entry is generated from job billing.",
    )

    party = models.ForeignKey(InventoryParty, on_delete=models.PROTECT, related_name='inventory_entries')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='inventory_entries')

    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=18)
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    stock_before = models.IntegerField(default=0)
    stock_after = models.IntegerField(default=0)

    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='inventory_entries')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-entry_date', '-id']

    def __str__(self):
        return f"{self.get_entry_type_display()} {self.entry_number}"

    @property
    def stock_effect(self):
        if self.entry_type in {'purchase', 'sale_return'}:
            return self.quantity
        return -self.quantity


class InventoryCreditPayment(models.Model):
    DIRECTION_PAYABLE = 'payable'
    DIRECTION_RECEIVABLE = 'receivable'
    DIRECTION_CHOICES = [
        (DIRECTION_PAYABLE, 'Payable'),
        (DIRECTION_RECEIVABLE, 'Receivable'),
    ]

    METHOD_CASH = 'cash'
    METHOD_TRANSFER = 'transfer'
    METHOD_CHOICES = [
        (METHOD_CASH, 'Cash'),
        (METHOD_TRANSFER, 'Transfer'),
    ]

    workspace = models.ForeignKey(
        CompanyWorkspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_credit_payments',
        db_index=True,
    )
    party = models.ForeignKey(InventoryParty, on_delete=models.PROTECT, related_name='credit_payments')
    bill = models.ForeignKey(InventoryBill, on_delete=models.CASCADE, related_name='credit_payments')
    direction = models.CharField(max_length=20, choices=DIRECTION_CHOICES)
    payment_date = models.DateField(default=timezone.localdate)
    payment_method = models.CharField(max_length=20, choices=METHOD_CHOICES, default=METHOD_CASH)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_before = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reference_no = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_credit_payments_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date', '-created_at']
        indexes = [
            models.Index(fields=['direction', 'payment_date']),
            models.Index(fields=['bill', 'direction']),
        ]

    def __str__(self):
        return f"{self.get_direction_display()} {self.party.name} - {self.amount}"


class JobTicket(models.Model):
    FEEDBACK_PENDING = 'pending'
    FEEDBACK_MESSAGE_SENT = 'message_sent'
    FEEDBACK_RECEIVED = 'received'
    FEEDBACK_CALLED_HAPPY = 'called_happy'
    FEEDBACK_CALLED_ISSUE = 'called_issue'
    FEEDBACK_NO_ANSWER = 'no_answer'
    FEEDBACK_CALL_LATER = 'call_later'
    FEEDBACK_FOLLOWUP_CHOICES = [
        (FEEDBACK_PENDING, 'Pending'),
        (FEEDBACK_MESSAGE_SENT, 'Message Sent'),
        (FEEDBACK_RECEIVED, 'Feedback Received'),
        (FEEDBACK_CALLED_HAPPY, 'Called - Happy'),
        (FEEDBACK_CALLED_ISSUE, 'Called - Issue'),
        (FEEDBACK_NO_ANSWER, 'No Answer'),
        (FEEDBACK_CALL_LATER, 'Call Later'),
    ]

    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Under Inspection', 'Under Inspection'),
        ('Repairing', 'Repairing'),
        ('Specialized Service', 'Specialized Service'), 
        ('Returned', 'Returned'),
        ('Completed', 'Completed'),
        ('Ready for Pickup', 'Ready for Pickup'),
        ('Closed', 'Closed'),

    ]

    workspace = models.ForeignKey(
        CompanyWorkspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='job_tickets',
        db_index=True,
    )
    job_code = models.CharField(max_length=50, unique=True, editable=False)  # Will be generated automatically

    # Customer Details
    customer_name = models.CharField(max_length=200)
    customer_phone = models.CharField(max_length=15)

    # Device Details
    device_type = models.CharField(max_length=100)  # e.g., Laptop, Desktop, Printer
    device_brand = models.CharField(max_length=100, blank=True)
    device_model = models.CharField(max_length=100, blank=True)
    device_serial = models.CharField(max_length=100, blank=True)
    reported_issue = models.TextField()
    additional_items = models.TextField(blank=True, help_text="e.g., Laptop bag, Charger, Mouse")

    # Service & Status
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='Pending')
    assigned_to = models.ForeignKey(TechnicianProfile, on_delete=models.SET_NULL, null=True, blank=True,
                                    help_text="Current accepted technician (set when assignment accepted)")
    
    # Indicates the job was newly assigned to a technician and awaiting acknowledgement
    is_new_assignment = models.BooleanField(default=False, help_text="True when job is newly assigned and awaiting technician acknowledgement.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # Re-entry option
    original_job_ticket = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                            help_text="Link to the original job ticket for re-entry/rework")

    # Add this new field for the technician's private notes
    technician_notes = models.TextField(blank=True, help_text="Internal notes for technicians/staff.")
    technician_checklist = models.JSONField(
        default=dict,
        blank=True,
        help_text="Technician checklist answers keyed by checklist field key.",
    )
    requires_laptop_inspection_checklist = models.BooleanField(
        default=False,
        help_text="When enabled for laptop jobs, the technician must complete the inspection checklist before marking the ticket completed.",
    )

    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Add a field for the user who created the ticket
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    is_under_warranty = models.BooleanField(default=False, help_text="Check if this job is under company warranty.")

    estimated_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estimation_note = models.TextField(blank=True, help_text="Customer-facing estimation/callback note.")
    estimated_delivery = models.DateField(null=True, blank=True)
    
    vyapar_invoice_number = models.CharField(max_length=50, blank=True, null=True)

    customer_group_id = models.CharField(
        max_length=50, 
        blank=True, 
        help_text="ID used to group multiple jobs from one customer submission."
    )
    
    # Feedback fields
    feedback_rating = models.IntegerField(
        null=True, 
        blank=True, 
        choices=[(i, i) for i in range(1, 11)],
        help_text="Customer rating (1-10)"
    )
    feedback_comment = models.TextField(blank=True, help_text="Customer feedback comment")
    feedback_date = models.DateTimeField(null=True, blank=True, help_text="When feedback was submitted")
    feedback_due_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When the post-service feedback follow-up becomes due.",
    )
    feedback_followup_enabled = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Enabled when this job should enter the 7-day feedback follow-up queue.",
    )
    feedback_message_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the 7-day feedback WhatsApp was queued/sent.",
    )
    feedback_followup_status = models.CharField(
        max_length=30,
        choices=FEEDBACK_FOLLOWUP_CHOICES,
        default=FEEDBACK_PENDING,
        db_index=True,
    )
    feedback_followup_note = models.TextField(blank=True)
    feedback_followup_called_at = models.DateTimeField(null=True, blank=True)
    feedback_followup_marked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='marked_feedback_followups',
    )

    def __str__(self):
        return f"Job Code: {self.job_code} - {self.customer_name}"
    
    def get_report_date(self):
        """Returns the date this job should be reported based on vendor concept.
        For vendor jobs: return date when returned from vendor
        For regular jobs: return completion/closure date
        """
        # Check if this is a vendor job
        if hasattr(self, 'specialized_service') and self.specialized_service:
            vendor_service = self.specialized_service
            # If returned from vendor, use the returned date
            if vendor_service.returned_date:
                return vendor_service.returned_date
            # If still with vendor, don't include in reports yet
            elif vendor_service.status == 'Sent to Vendor':
                return None
        
        if self.status == 'Closed' and self.closed_at:
            return self.closed_at

        # For regular jobs, use the updated_at (completion/closure date)
        return self.updated_at
    
    def is_vendor_job(self):
        """Check if this job was sent to a vendor"""
        return hasattr(self, 'specialized_service') and self.specialized_service is not None

    @property
    def has_feedback_followup_due(self):
        return bool(
            self.status == 'Closed'
            and self.feedback_followup_enabled
            and self.feedback_due_at
            and self.feedback_due_at <= timezone.now()
            and not self.feedback_rating
            and self.feedback_followup_status not in {
                self.FEEDBACK_RECEIVED,
                self.FEEDBACK_CALLED_HAPPY,
            }
        )

    # Helper: return the active (accepted) assignment or None
    def active_assignment(self):
        return self.assignments.filter(status='accepted').first()

    # Helper: called when an assignment is accepted to update job-level fields
    def _on_assignment_accepted(self, assignment):
        # Set assigned_to and move status to a progress state
        self.assigned_to = assignment.technician
        # Map acceptance to a job status — adjust if you prefer a different status
        self.status = 'Repairing'
        self.save(update_fields=['assigned_to', 'status', 'updated_at'])

    # Helper: called when assignments are rejected to possibly revert the job status
    def _on_assignment_rejected(self):
        # If no accepted assignments remain, set job back to Pending (or another desired status)
        if not self.assignments.filter(status='accepted').exists():
            self.assigned_to = None
            self.status = 'Pending'
            self.save(update_fields=['assigned_to', 'status', 'updated_at'])


class JobReminder(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_DONE = 'done'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_DONE, 'Done'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    job_ticket = models.ForeignKey(JobTicket, on_delete=models.CASCADE, related_name='reminders')
    due_at = models.DateTimeField(db_index=True)
    purpose = models.CharField(max_length=120, default='Customer callback')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    last_prompted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='job_reminders')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['due_at', 'id']
        indexes = [
            models.Index(fields=['status', 'due_at']),
        ]

    def __str__(self):
        return f"{self.job_ticket.job_code} reminder at {self.due_at:%Y-%m-%d %H:%M}"

    @property
    def is_due(self):
        return self.status == self.STATUS_PENDING and self.due_at <= timezone.now()


class JobTicketPhoto(models.Model):
    job_ticket = models.ForeignKey(JobTicket, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='job_ticket_photos/', blank=True, null=True)
    image_name = models.CharField(max_length=255, blank=True)
    image_content_type = models.CharField(max_length=100, blank=True)
    image_data = models.BinaryField(blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.job_ticket.job_code} photo {self.id}"

    @property
    def image_url(self):
        if self.image_data:
            return reverse('staff_job_photo_file', args=[self.job_ticket.job_code, self.id])
        if self.image:
            return self.image.url
        return ''


class Assignment(models.Model):
    ASSIGNMENT_STATUS = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
    ]

    job = models.ForeignKey(JobTicket, on_delete=models.CASCADE, related_name='assignments')
    technician = models.ForeignKey(TechnicianProfile, on_delete=models.CASCADE, related_name='assignments')
    status = models.CharField(max_length=16, choices=ASSIGNMENT_STATUS, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    response_note = models.TextField(blank=True)

    class Meta:
        unique_together = ('job', 'technician')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.job.job_code} → {self.technician.user.username} ({self.status})"

    def accept(self, note: str = ""):
        """
        Mark this assignment accepted. Updates job.assigned_to and job.status.
        Uses a transaction to reduce race conditions (but view-level locking recommended).
        """
        if self.status != 'pending':
            raise ValueError("Assignment already responded")

        with transaction.atomic():
            # refresh from DB to reduce race conditions
            self.refresh_from_db()
            if self.status != 'pending':
                raise ValueError("Assignment already responded")

            self.status = 'accepted'
            self.responded_at = timezone.now()
            self.response_note = note
            self.save(update_fields=['status', 'responded_at', 'response_note'])

            # Update the job ticket to reflect acceptance
            self.job._on_assignment_accepted(self)
            # Technician accepted the assignment — clear the new-assignment flag
            try:
                self.job.is_new_assignment = False
                self.job.save(update_fields=['is_new_assignment'])
            except Exception:
                # Keep acceptance even if clearing flag fails
                pass

    def reject(self, note: str = ""):
        """
        Mark this assignment rejected. If all assignments are rejected and none accepted,
        the job is reverted to Pending.
        """
        if self.status != 'pending':
            raise ValueError("Assignment already responded")

        with transaction.atomic():
            self.refresh_from_db()
            if self.status != 'pending':
                raise ValueError("Assignment already responded")

            self.status = 'rejected'
            self.responded_at = timezone.now()
            self.response_note = note
            self.save(update_fields=['status', 'responded_at', 'response_note'])

            # If there are no accepted assignments, update job status
            self.job._on_assignment_rejected()


class ServiceLog(models.Model):
    job_ticket = models.ForeignKey(JobTicket, on_delete=models.CASCADE, related_name='service_logs')
    description = models.CharField(max_length=255)
    part_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    service_charge = models.DecimalField(max_digits=10, decimal_places=2)
    
    # CORRECT PLACEMENT OF THE NEW FIELD:
    sales_invoice_number = models.CharField(
        max_length=50, 
        blank=True, 
        null=True, 
        help_text="Reference number from the external billing software."
    )
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.job_ticket.job_code} - {self.description}"


class ProductSale(models.Model):
    """Ledger of inventory sales captured from billing."""
    workspace = models.ForeignKey(
        CompanyWorkspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='product_sales',
        db_index=True,
    )
    job_ticket = models.ForeignKey(JobTicket, on_delete=models.CASCADE, related_name='product_sales')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='sales')
    service_log = models.OneToOneField(
        ServiceLog,
        on_delete=models.CASCADE,
        related_name='product_sale',
        null=True,
        blank=True,
    )
    inventory_entry = models.OneToOneField(
        InventoryEntry,
        on_delete=models.SET_NULL,
        related_name='product_sale_entry',
        null=True,
        blank=True,
        help_text="Linked inventory sales register entry for this job product sale.",
    )

    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_profit = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    sold_at = models.DateTimeField(auto_now_add=True)
    sold_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='product_sales')

    class Meta:
        ordering = ['-sold_at']

    def __str__(self):
        return f"{self.job_ticket.job_code} - {self.product.name} x{self.quantity}"


class JobTicketLog(models.Model):
    """Stores a log of all changes and events for a JobTicket."""
    ACTION_CHOICES = [
        ('CREATED', 'Job Created'),
        ('ASSIGNED', 'Technician Assigned'),
        ('STATUS', 'Status Changed'),
        ('NOTE', 'Note Updated'),
        ('SERVICE', 'Service Log Added/Updated'),
        ('BILLING', 'Billing Info Updated'),
        ('CLOSED', 'Job Closed'),
    ]

    job_ticket = models.ForeignKey(JobTicket, on_delete=models.CASCADE, related_name='logs')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, help_text="User who performed the action")
    timestamp = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    details = models.TextField(help_text="Description of the change, e.g., 'Status changed from Pending to Repairing'")

    class Meta:
        ordering = ['-timestamp'] # Show newest logs first

    def __str__(self):
        return f"{self.job_ticket.job_code} - {self.action} at {self.timestamp.strftime('%Y-%m-%d %H:%M')}"
    

# Add this new model at the end of job_tickets/models.py

class Vendor(models.Model):
    """Represents a third-party service provider or company."""
    workspace = models.ForeignKey(
        CompanyWorkspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vendors',
        db_index=True,
    )
    name = models.CharField(max_length=200, help_text="The individual's name or contact person.")
    company_name = models.CharField(max_length=255, help_text="The official name of the vendor company.")
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    specialties = models.TextField(blank=True, help_text="Notes on what this vendor specializes in, e.g., 'Motherboard chip-level repair', 'Data recovery'.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['company_name']
        constraints = [
            models.UniqueConstraint(fields=['workspace', 'company_name'], name='unique_vendor_company_per_workspace'),
        ]

    def __str__(self):
        return self.company_name
    
# Add this new model at the end of job_tickets/models.py

class SpecializedService(models.Model):
    """Tracks a job that has been sent to an external vendor."""
    STATUS_CHOICES = [
        ('Awaiting Assignment', 'Awaiting Vendor Assignment'),
        ('Sent to Vendor', 'Sent to Vendor'),
        ('Returned from Vendor', 'Returned from Vendor'),
    ]
    
    job_ticket = models.OneToOneField(JobTicket, on_delete=models.CASCADE, related_name='specialized_service')
    vendor = models.ForeignKey(Vendor, on_delete=models.SET_NULL, null=True, blank=True, related_name='services')
    
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='Awaiting Assignment')
    
    # Financials
    vendor_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="The amount we pay the vendor.")
    vendor_discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Discount or adjustment received from the vendor.",
    )
    vendor_paid_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Amount already paid to the vendor.",
    )
    vendor_balance_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Remaining amount payable to the vendor after discount and paid amount.",
    )
    client_charge = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="The amount we charge the client for this service.")
    
    # Tracking
    sent_date = models.DateTimeField(null=True, blank=True)
    returned_date = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, help_text="Internal notes about this specialized service.")

    @property
    def vendor_net_payable(self):
        vendor_cost = self.vendor_cost or Decimal('0.00')
        discount = self.vendor_discount_amount or Decimal('0.00')
        payable = vendor_cost - discount
        return payable if payable > Decimal('0.00') else Decimal('0.00')

    @property
    def vendor_payment_status(self):
        if not self.vendor_cost:
            return 'Not Entered'
        if (self.vendor_balance_amount or Decimal('0.00')) <= Decimal('0.00'):
            return 'Paid'
        if (self.vendor_paid_amount or Decimal('0.00')) > Decimal('0.00'):
            return 'Part Paid'
        return 'Balance Due'

    def __str__(self):
        return f"{self.job_ticket.job_code} -> {self.vendor.company_name if self.vendor else 'Unassigned'}"


class VendorPayment(models.Model):
    METHOD_CASH = 'cash'
    METHOD_TRANSFER = 'transfer'
    METHOD_CHOICES = [
        (METHOD_CASH, 'Cash'),
        (METHOD_TRANSFER, 'Transfer'),
    ]

    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='payments')
    specialized_service = models.ForeignKey(
        SpecializedService,
        on_delete=models.CASCADE,
        related_name='payment_transactions',
    )
    payment_date = models.DateField(default=timezone.localdate)
    payment_method = models.CharField(max_length=20, choices=METHOD_CHOICES, default=METHOD_CASH)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    balance_before = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    balance_after = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    reference_no = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendor_payments_created')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date', '-created_at']

    def __str__(self):
        return f"{self.vendor.company_name} payment {self.amount} on {self.payment_date}"


class DailyJobCodeSequence(models.Model):
    """Tracks the last issued counter for a given job-code date prefix."""
    date = models.DateField(unique=True)
    last_counter = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"{self.date}: {self.last_counter}"


class CompanyProfile(models.Model):
    """Company profile settings - single instance"""
    workspace = models.ForeignKey(
        CompanyWorkspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='company_profiles',
        db_index=True,
    )
    # Basic Info
    company_name = models.CharField(max_length=200, default="GI Hostings")
    legal_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Registered legal name used on GST documents.",
    )
    tagline = models.CharField(max_length=200, default="Service Billing", blank=True)
    logo = models.ImageField(upload_to='company_logos/', blank=True, null=True)
    logo_url = models.URLField(max_length=500, blank=True, help_text="Or use image URL")
    
    # Contact Details
    address = models.TextField(default="Your Business Address")
    city = models.CharField(max_length=100, default="", blank=True)
    state = models.CharField(max_length=100, default="", blank=True)
    pincode = models.CharField(max_length=10, default="", blank=True)
    phone1 = models.CharField(max_length=20, default="+919567227005")
    phone2 = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True, default="https://gihostings.com")
    
    # Legal & Tax Details
    gstin = models.CharField(
        max_length=15,
        blank=True,
        validators=[validate_gstin],
        help_text="GST Identification Number",
    )
    pan = models.CharField(
        max_length=10,
        blank=True,
        validators=[validate_pan],
        help_text="PAN Number",
    )
    state_code = models.CharField(
        max_length=2,
        blank=True,
        validators=[validate_state_code],
        help_text="2-digit GST state code of the business registration.",
    )
    registration_type = models.CharField(
        max_length=20,
        choices=COMPANY_REGISTRATION_TYPE_CHOICES,
        default='regular',
    )
    filing_frequency = models.CharField(
        max_length=20,
        choices=FILING_FREQUENCY_CHOICES,
        default='monthly',
    )
    qrmp_enabled = models.BooleanField(default=False, help_text="Enable quarterly return filing under QRMP.")
    lut_bond_enabled = models.BooleanField(default=False, help_text="Use LUT/Bond for eligible zero-rated supplies.")
    annual_turnover_band = models.CharField(
        max_length=20,
        choices=ANNUAL_TURNOVER_BAND_CHOICES,
        default='up_to_5cr',
    )
    e_invoice_applicable = models.BooleanField(default=False, help_text="Whether e-invoice compliance applies to this business.")
    e_way_bill_enabled = models.BooleanField(default=True, help_text="Enable e-Way Bill related workflow fields.")
    default_place_of_supply_state = models.CharField(
        max_length=2,
        blank=True,
        validators=[validate_state_code],
        help_text="Default place of supply state code used for billing.",
    )
    
    # Bank Details
    bank_name = models.CharField(max_length=200, blank=True)
    account_number = models.CharField(max_length=50, blank=True)
    ifsc_code = models.CharField(max_length=11, blank=True)
    branch = models.CharField(max_length=200, blank=True)
    upi_id = models.CharField(max_length=100, blank=True, help_text="UPI ID for payments")
    
    PRINT_PAPER_A4 = 'a4'
    PRINT_PAPER_A5 = 'a5'
    PRINT_PAPER_THERMAL_80 = 'thermal_80'
    PRINT_PAPER_CHOICES = [
        (PRINT_PAPER_A4, 'A4'),
        (PRINT_PAPER_A5, 'A5'),
        (PRINT_PAPER_THERMAL_80, 'Thermal 80mm'),
    ]
    PRINT_PAGE_SIZE_CSS = {
        PRINT_PAPER_A4: 'A4 portrait',
        PRINT_PAPER_A5: 'A5 portrait',
        PRINT_PAPER_THERMAL_80: '80mm 297mm',
    }
    PRINT_PAGE_WIDTH_CSS = {
        PRINT_PAPER_A4: '210mm',
        PRINT_PAPER_A5: '148mm',
        PRINT_PAPER_THERMAL_80: '80mm',
    }

    # Job Ticket Settings
    job_code_prefix = models.CharField(max_length=10, default="GI", help_text="Prefix for job codes (e.g., GI, SERV)")
    job_ticket_print_paper_size = models.CharField(
        max_length=20,
        choices=PRINT_PAPER_CHOICES,
        default=PRINT_PAPER_A5,
        help_text="Default paper size for job ticket / receipt prints.",
    )
    bill_print_paper_size = models.CharField(
        max_length=20,
        choices=PRINT_PAPER_CHOICES,
        default=PRINT_PAPER_A4,
        help_text="Default paper size for service and inventory bill prints.",
    )
    sales_invoice_prefix = models.CharField(
        max_length=20,
        default="INV",
        blank=True,
        help_text="Prefix for auto-generated sales invoice numbers.",
    )
    sales_invoice_next_number = models.PositiveIntegerField(
        default=1,
        help_text="Next sequence number to use for auto-generated sales invoices.",
    )
    
    # GST Settings
    enable_gst = models.BooleanField(default=False, help_text="Enable GST on invoices")
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=18.00, help_text="GST rate in percentage")
    
    # Terms & Policies
    terms_conditions = models.TextField(blank=True, default="1. All repairs carry 30 days warranty.\n2. No warranty on physical/liquid damage.\n3. Payment due on delivery.")
    warranty_policy = models.TextField(blank=True, default="30 days warranty on all repairs. Does not cover physical or liquid damage.")
    
    class Meta:
        verbose_name = "Company Profile"
        verbose_name_plural = "Company Profile"
        permissions = [
            ("view_financial_reports", "Can view financial reports"),
        ]
    
    def __str__(self):
        return self.company_name

    @staticmethod
    def _print_page_size_css(paper_size):
        return CompanyProfile.PRINT_PAGE_SIZE_CSS.get(paper_size, 'A4 portrait')

    @staticmethod
    def _print_page_width_css(paper_size):
        return CompanyProfile.PRINT_PAGE_WIDTH_CSS.get(paper_size, '210mm')

    @staticmethod
    def _print_margin_css(paper_size, default_margin='12mm'):
        if paper_size == CompanyProfile.PRINT_PAPER_THERMAL_80:
            return '3mm'
        return default_margin

    @property
    def job_ticket_print_page_size_css(self):
        return self._print_page_size_css(self.job_ticket_print_paper_size)

    @property
    def job_ticket_print_page_width_css(self):
        return self._print_page_width_css(self.job_ticket_print_paper_size)

    @property
    def job_ticket_print_margin_css(self):
        return self._print_margin_css(self.job_ticket_print_paper_size, '6mm')

    @property
    def bill_print_page_size_css(self):
        return self._print_page_size_css(self.bill_print_paper_size)

    @property
    def bill_print_page_width_css(self):
        return self._print_page_width_css(self.bill_print_paper_size)

    @property
    def bill_print_margin_css(self):
        return self._print_margin_css(self.bill_print_paper_size, '12mm')
    
    @classmethod
    def get_profile(cls, workspace=None):
        """Get or create the company profile for the active workspace."""
        if workspace:
            profile, created = cls.objects.get_or_create(
                workspace=workspace,
                defaults={'company_name': workspace.name},
            )
            return profile
        profile, created = cls.objects.get_or_create(id=1)
        return profile


class PlatformSettings(models.Model):
    """Platform-level branding and footer support settings."""
    billing_author_name = models.CharField(
        max_length=200,
        default="GI HOSTINGS",
        help_text="Footer author name shown as 'Service Billing by ...'",
    )
    support_phone = models.CharField(
        max_length=20,
        default="+91 9567227005",
        help_text="Customer support phone number displayed in footer.",
    )
    whatsapp_number = models.CharField(
        max_length=20,
        default="+91 9567227005",
        help_text="WhatsApp support number displayed in footer.",
    )
    website = models.URLField(blank=True, default="https://gihostings.com")

    class Meta:
        verbose_name = "Platform Settings"
        verbose_name_plural = "Platform Settings"

    def __str__(self):
        return self.billing_author_name

    @property
    def support_phone_href(self):
        return ''.join(ch for ch in self.support_phone if ch.isdigit() or ch == '+')

    @property
    def whatsapp_link(self):
        digits = ''.join(ch for ch in self.whatsapp_number if ch.isdigit())
        if not digits:
            return ''
        return f"https://wa.me/{digits}"

    @classmethod
    def get_settings(cls):
        settings_obj, created = cls.objects.get_or_create(id=1)
        return settings_obj


class WhatsAppIntegrationSettings(models.Model):
    """Configuration for WhatsApp delivery through Cloud API or local QR bridge."""

    DELIVERY_CLOUD_API = 'cloud_api'
    DELIVERY_BRIDGE = 'bridge'
    DELIVERY_METHOD_CHOICES = [
        (DELIVERY_CLOUD_API, 'WhatsApp Cloud API'),
        (DELIVERY_BRIDGE, 'WhatsApp Bridge (QR Login)'),
    ]

    workspace = models.ForeignKey(
        CompanyWorkspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='whatsapp_settings',
        db_index=True,
    )
    delivery_method = models.CharField(
        max_length=20,
        choices=DELIVERY_METHOD_CHOICES,
        default=DELIVERY_CLOUD_API,
        help_text="Choose how automatic WhatsApp notifications are sent.",
    )
    bridge_base_url = models.URLField(
        default='http://127.0.0.1:3001',
        help_text="Base URL of the local WhatsApp bridge service used for QR login delivery.",
    )

    api_version = models.CharField(
        max_length=16,
        default='v23.0',
        help_text="Graph API version used for WhatsApp Cloud API requests.",
    )
    phone_number_id = models.CharField(
        max_length=64,
        blank=True,
        help_text="Phone Number ID from Meta WhatsApp Manager / API Setup.",
    )
    access_token = models.TextField(
        blank=True,
        help_text="Permanent access token used to call the WhatsApp Cloud API.",
    )
    webhook_verify_token = models.CharField(
        max_length=255,
        blank=True,
        help_text="Custom verify token used while configuring the Meta webhook.",
    )
    app_secret = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional Meta app secret used to validate webhook signatures.",
    )
    public_site_url = models.URLField(
        # default='http://127.0.0.1:8000', 
        default='http://192.168.1.4:8000',
        help_text="Public base URL used for client status/receipt links sent on WhatsApp.",
    )
    is_enabled = models.BooleanField(
        default=False,
        help_text="Enable automatic WhatsApp notifications for ticket events.",
    )
    default_country_code = models.CharField(
        max_length=5,
        default='91',
        help_text="Used when a customer phone number has no country code.",
    )
    template_language_code = models.CharField(
        max_length=20,
        default='en_US',
        help_text="Language code used for approved template messages (example: en_US).",
    )
    test_template_name = models.CharField(
        max_length=100,
        default='hello_world',
        blank=True,
        help_text="Approved template name used for manual Cloud API test sends.",
    )
    notify_on_created = models.BooleanField(default=True)
    notify_on_completed = models.BooleanField(default=True)
    notify_on_delivered = models.BooleanField(default=True)
    notify_on_feedback = models.BooleanField(default=True)
    created_template_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Approved template name used for the ticket created notification.",
    )
    created_template = models.TextField(
        default=(
            "Hello {customer_name}, your ticket {job_code} has been created.\n"
            "Device: {device_type} - {device_brand} {device_model}\n"
            "Issue: {reported_issue}\n"
            "Status: {status}\n"
            "Receipt: {receipt_link}"
        )
    )
    completed_template_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Approved template name used for the ticket completed notification.",
    )
    completed_template = models.TextField(
        default=(
            "Hello {customer_name}, your ticket {job_code} is completed.\n"
            "Device: {device_brand} {device_model} ({device_type})\n"
            "Status: {status}\n"
            "Track status: {status_link}"
        )
    )
    delivered_template_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Approved template name used for the ticket delivered/closed notification.",
    )
    delivered_template = models.TextField(
        default=(
            "Hello {customer_name}, your ticket {job_code} is now closed.\n"
            "We hope you're happy with the service.\n"
            "Please share your feedback here: {status_link}"
        )
    )
    estimate_template_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Approved template name used for manual estimate messages.",
    )
    estimate_template = models.TextField(
        default=(
            "Hello {customer_name}, estimate for ticket {job_code} is {estimated_amount}.\n"
            "Device: {device_brand} {device_model} ({device_type})\n"
            "Note: {estimation_note}\n"
            "Status: {status}\n"
            "Track status: {status_link}"
        )
    )
    feedback_template_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Approved template name used for 7-day feedback follow-up messages.",
    )
    feedback_template = models.TextField(
        default=(
            "Hello {customer_name}, your ticket {job_code} was closed 7 days ago.\n"
            "Please share your service feedback here: {status_link}"
        ),
        blank=True,
    )
    created_pdf_caption_template = models.TextField(
        default="Job Ticket {job_code}",
        blank=True,
        help_text="Caption used when sending the job ticket PDF on creation.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "WhatsApp Integration Settings"
        verbose_name_plural = "WhatsApp Integration Settings"

    def __str__(self):
        return "WhatsApp Integration Settings"

    @classmethod
    def get_settings(cls, workspace=None):
        if workspace:
            settings_obj, _ = cls.objects.get_or_create(workspace=workspace)
            return settings_obj
        settings_obj, _ = cls.objects.get_or_create(id=1)
        return settings_obj


class WhatsAppNotificationLog(models.Model):
    EVENT_CHOICES = [
        ('created', 'Created'),
        ('completed', 'Completed'),
        ('delivered', 'Delivered'),
        ('estimate', 'Estimate'),
        ('feedback', 'Feedback'),
        ('manual', 'Manual'),
    ]

    message_queue = models.OneToOneField(
        'MessageQueue',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notification_log',
    )

    job_ticket = models.ForeignKey(
        JobTicket,
        on_delete=models.CASCADE,
        related_name='whatsapp_notifications',
    )
    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES)
    target_phone = models.CharField(max_length=20)
    message = models.TextField()
    was_successful = models.BooleanField(default=False)
    response_text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.job_ticket.job_code} - {self.event_type} - {'ok' if self.was_successful else 'failed'}"


class MessageQueue(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
    ]

    CHANNEL_WHATSAPP = 'whatsapp'
    CHANNEL_CHOICES = [
        (CHANNEL_WHATSAPP, 'WhatsApp'),
    ]

    EVENT_CREATED = 'created'
    EVENT_COMPLETED = 'completed'
    EVENT_DELIVERED = 'delivered'
    EVENT_ESTIMATE = 'estimate'
    EVENT_FEEDBACK = 'feedback'
    EVENT_MANUAL = 'manual'
    EVENT_CHOICES = [
        (EVENT_CREATED, 'Created'),
        (EVENT_COMPLETED, 'Completed'),
        (EVENT_DELIVERED, 'Delivered'),
        (EVENT_ESTIMATE, 'Estimate'),
        (EVENT_FEEDBACK, 'Feedback'),
        (EVENT_MANUAL, 'Manual'),
    ]

    job_ticket = models.ForeignKey(
        JobTicket,
        on_delete=models.CASCADE,
        related_name='message_queues',
        null=True,
        blank=True,
    )
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default=CHANNEL_WHATSAPP, db_index=True)
    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES, default=EVENT_MANUAL, db_index=True)
    target_phone = models.CharField(max_length=20)
    message = models.TextField(blank=True)
    pdf_url = models.URLField(blank=True)
    caption = models.TextField(blank=True)
    filename = models.CharField(max_length=255, blank=True, default='job-ticket.pdf')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    transport = models.CharField(max_length=50, blank=True, default='whatsapp-cloud-api')
    bridge_message_id = models.CharField(max_length=255, blank=True)
    bridge_status_code = models.PositiveIntegerField(null=True, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        label = self.job_ticket.job_code if self.job_ticket_id else self.target_phone
        return f"{label} - {self.event_type} - {self.status}"

    @property
    def is_document(self):
        return bool((self.pdf_url or '').strip())


class UserSessionActivity(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_LOGGED_OUT = 'logged_out'
    STATUS_EXPIRED = 'expired'
    LOGOUT_REASON_NEW_LOGIN = 'new_login_elsewhere'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_LOGGED_OUT, 'Logged Out'),
        (STATUS_EXPIRED, 'Expired'),
    ]

    CHANNEL_WEB = 'web'
    CHANNEL_ADMIN = 'admin'
    CHANNEL_API = 'api'
    CHANNEL_CHOICES = [
        (CHANNEL_WEB, 'Web'),
        (CHANNEL_ADMIN, 'Admin'),
        (CHANNEL_API, 'API'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='session_activities')
    session_key = models.CharField(max_length=64, unique=True, db_index=True)
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default=CHANNEL_WEB)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    login_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_activity_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_activity_path = models.CharField(max_length=255, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    logout_at = models.DateTimeField(null=True, blank=True)
    logout_reason = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ['-login_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['user', '-login_at']),
        ]
        verbose_name = 'User Session Activity'
        verbose_name_plural = 'User Session Activities'

    def __str__(self):
        return f"{self.user.username} - {self.get_status_display()} - {self.login_at:%Y-%m-%d %H:%M}"

    @property
    def device_label(self):
        user_agent = (self.user_agent or '').lower()
        if not user_agent:
            return 'Unknown Device'

        if 'android' in user_agent:
            os_name = 'Android'
        elif 'iphone' in user_agent or 'ipad' in user_agent or 'ios' in user_agent:
            os_name = 'iOS'
        elif 'windows' in user_agent:
            os_name = 'Windows'
        elif 'mac os' in user_agent or 'macintosh' in user_agent:
            os_name = 'macOS'
        elif 'linux' in user_agent:
            os_name = 'Linux'
        else:
            os_name = 'Unknown OS'

        if 'edg/' in user_agent:
            browser = 'Edge'
        elif 'chrome/' in user_agent and 'edg/' not in user_agent:
            browser = 'Chrome'
        elif 'firefox/' in user_agent:
            browser = 'Firefox'
        elif 'safari/' in user_agent and 'chrome/' not in user_agent:
            browser = 'Safari'
        elif 'opr/' in user_agent or 'opera' in user_agent:
            browser = 'Opera'
        else:
            browser = 'Unknown Browser'

        return f"{browser} on {os_name}"
