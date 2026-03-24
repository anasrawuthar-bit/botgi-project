# job_tickets/models.py
from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse

# A user profile to link to the technician
class TechnicianProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='technician_profile')
    unique_id = models.CharField(max_length=10, unique=True)

    def __str__(self):
        return self.user.username


class Client(models.Model):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, unique=True)
    email = models.EmailField(blank=True)
    company_name = models.CharField(max_length=200, blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.phone})"


class JobFieldPreset(models.Model):
    FIELD_CHOICES = [
        ('device_type', 'Device Type'),
        ('device_brand', 'Device Brand'),
        ('reported_issue', 'Reported Issue'),
        ('additional_items', 'Additional Items'),
    ]

    field_name = models.CharField(max_length=32, choices=FIELD_CHOICES, db_index=True)
    value = models.CharField(max_length=255)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['field_name', 'sort_order', 'value']
        unique_together = ('field_name', 'value')

    def __str__(self):
        return f"{self.get_field_name_display()}: {self.value}"


class DeviceChecklistTemplate(models.Model):
    device_type = models.CharField(
        max_length=100,
        unique=True,
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


class Product(models.Model):
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=50, unique=True, null=True, blank=True)
    category = models.CharField(max_length=120, blank=True)
    brand = models.CharField(max_length=120, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cost_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Internal purchase/stock cost per unit for profit calculations.",
    )
    stock_quantity = models.PositiveIntegerField(default=0)
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

    def __str__(self):
        return self.name


class InventoryParty(models.Model):
    PARTY_TYPE_CHOICES = [
        ('supplier', 'Supplier'),
        ('customer', 'Customer'),
        ('both', 'Both'),
    ]

    name = models.CharField(max_length=200)
    party_type = models.CharField(max_length=20, choices=PARTY_TYPE_CHOICES, default='both')
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    gstin = models.CharField(max_length=15, blank=True, help_text="GSTIN for B2B transactions.")
    pan = models.CharField(max_length=10, blank=True)
    address = models.TextField(blank=True)
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
    bill_number = models.CharField(max_length=40, unique=True)
    entry_type = models.CharField(max_length=20, choices=INVENTORY_ENTRY_TYPE_CHOICES)
    entry_date = models.DateField(default=timezone.localdate)
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


class JobTicket(models.Model):
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

    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Add a field for the user who created the ticket
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    is_under_warranty = models.BooleanField(default=False, help_text="Check if this job is under company warranty.")

    estimated_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
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
        
        # For regular jobs, use the updated_at (completion/closure date)
        return self.updated_at
    
    def is_vendor_job(self):
        """Check if this job was sent to a vendor"""
        return hasattr(self, 'specialized_service') and self.specialized_service is not None

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
    name = models.CharField(max_length=200, help_text="The individual's name or contact person.")
    company_name = models.CharField(max_length=255, unique=True, help_text="The official name of the vendor company.")
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    specialties = models.TextField(blank=True, help_text="Notes on what this vendor specializes in, e.g., 'Motherboard chip-level repair', 'Data recovery'.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['company_name']

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
    client_charge = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="The amount we charge the client for this service.")
    
    # Tracking
    sent_date = models.DateTimeField(null=True, blank=True)
    returned_date = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, help_text="Internal notes about this specialized service.")

    def __str__(self):
        return f"{self.job_ticket.job_code} -> {self.vendor.company_name if self.vendor else 'Unassigned'}"


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
    # Basic Info
    company_name = models.CharField(max_length=200, default="GI Hostings")
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
    gstin = models.CharField(max_length=15, blank=True, help_text="GST Identification Number")
    pan = models.CharField(max_length=10, blank=True, help_text="PAN Number")
    
    # Bank Details
    bank_name = models.CharField(max_length=200, blank=True)
    account_number = models.CharField(max_length=50, blank=True)
    ifsc_code = models.CharField(max_length=11, blank=True)
    branch = models.CharField(max_length=200, blank=True)
    upi_id = models.CharField(max_length=100, blank=True, help_text="UPI ID for payments")
    
    # Job Ticket Settings
    job_code_prefix = models.CharField(max_length=10, default="GI", help_text="Prefix for job codes (e.g., GI, SERV)")
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
    
    @classmethod
    def get_profile(cls):
        """Get or create the single company profile instance"""
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
    """Configuration for WhatsApp Web bridge integration (QR-based login)."""

    bridge_base_url = models.URLField(
        default='http://127.0.0.1:3001',
        help_text="Base URL of the local WhatsApp bridge service.",
    )
    public_site_url = models.URLField(
        default='http://127.0.0.1:8000',
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
    notify_on_created = models.BooleanField(default=True)
    notify_on_completed = models.BooleanField(default=True)
    notify_on_delivered = models.BooleanField(default=True)
    created_template = models.TextField(
        default=(
            "Hello {customer_name}, your ticket {job_code} has been created.\n"
            "Device: {device_type} - {device_brand} {device_model}\n"
            "Issue: {reported_issue}\n"
            "Status: {status}\n"
            "We have attached your job ticket PDF."
        )
    )
    completed_template = models.TextField(
        default=(
            "Hello {customer_name}, your ticket {job_code} is completed.\n"
            "Device: {device_brand} {device_model} ({device_type})\n"
            "Status: {status}\n"
            "Track status: {status_link}"
        )
    )
    delivered_template = models.TextField(
        default=(
            "Hello {customer_name}, your ticket {job_code} is now closed.\n"
            "We hope you're happy with the service.\n"
            "Please share your feedback here: {status_link}"
        )
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
    def get_settings(cls):
        settings_obj, _ = cls.objects.get_or_create(id=1)
        return settings_obj


class WhatsAppNotificationLog(models.Model):
    EVENT_CHOICES = [
        ('created', 'Created'),
        ('completed', 'Completed'),
        ('delivered', 'Delivered'),
    ]

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


class UserSessionActivity(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_LOGGED_OUT = 'logged_out'
    STATUS_EXPIRED = 'expired'
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
