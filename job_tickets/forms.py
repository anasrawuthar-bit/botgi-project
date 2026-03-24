# job_tickets/forms.py
from django import forms
from django.db.models import Q
from django.utils import timezone

from .models import (
    Client,
    CompanyProfile,
    InventoryEntry,
    InventoryParty,
    JobTicket,
    Product,
    ServiceLog,
    TechnicianProfile,
    Vendor,
    WhatsAppIntegrationSettings,
)
from django.contrib.auth.models import User, Group
from django.contrib.auth.forms import UserCreationForm
from .phone_utils import normalize_indian_phone

class TechnicianCreationForm(UserCreationForm):
    ROLE_CHOICES = [
        ('technician', 'Technician'),
        ('staff', 'Staff Member')
    ]
    
    unique_id = forms.CharField(max_length=10, required=True, help_text='Unique identifier for the user')
    role = forms.ChoiceField(choices=ROLE_CHOICES, required=True, help_text='Select whether this user is a technician or staff member')
    
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ['username', 'email']

    def save(self, commit=False):
        # We'll handle the commit and group assignment in the view
        return super().save(commit=False)

class JobTicketForm(forms.ModelForm):
    class Meta:
        model = JobTicket
        fields = ['customer_name', 'customer_phone', 'device_type', 
                  'device_brand', 'device_model', 'device_serial', 
                  'reported_issue', 'additional_items', 'is_under_warranty',
                  'estimated_amount', 'estimated_delivery']

        widgets = {
            'estimated_delivery': forms.DateInput(attrs={'type': 'date'}),

            'customer_name': forms.TextInput(attrs={
            'autocomplete': 'off'
                }),
            'customer_phone': forms.TextInput(attrs={
                'type': 'text',
                'autocomplete': 'off',
                'inputmode': 'numeric',
                'placeholder': '98765 43210',
            }),

            'device_type': forms.TextInput(attrs={
            'autocomplete': 'off'
                }),

            'device_model': forms.TextInput(attrs={
            'autocomplete': 'off'
                }),

            'device_serial': forms.TextInput(attrs={
            'autocomplete': 'off'
                }),
        }

    def clean_customer_phone(self):
        phone, error = normalize_indian_phone(
            self.cleaned_data.get('customer_phone'),
            field_label='Customer Phone',
        )
        if error:
            raise forms.ValidationError(error)
        return phone

class ServiceLogForm(forms.ModelForm):
    class Meta:
        model = ServiceLog
        fields = ['description', 'part_cost', 'service_charge']

class AssignJobForm(forms.Form):
    technician = forms.ModelChoiceField(
        queryset=TechnicianProfile.objects.all(),
        label="Assign to Technician"
    )
    job_code = forms.CharField(widget=forms.HiddenInput())

class ReworkForm(forms.Form):
    rework_reason = forms.CharField(label="Reason for Rework", widget=forms.Textarea(attrs={'class': 'form-control'}))

class DiscountForm(forms.Form):
    discount_amount = forms.DecimalField(
        label="Discount Amount",
        max_digits=10,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )


class AssignVendorForm(forms.Form):
    vendor = forms.ModelChoiceField(
        queryset=Vendor.objects.all(),
        label="Assign to Vendor",
        empty_label="-- Select a Vendor --"
    )
    # This hidden field will identify which SpecializedService record we are updating
    specialized_service_id = forms.IntegerField(widget=forms.HiddenInput())

class ReturnVendorServiceForm(forms.Form):
    """Form for when device returns from vendor - requires cost fields"""
    vendor_cost = forms.DecimalField(
        label="Vendor Cost (Our Cost)",
        required=True,
        widget=forms.NumberInput(attrs={'placeholder': 'e.g., 2500', 'step': '0.01'})
    )
    client_charge = forms.DecimalField(
        label="Client Charge",
        required=True,
        widget=forms.NumberInput(attrs={'placeholder': 'e.g., 3500', 'step': '0.01'})
    )
    specialized_service_id = forms.IntegerField(widget=forms.HiddenInput())

class ReassignTechnicianForm(forms.Form):
    job_code = forms.CharField(widget=forms.HiddenInput())
    new_technician = forms.ModelChoiceField(
        queryset=TechnicianProfile.objects.all().select_related('user'),
        label="Select New Technician",
        empty_label="--- Unassign Job ---", # Allows staff to unassign if needed
        required=False
    )

class VendorForm(forms.ModelForm):
    class Meta:
        model = Vendor
        fields = ['company_name', 'name', 'phone', 'email', 'specialties']
        widgets = {
            'specialties': forms.Textarea(attrs={'rows': 3}),
        }


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ['name', 'phone', 'address', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '98765 43210', 'inputmode': 'numeric'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def clean_phone(self):
        phone, error = normalize_indian_phone(
            self.cleaned_data.get('phone'),
            field_label='Phone number',
        )
        if error:
            raise forms.ValidationError(error)
        return phone


class ProductForm(forms.ModelForm):
    PRICE_TAX_MODE_CHOICES = [
        ('without_tax', 'Without Tax'),
        ('with_tax', 'With Tax'),
    ]
    purchase_price_tax_mode = forms.ChoiceField(
        choices=PRICE_TAX_MODE_CHOICES,
        initial='without_tax',
        label='Purchase Price Type',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    sales_price_tax_mode = forms.ChoiceField(
        choices=PRICE_TAX_MODE_CHOICES,
        initial='without_tax',
        label='Sales Price Type',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = Product
        fields = ['name', 'category', 'brand', 'cost_price', 'unit_price', 'stock_quantity', 'reserved_stock', 'description']
        labels = {
            'cost_price': 'Purchase Price',
            'unit_price': 'Sales Price',
            'stock_quantity': 'Opening Stock Quantity',
            'reserved_stock': 'Reserved Stock Alert',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.TextInput(attrs={'class': 'form-control'}),
            'brand': forms.TextInput(attrs={'class': 'form-control'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cost_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'stock_quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '1'}),
            'reserved_stock': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '1'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def clean_cost_price(self):
        cost_price = self.cleaned_data.get('cost_price')
        if cost_price is not None and cost_price < 0:
            raise forms.ValidationError('Purchase price cannot be negative.')
        return cost_price

    def clean_unit_price(self):
        unit_price = self.cleaned_data.get('unit_price')
        if unit_price is not None and unit_price < 0:
            raise forms.ValidationError('Sales price cannot be negative.')
        return unit_price

    def clean_reserved_stock(self):
        reserved_stock = self.cleaned_data.get('reserved_stock')
        if reserved_stock is not None and reserved_stock < 0:
            raise forms.ValidationError('Reserved stock cannot be negative.')
        return reserved_stock


class InventoryPartyForm(forms.ModelForm):
    class Meta:
        model = InventoryParty
        fields = [
            'name',
            'party_type',
            'phone',
            'gstin',
            'pan',
            'email',
            'address',
            'city',
            'state',
            'pincode',
            'opening_balance',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'party_type': forms.Select(attrs={'class': 'form-select'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+91XXXXXXXXXX'}),
            'gstin': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '22AAAAA0000A1Z5'}),
            'pan': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'AAAAA0000A'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'pincode': forms.TextInput(attrs={'class': 'form-control'}),
            'opening_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep supplier/customer master separated and avoid mixed "both" on new records.
        self.fields['party_type'].choices = [
            ('supplier', 'Supplier'),
            ('customer', 'Customer'),
        ]


class InventoryEntryForm(forms.ModelForm):
    class Meta:
        model = InventoryEntry
        fields = ['entry_date', 'invoice_number', 'party']
        widgets = {
            'entry_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'invoice_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Leave blank for auto invoice number'}),
            'party': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, entry_type='purchase', **kwargs):
        super().__init__(*args, **kwargs)
        self.entry_type = entry_type

        if entry_type in {'purchase', 'purchase_return'}:
            party_filter = Q(party_type='supplier')
            self.fields['party'].label = "Supplier"
        else:
            party_filter = Q(party_type='customer')
            self.fields['party'].label = "Customer"

        self.fields['party'].queryset = InventoryParty.objects.filter(is_active=True).filter(party_filter).order_by('name')
        self.fields['party'].label_from_instance = (
            lambda party: f"{party.name} ({party.phone})" if (party.phone or '').strip() else party.name
        )
        self.fields['entry_date'].initial = timezone.localdate
        if entry_type == 'sale':
            self.fields['invoice_number'].required = False
            self.fields['invoice_number'].widget.attrs.update({
                'placeholder': 'Auto generated invoice number',
                'readonly': 'readonly',
            })
        elif entry_type == 'purchase':
            self.fields['invoice_number'].required = True
            self.fields['invoice_number'].widget.attrs['placeholder'] = 'Supplier invoice number'
        else:
            self.fields['invoice_number'].required = True
            self.fields['invoice_number'].widget.attrs['placeholder'] = 'Invoice number'

class FeedbackForm(forms.Form):
    rating = forms.ChoiceField(
        choices=[(i, i) for i in range(1, 11)],
        widget=forms.RadioSelect,
        label="Rate your experience (1-10)"
    )
    comment = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4, 'placeholder': 'Share your experience with us...'}),
        required=False,
        label="Additional comments"
    )

class CompanyProfileForm(forms.ModelForm):
    class Meta:
        model = CompanyProfile
        fields = [
            'company_name', 'tagline', 'logo', 'logo_url',
            'address', 'city', 'state', 'pincode',
            'phone1', 'phone2', 'email', 'website',
            'gstin', 'pan',
            'bank_name', 'account_number', 'ifsc_code', 'branch', 'upi_id',
            'job_code_prefix',
            'enable_gst', 'gst_rate',
            'terms_conditions'
        ]
        widgets = {
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'tagline': forms.TextInput(attrs={'class': 'form-control'}),
            'logo_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://example.com/logo.png'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'pincode': forms.TextInput(attrs={'class': 'form-control'}),
            'phone1': forms.TextInput(attrs={'class': 'form-control'}),
            'phone2': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'website': forms.URLInput(attrs={'class': 'form-control'}),
            'gstin': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '22AAAAA0000A1Z5'}),
            'pan': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'AAAAA0000A'}),
            'bank_name': forms.TextInput(attrs={'class': 'form-control'}),
            'account_number': forms.TextInput(attrs={'class': 'form-control'}),
            'ifsc_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'SBIN0001234'}),
            'branch': forms.TextInput(attrs={'class': 'form-control'}),
            'upi_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'yourname@paytm'}),
            'job_code_prefix': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'GI'}),
            'gst_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'terms_conditions': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }


class WhatsAppIntegrationSettingsForm(forms.ModelForm):
    class Meta:
        model = WhatsAppIntegrationSettings
        fields = [
            'is_enabled',
            'bridge_base_url',
            'public_site_url',
            'default_country_code',
            'notify_on_created',
            'notify_on_completed',
            'notify_on_delivered',
            'created_template',
            'completed_template',
            'delivered_template',
        ]
        widgets = {
            'is_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'bridge_base_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'http://127.0.0.1:3001'}),
            'public_site_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'http://127.0.0.1:8000'}),
            'default_country_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '91'}),
            'notify_on_created': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_on_completed': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_on_delivered': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'created_template': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'completed_template': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'delivered_template': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }
