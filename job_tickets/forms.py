# job_tickets/forms.py
from decimal import Decimal

from django import forms
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
from .gst_utils import (
    normalize_compact_code,
    normalize_text_code,
)
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


def get_assignable_technician_queryset():
    return (
        TechnicianProfile.objects.filter(
            user__is_active=True,
            user__is_staff=False,
        )
        .select_related('user')
        .order_by('user__username')
    )


class AssignJobForm(forms.Form):
    technician = forms.ModelChoiceField(
        queryset=TechnicianProfile.objects.none(),
        label="Assign to Technician"
    )
    job_code = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['technician'].queryset = get_assignable_technician_queryset()

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
        queryset=TechnicianProfile.objects.none(),
        label="Select New Technician",
        empty_label="--- Unassign Job ---", # Allows staff to unassign if needed
        required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_technician'].queryset = get_assignable_technician_queryset()

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
        fields = [
            'name',
            'category',
            'brand',
            'item_type',
            'hsn_sac_code',
            'uqc',
            'tax_category',
            'gst_rate',
            'cess_rate',
            'is_tax_inclusive_default',
            'cost_price',
            'unit_price',
            'stock_quantity',
            'reserved_stock',
            'description',
        ]
        labels = {
            'item_type': 'Item Type',
            'hsn_sac_code': 'HSN / SAC Code',
            'uqc': 'UQC',
            'tax_category': 'Tax Category',
            'gst_rate': 'GST Rate (%)',
            'cess_rate': 'Cess Rate (%)',
            'is_tax_inclusive_default': 'Prices include tax by default',
            'cost_price': 'Purchase Price',
            'unit_price': 'Sales Price',
            'stock_quantity': 'Opening Stock Quantity',
            'reserved_stock': 'Reserved Stock Alert',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.TextInput(attrs={'class': 'form-control'}),
            'brand': forms.TextInput(attrs={'class': 'form-control'}),
            'item_type': forms.Select(attrs={'class': 'form-select'}),
            'hsn_sac_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '8471 or 9987'}),
            'uqc': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'NOS, KGS, BOX'}),
            'tax_category': forms.Select(attrs={'class': 'form-select'}),
            'gst_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'cess_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'is_tax_inclusive_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cost_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'stock_quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '1'}),
            'reserved_stock': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '1'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and not getattr(self.instance, 'pk', None):
            try:
                self.fields['gst_rate'].initial = CompanyProfile.get_profile().gst_rate or Decimal('18.00')
            except Exception:
                self.fields['gst_rate'].initial = Decimal('18.00')
            self.fields['uqc'].initial = 'NOS'
            self.fields['cess_rate'].initial = Decimal('0.00')
            self.fields['cost_price'].initial = Decimal('0.00')
            self.fields['unit_price'].initial = Decimal('0.00')
            self.fields['stock_quantity'].initial = 0
            self.fields['reserved_stock'].initial = 0

    def clean_hsn_sac_code(self):
        return normalize_compact_code(self.cleaned_data.get('hsn_sac_code'))

    def clean_uqc(self):
        return normalize_text_code(self.cleaned_data.get('uqc'))

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

    def clean_gst_rate(self):
        gst_rate = self.cleaned_data.get('gst_rate')
        if gst_rate is not None and gst_rate < 0:
            raise forms.ValidationError('GST rate cannot be negative.')
        return gst_rate

    def clean_cess_rate(self):
        cess_rate = self.cleaned_data.get('cess_rate')
        if cess_rate is not None and cess_rate < 0:
            raise forms.ValidationError('Cess rate cannot be negative.')
        return cess_rate

    def clean(self):
        cleaned_data = super().clean()
        tax_category = cleaned_data.get('tax_category') or 'taxable'
        gst_rate = cleaned_data.get('gst_rate') or Decimal('0.00')
        cess_rate = cleaned_data.get('cess_rate') or Decimal('0.00')

        if tax_category != 'taxable':
            if gst_rate > 0:
                self.add_error('gst_rate', 'GST rate must be 0 for exempt, nil-rated, or non-GST items.')
            if cess_rate > 0:
                self.add_error('cess_rate', 'Cess rate must be 0 for exempt, nil-rated, or non-GST items.')

        return cleaned_data


class InventoryPartyForm(forms.ModelForm):
    class Meta:
        model = InventoryParty
        fields = [
            'name',
            'legal_name',
            'contact_person',
            'gst_registration_type',
            'phone',
            'gstin',
            'state_code',
            'default_place_of_supply_state',
            'pan',
            'email',
            'address',
            'shipping_address',
            'city',
            'state',
            'country',
            'pincode',
            'opening_balance',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'legal_name': forms.TextInput(attrs={'class': 'form-control'}),
            'contact_person': forms.TextInput(attrs={'class': 'form-control'}),
            'gst_registration_type': forms.Select(attrs={'class': 'form-select'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+91XXXXXXXXXX'}),
            'gstin': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '22AAAAA0000A1Z5'}),
            'state_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '32'}),
            'default_place_of_supply_state': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '32'}),
            'pan': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'AAAAA0000A'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'shipping_address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'country': forms.TextInput(attrs={'class': 'form-control'}),
            'pincode': forms.TextInput(attrs={'class': 'form-control'}),
            'opening_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'name': 'Party Name',
            'legal_name': 'Legal Name',
            'contact_person': 'Contact Person',
            'gst_registration_type': 'GST Registration',
            'state_code': 'State Code',
            'default_place_of_supply_state': 'Default POS State',
            'address': 'Billing Address',
            'shipping_address': 'Shipping Address',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and not getattr(self.instance, 'pk', None):
            self.fields['country'].initial = 'India'
            self.fields['opening_balance'].initial = Decimal('0.00')
            self.fields['is_active'].initial = True

    def clean_gstin(self):
        return normalize_compact_code(self.cleaned_data.get('gstin'))

    def clean_pan(self):
        return normalize_compact_code(self.cleaned_data.get('pan'))

    def clean_state_code(self):
        return normalize_compact_code(self.cleaned_data.get('state_code'))

    def clean_default_place_of_supply_state(self):
        return normalize_compact_code(self.cleaned_data.get('default_place_of_supply_state'))

    def clean_country(self):
        return (self.cleaned_data.get('country') or '').strip() or 'India'

    def clean(self):
        cleaned_data = super().clean()
        gstin = cleaned_data.get('gstin') or ''
        state_code = cleaned_data.get('state_code') or ''
        registration_type = cleaned_data.get('gst_registration_type') or 'unregistered'
        default_pos = cleaned_data.get('default_place_of_supply_state') or ''

        if gstin and not state_code:
            cleaned_data['state_code'] = gstin[:2]
            state_code = cleaned_data['state_code']

        if gstin and state_code and gstin[:2] != state_code:
            self.add_error('state_code', 'State code must match the first two digits of the GSTIN.')

        if registration_type in {'registered', 'composition', 'sez'} and not gstin:
            self.add_error('gstin', 'GSTIN is required for the selected registration type.')

        if not default_pos and state_code:
            cleaned_data['default_place_of_supply_state'] = state_code

        return cleaned_data

    def save(self, commit=True):
        party = super().save(commit=False)
        # Keep a single shared party master for both purchase and sales flows.
        party.party_type = 'both'
        if commit:
            party.save()
            self.save_m2m()
        return party


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

        self.fields['party'].label = "Party"
        self.fields['party'].queryset = InventoryParty.objects.filter(is_active=True).order_by('name')
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
            self.fields['invoice_number'].widget.attrs['placeholder'] = 'Party invoice number'
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
            'company_name', 'legal_name', 'tagline', 'logo', 'logo_url',
            'address', 'city', 'state', 'pincode',
            'phone1', 'phone2', 'email', 'website',
            'gstin', 'pan', 'state_code', 'registration_type', 'filing_frequency', 'qrmp_enabled',
            'lut_bond_enabled', 'annual_turnover_band', 'e_invoice_applicable', 'e_way_bill_enabled',
            'default_place_of_supply_state',
            'bank_name', 'account_number', 'ifsc_code', 'branch', 'upi_id',
            'job_code_prefix',
            'enable_gst', 'gst_rate',
            'terms_conditions'
        ]
        widgets = {
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'legal_name': forms.TextInput(attrs={'class': 'form-control'}),
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
            'state_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '32'}),
            'registration_type': forms.Select(attrs={'class': 'form-select'}),
            'filing_frequency': forms.Select(attrs={'class': 'form-select'}),
            'qrmp_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'lut_bond_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'annual_turnover_band': forms.Select(attrs={'class': 'form-select'}),
            'e_invoice_applicable': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'e_way_bill_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'default_place_of_supply_state': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '32'}),
            'bank_name': forms.TextInput(attrs={'class': 'form-control'}),
            'account_number': forms.TextInput(attrs={'class': 'form-control'}),
            'ifsc_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'SBIN0001234'}),
            'branch': forms.TextInput(attrs={'class': 'form-control'}),
            'upi_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'yourname@paytm'}),
            'job_code_prefix': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'GI'}),
            'gst_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'terms_conditions': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }
        labels = {
            'legal_name': 'Legal Name',
            'state_code': 'State Code',
            'default_place_of_supply_state': 'Default POS State',
            'qrmp_enabled': 'Enable QRMP',
            'lut_bond_enabled': 'LUT / Bond Enabled',
            'e_invoice_applicable': 'E-Invoice Applicable',
            'e_way_bill_enabled': 'Enable e-Way Bill',
        }

    def clean_gstin(self):
        return normalize_compact_code(self.cleaned_data.get('gstin'))

    def clean_pan(self):
        return normalize_compact_code(self.cleaned_data.get('pan'))

    def clean_state_code(self):
        return normalize_compact_code(self.cleaned_data.get('state_code'))

    def clean_default_place_of_supply_state(self):
        return normalize_compact_code(self.cleaned_data.get('default_place_of_supply_state'))

    def clean_gst_rate(self):
        gst_rate = self.cleaned_data.get('gst_rate')
        if gst_rate is not None and gst_rate < 0:
            raise forms.ValidationError('GST rate cannot be negative.')
        return gst_rate

    def clean(self):
        cleaned_data = super().clean()
        gstin = cleaned_data.get('gstin') or ''
        state_code = cleaned_data.get('state_code') or ''
        default_pos = cleaned_data.get('default_place_of_supply_state') or ''
        registration_type = cleaned_data.get('registration_type') or 'regular'
        enable_gst = bool(cleaned_data.get('enable_gst'))
        filing_frequency = cleaned_data.get('filing_frequency') or 'monthly'
        qrmp_enabled = bool(cleaned_data.get('qrmp_enabled'))

        if gstin and not state_code:
            cleaned_data['state_code'] = gstin[:2]
            state_code = cleaned_data['state_code']

        if gstin and state_code and gstin[:2] != state_code:
            self.add_error('state_code', 'State code must match the first two digits of the GSTIN.')

        if enable_gst and registration_type != 'unregistered' and not gstin:
            self.add_error('gstin', 'GSTIN is required when GST billing is enabled for a registered business.')

        if qrmp_enabled and filing_frequency != 'quarterly':
            self.add_error('filing_frequency', 'QRMP can only be enabled when filing frequency is quarterly.')

        if not default_pos and state_code:
            cleaned_data['default_place_of_supply_state'] = state_code

        return cleaned_data


class WhatsAppIntegrationSettingsForm(forms.ModelForm):
    class Meta:
        model = WhatsAppIntegrationSettings
        fields = [
            'is_enabled',
            'api_version',
            'phone_number_id',
            'access_token',
            'webhook_verify_token',
            'app_secret',
            'public_site_url',
            'default_country_code',
            'template_language_code',
            'test_template_name',
            'notify_on_created',
            'notify_on_completed',
            'notify_on_delivered',
            'created_template_name',
            'created_template',
            'completed_template_name',
            'completed_template',
            'delivered_template_name',
            'delivered_template',
        ]
        widgets = {
            'is_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'api_version': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'v23.0'}),
            'phone_number_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '123456789012345'}),
            'access_token': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'EAAG...'}),
            'webhook_verify_token': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'choose-a-random-secret'}),
            'app_secret': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Meta app secret (optional)'}),
            'public_site_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'http://127.0.0.1:8000'}),
            'default_country_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '91'}),
            'template_language_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'en_US'}),
            'test_template_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'hello_world'}),
            'notify_on_created': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_on_completed': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_on_delivered': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'created_template_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'job_created_update'}),
            'created_template': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'completed_template_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'job_completed_update'}),
            'completed_template': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'delivered_template_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'job_closed_update'}),
            'delivered_template': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }

    def clean(self):
        cleaned_data = super().clean()

        text_fields = [
            'api_version',
            'phone_number_id',
            'access_token',
            'webhook_verify_token',
            'app_secret',
            'public_site_url',
            'default_country_code',
            'template_language_code',
            'test_template_name',
            'created_template_name',
            'completed_template_name',
            'delivered_template_name',
        ]
        for field_name in text_fields:
            value = cleaned_data.get(field_name)
            if isinstance(value, str):
                cleaned_data[field_name] = value.strip()

        if not cleaned_data.get('is_enabled'):
            return cleaned_data

        required_fields = {
            'api_version': 'API version is required when WhatsApp notifications are enabled.',
            'phone_number_id': 'Phone Number ID is required when WhatsApp notifications are enabled.',
            'access_token': 'Access token is required when WhatsApp notifications are enabled.',
            'public_site_url': 'Public Site URL is required so status and receipt links work correctly.',
            'template_language_code': 'Template language code is required when WhatsApp notifications are enabled.',
        }
        for field_name, error_message in required_fields.items():
            if not cleaned_data.get(field_name):
                self.add_error(field_name, error_message)

        if cleaned_data.get('notify_on_created') and not cleaned_data.get('created_template_name'):
            self.add_error('created_template_name', 'Approved template name is required for created notifications.')
        if cleaned_data.get('notify_on_completed') and not cleaned_data.get('completed_template_name'):
            self.add_error('completed_template_name', 'Approved template name is required for completed notifications.')
        if cleaned_data.get('notify_on_delivered') and not cleaned_data.get('delivered_template_name'):
            self.add_error('delivered_template_name', 'Approved template name is required for delivered notifications.')

        return cleaned_data
