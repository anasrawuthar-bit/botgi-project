# Shared imports, constants, and helper functions extracted from the former
# monolithic job_tickets/views.py module.
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from ..forms import TechnicianCreationForm
from ..access_control import (
    ACCESS_OPTIONS,
    apply_staff_access,
    clear_staff_access,
    get_staff_access,
    parse_access_keys,
    user_has_staff_access,
)
from datetime import datetime, timedelta, date
from django.db.models import Max, Q, Sum, Count, F, DecimalField, Value, OuterRef, Subquery, IntegerField
from ..models import (
    Assignment,
    Client,
    CompanyProfile,
    DailyJobCodeSequence,
    DeviceChecklistTemplate,
    InventoryBill,
    InventoryEntry,
    InventoryParty,
    JobFieldPreset,
    JobTicket,
    JobTicketPhoto,
    JobTicketLog,
    Product,
    ProductSale,
    ServiceLog,
    SpecializedService,
    TechnicianProfile,
    UserSessionActivity,
    Vendor,
    WhatsAppIntegrationSettings,
)
from ..forms import JobTicketForm, AssignJobForm, ServiceLogForm, ReworkForm, DiscountForm, AssignVendorForm, ReturnVendorServiceForm, ReassignTechnicianForm, VendorForm, FeedbackForm, CompanyProfileForm, ClientForm, ProductForm, InventoryPartyForm, InventoryEntryForm, WhatsAppIntegrationSettingsForm, get_assignable_technician_queryset
from ..gst_utils import effective_tax_rate
from ..phone_utils import normalize_indian_phone, phone_lookup_variants
from ..whatsapp_service import verify_receipt_access_token
from django.db import transaction, OperationalError, ProgrammingError
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseBadRequest, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.contrib import messages
from django.db.models.functions import Coalesce
from decimal import Decimal, InvalidOperation
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from uuid import uuid4 
from django.urls import Resolver404, resolve, reverse
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.conf import settings
from types import SimpleNamespace
import csv
import mimetypes
import re
import base64
import hmac
import hashlib
import json
from urllib.parse import urlencode, urlsplit

PRODUCT_SALE_LOG_PATTERN = re.compile(
    r'^Product Sale - (?P<name>.+?) \(Qty: (?P<qty>\d+)\)(?: \[PROD#(?P<product_id>\d+)\])?$'
)

JOB_PRESET_FIELDS = ('device_type', 'device_brand', 'reported_issue', 'additional_items')
MOBILE_JWT_EXP_SECONDS = 60 * 60 * 24 * 7  # 7 days
MOBILE_JWT_ALGORITHM = 'HS256'
CHECKLIST_FIELD_TYPES = {'text', 'textarea', 'number', 'select', 'checkbox'}
DEFAULT_LAPTOP_CHECKLIST_SCHEMA = [
    {
        'key': 'ports_condition',
        'label': 'Ports Condition',
        'type': 'select',
        'required': True,
        'options': ['Good', 'Issue Found', 'Not Tested'],
        'placeholder': '',
        'help_text': 'USB/Type-C/HDMI/audio ports.',
    },
    {
        'key': 'speaker_condition',
        'label': 'Speaker Condition',
        'type': 'select',
        'required': True,
        'options': ['Good', 'Issue Found', 'Not Tested'],
        'placeholder': '',
        'help_text': '',
    },
    {
        'key': 'body_condition',
        'label': 'Body Condition',
        'type': 'select',
        'required': True,
        'options': ['Good', 'Minor Damage', 'Major Damage'],
        'placeholder': '',
        'help_text': '',
    },
    {
        'key': 'screen_condition',
        'label': 'Screen Condition',
        'type': 'select',
        'required': True,
        'options': ['Good', 'Minor Issue', 'Major Issue'],
        'placeholder': '',
        'help_text': '',
    },
    {
        'key': 'keyboard_condition',
        'label': 'Keyboard Condition',
        'type': 'select',
        'required': True,
        'options': ['Good', 'Issue Found', 'Not Tested'],
        'placeholder': '',
        'help_text': '',
    },
    {
        'key': 'touchpad_condition',
        'label': 'Touchpad Condition',
        'type': 'select',
        'required': True,
        'options': ['Good', 'Issue Found', 'Not Tested'],
        'placeholder': '',
        'help_text': '',
    },
    {
        'key': 'hinges_condition',
        'label': 'Hinges Condition',
        'type': 'select',
        'required': True,
        'options': ['Good', 'Loose', 'Broken'],
        'placeholder': '',
        'help_text': '',
    },
    {
        'key': 'battery_health',
        'label': 'Battery Health',
        'type': 'text',
        'required': True,
        'options': [],
        'placeholder': 'Example: 82% / Good / Needs replacement',
        'help_text': '',
    },
    {
        'key': 'cpu_spec',
        'label': 'CPU',
        'type': 'text',
        'required': True,
        'options': [],
        'placeholder': 'Example: Intel i5 11th Gen',
        'help_text': '',
    },
    {
        'key': 'ram_spec_gb',
        'label': 'RAM (GB)',
        'type': 'text',
        'required': True,
        'options': [],
        'placeholder': 'Example: 8 GB DDR4',
        'help_text': '',
    },
    {
        'key': 'ssd_spec_gb',
        'label': 'SSD (GB)',
        'type': 'text',
        'required': True,
        'options': [],
        'placeholder': 'Example: 512 GB',
        'help_text': '',
    },
    {
        'key': 'hdd_spec_gb',
        'label': 'HDD (GB)',
        'type': 'text',
        'required': True,
        'options': [],
        'placeholder': 'Example: 1000 GB / None',
        'help_text': '',
    },
]

def _normalize_device_type(raw_device_type):
    return re.sub(r'\s+', ' ', (raw_device_type or '').strip()).lower()

def _sanitize_checklist_key(raw_key):
    key = re.sub(r'[^a-z0-9_]+', '_', (raw_key or '').strip().lower())
    return re.sub(r'_+', '_', key).strip('_')

def _normalize_checklist_answer(raw_value):
    if raw_value is None:
        return ''
    return str(raw_value).strip()

def _normalize_checkbox_answer(raw_value):
    value = _normalize_checklist_answer(raw_value).lower()
    return '1' if value in {'1', 'true', 'yes', 'on', 'checked'} else ''

def _get_job_checklist_answers(job):
    raw_data = getattr(job, 'technician_checklist', None)
    return raw_data if isinstance(raw_data, dict) else {}

def _apply_job_checklist_rules(job, normalized_type, checklist_schema, checklist_notes):
    if not checklist_schema:
        return checklist_schema, checklist_notes

    if 'laptop' not in normalized_type:
        return checklist_schema, checklist_notes

    requires_checklist = bool(getattr(job, 'requires_laptop_inspection_checklist', False))
    if requires_checklist:
        required_note = 'This checklist must be completed before the technician can mark the job as completed.'
        if checklist_notes:
            checklist_notes = f"{checklist_notes} {required_note}".strip()
        else:
            checklist_notes = required_note
        return checklist_schema, checklist_notes

    optional_note = 'Checklist is optional for this job. Technician can complete the ticket even without filling these fields.'
    checklist_schema = [{**field, 'required': False} for field in checklist_schema]
    if checklist_notes:
        checklist_notes = f"{checklist_notes} {optional_note}".strip()
    else:
        checklist_notes = optional_note
    return checklist_schema, checklist_notes

def _checklist_requires_completion(checklist_schema):
    return any(field.get('required') for field in (checklist_schema or []))

def _build_checklist_schema_for_job(job):
    device_type = (getattr(job, 'device_type', '') or '').strip()
    normalized_type = _normalize_device_type(device_type)
    answers = _get_job_checklist_answers(job)

    schema = []
    checklist_title = ''
    checklist_notes = ''

    template = None
    if device_type:
        template = (
            DeviceChecklistTemplate.objects.filter(is_active=True, device_type__iexact=device_type)
            .prefetch_related('fields')
            .first()
        )

    if template:
        checklist_title = (template.name or template.device_type).strip()
        checklist_notes = (template.notes or '').strip()
        active_fields = [field for field in template.fields.all() if field.is_active]
        active_fields.sort(key=lambda field: (field.sort_order, (field.label or '').lower()))

        seen_keys = set()
        for field in active_fields:
            field_key = _sanitize_checklist_key(field.field_key)
            if not field_key or field_key in seen_keys:
                continue
            seen_keys.add(field_key)

            field_type = field.field_type if field.field_type in CHECKLIST_FIELD_TYPES else 'text'
            options = field.get_option_list() if field_type == 'select' else []
            if field_type == 'checkbox':
                value = _normalize_checkbox_answer(answers.get(field_key, ''))
            else:
                value = _normalize_checklist_answer(answers.get(field_key, ''))
            if field_type == 'select' and value and value not in options:
                options.append(value)

            schema.append(
                {
                    'key': field_key,
                    'label': (field.label or field_key.replace('_', ' ').title()).strip(),
                    'type': field_type,
                    'required': bool(field.is_required),
                    'placeholder': (field.placeholder or '').strip(),
                    'help_text': (field.help_text or '').strip(),
                    'options': options,
                    'value': value,
                }
            )

    elif 'laptop' in normalized_type:
        checklist_title = 'Laptop Full Check'
        checklist_notes = 'Default checklist is active. Staff/admin can override from admin using Device Checklist Templates.'
        for item in DEFAULT_LAPTOP_CHECKLIST_SCHEMA:
            field_key = _sanitize_checklist_key(item.get('key', ''))
            if not field_key:
                continue
            schema.append(
                {
                    'key': field_key,
                    'label': item.get('label', field_key.replace('_', ' ').title()),
                    'type': item.get('type', 'text'),
                    'required': bool(item.get('required', False)),
                    'placeholder': item.get('placeholder', ''),
                    'help_text': item.get('help_text', ''),
                    'options': list(item.get('options') or []),
                    'value': _normalize_checklist_answer(answers.get(field_key, '')),
                }
            )

    schema, checklist_notes = _apply_job_checklist_rules(
        job,
        normalized_type,
        schema,
        checklist_notes,
    )
    return schema, checklist_title, checklist_notes

def _extract_checklist_answers_from_post(post_data, checklist_schema):
    cleaned = {}
    missing_required_labels = []
    invalid_option_labels = []

    for field in checklist_schema:
        key = field['key']
        field_type = field.get('type')
        if field_type == 'checkbox':
            value = _normalize_checkbox_answer(post_data.get(f'checklist_{key}', ''))
        else:
            value = _normalize_checklist_answer(post_data.get(f'checklist_{key}', ''))
        options = field.get('options') or []

        if field_type == 'select' and value and options and value not in options:
            invalid_option_labels.append(field['label'])
            value = ''

        cleaned[key] = value

        if field.get('required') and not value:
            missing_required_labels.append(field['label'])

    return cleaned, missing_required_labels, invalid_option_labels

def _merge_checklist_answers(existing_answers, posted_answers):
    merged = dict(existing_answers or {})
    merged.update(posted_answers or {})
    return merged

def _missing_required_checklist_labels(job, checklist_schema):
    answers = _get_job_checklist_answers(job)
    missing = []
    for field in checklist_schema:
        if not field.get('required'):
            continue
        if field.get('type') == 'checkbox':
            value = _normalize_checkbox_answer(answers.get(field['key'], ''))
        else:
            value = _normalize_checklist_answer(answers.get(field['key'], ''))
        if not value:
            missing.append(field['label'])
    return missing

def _format_checklist_required_error(missing_labels):
    if not missing_labels:
        return 'Checklist is incomplete.'
    preview = ', '.join(missing_labels[:6])
    suffix = '...' if len(missing_labels) > 6 else ''
    return f"Complete required checklist fields before marking completed: {preview}{suffix}"

def _b64url_encode(raw_bytes):
    return base64.urlsafe_b64encode(raw_bytes).decode('utf-8').rstrip('=')

def _b64url_decode(encoded_text):
    padding = '=' * (-len(encoded_text) % 4)
    return base64.urlsafe_b64decode(f"{encoded_text}{padding}")

def issue_mobile_jwt(user):
    now_ts = int(timezone.now().timestamp())
    payload = {
        'sub': str(user.id),
        'username': user.username,
        'is_staff': bool(user.is_staff),
        'iat': now_ts,
        'exp': now_ts + MOBILE_JWT_EXP_SECONDS,
    }
    header = {'alg': MOBILE_JWT_ALGORITHM, 'typ': 'JWT'}
    header_b64 = _b64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8'))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(',', ':')).encode('utf-8'))
    signing_input = f"{header_b64}.{payload_b64}".encode('utf-8')
    signature = hmac.new(settings.SECRET_KEY.encode('utf-8'), signing_input, hashlib.sha256).digest()
    signature_b64 = _b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{signature_b64}"

def decode_mobile_jwt(token):
    token = (token or '').strip()
    token_parts = token.split('.')
    if len(token_parts) != 3:
        return None, "Token format is invalid."

    header_b64, payload_b64, signature_b64 = token_parts
    signing_input = f"{header_b64}.{payload_b64}".encode('utf-8')
    expected_signature = hmac.new(settings.SECRET_KEY.encode('utf-8'), signing_input, hashlib.sha256).digest()
    expected_signature_b64 = _b64url_encode(expected_signature)
    if not hmac.compare_digest(expected_signature_b64, signature_b64):
        return None, "Token signature mismatch."

    try:
        header = json.loads(_b64url_decode(header_b64).decode('utf-8'))
        payload = json.loads(_b64url_decode(payload_b64).decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None, "Token payload is invalid."

    if header.get('alg') != MOBILE_JWT_ALGORITHM:
        return None, "Unsupported token algorithm."

    try:
        exp_ts = int(payload.get('exp', 0))
    except (TypeError, ValueError):
        return None, "Token expiration value is invalid."

    if exp_ts <= int(timezone.now().timestamp()):
        return None, "Token has expired."

    return payload, None

def authenticate_mobile_request(request):
    auth_header = (request.headers.get('Authorization') or '').strip()
    if not auth_header.startswith('Bearer '):
        return None, JsonResponse(
            {'error': 'missing_token', 'message': 'Authorization header missing Bearer token.'},
            status=401,
        )

    token = auth_header.split(' ', 1)[1].strip()
    payload, error_message = decode_mobile_jwt(token)
    if error_message:
        return None, JsonResponse({'error': 'invalid_token', 'message': error_message}, status=401)

    user_id = payload.get('sub')
    try:
        user = User.objects.get(id=int(user_id), is_active=True)
    except (TypeError, ValueError, User.DoesNotExist):
        return None, JsonResponse({'error': 'invalid_user', 'message': 'Token user no longer exists.'}, status=401)

    return user, None

def get_mobile_job_permissions(user, job):
    is_assigned_tech = (
        hasattr(user, 'technician_profile') and
        job.assigned_to_id == user.technician_profile.id
    )
    staff_can_access = bool(user.is_staff and user_has_staff_access(user, "staff_dashboard"))
    can_access = staff_can_access or is_assigned_tech
    return {
        'is_staff': bool(staff_can_access),
        'is_assigned_tech': bool(is_assigned_tech),
        'can_access': bool(can_access),
    }

def user_can_view_financial_reports(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    if user.has_perm("job_tickets.view_financial_reports"):
        return True
    access = get_staff_access(user)
    return bool(
        access.get("reports_dashboard")
        or access.get("reports_financial")
        or access.get("reports_technician")
        or access.get("reports_vendor")
    )

def _staff_access_required(request, key, json=False):
    if not request.user.is_staff or not user_has_staff_access(request.user, key):
        if json:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        return redirect('unauthorized')
    return None

def get_mobile_job_available_actions(user, job):
    permissions = get_mobile_job_permissions(user, job)
    if not permissions['can_access']:
        return []

    actions = []
    if job.status in ['Pending', 'Under Inspection']:
        actions.append({'key': 'start', 'label': 'Mark Started'})

    if job.status in ['Under Inspection', 'Repairing', 'Specialized Service']:
        actions.append({'key': 'complete', 'label': 'Mark Completed'})

    if permissions['is_staff'] and job.status == 'Completed':
        actions.append({'key': 'ready_for_pickup', 'label': 'Ready for Pickup'})

    if permissions['is_staff'] and job.status in ['Completed', 'Ready for Pickup']:
        actions.append({'key': 'close', 'label': 'Close Job'})

    return actions

def mobile_can_edit_notes(user, job):
    permissions = get_mobile_job_permissions(user, job)
    return bool(permissions['can_access'])

def mobile_can_manage_service_lines(user, job):
    permissions = get_mobile_job_permissions(user, job)
    if not permissions['can_access']:
        return False

    # Do not allow manual line changes while job is with vendor.
    if job.status == 'Specialized Service':
        return False

    # Staff can manage billing lines across statuses when needed.
    if permissions['is_staff']:
        return True

    # Technicians should not mutate billing after finalization or invoicing.
    if job.vyapar_invoice_number:
        return False
    if job.status in ['Completed', 'Ready for Pickup', 'Closed']:
        return False

    return bool(permissions['is_assigned_tech'])

def _mobile_parse_decimal(raw_value, field_label):
    text = str(raw_value if raw_value is not None else '').strip()
    if text == '':
        return Decimal('0.00'), None

    try:
        return Decimal(text), None
    except (InvalidOperation, TypeError, ValueError):
        return None, f"Invalid amount for '{field_label}'."

def _mobile_parse_bool(raw_value):
    if isinstance(raw_value, bool):
        return raw_value
    text = str(raw_value if raw_value is not None else '').strip().lower()
    return text in {'1', 'true', 'yes', 'on'}

def get_job_field_presets():
    grouped = {field: [] for field in JOB_PRESET_FIELDS}
    seen_values = {field: set() for field in JOB_PRESET_FIELDS}

    for field_name, raw_value in JobFieldPreset.objects.filter(is_active=True).values_list('field_name', 'value'):
        if field_name not in grouped:
            continue
        value = (raw_value or '').strip()
        if not value:
            continue

        dedupe_key = value.lower()
        if dedupe_key in seen_values[field_name]:
            continue
        seen_values[field_name].add(dedupe_key)
        grouped[field_name].append(value)

    return grouped

def sync_job_field_presets(device_submissions):
    if not device_submissions:
        return

    values_by_field = {field: set() for field in JOB_PRESET_FIELDS}
    for device_data in device_submissions:
        for field in JOB_PRESET_FIELDS:
            value = (device_data.get(field) or '').strip()
            if value:
                values_by_field[field].add(value[:255])

    for field_name, values in values_by_field.items():
        if not values:
            continue

        existing_values = set(
            JobFieldPreset.objects.filter(field_name=field_name, value__in=values).values_list('value', flat=True)
        )
        new_rows = [
            JobFieldPreset(field_name=field_name, value=value, sort_order=100, is_active=True)
            for value in values
            if value not in existing_values
        ]
        if new_rows:
            JobFieldPreset.objects.bulk_create(new_rows, ignore_conflicts=True)

def parse_product_sale_log(description):
    match = PRODUCT_SALE_LOG_PATTERN.match((description or '').strip())
    if not match:
        return None
    product_id_raw = match.group('product_id')
    return {
        'product_id': int(product_id_raw) if product_id_raw else None,
        'quantity': int(match.group('qty')),
        'name': match.group('name').strip(),
    }

def summarize_stock_sales(finished_jobs_qs, service_logs=None):
    """Build stock sale metrics from ProductSale ledger (with legacy fallback)."""
    sales = list(
        ProductSale.objects.filter(job_ticket__in=finished_jobs_qs).select_related('product', 'service_log')
    )

    total_revenue = Decimal('0.00')
    total_cogs = Decimal('0.00')
    total_profit = Decimal('0.00')
    total_units = 0
    sale_lines_count = 0
    product_rows = {}
    product_sale_log_ids = set()

    for sale in sales:
        revenue = sale.line_total or Decimal('0.00')
        cogs = sale.line_cost or Decimal('0.00')
        profit = sale.line_profit if sale.line_profit is not None else (revenue - cogs)
        quantity = sale.quantity or 0

        total_revenue += revenue
        total_cogs += cogs
        total_profit += profit
        total_units += quantity
        sale_lines_count += 1
        if sale.service_log_id:
            product_sale_log_ids.add(sale.service_log_id)

        product_obj = sale.product
        row = product_rows.setdefault(
            product_obj.id,
            {
                'product_id': product_obj.id,
                'name': product_obj.name,
                'sku': product_obj.sku or '-',
                'category': product_obj.category or '-',
                'units_sold': 0,
                'sale_lines': 0,
                'revenue': Decimal('0.00'),
                'cogs': Decimal('0.00'),
                'profit': Decimal('0.00'),
                'average_unit_price': Decimal('0.00'),
            },
        )
        row['units_sold'] += quantity
        row['sale_lines'] += 1
        row['revenue'] += revenue
        row['cogs'] += cogs
        row['profit'] += profit

    # Legacy fallback: include product sale logs that predate ProductSale ledger rows.
    if service_logs is not None:
        fallback_logs = []
        fallback_product_ids = set()
        for log in service_logs:
            if log.id in product_sale_log_ids:
                continue
            parsed = parse_product_sale_log(log.description)
            if not parsed:
                continue
            fallback_logs.append((log, parsed))
            if parsed['product_id']:
                fallback_product_ids.add(parsed['product_id'])

        fallback_products = Product.objects.in_bulk(fallback_product_ids) if fallback_product_ids else {}

        for log, parsed in fallback_logs:
            quantity = parsed['quantity']
            if quantity <= 0:
                continue

            product_obj = fallback_products.get(parsed['product_id'])
            revenue = log.part_cost or Decimal('0.00')
            unit_cost = product_obj.cost_price if product_obj else Decimal('0.00')
            cogs = unit_cost * Decimal(quantity)
            profit = revenue - cogs

            total_revenue += revenue
            total_cogs += cogs
            total_profit += profit
            total_units += quantity
            sale_lines_count += 1
            product_sale_log_ids.add(log.id)

            row_key = parsed['product_id'] or f"legacy:{parsed['name'].strip().lower()}"
            row = product_rows.setdefault(
                row_key,
                {
                    'product_id': parsed['product_id'],
                    'name': product_obj.name if product_obj else parsed['name'],
                    'sku': (product_obj.sku if product_obj else '') or '-',
                    'category': (product_obj.category if product_obj else '') or '-',
                    'units_sold': 0,
                    'sale_lines': 0,
                    'revenue': Decimal('0.00'),
                    'cogs': Decimal('0.00'),
                    'profit': Decimal('0.00'),
                    'average_unit_price': Decimal('0.00'),
                },
            )
            row['units_sold'] += quantity
            row['sale_lines'] += 1
            row['revenue'] += revenue
            row['cogs'] += cogs
            row['profit'] += profit

    products = list(product_rows.values())
    for row in products:
        if row['units_sold'] > 0:
            row['average_unit_price'] = row['revenue'] / Decimal(row['units_sold'])
    products.sort(key=lambda item: item['revenue'], reverse=True)

    avg_sale_value = (total_revenue / Decimal(sale_lines_count)) if sale_lines_count else Decimal('0.00')

    return {
        'total_revenue': total_revenue,
        'total_cogs': total_cogs,
        'total_profit': total_profit,
        'total_units': total_units,
        'sale_lines_count': sale_lines_count,
        'products': products,
        'products_count': len(products),
        'avg_sale_value': avg_sale_value,
        'service_log_ids': product_sale_log_ids,
    }

def _money_or_zero(value):
    return value if value is not None else Decimal('0.00')

def _sum_job_discounts(job_queryset):
    return job_queryset.aggregate(
        total=Coalesce(Sum('discount_amount', output_field=DecimalField()), Decimal('0.00'))
    )['total']

def _net_amount_after_discount(gross_amount, discount_amount):
    gross = _money_or_zero(gross_amount)
    discount = _money_or_zero(discount_amount)
    return max(Decimal('0.00'), gross - discount)

def _money_text(amount):
    return format((_money_or_zero(amount)).quantize(Decimal('0.01')), 'f')

def get_monthly_summary_context(start_of_period, end_of_period, start_date_str, end_date_str, preset='', show_jobs=''):
    """Build unified financial summary context for HTML/CSV/PDF outputs."""
    valid_show_jobs = {'created', 'finished', 'returned', 'vendor'}
    if show_jobs not in valid_show_jobs:
        show_jobs = ''

    monthly_finished_jobs_list = get_jobs_for_report_period(start_of_period, end_of_period)
    finished_job_ids = [job.id for job in monthly_finished_jobs_list]
    monthly_finished_jobs = JobTicket.objects.filter(id__in=finished_job_ids)

    jobs_created = JobTicket.objects.filter(created_at__gte=start_of_period, created_at__lt=end_of_period)
    jobs_returned = JobTicket.objects.filter(status='Returned', updated_at__gte=start_of_period, updated_at__lt=end_of_period)
    vendor_jobs = [job for job in monthly_finished_jobs_list if job.is_vendor_job()]

    job_list = []
    if show_jobs == 'created':
        job_list = list(jobs_created.select_related('assigned_to__user').order_by('-created_at'))
    elif show_jobs == 'finished':
        job_list = list(monthly_finished_jobs.select_related('assigned_to__user').order_by('-updated_at'))
    elif show_jobs == 'returned':
        job_list = list(jobs_returned.select_related('assigned_to__user').order_by('-updated_at'))
    elif show_jobs == 'vendor':
        job_list = list(
            JobTicket.objects.filter(id__in=[job.id for job in vendor_jobs])
            .select_related('assigned_to__user', 'specialized_service__vendor')
            .order_by('-updated_at')
        )

    logs_in_period = list(ServiceLog.objects.filter(job_ticket__in=monthly_finished_jobs).select_related('job_ticket'))
    stock_sales = summarize_stock_sales(monthly_finished_jobs, logs_in_period)
    product_sale_log_ids = stock_sales['service_log_ids']

    non_product_logs = [log for log in logs_in_period if log.id not in product_sale_log_ids]

    # Keep vendor-related services in vendor block, not service block.
    service_logs = [log for log in non_product_logs if 'Specialized Service' not in (log.description or '')]

    service_parts_revenue = sum((log.part_cost or Decimal('0.00') for log in service_logs), Decimal('0.00'))
    service_labor_revenue = sum((log.service_charge or Decimal('0.00') for log in service_logs), Decimal('0.00'))
    service_revenue = service_parts_revenue + service_labor_revenue
    service_expense = Decimal('0.00')
    service_profit = service_revenue - service_expense

    stock_sales_income = stock_sales['total_revenue']
    stock_sales_cogs = stock_sales['total_cogs']
    stock_sales_profit = stock_sales['total_profit']

    vendor_services_in_period = SpecializedService.objects.filter(job_ticket__in=monthly_finished_jobs)
    vendor_expense = vendor_services_in_period.aggregate(
        total=Coalesce(Sum('vendor_cost', output_field=DecimalField()), Decimal('0.00'))
    )['total']
    vendor_revenue = vendor_services_in_period.aggregate(
        total=Coalesce(Sum('client_charge', output_field=DecimalField()), Decimal('0.00'))
    )['total']
    vendor_profit = vendor_revenue - vendor_expense

    total_discounts = _sum_job_discounts(monthly_finished_jobs)
    overall_revenue = _net_amount_after_discount(
        service_revenue + stock_sales_income + vendor_revenue,
        total_discounts,
    )
    overall_expense = service_expense + stock_sales_cogs + vendor_expense
    overall_profit = overall_revenue - overall_expense
    overall_margin = (overall_profit / overall_revenue * 100) if overall_revenue > 0 else Decimal('0.00')

    all_part_income = sum((log.part_cost or Decimal('0.00') for log in logs_in_period), Decimal('0.00'))
    all_service_income = sum((log.service_charge or Decimal('0.00') for log in logs_in_period), Decimal('0.00'))

    return {
        'current_report_date': start_of_period,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'preset': preset,
        'show_jobs': show_jobs,
        'job_list': job_list,
        'jobs_created_count': jobs_created.count(),
        'jobs_finished_count': monthly_finished_jobs.count(),
        'jobs_returned_count': jobs_returned.count(),
        'vendor_jobs_count': len(vendor_jobs),

        # Service block
        'service_parts_revenue': service_parts_revenue,
        'service_labor_revenue': service_labor_revenue,
        'service_revenue': service_revenue,
        'service_expense': service_expense,
        'service_profit': service_profit,

        # Stock block
        'stock_sales_income': stock_sales_income,
        'stock_sales_cogs': stock_sales_cogs,
        'stock_sales_profit': stock_sales_profit,
        'stock_sales_units': stock_sales['total_units'],
        'stock_sale_lines_count': stock_sales['sale_lines_count'],
        'stock_products_count': stock_sales['products_count'],
        'stock_avg_sale_value': stock_sales['avg_sale_value'],
        'stock_products_breakdown': stock_sales['products'],

        # Vendor block
        'vendor_revenue': vendor_revenue,
        'vendor_expense': vendor_expense,
        'vendor_profit': vendor_profit,

        # Overall
        'overall_revenue': overall_revenue,
        'overall_expense': overall_expense,
        'overall_profit': overall_profit,
        'overall_margin': overall_margin,
        'total_discounts': total_discounts,

        # Compatibility keys used elsewhere
        'monthly_total_income': overall_revenue,
        'monthly_income_parts': all_part_income,
        'monthly_income_service': all_service_income,
        'monthly_vendor_expense': vendor_expense,
        'monthly_net_profit': overall_profit,
        'profit_margin': overall_margin,
        'repair_parts_income': service_parts_revenue,
    }

def validate_sales_invoice_number_uniqueness(
    invoice_number,
    exclude_job_id=None,
    exclude_inventory_entry_id=None,
    exclude_inventory_bill_id=None,
    allow_inventory_job_id=None,
):
    invoice_number = (invoice_number or '').strip()
    if not invoice_number:
        return
    duplicate_qs = JobTicket.objects.filter(vyapar_invoice_number__iexact=invoice_number)
    if exclude_job_id:
        duplicate_qs = duplicate_qs.exclude(pk=exclude_job_id)
    if duplicate_qs.exists():
        raise ValueError(f"Invoice number '{invoice_number}' is already used by another job.")

    excluded_bill_ids = set()
    if exclude_inventory_bill_id:
        excluded_bill_ids.add(exclude_inventory_bill_id)
    if exclude_inventory_entry_id:
        linked_bill_id = (
            InventoryEntry.objects.filter(pk=exclude_inventory_entry_id)
            .values_list('bill_id', flat=True)
            .first()
        )
        if linked_bill_id:
            excluded_bill_ids.add(linked_bill_id)

    inventory_qs = InventoryBill.objects.filter(
        entry_type='sale',
        invoice_number__iexact=invoice_number,
    )
    if excluded_bill_ids:
        inventory_qs = inventory_qs.exclude(pk__in=excluded_bill_ids)
    if allow_inventory_job_id:
        inventory_qs = inventory_qs.exclude(job_ticket_id=allow_inventory_job_id)
    if inventory_qs.exists():
        raise ValueError(f"Invoice number '{invoice_number}' is already used in sales register.")

def _inventory_sales_invoice_prefix():
    try:
        profile = CompanyProfile.get_profile()
        raw_prefix = (profile.sales_invoice_prefix or '').strip()
    except (OperationalError, ProgrammingError):
        raw_prefix = ''
    prefix = re.sub(r'[^A-Za-z0-9]+', '', raw_prefix).upper() or 'INV'
    return prefix[:20]

def _build_dated_inventory_invoice_number(entry_type, entry_date, prefix, exclude_bill_id=None):
    date_part = entry_date.strftime('%Y%m%d')
    scope_qs = InventoryBill.objects.filter(entry_type=entry_type, entry_date=entry_date)
    if exclude_bill_id:
        scope_qs = scope_qs.exclude(pk=exclude_bill_id)
    sequence = scope_qs.count() + 1
    invoice_number = f'{prefix}-{date_part}-{sequence:03d}'
    duplicate_qs = InventoryBill.objects.filter(entry_type=entry_type, invoice_number=invoice_number)
    if exclude_bill_id:
        duplicate_qs = duplicate_qs.exclude(pk=exclude_bill_id)
    while duplicate_qs.exists():
        sequence += 1
        invoice_number = f'{prefix}-{date_part}-{sequence:03d}'
        duplicate_qs = InventoryBill.objects.filter(entry_type=entry_type, invoice_number=invoice_number)
        if exclude_bill_id:
            duplicate_qs = duplicate_qs.exclude(pk=exclude_bill_id)
    return invoice_number

def get_next_job_code():
    """
    Generates the next job code using the format PREFIX-YYMMDD-XXX, where PREFIX
    is from company profile, and XXX is a zero-padded counter that resets each day.
    """
    from django.db import transaction
    import re

    # Get dynamic prefix from company profile
    company = CompanyProfile.get_profile()
    job_prefix = company.job_code_prefix or 'GI'
    
    today = timezone.localdate()
    date_fragment = today.strftime('%y%m%d')
    prefix = f'{job_prefix}-{date_fragment}-'

    pattern_today = re.compile(rf'{re.escape(prefix)}(\d+)$')
    pattern_global = re.compile(rf'{re.escape(job_prefix)}-\d{{6}}-(\d+)$')

    with transaction.atomic():
        sequence, _ = DailyJobCodeSequence.objects.select_for_update().get_or_create(date=today)

        highest_counter = sequence.last_counter
        today_job_codes = JobTicket.objects.filter(job_code__startswith=prefix).values_list('job_code', flat=True)
        for code in today_job_codes:
            match = pattern_today.search(code)
            if match:
                highest_counter = max(highest_counter, int(match.group(1)))

        # Ensure we never go backward if historical data exists
        all_time_highest = DailyJobCodeSequence.objects.aggregate(max_counter=Max('last_counter'))['max_counter'] or 0
        highest_counter = max(highest_counter, all_time_highest)

        if highest_counter == 0:
            # Fallback: scan existing job codes with current prefix
            existing_codes = JobTicket.objects.filter(job_code__startswith=job_prefix).values_list('job_code', flat=True)
            for code in existing_codes:
                match = pattern_global.search(code)
                if match:
                    highest_counter = max(highest_counter, int(match.group(1)))

        next_counter = highest_counter + 1
        job_code = f'{prefix}{next_counter:03d}'

        # Double-check to avoid duplicates (race-condition safety)
        while JobTicket.objects.filter(job_code=job_code).exists():
            next_counter += 1
            job_code = f'{prefix}{next_counter:03d}'

        sequence.last_counter = next_counter
        sequence.save(update_fields=['last_counter'])

    return job_code

def get_phone_service_snapshot(phone):
    normalized_phone, _ = normalize_indian_phone(phone, required=False)
    if not normalized_phone:
        return {
            'phone': '',
            'exists': False,
            'client_id': None,
            'client_name': '',
            'total_jobs': 0,
            'open_jobs': 0,
            'recent_jobs': [],
        }

    phone_variants = phone_lookup_variants(normalized_phone)
    jobs_qs = JobTicket.objects.filter(customer_phone__in=phone_variants).order_by('-created_at')
    total_jobs = jobs_qs.count()
    open_jobs = jobs_qs.exclude(status='Closed').count()
    latest_job = jobs_qs.first()

    recent_jobs = []
    for job in jobs_qs[:3]:
        recent_jobs.append({
            'job_code': job.job_code,
            'device_type': job.device_type,
            'status': job.status,
            'created_at': job.created_at.strftime('%Y-%m-%d'),
        })

    client = Client.objects.filter(phone__in=phone_variants).order_by('id').first()
    fallback_name = latest_job.customer_name if (latest_job and not client) else ''

    return {
        'phone': normalized_phone,
        'exists': client is not None,
        'client_id': client.id if client else None,
        'client_name': client.name if client else fallback_name,
        'total_jobs': total_jobs,
        'open_jobs': open_jobs,
        'recent_jobs': recent_jobs,
    }


# --- HELPER FUNCTION FOR WEBSOCKET UPDATES ---

def send_job_update_message(job_code, new_status):
    """Utility to send a real-time status update to all clients watching jobs."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        from ..consumers import STAFF_GROUP, TECH_GROUP
        
        channel_layer = get_channel_layer()
        if channel_layer:
            message = {
                'type': 'job_status_update',
                'job_code': job_code,
                'status': new_status,
            }
            # Send to both staff and technician groups
            async_to_sync(channel_layer.group_send)(STAFF_GROUP, message)
            async_to_sync(channel_layer.group_send)(TECH_GROUP, message)
            
            # Also send to job-specific group
            job_group = f'job_{job_code}'
            async_to_sync(channel_layer.group_send)(job_group, message)
    except Exception as e:
        # Silently fail if channels is not configured
        print(f"WebSocket update failed: {e}")

def get_jobs_for_report_period(start_of_period, end_of_period, status_filter=None):
    """Get jobs that should be reported in the given period using vendor concept.
    
    Vendor jobs are only included when they return from vendor in the period.
    Regular jobs are included when they are completed/closed in the period.
    """
    from django.db.models import Q
    
    finished_statuses = ['Completed', 'Closed']
    
    # Base filter for finished jobs in the period
    base_filter = Q(status__in=finished_statuses)
    
    # Apply status filter if provided
    if status_filter == 'ALL_FINISHED':
        base_filter &= Q(status__in=finished_statuses)
    elif status_filter == 'ACTIVE_WORKLOAD':
        base_filter = Q(status__in=['Under Inspection', 'Repairing', 'Specialized Service'])
    elif status_filter and status_filter != 'ALL':
        base_filter &= Q(status=status_filter)
    
    # Get all jobs that match the base criteria
    all_jobs = JobTicket.objects.filter(base_filter).select_related('specialized_service')
    
    # Filter jobs based on vendor concept
    reportable_jobs = []
    for job in all_jobs:
        report_date = job.get_report_date()
        if report_date and start_of_period <= report_date < end_of_period:
            reportable_jobs.append(job)
    
    return reportable_jobs

def calculate_job_totals(jobs, exclude_vendor_charges=False):
    """Calculates part_total, service_total, and total for a list of JobTicket objects."""
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

    def safe_decimal(value):
        """Safely convert a value to Decimal, returning Decimal('0') if invalid."""
        if value is None:
            return Decimal('0')
        try:
            return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError, TypeError):
            return Decimal('0')

    for job in jobs:
        try:
            # Access the logs directly from the job object (already prefetched or lazy loaded)
            job_logs = list(job.service_logs.all())
            
            # Filter out vendor service charges if requested
            if exclude_vendor_charges:
                job_logs = [log for log in job_logs if 'Specialized Service' not in log.description]
            
            # Calculate totals with safe conversion
            job.part_total = sum(safe_decimal(log.part_cost) for log in job_logs)
            job.service_total = sum(safe_decimal(log.service_charge) for log in job_logs)
            job.total = job.part_total + job.service_total

        except Exception:
            # Fallback to zero for any calculation error
            job.part_total = Decimal('0')
            job.service_total = Decimal('0')
            job.total = Decimal('0')

# --- CHANNELS HELPER FUNCTION (Removed - Django Channels no longer used) ---
# def send_job_update_message(job_code, new_status_display):
#     """Utility to send a real-time status update to all clients watching a job."""
#     pass
# ----------------------------------------------------------------------------------

def _get_post_login_redirect(user):
    if user.is_staff:
        access = get_staff_access(user)
        if access.get("staff_dashboard"):
            return redirect('staff_dashboard')
        if access.get("reports_dashboard"):
            return redirect('reports_dashboard')
        if access.get("inventory"):
            return redirect('inventory_dashboard')
        if access.get("team_management"):
            return redirect('staff_technicians')
        if access.get("feedback_analytics"):
            return redirect('feedback_analytics')
        if access.get("company_settings"):
            return redirect('company_profile_settings')
        return redirect('unauthorized')
    if user.groups.filter(name='Technicians').exists():
        return redirect('technician_dashboard')
    return redirect('home')

def _get_safe_next_url(request):
    next_url = (request.POST.get('next') or request.GET.get('next') or '').strip()
    if not next_url:
        return ''

    if url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        candidate_path = urlsplit(next_url).path or '/'
        try:
            resolve(candidate_path)
        except Resolver404:
            return ''
        return next_url
    return ''

def _summarize_user_agent(user_agent):
    user_agent = (user_agent or '').lower()
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

    return f'{browser} on {os_name}'

def get_report_period(request):
    """Parses date parameters and returns timezone-aware start_date and end_date."""
    
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    status_filter = request.GET.get('status_filter') # NEW
    preset = request.GET.get('preset')
    
    today = timezone.localdate()
    
    # 1. Custom Date Range
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            start_of_period = timezone.make_aware(datetime(start_date.year, start_date.month, start_date.day))
            end_of_period = timezone.make_aware(datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59))
            
            period_name = f"Custom: {start_date_str} to {end_date_str}"
            
            return {
                'start': start_of_period,
                'end': end_of_period,
                'name': period_name,
                'start_date_str': start_date_str, # Use string from GET for input field
                'end_date_str': end_date_str,     # Use string from GET for input field
            }
            
        except ValueError:
            # Fallback if dates are invalid
            return get_report_period_default()
            
    # 2. Preset: This Month
    elif preset == 'this_month':
        start_date = today.replace(day=1)
        # Calculate the first day of the next month (exclusive end boundary)
        if today.month == 12:
            end_date_boundary = today.replace(year=today.year + 1, month=1, day=1)
        else:
            end_date_boundary = today.replace(month=today.month + 1, day=1)
            
        end_date_for_input = end_date_boundary - timedelta(days=1)
        
        start_of_period = timezone.make_aware(datetime(start_date.year, start_date.month, start_date.day))
        end_of_period = timezone.make_aware(datetime(end_date_boundary.year, end_date_boundary.month, end_date_boundary.day))
        period_name = f"Monthly: {start_date.strftime('%B %Y')}"
        
        return {
            'start': start_of_period,
            'end': end_of_period,
            'name': period_name,
            'start_date_str': start_date.strftime('%Y-%m-%d'),
            'end_date_str': end_date_for_input.strftime('%Y-%m-%d'),
        }
        
    # 3. Preset: Last 7 Days (Weekly Meetup)
    elif preset == 'last_7_days':
        start_date = today - timedelta(days=6)
        end_date = today # Today is the end
        
        start_of_period = timezone.make_aware(datetime(start_date.year, start_date.month, start_date.day))
        end_of_period = timezone.make_aware(datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59))
        period_name = "Last 7 Days (Weekly)"

        return {
            'start': start_of_period,
            'end': end_of_period,
            'name': period_name,
            'start_date_str': start_date.strftime('%Y-%m-%d'),
            'end_date_str': end_date.strftime('%Y-%m-%d'),
        }

    # 4. Fallback/Default: If no parameters are passed, use the default helper.
    return get_report_period_default()

def get_report_period_default():
    today = timezone.localdate()
    start_date = today.replace(day=1)
    
    # Calculate the first day of the NEXT month. This is the boundary.
    if start_date.month == 12:
        # If December, next month is January of next year
        end_date_boundary = start_date.replace(year=start_date.year + 1, month=1)
    else:
        # Otherwise, just increment the month
        end_date_boundary = start_date.replace(month=start_date.month + 1)
        
    # The end date for the input field is the last day of the current month
    end_date_for_input = end_date_boundary - timedelta(days=1)
    
    # 1. Start of Period (00:00:00)
    start_of_period = timezone.make_aware(datetime(start_date.year, start_date.month, start_date.day))
    
    # 2. End of Period (The start of the next month, 00:00:00)
    # NOTE: We use end_date_boundary here, which is the correct non-inclusive end for queries
    end_of_period = timezone.make_aware(datetime(end_date_boundary.year, end_date_boundary.month, end_date_boundary.day))
    
    return {
        'start': start_of_period,
        'end': end_of_period,
        'name': f"Monthly: {start_date.strftime('%B %Y')}",
        'start_date_str': start_date.strftime('%Y-%m-%d'),
        'end_date_str': end_date_for_input.strftime('%Y-%m-%d'), # for input fields
    }

def _parse_autoprint_flag(request, default=True):
    raw_value = (request.GET.get('autoprint') or '').strip().lower()
    if not raw_value:
        return default
    return raw_value not in {'0', 'false', 'no', 'off'}

def resolve_monthly_summary_period(request):
    """Resolve monthly summary period and return normalized date metadata."""
    start_date_str = (request.GET.get('start_date') or '').strip()
    end_date_str = (request.GET.get('end_date') or '').strip()
    preset = (request.GET.get('preset') or '').strip()
    show_jobs = (request.GET.get('show_jobs') or '').strip()

    start_date = None
    end_date = None
    today = timezone.localdate()

    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            if end_date < start_date:
                raise ValueError("End date cannot be before start date")
        except ValueError:
            start_date = None
            end_date = None
            start_date_str = ''
            end_date_str = ''

    if start_date is None or end_date is None:
        if preset == 'last_month':
            first_day_this_month = today.replace(day=1)
            end_date = first_day_this_month - timedelta(days=1)
            start_date = end_date.replace(day=1)
        elif preset == 'this_month':
            start_date = today.replace(day=1)
            end_date = today
        else:
            start_date = today.replace(day=1)
            if start_date.month == 12:
                next_month_start = start_date.replace(year=start_date.year + 1, month=1, day=1)
            else:
                next_month_start = start_date.replace(month=start_date.month + 1, day=1)
            end_date = next_month_start - timedelta(days=1)
            preset = ''

        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')

    start_of_period = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
    end_of_period = timezone.make_aware(datetime.combine(end_date + timedelta(days=1), datetime.min.time()))

    return {
        'start_of_period': start_of_period,
        'end_of_period': end_of_period,
        'start_date_str': start_date_str,
        'end_date_str': end_date_str,
        'preset': preset,
        'show_jobs': show_jobs,
    }
INVENTORY_ENTRY_CONFIG = {
    'purchase': {
        'title': 'Purchase',
        'icon': 'fa-cart-arrow-down',
        'description': 'Add purchase entries to increase stock.',
        'url_name': 'inventory_purchase_dashboard',
        'submit_label': 'Record Purchase',
        'success_label': 'Purchase',
        'party_label': 'Parties',
        'party_label_singular': 'Party',
    },
    'purchase_return': {
        'title': 'Purchase Return',
        'icon': 'fa-rotate-left',
        'description': 'Review purchase return bills created from the purchase register.',
        'url_name': 'inventory_purchase_return_dashboard',
        'submit_label': 'Record Purchase Return',
        'success_label': 'Purchase return',
        'party_label': 'Parties',
        'party_label_singular': 'Party',
    },
    'sale': {
        'title': 'Sales',
        'icon': 'fa-cart-shopping',
        'description': 'Create sales entries that reduce stock.',
        'url_name': 'inventory_sales_dashboard',
        'submit_label': 'Record Sale',
        'success_label': 'Sale',
        'party_label': 'Parties',
        'party_label_singular': 'Party',
    },
    'sale_return': {
        'title': 'Sales Return',
        'icon': 'fa-rotate-right',
        'description': 'Review sales return bills created from the sales register.',
        'url_name': 'inventory_sales_return_dashboard',
        'submit_label': 'Record Sales Return',
        'success_label': 'Sales return',
        'party_label': 'Parties',
        'party_label_singular': 'Party',
    },
}


def _generate_inventory_entry_number(entry_type, entry_date):
    prefix_map = {
        'purchase': 'PUR',
        'purchase_return': 'PRN',
        'sale': 'SAL',
        'sale_return': 'SRN',
    }
    prefix = prefix_map.get(entry_type, 'INV')
    date_part = entry_date.strftime('%Y%m%d')
    sequence = InventoryEntry.objects.filter(entry_type=entry_type, entry_date=entry_date).count() + 1
    entry_number = f'{prefix}-{date_part}-{sequence:03d}'
    while InventoryEntry.objects.filter(entry_number=entry_number).exists():
        sequence += 1
        entry_number = f'{prefix}-{date_part}-{sequence:03d}'
    return entry_number

def _generate_inventory_bill_number(entry_type, entry_date):
    prefix_map = {
        'purchase': 'PB',
        'purchase_return': 'PRB',
        'sale': 'SB',
        'sale_return': 'SRB',
    }
    prefix = prefix_map.get(entry_type, 'IB')
    date_part = entry_date.strftime('%Y%m%d')
    sequence = InventoryBill.objects.filter(entry_type=entry_type, entry_date=entry_date).count() + 1
    bill_number = f'{prefix}-{date_part}-{sequence:03d}'
    while InventoryBill.objects.filter(bill_number=bill_number).exists():
        sequence += 1
        bill_number = f'{prefix}-{date_part}-{sequence:03d}'
    return bill_number

def _generate_inventory_invoice_number(entry_type, entry_date):
    if entry_type == 'sale':
        return _build_dated_inventory_invoice_number(
            entry_type='sale',
            entry_date=entry_date,
            prefix=_inventory_sales_invoice_prefix(),
        )
    
    prefix_map = {
        'purchase': 'PIB',
        'purchase_return': 'PRB',
        'sale_return': 'SRB',
    }
    prefix = prefix_map.get(entry_type, 'IB')
    date_part = entry_date.strftime('%Y%m%d')
    sequence = InventoryBill.objects.filter(entry_type=entry_type, entry_date=entry_date).count() + 1
    invoice_number = f'{prefix}-{date_part}-{sequence:04d}'
    while InventoryBill.objects.filter(entry_type=entry_type, invoice_number=invoice_number).exists():
        sequence += 1
        invoice_number = f'{prefix}-{date_part}-{sequence:04d}'
    return invoice_number

def _peek_sales_invoice_number():
    return _build_dated_inventory_invoice_number(
        entry_type='sale',
        entry_date=timezone.localdate(),
        prefix=_inventory_sales_invoice_prefix(),
    )

def _parse_inventory_decimal(raw_value, label, default='0.00'):
    text = (raw_value or '').strip()
    if text == '':
        return Decimal(default)
    try:
        return Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(label)

def _collect_inventory_bill_lines(product_ids, quantities, unit_prices, gst_rates):
    max_lines = max(
        len(product_ids),
        len(quantities),
        len(unit_prices),
        len(gst_rates),
    )

    def get_row_value(values, idx):
        if idx < len(values):
            return (values[idx] or '').strip()
        return ''

    line_items = []
    seen_product_ids = set()
    for idx in range(max_lines):
        product_id = get_row_value(product_ids, idx)
        qty_raw = get_row_value(quantities, idx)
        unit_price_raw = get_row_value(unit_prices, idx)
        gst_raw = get_row_value(gst_rates, idx)

        if not any([product_id, qty_raw, unit_price_raw, gst_raw]):
            continue

        line_no = idx + 1
        if not product_id:
            raise ValueError(f"Line {line_no}: select a product.")

        try:
            quantity = int(qty_raw or '0')
        except (TypeError, ValueError):
            raise ValueError(f"Line {line_no}: quantity must be a whole number.")
        if quantity <= 0:
            raise ValueError(f"Line {line_no}: quantity must be greater than zero.")

        unit_price = _parse_inventory_decimal(unit_price_raw, f"Line {line_no}: invalid unit price.")
        if unit_price < 0:
            raise ValueError(f"Line {line_no}: unit price cannot be negative.")

        gst_rate = _parse_inventory_decimal(gst_raw, f"Line {line_no}: invalid GST rate.")
        if gst_rate < 0:
            raise ValueError(f"Line {line_no}: GST rate cannot be negative.")

        product = Product.objects.filter(pk=product_id, is_active=True).first()
        if not product:
            raise ValueError(f"Line {line_no}: selected product was not found.")
        if product.id in seen_product_ids:
            raise ValueError(
                f"Line {line_no}: duplicate product '{product.name}' is not allowed in the same bill."
            )
        seen_product_ids.add(product.id)

        line_items.append(
            {
                'product': product,
                'quantity': quantity,
                'unit_price': unit_price,
                'line_amount': Decimal(quantity) * unit_price,
                'gst_rate': gst_rate,
            }
        )

    if not line_items:
        raise ValueError("Add at least one product line.")
    return line_items

def _apply_inventory_bill_discount(line_items, bill_discount_amount, bill_notes):
    subtotal_amount = sum((line['line_amount'] for line in line_items), Decimal('0.00'))
    if bill_discount_amount > subtotal_amount:
        raise ValueError("Bill discount cannot exceed subtotal amount.")

    line_discounts = [Decimal('0.00') for _ in line_items]
    if bill_discount_amount > 0 and subtotal_amount > 0:
        for idx, line in enumerate(line_items):
            provisional = (
                (bill_discount_amount * line['line_amount']) / subtotal_amount
            ).quantize(Decimal('0.01'))
            if provisional > line['line_amount']:
                provisional = line['line_amount']
            line_discounts[idx] = provisional

        allocated_discount = sum(line_discounts, Decimal('0.00'))
        remaining_discount = (bill_discount_amount - allocated_discount).quantize(Decimal('0.01'))
        step = Decimal('0.01')
        reorder_indexes = sorted(
            range(len(line_items)),
            key=lambda row_idx: line_items[row_idx]['line_amount'],
            reverse=True,
        )
        while remaining_discount != Decimal('0.00'):
            changed = False
            for row_idx in reorder_indexes:
                if remaining_discount > 0:
                    capacity = line_items[row_idx]['line_amount'] - line_discounts[row_idx]
                    if capacity >= step:
                        line_discounts[row_idx] += step
                        remaining_discount -= step
                        changed = True
                else:
                    if line_discounts[row_idx] >= step:
                        line_discounts[row_idx] -= step
                        remaining_discount += step
                        changed = True
                remaining_discount = remaining_discount.quantize(Decimal('0.01'))
                if remaining_discount == Decimal('0.00'):
                    break
            if not changed:
                break

    return [
        {
            'product': line['product'],
            'quantity': line['quantity'],
            'unit_price': line['unit_price'],
            'discount_amount': line_discounts[idx],
            'gst_rate': line['gst_rate'],
            'notes': bill_notes,
        }
        for idx, line in enumerate(line_items)
    ]

def _require_inventory_edit_password(request):
    password = (request.POST.get('edit_password') or '').strip()
    if not password:
        raise ValueError('Enter your password to edit the bill.')
    if not request.user.check_password(password):
        raise ValueError('Incorrect password.')

def _replace_inventory_bill_entries(
    request,
    *,
    entry_type,
    bill_id,
    entry_date,
    party,
    invoice_number,
    line_items,
    job_ticket=None,
):
    with transaction.atomic():
        locked_bill = (
            InventoryBill.objects.select_for_update()
            .filter(pk=bill_id, entry_type=entry_type)
            .first()
        )
        if not locked_bill:
            raise ValueError('Selected bill was not found.')

        locked_entries = list(
            InventoryEntry.objects.select_for_update()
            .filter(bill_id=locked_bill.id, entry_type=entry_type)
            .select_related('product')
            .order_by('id')
        )
        if not locked_entries:
            raise ValueError('Selected bill was not found.')

        locked_products = {
            product.id: product
            for product in Product.objects.select_for_update().filter(
                pk__in={row.product_id for row in locked_entries}
            )
        }
        scope_label = (invoice_number or locked_bill.invoice_number or locked_bill.bill_number).strip()
        for old_entry in locked_entries:
            product = locked_products.get(old_entry.product_id)
            if not product:
                raise ValueError(f"Product for invoice '{scope_label or old_entry.entry_number}' was not found.")
            restored_stock = product.stock_quantity - old_entry.stock_effect
            if restored_stock < 0:
                raise ValueError(
                    f"Cannot edit invoice '{scope_label or old_entry.entry_number}'. "
                    f"Stock reconciliation failed for '{product.name}'."
                )
            product.stock_quantity = restored_stock

        for product in locked_products.values():
            product.save(update_fields=['stock_quantity'])

        InventoryEntry.objects.filter(pk__in=[row.id for row in locked_entries]).delete()
        return _record_inventory_entries(
            request=request,
            entry_type=entry_type,
            entry_date=entry_date,
            party=party,
            invoice_number=invoice_number,
            line_items=line_items,
            job_ticket=job_ticket,
            existing_bill=locked_bill,
        )

def _build_inventory_redirect_url(request, url_name, extra_params=None):
    params = request.GET.copy()
    for key, value in (extra_params or {}).items():
        if value in (None, ''):
            params.pop(key, None)
        else:
            params[key] = value
    base_url = reverse(url_name)
    query_string = params.urlencode()
    return f"{base_url}?{query_string}" if query_string else base_url

def _inventory_post_response(request, url_name, ok, message, extra_params=None):
    redirect_url = _build_inventory_redirect_url(request, url_name, extra_params=extra_params)
    is_async = (
        request.headers.get('X-Botgi-Async') == '1'
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )
    if is_async:
        payload = {
            'ok': ok,
            'message': message,
        }
        if ok:
            payload['reload_url'] = redirect_url
        return JsonResponse(payload)

    if ok:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return redirect(redirect_url)

def _process_inventory_grouped_bill_edit(request, *, entry_type):
    config = INVENTORY_ENTRY_CONFIG[entry_type]
    bill_id_raw = (request.POST.get('bill_id') or '').strip()
    entry_id = (request.POST.get('entry_id') or '').strip()
    if not entry_id or not bill_id_raw.isdigit():
        raise ValueError('Selected bill was not found.')

    grouped_entry = InventoryEntry.objects.filter(
        pk=entry_id,
        bill_id=int(bill_id_raw),
        entry_type=entry_type,
    ).select_related('job_ticket', 'party').first()
    if not grouped_entry:
        raise ValueError('Selected bill was not found.')

    _require_inventory_edit_password(request)

    edit_entry_date_raw = (request.POST.get('edit_entry_date') or '').strip()
    if not edit_entry_date_raw:
        raise ValueError('Entry date is required.')
    try:
        new_entry_date = datetime.strptime(edit_entry_date_raw, '%Y-%m-%d').date()
    except ValueError as exc:
        raise ValueError('Entry date is invalid.') from exc

    new_invoice_number = (request.POST.get('edit_invoice_number') or '').strip()
    if not new_invoice_number:
        raise ValueError('Invoice number is required.')

    bill_notes = (
        request.POST.get('edit_bill_notes')
        or request.POST.get('edit_notes')
        or ''
    ).strip()
    bill_discount_amount = _parse_inventory_decimal(
        (request.POST.get('edit_bill_discount_amount') or '').strip() or '0.00',
        "Invalid bill discount amount.",
    )
    if bill_discount_amount < 0:
        raise ValueError("Bill discount cannot be negative.")

    scoped_entries = list(
        InventoryEntry.objects.filter(
            bill_id=int(bill_id_raw),
            entry_type=entry_type,
        ).select_related('bill', 'party', 'job_ticket').order_by('id')
    )
    if not scoped_entries:
        raise ValueError('Selected bill was not found.')

    linked_job_ids = {row.job_ticket_id for row in scoped_entries if row.job_ticket_id}
    if len(linked_job_ids) > 1:
        raise ValueError('Cannot edit a bill linked to multiple jobs.')
    if entry_type == 'sale' and linked_job_ids:
        raise ValueError('Service-linked sales bills must be edited from the job billing screen.')

    valid_party_qs = InventoryParty.objects.filter(is_active=True)

    if linked_job_ids:
        new_party = scoped_entries[0].party
    else:
        edit_party_id = (request.POST.get('edit_party_id') or '').strip()
        new_party = valid_party_qs.filter(pk=edit_party_id).first()
    if not new_party:
        raise ValueError(f"Please select a valid {config['party_label_singular'].lower()}.")

    if entry_type == 'sale':
        validate_sales_invoice_number_uniqueness(
            new_invoice_number,
            exclude_inventory_bill_id=int(bill_id_raw),
        )

    line_items = _collect_inventory_bill_lines(
        request.POST.getlist('edit_line_product_id[]'),
        request.POST.getlist('edit_line_quantity[]'),
        request.POST.getlist('edit_line_unit_price[]'),
        request.POST.getlist('edit_line_gst_rate[]'),
    )
    final_line_items = _apply_inventory_bill_discount(
        line_items,
        bill_discount_amount,
        bill_notes,
    )
    created_entries = _replace_inventory_bill_entries(
        request,
        entry_type=entry_type,
        bill_id=int(bill_id_raw),
        entry_date=new_entry_date,
        party=new_party,
        invoice_number=new_invoice_number,
        line_items=final_line_items,
        job_ticket=scoped_entries[0].job_ticket if linked_job_ids else None,
    )

    if entry_type in {'purchase', 'purchase_return'}:
        for created_entry in created_entries:
            product = created_entry.product
            if product.cost_price != created_entry.unit_price:
                product.cost_price = created_entry.unit_price
                product.save(update_fields=['cost_price'])

    saved_invoice = created_entries[0].invoice_number if created_entries else new_invoice_number
    return {
        'invoice_number': saved_invoice,
        'message': f"{config['success_label']} invoice {saved_invoice} updated successfully.",
    }

def _get_or_create_inventory_customer_party_for_job(job):
    customer_name = (job.customer_name or '').strip() or f"Customer {job.job_code}"
    customer_phone = (job.customer_phone or '').strip()

    party_qs = InventoryParty.objects.all()
    party = None
    if customer_phone:
        party = party_qs.filter(phone=customer_phone).first()
    if not party and customer_name:
        party = party_qs.filter(name__iexact=customer_name).first()

    if party:
        update_fields = []
        if not party.is_active:
            party.is_active = True
            update_fields.append('is_active')
        if customer_phone and party.phone != customer_phone:
            party.phone = customer_phone[:20]
            update_fields.append('phone')
        if customer_name and party.name != customer_name:
            party.name = customer_name[:200]
            update_fields.append('name')
        if update_fields:
            party.save(update_fields=update_fields)
        return party

    return InventoryParty.objects.create(
        name=customer_name[:200],
        party_type='both',
        phone=customer_phone[:20],
        is_active=True,
    )

def _record_inventory_entries(request, entry_type, entry_date, party, invoice_number, line_items, job_ticket=None, existing_bill=None):
    if not line_items:
        raise ValueError("Add at least one product line.")

    normalized_invoice = (invoice_number or '').strip()
    created_entries = []

    with transaction.atomic():
        shared_invoice = normalized_invoice or _generate_inventory_invoice_number(entry_type, entry_date)
        shared_notes = next(((line.get('notes') or '').strip() for line in line_items if (line.get('notes') or '').strip()), '')

        if existing_bill:
            bill = InventoryBill.objects.select_for_update().get(pk=existing_bill.pk)
            update_fields = []
            if bill.entry_type != entry_type:
                bill.entry_type = entry_type
                update_fields.append('entry_type')
            if bill.entry_date != entry_date:
                bill.entry_date = entry_date
                update_fields.append('entry_date')
            if (bill.invoice_number or '') != shared_invoice:
                bill.invoice_number = shared_invoice
                update_fields.append('invoice_number')
            if bill.party_id != party.id:
                bill.party = party
                update_fields.append('party')
            if bill.job_ticket_id != (job_ticket.id if job_ticket else None):
                bill.job_ticket = job_ticket
                update_fields.append('job_ticket')
            if (bill.notes or '') != shared_notes:
                bill.notes = shared_notes
                update_fields.append('notes')
            if bill.created_by_id is None and request.user.is_authenticated:
                bill.created_by = request.user
                update_fields.append('created_by')
            if update_fields:
                bill.save(update_fields=update_fields + ['updated_at'])
        else:
            bill = InventoryBill.objects.create(
                bill_number=_generate_inventory_bill_number(entry_type, entry_date),
                entry_type=entry_type,
                entry_date=entry_date,
                invoice_number=shared_invoice,
                job_ticket=job_ticket,
                party=party,
                notes=shared_notes,
                created_by=request.user if request.user.is_authenticated else None,
            )

        for line in line_items:
            product = Product.objects.select_for_update().get(pk=line['product'].pk)
            quantity = int(line['quantity'])
            unit_price = line['unit_price']
            discount_amount = line['discount_amount']
            gst_rate = line['gst_rate']
            notes = line['notes']

            stock_before = product.stock_quantity
            stock_delta = quantity if entry_type in {'purchase', 'sale_return'} else -quantity
            stock_after = stock_before + stock_delta

            if stock_after < 0 and entry_type == 'purchase_return':
                raise ValueError(
                    f"Only {stock_before} unit(s) available in stock for '{product.name}'."
                )

            taxable_amount = (Decimal(quantity) * unit_price) - discount_amount
            gst_amount = (taxable_amount * gst_rate) / Decimal('100')
            total_amount = taxable_amount + gst_amount

            entry = InventoryEntry.objects.create(
                bill=bill,
                entry_number=_generate_inventory_entry_number(entry_type, entry_date),
                entry_type=entry_type,
                entry_date=entry_date,
                invoice_number=shared_invoice,
                job_ticket=job_ticket,
                party=party,
                product=product,
                quantity=quantity,
                unit_price=unit_price,
                discount_amount=discount_amount,
                gst_rate=gst_rate,
                taxable_amount=taxable_amount.quantize(Decimal('0.01')),
                gst_amount=gst_amount.quantize(Decimal('0.01')),
                total_amount=total_amount.quantize(Decimal('0.01')),
                stock_before=stock_before,
                stock_after=stock_after,
                notes=notes,
                created_by=request.user,
            )
            created_entries.append(entry)

            # Keep master product pricing fresh from purchases.
            if entry_type in {'purchase', 'purchase_return'}:
                update_fields = []
                if product.cost_price != unit_price:
                    product.cost_price = unit_price
                    update_fields.append('cost_price')
                if (product.unit_price or Decimal('0.00')) <= 0 and unit_price > 0:
                    product.unit_price = unit_price
                    update_fields.append('unit_price')
                product.stock_quantity = stock_after
                update_fields.append('stock_quantity')
                product.save(update_fields=update_fields)
            else:
                product.stock_quantity = stock_after
                product.save(update_fields=['stock_quantity'])

    return created_entries

def _prepare_inventory_sale_bill_print_context(sale_bill, sale_entries, invoice_label=''):
    subtotal_amount = Decimal('0.00')
    total_discount = Decimal('0.00')
    taxable_total = Decimal('0.00')
    tax_total = Decimal('0.00')
    grand_total = Decimal('0.00')
    total_quantity = 0

    for line in sale_entries:
        line_subtotal = (Decimal(line.quantity or 0) * (line.unit_price or Decimal('0.00'))).quantize(Decimal('0.01'))
        line.line_subtotal = line_subtotal
        total_quantity += int(line.quantity or 0)
        subtotal_amount += line_subtotal
        total_discount += line.discount_amount or Decimal('0.00')
        taxable_total += line.taxable_amount or Decimal('0.00')
        tax_total += line.gst_amount or Decimal('0.00')
        grand_total += line.total_amount or Decimal('0.00')

    linked_job_codes = sorted(
        {line.job_ticket.job_code for line in sale_entries if line.job_ticket_id}
    )

    return {
        'bill_number': sale_bill.bill_number,
        'invoice_number': (sale_bill.invoice_number or invoice_label or sale_bill.bill_number).strip(),
        'sale_entries': sale_entries,
        'party': sale_bill.party,
        'invoice_date': sale_bill.entry_date,
        'notes': sale_bill.notes or next((line.notes for line in sale_entries if (line.notes or '').strip()), ''),
        'linked_job_codes': linked_job_codes,
        'subtotal_amount': subtotal_amount,
        'total_discount': total_discount,
        'total_quantity': total_quantity,
        'taxable_total': taxable_total,
        'tax_total': tax_total,
        'grand_total': grand_total,
        'company': CompanyProfile.get_profile(),
    }

def _inventory_bill_group_key(entry):
    if getattr(entry, 'bill_id', None):
        return f"bill:{entry.bill_id}"
    invoice_number = (entry.invoice_number or '').strip()
    if invoice_number:
        return f"{entry.entry_type}:{entry.party_id}:{invoice_number}"
    return f"{entry.entry_type}:{entry.party_id}:entry-{entry.id}"

def _build_inventory_bill_summaries(entries, max_groups=None):
    bill_summaries = []
    bill_map = {}

    for entry in entries:
        bill_key = _inventory_bill_group_key(entry)
        header_bill = getattr(entry, 'bill', None) if getattr(entry, 'bill_id', None) else None
        bill = bill_map.get(bill_key)
        if bill is None:
            safe_key = re.sub(r'[^A-Za-z0-9_-]+', '-', bill_key).strip('-') or f"inventory-bill-{len(bill_summaries) + 1}"
            bill = {
                'bill_key': bill_key,
                'bill_id': header_bill.id if header_bill else None,
                'bill_number': header_bill.bill_number if header_bill else '',
                'collapse_id': f"inventory-bill-{safe_key}",
                'entry_type': header_bill.entry_type if header_bill else entry.entry_type,
                'entry_type_label': header_bill.get_entry_type_display() if header_bill else entry.get_entry_type_display(),
                'entry_date': header_bill.entry_date if header_bill else entry.entry_date,
                'invoice_number': ((header_bill.invoice_number if header_bill else entry.invoice_number) or '').strip(),
                'invoice_display': ((header_bill.invoice_number if header_bill else entry.invoice_number) or '').strip() or (header_bill.bill_number if header_bill else entry.entry_number),
                'job_ticket': header_bill.job_ticket if header_bill and header_bill.job_ticket_id else entry.job_ticket,
                'job_code': (
                    header_bill.job_ticket.job_code
                    if header_bill and header_bill.job_ticket_id
                    else (entry.job_ticket.job_code if entry.job_ticket_id else '')
                ),
                'party': header_bill.party if header_bill else entry.party,
                'party_id': header_bill.party_id if header_bill else entry.party_id,
                'created_by': header_bill.created_by if header_bill and header_bill.created_by_id else entry.created_by,
                'notes': (header_bill.notes if header_bill else entry.notes) or '',
                'lines': [],
                'voucher_numbers': [],
                'line_count': 0,
                'total_quantity': 0,
                'total_amount': Decimal('0.00'),
                'stock_effect_total': 0,
                '_product_names': [],
                '_product_seen': set(),
            }
            bill_map[bill_key] = bill
            bill_summaries.append(bill)

        bill['lines'].append(entry)
        bill['voucher_numbers'].append(entry.entry_number)
        bill['line_count'] += 1
        bill['total_quantity'] += int(entry.quantity or 0)
        bill['total_amount'] += entry.total_amount or Decimal('0.00')
        bill['stock_effect_total'] += entry.stock_effect

        if not bill['notes'] and entry.notes:
            bill['notes'] = entry.notes

        product_name = entry.product.name
        if product_name not in bill['_product_seen']:
            bill['_product_seen'].add(product_name)
            bill['_product_names'].append(product_name)

    if max_groups is not None:
        bill_summaries = bill_summaries[:max_groups]

    for bill in bill_summaries:
        product_names = bill.pop('_product_names')
        bill.pop('_product_seen', None)
        bill['primary_voucher_number'] = bill['voucher_numbers'][0] if bill['voucher_numbers'] else ''
        extra_voucher_count = max(len(bill['voucher_numbers']) - 1, 0)
        bill['voucher_display'] = (
            f"{bill['primary_voucher_number']} +{extra_voucher_count} more"
            if extra_voucher_count
            else bill['primary_voucher_number']
        )
        if len(product_names) > 2:
            bill['product_summary'] = f"{', '.join(product_names[:2])} +{len(product_names) - 2} more"
        else:
            bill['product_summary'] = ', '.join(product_names)
        bill['item_label'] = f"{bill['line_count']} item" if bill['line_count'] == 1 else f"{bill['line_count']} items"
        bill['bill_number_display'] = bill['bill_number'] or bill['primary_voucher_number']

    return bill_summaries

def _build_inventory_dashboard_metrics():
    month_start = timezone.localdate().replace(day=1)
    monthly_totals_qs = (
        InventoryEntry.objects.filter(entry_date__gte=month_start)
        .values('entry_type')
        .annotate(
            total_amount=Coalesce(Sum('total_amount', output_field=DecimalField()), Decimal('0.00')),
            total_quantity=Coalesce(Sum('quantity'), 0),
        )
    )
    monthly_totals = {row['entry_type']: row for row in monthly_totals_qs}

    monthly_purchase_total = monthly_totals.get('purchase', {}).get('total_amount', Decimal('0.00'))
    monthly_purchase_return_total = monthly_totals.get('purchase_return', {}).get('total_amount', Decimal('0.00'))
    monthly_sales_total = monthly_totals.get('sale', {}).get('total_amount', Decimal('0.00'))
    monthly_sales_return_total = monthly_totals.get('sale_return', {}).get('total_amount', Decimal('0.00'))

    monthly_purchase_qty = monthly_totals.get('purchase', {}).get('total_quantity', 0)
    monthly_purchase_return_qty = monthly_totals.get('purchase_return', {}).get('total_quantity', 0)
    monthly_sales_qty = monthly_totals.get('sale', {}).get('total_quantity', 0)
    monthly_sales_return_qty = monthly_totals.get('sale_return', {}).get('total_quantity', 0)

    monthly_stock_in_qty = monthly_purchase_qty + monthly_sales_return_qty
    monthly_stock_out_qty = monthly_sales_qty + monthly_purchase_return_qty
    monthly_net_stock_qty = monthly_stock_in_qty - monthly_stock_out_qty

    monthly_stock_in_amount = monthly_purchase_total + monthly_sales_return_total
    monthly_stock_out_amount = monthly_sales_total + monthly_purchase_return_total
    monthly_net_amount = monthly_stock_in_amount - monthly_stock_out_amount

    inventory_value = Decimal('0.00')
    for product in Product.objects.only('stock_quantity', 'cost_price'):
        inventory_value += Decimal(product.stock_quantity or 0) * (product.cost_price or Decimal('0.00'))

    reserved_stock_products = list(
        Product.objects.filter(
            reserved_stock__gt=0,
            stock_quantity__lte=F('reserved_stock'),
        ).order_by('stock_quantity', 'reserved_stock', 'name')[:8]
    )
    reserved_alert_count = Product.objects.filter(
        reserved_stock__gt=0,
        stock_quantity__lte=F('reserved_stock'),
    ).count()

    recent_entries = list(
        InventoryEntry.objects.select_related('party', 'product', 'created_by').order_by('-entry_date', '-id')[:10]
    )

    return {
        'party_count': InventoryParty.objects.count(),
        'product_count': Product.objects.count(),
        'low_stock_count': Product.objects.filter(stock_quantity__lte=5).count(),
        'reserved_alert_count': reserved_alert_count,
        'inventory_value': inventory_value.quantize(Decimal('0.01')) if inventory_value else Decimal('0.00'),
        'monthly_purchase_total': monthly_purchase_total,
        'monthly_purchase_return_total': monthly_purchase_return_total,
        'monthly_sales_total': monthly_sales_total,
        'monthly_sales_return_total': monthly_sales_return_total,
        'monthly_purchase_qty': monthly_purchase_qty,
        'monthly_purchase_return_qty': monthly_purchase_return_qty,
        'monthly_sales_qty': monthly_sales_qty,
        'monthly_sales_return_qty': monthly_sales_return_qty,
        'monthly_stock_in_qty': monthly_stock_in_qty,
        'monthly_stock_out_qty': monthly_stock_out_qty,
        'monthly_net_stock_qty': monthly_net_stock_qty,
        'monthly_stock_in_amount': monthly_stock_in_amount,
        'monthly_stock_out_amount': monthly_stock_out_amount,
        'monthly_net_amount': monthly_net_amount,
        'reserved_stock_products': reserved_stock_products,
        'recent_entries': recent_entries,
    }

def _build_inventory_party_directory(query='', start_date=None, end_date=None):
    parties = InventoryParty.objects.all()

    if query:
        parties = parties.filter(
            Q(name__icontains=query)
            | Q(legal_name__icontains=query)
            | Q(contact_person__icontains=query)
            | Q(phone__icontains=query)
            | Q(gstin__icontains=query)
            | Q(city__icontains=query)
            | Q(state_code__icontains=query)
        )

    parties = list(parties.order_by('name'))
    suppliers = list(parties)
    customers = list(parties)
    legacy_both_count = 0

    party_ids = [party.id for party in parties]
    stats_map = {}
    recent_map = {
        party_id: {
            'purchase': [],
            'purchase_return': [],
            'sale': [],
            'sale_return': [],
        }
        for party_id in party_ids
    }

    if party_ids:
        max_recent_per_type = 20 if start_date or end_date else 8
        party_entries_map = {party_id: [] for party_id in party_ids}
        recent_entries = InventoryEntry.objects.filter(party_id__in=party_ids)
        if start_date:
            recent_entries = recent_entries.filter(entry_date__gte=start_date)
        if end_date:
            recent_entries = recent_entries.filter(entry_date__lte=end_date)
        recent_entries = recent_entries.select_related(
            'bill',
            'party',
            'product',
            'job_ticket',
            'created_by',
        ).order_by('-entry_date', '-id')

        for entry in recent_entries:
            party_entries_map.setdefault(entry.party_id, []).append(entry)

        for party_id, entry_list in party_entries_map.items():
            grouped_bills = _build_inventory_bill_summaries(entry_list)
            grouped_by_type = {
                'purchase': [],
                'purchase_return': [],
                'sale': [],
                'sale_return': [],
            }

            for bill in grouped_bills:
                grouped_by_type.setdefault(bill['entry_type'], []).append(bill)

            stats_map[party_id] = {
                'purchase_count': len(grouped_by_type['purchase']),
                'purchase_amount': sum((bill['total_amount'] for bill in grouped_by_type['purchase']), Decimal('0.00')),
                'purchase_return_count': len(grouped_by_type['purchase_return']),
                'purchase_return_amount': sum((bill['total_amount'] for bill in grouped_by_type['purchase_return']), Decimal('0.00')),
                'sale_count': len(grouped_by_type['sale']),
                'sale_amount': sum((bill['total_amount'] for bill in grouped_by_type['sale']), Decimal('0.00')),
                'sale_return_count': len(grouped_by_type['sale_return']),
                'sale_return_amount': sum((bill['total_amount'] for bill in grouped_by_type['sale_return']), Decimal('0.00')),
            }

            for entry_type_key in grouped_by_type:
                recent_map[party_id][entry_type_key] = grouped_by_type[entry_type_key][:max_recent_per_type]

    def attach_party_history(party_list):
        for party in party_list:
            stats = stats_map.get(party.id, {})
            party.purchase_count = stats.get('purchase_count', 0)
            party.purchase_amount = stats.get('purchase_amount', Decimal('0.00'))
            party.purchase_return_count = stats.get('purchase_return_count', 0)
            party.purchase_return_amount = stats.get('purchase_return_amount', Decimal('0.00'))
            party.sale_count = stats.get('sale_count', 0)
            party.sale_amount = stats.get('sale_amount', Decimal('0.00'))
            party.sale_return_count = stats.get('sale_return_count', 0)
            party.sale_return_amount = stats.get('sale_return_amount', Decimal('0.00'))

            party.purchase_history = recent_map.get(party.id, {}).get('purchase', [])
            party.purchase_return_history = recent_map.get(party.id, {}).get('purchase_return', [])
            party.sale_history = recent_map.get(party.id, {}).get('sale', [])
            party.sale_return_history = recent_map.get(party.id, {}).get('sale_return', [])
            party.combined_history = sorted(
                (
                    party.purchase_history
                    + party.purchase_return_history
                    + party.sale_history
                    + party.sale_return_history
                ),
                key=lambda item: (item['entry_date'], item['bill_key']),
                reverse=True,
            )[:16]

    attach_party_history(parties)

    return {
        'parties': parties,
        'suppliers': suppliers,
        'customers': customers,
        'legacy_both_count': legacy_both_count,
        'total_parties': InventoryParty.objects.count(),
        'supplier_count': InventoryParty.objects.count(),
        'customer_count': InventoryParty.objects.count(),
    }

def _build_inventory_product_catalog(query=''):
    products = Product.objects.all()

    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(sku__icontains=query)
            | Q(category__icontains=query)
            | Q(brand__icontains=query)
            | Q(hsn_sac_code__icontains=query)
            | Q(uqc__icontains=query)
        )

    latest_purchase_entry = InventoryEntry.objects.filter(
        product=OuterRef('pk'),
        entry_type='purchase',
    ).order_by('-entry_date', '-id')
    products = products.annotate(
        latest_purchase_party=Subquery(latest_purchase_entry.values('party__name')[:1]),
        latest_purchase_invoice=Subquery(latest_purchase_entry.values('invoice_number')[:1]),
        latest_purchase_date=Subquery(latest_purchase_entry.values('entry_date')[:1]),
    )
    product_rows = list(products.order_by('name'))
    product_ids = [product.id for product in product_rows]
    opening_stock_map = {
        product.id: int(product.stock_quantity or 0)
        for product in product_rows
    }
    history_map = {
        product_id: {
            'purchase': [],
            'sale': [],
            'sale_return': [],
            'purchase_return': [],
            'combined': [],
        }
        for product_id in product_ids
    }
    max_history_per_type = 10
    max_combined_history = 20

    if product_ids:
        history_entries = (
            InventoryEntry.objects.filter(product_id__in=product_ids)
            .select_related('party')
            .order_by('-entry_date', '-id')
        )
        for entry in history_entries:
            product_history = history_map.get(entry.product_id, {})
            if entry.product_id in opening_stock_map:
                opening_stock_map[entry.product_id] -= entry.stock_effect
            bucket = product_history.get(entry.entry_type)
            if bucket is None:
                continue
            if len(bucket) < max_history_per_type:
                bucket.append(entry)
            combined = product_history.get('combined')
            if combined is not None and len(combined) < max_combined_history:
                combined.append(entry)

    def build_opening_history_entry(product, opening_quantity):
        if opening_quantity <= 0:
            return None

        opening_date = timezone.localtime(product.created_at).date() if product.created_at else None
        total_amount = (Decimal(opening_quantity) * (product.cost_price or Decimal('0.00'))).quantize(Decimal('0.01'))
        return SimpleNamespace(
            entry_type='opening_stock',
            entry_date=opening_date,
            invoice_number='Opening Stock',
            party=SimpleNamespace(name='-'),
            quantity=opening_quantity,
            total_amount=total_amount,
            created_at=product.created_at,
            sort_id=-1,
        )

    def history_sort_key(item):
        entry_date = getattr(item, 'entry_date', None) or date.min
        created_at = getattr(item, 'created_at', None)
        created_at_sort = created_at.timestamp() if created_at else 0
        sort_id = getattr(item, 'id', None)
        if sort_id is None:
            sort_id = getattr(item, 'sort_id', 0)
        return (entry_date, created_at_sort, sort_id)

    for product in product_rows:
        history = history_map.get(product.id, {})
        product.purchase_history = history.get('purchase', [])
        product.sale_history = history.get('sale', [])
        product.sale_return_history = history.get('sale_return', [])
        product.purchase_return_history = history.get('purchase_return', [])
        combined_history = list(history.get('combined', []))
        opening_entry = build_opening_history_entry(product, opening_stock_map.get(product.id, 0))
        if opening_entry:
            combined_history.append(opening_entry)
        combined_history.sort(key=history_sort_key, reverse=True)
        if len(combined_history) > max_combined_history:
            if opening_entry and opening_entry in combined_history[max_combined_history:]:
                combined_history = combined_history[:max_combined_history - 1] + [opening_entry]
            else:
                combined_history = combined_history[:max_combined_history]
        product.combined_history = combined_history
        product.has_transaction_history = bool(product.combined_history)

    return {
        'products': product_rows,
        'query': query,
        'total_products': Product.objects.count(),
        'filtered_count': len(product_rows),
        'out_of_stock_count': Product.objects.filter(stock_quantity=0).count(),
        'reserved_alert_count': Product.objects.filter(
            reserved_stock__gt=0,
            stock_quantity__lte=F('reserved_stock'),
        ).count(),
    }

def _build_inventory_register_snapshot(
    entry_type,
    *,
    query='',
    source_bill_id=None,
    source_invoice='',
    source_party_id=None,
):
    config = INVENTORY_ENTRY_CONFIG[entry_type]
    entries = InventoryEntry.objects.filter(entry_type=entry_type).select_related(
        'bill',
        'party',
        'product',
        'created_by',
        'job_ticket',
    )

    if query:
        entries = entries.filter(
            Q(entry_number__icontains=query)
            | Q(bill__bill_number__icontains=query)
            | Q(invoice_number__icontains=query)
            | Q(job_ticket__job_code__icontains=query)
            | Q(party__name__icontains=query)
            | Q(product__name__icontains=query)
        )

    source_bill_payload = None
    source_bill_lines = []
    normalized_source_invoice = (source_invoice or '').strip()
    normalized_source_bill_id = int(source_bill_id) if source_bill_id else None
    normalized_source_party_id = int(source_party_id) if source_party_id else None
    if entry_type in {'purchase_return', 'sale_return'}:
        source_entry_type = 'purchase' if entry_type == 'purchase_return' else 'sale'
        source_entries = []

        if normalized_source_bill_id:
            source_bill_obj = (
                InventoryBill.objects.filter(pk=normalized_source_bill_id, entry_type=source_entry_type)
                .select_related('party')
                .first()
            )
            if source_bill_obj:
                normalized_source_party_id = source_bill_obj.party_id
                normalized_source_invoice = (source_bill_obj.invoice_number or '').strip()
                source_entries = list(
                    source_bill_obj.lines.select_related('bill', 'party', 'product').order_by('id')
                )
        elif normalized_source_invoice and normalized_source_party_id:
            source_entries = list(
                InventoryEntry.objects.filter(
                    entry_type=source_entry_type,
                    invoice_number=normalized_source_invoice,
                    party_id=normalized_source_party_id,
                )
                .select_related('bill', 'party', 'product')
                .order_by('id')
            )

        if source_entries:
            line_map = {}
            for src in source_entries:
                row = line_map.get(src.product_id)
                if row is None:
                    line_map[src.product_id] = {
                        'product_id': src.product_id,
                        'product_name': src.product.name,
                        'product_stock': int(src.product.stock_quantity or 0),
                        'max_quantity': int(src.quantity or 0),
                        'unit_price': src.unit_price or Decimal('0.00'),
                        'gst_rate': src.gst_rate or Decimal('0.00'),
                    }
                else:
                    row['max_quantity'] += int(src.quantity or 0)

            source_bill_lines = list(line_map.values())
            source_bill_payload = {
                'bill_id': source_entries[0].bill_id,
                'bill_number': source_entries[0].bill.bill_number if source_entries[0].bill_id else '',
                'invoice_number': normalized_source_invoice,
                'party_name': source_entries[0].party.name,
                'source_label': 'Purchase' if source_entry_type == 'purchase' else 'Sales',
            }

    ordered_entries = entries.order_by('-entry_date', '-id')
    register_rows = _build_inventory_bill_summaries(ordered_entries)

    return {
        'config': config,
        'query': query,
        'entry_count': len(register_rows),
        'total_quantity': entries.aggregate(total=Coalesce(Sum('quantity'), 0))['total'],
        'total_amount': entries.aggregate(
            total=Coalesce(Sum('total_amount', output_field=DecimalField()), Decimal('0.00'))
        )['total'],
        'register_rows': register_rows,
        'show_add_entry_button': entry_type not in {'purchase_return', 'sale_return'},
        'source_bill': source_bill_payload,
        'source_bill_lines': source_bill_lines,
    }

def _serialize_inventory_bill_summary_for_api(bill):
    return {
        'bill_id': bill['bill_id'] or '',
        'bill_key': bill['bill_key'],
        'entry_type': bill['entry_type'],
        'entry_type_label': bill['entry_type_label'],
        'entry_date': bill['entry_date'].isoformat() if bill['entry_date'] else '',
        'invoice_display': bill['invoice_display'],
        'bill_number_display': bill['bill_number_display'],
        'item_label': bill['item_label'],
        'total_quantity': int(bill['total_quantity'] or 0),
        'total_amount': _money_text(bill['total_amount']),
        'product_summary': bill['product_summary'],
        'job_code': bill['job_code'] or '',
        'notes': bill['notes'] or '',
    }

def _serialize_inventory_party_for_api(party):
    return {
        'id': party.id,
        'name': party.name,
        'legal_name': party.legal_name or '',
        'contact_person': party.contact_person or '',
        'party_type': party.party_type,
        'phone': party.phone or '',
        'gst_registration_type': party.gst_registration_type,
        'gst_registration_label': party.get_gst_registration_type_display(),
        'gstin': party.gstin or '',
        'state_code': party.state_code or '',
        'default_place_of_supply_state': party.default_place_of_supply_state or '',
        'pan': party.pan or '',
        'email': party.email or '',
        'address': party.address or '',
        'shipping_address': party.shipping_address or '',
        'city': party.city or '',
        'state': party.state or '',
        'country': party.country or '',
        'pincode': party.pincode or '',
        'opening_balance': _money_text(party.opening_balance),
        'is_active': bool(party.is_active),
        'purchase_count': int(getattr(party, 'purchase_count', 0) or 0),
        'purchase_amount': _money_text(getattr(party, 'purchase_amount', Decimal('0.00'))),
        'purchase_return_count': int(getattr(party, 'purchase_return_count', 0) or 0),
        'purchase_return_amount': _money_text(getattr(party, 'purchase_return_amount', Decimal('0.00'))),
        'sale_count': int(getattr(party, 'sale_count', 0) or 0),
        'sale_amount': _money_text(getattr(party, 'sale_amount', Decimal('0.00'))),
        'sale_return_count': int(getattr(party, 'sale_return_count', 0) or 0),
        'sale_return_amount': _money_text(getattr(party, 'sale_return_amount', Decimal('0.00'))),
        'combined_history': [
            _serialize_inventory_bill_summary_for_api(bill)
            for bill in getattr(party, 'combined_history', [])
        ],
    }

def _inventory_party_form_payload_from_api(payload):
    gstin = (payload.get('gstin') or '').strip()
    return {
        'name': (payload.get('name') or '').strip(),
        'legal_name': (payload.get('legal_name') or '').strip(),
        'contact_person': (payload.get('contact_person') or '').strip(),
        'gst_registration_type': (payload.get('gst_registration_type') or ('registered' if gstin else 'unregistered')).strip(),
        'phone': (payload.get('phone') or '').strip(),
        'gstin': gstin,
        'state_code': (payload.get('state_code') or '').strip(),
        'default_place_of_supply_state': (payload.get('default_place_of_supply_state') or '').strip(),
        'pan': (payload.get('pan') or '').strip(),
        'email': (payload.get('email') or '').strip(),
        'address': (payload.get('address') or '').strip(),
        'shipping_address': (payload.get('shipping_address') or '').strip(),
        'city': (payload.get('city') or '').strip(),
        'state': (payload.get('state') or '').strip(),
        'country': (payload.get('country') or '').strip() or 'India',
        'pincode': (payload.get('pincode') or '').strip(),
        'opening_balance': str(payload.get('opening_balance') or '0.00'),
        'is_active': 'on' if _mobile_parse_bool(payload.get('is_active', True)) else '',
    }

def _serialize_inventory_product_history_for_api(entry):
    entry_type = getattr(entry, 'entry_type', '') or ''
    if entry_type == 'opening_stock':
        entry_type_label = 'Opening Stock'
    elif hasattr(entry, 'get_entry_type_display'):
        entry_type_label = entry.get_entry_type_display()
    else:
        entry_type_label = entry_type.replace('_', ' ').title()

    party = getattr(entry, 'party', None)
    return {
        'entry_type': entry_type,
        'entry_type_label': entry_type_label,
        'entry_date': entry.entry_date.isoformat() if getattr(entry, 'entry_date', None) else '',
        'invoice_number': getattr(entry, 'invoice_number', '') or '',
        'party_name': getattr(party, 'name', '') if party else '',
        'quantity': int(getattr(entry, 'quantity', 0) or 0),
        'total_amount': _money_text(getattr(entry, 'total_amount', Decimal('0.00'))),
    }

def _serialize_inventory_product_for_api(product):
    return {
        'id': product.id,
        'name': product.name,
        'sku': product.sku or '',
        'category': product.category or '',
        'brand': product.brand or '',
        'item_type': product.item_type,
        'item_type_label': product.get_item_type_display(),
        'hsn_sac_code': product.hsn_sac_code or '',
        'uqc': product.uqc or '',
        'tax_category': product.tax_category,
        'tax_category_label': product.get_tax_category_display(),
        'gst_rate': _money_text(product.gst_rate),
        'effective_gst_rate': _money_text(product.effective_gst_rate),
        'cess_rate': _money_text(product.cess_rate),
        'is_tax_inclusive_default': bool(product.is_tax_inclusive_default),
        'unit_price': _money_text(product.unit_price),
        'cost_price': _money_text(product.cost_price),
        'stock_quantity': int(product.stock_quantity or 0),
        'reserved_stock': int(product.reserved_stock or 0),
        'description': product.description or '',
        'is_active': bool(product.is_active),
        'updated_at': timezone.localtime(product.updated_at).strftime('%Y-%m-%d %H:%M'),
        'latest_purchase_party': getattr(product, 'latest_purchase_party', '') or '',
        'latest_purchase_invoice': getattr(product, 'latest_purchase_invoice', '') or '',
        'latest_purchase_date': (
            getattr(product, 'latest_purchase_date').isoformat()
            if getattr(product, 'latest_purchase_date', None)
            else ''
        ),
        'combined_history': [
            _serialize_inventory_product_history_for_api(entry)
            for entry in getattr(product, 'combined_history', [])
        ],
    }

def _serialize_inventory_register_bill_for_api(bill):
    entry_type = bill['entry_type']
    config = INVENTORY_ENTRY_CONFIG[entry_type]
    legacy_url = reverse(config['url_name'])
    print_url = ''
    return_url = ''

    if entry_type == 'sale' and bill['bill_id']:
        print_url = reverse('inventory_sales_print_bill_view', kwargs={'bill_id': bill['bill_id']})

    if entry_type == 'purchase':
        if bill['bill_id']:
            return_url = f"{reverse('inventory_purchase_return_dashboard')}?{urlencode({'source_bill_id': bill['bill_id']})}"
        elif bill['invoice_number'] and bill['party_id']:
            return_url = f"{reverse('inventory_purchase_return_dashboard')}?{urlencode({'source_invoice': bill['invoice_number'], 'source_party_id': bill['party_id']})}"
    elif entry_type == 'sale':
        if bill['bill_id']:
            return_url = f"{reverse('inventory_sales_return_dashboard')}?{urlencode({'source_bill_id': bill['bill_id']})}"
        elif bill['invoice_number'] and bill['party_id']:
            return_url = f"{reverse('inventory_sales_return_dashboard')}?{urlencode({'source_invoice': bill['invoice_number'], 'source_party_id': bill['party_id']})}"

    return {
        **_serialize_inventory_bill_summary_for_api(bill),
        'party_name': bill['party'].name if bill.get('party') else '',
        'created_by_name': bill['created_by'].username if bill.get('created_by') else '',
        'voucher_display': bill.get('voucher_display', ''),
        'legacy_url': legacy_url,
        'return_url': return_url,
        'print_url': print_url,
        'show_return_action': bool(return_url),
        'show_print_action': bool(print_url),
    }

def _inventory_form_errors(form):
    errors = {}
    for field_name, field_errors in form.errors.items():
        errors[field_name] = [str(error) for error in field_errors]
    return errors

def _normalize_tax_mode_price(raw_price, price_mode, gst_rate):
    price = raw_price or Decimal('0.00')
    if price_mode == 'with_tax' and gst_rate > 0:
        divisor = Decimal('100.00') + gst_rate
        if divisor > 0:
            price = (price * Decimal('100.00')) / divisor
    return price.quantize(Decimal('0.01'))

def _inventory_entry_dashboard(request, entry_type):
    denied = _staff_access_required(request, "inventory")
    if denied:
        return denied

    config = INVENTORY_ENTRY_CONFIG[entry_type]
    query = (request.GET.get('q') or '').strip()
    entries = InventoryEntry.objects.filter(entry_type=entry_type).select_related('bill', 'party', 'product', 'created_by', 'job_ticket')

    if query:
        entries = entries.filter(
            Q(entry_number__icontains=query)
            | Q(bill__bill_number__icontains=query)
            | Q(invoice_number__icontains=query)
            | Q(job_ticket__job_code__icontains=query)
            | Q(party__name__icontains=query)
            | Q(product__name__icontains=query)
        )

    source_bill = None
    source_bill_lines = []
    auto_open_add_modal = False
    source_party_id = None
    source_invoice = ''
    source_bill_id = None
    if entry_type in {'purchase_return', 'sale_return'}:
        source_bill_id_raw = (request.GET.get('source_bill_id') or '').strip()
        source_invoice = (request.GET.get('source_invoice') or '').strip()
        source_party_raw = (request.GET.get('source_party_id') or '').strip()
        source_entry_type = 'purchase' if entry_type == 'purchase_return' else 'sale'

        source_entries = []
        if source_bill_id_raw.isdigit():
            source_bill_id = int(source_bill_id_raw)
            source_bill_obj = (
                InventoryBill.objects.filter(pk=source_bill_id, entry_type=source_entry_type)
                .select_related('party')
                .first()
            )
            if source_bill_obj:
                source_party_id = source_bill_obj.party_id
                source_invoice = (source_bill_obj.invoice_number or '').strip()
                source_entries = list(
                    source_bill_obj.lines.select_related('bill', 'party', 'product').order_by('id')
                )
        elif source_invoice and source_party_raw.isdigit():
            source_party_id = int(source_party_raw)
            source_entries = list(
                InventoryEntry.objects.filter(
                    entry_type=source_entry_type,
                    invoice_number=source_invoice,
                    party_id=source_party_id,
                )
                .select_related('bill', 'party', 'product')
                .order_by('id')
            )

        if source_entries:
            line_map = {}
            for src in source_entries:
                row = line_map.get(src.product_id)
                if row is None:
                    line_map[src.product_id] = {
                        'product_id': src.product_id,
                        'product_name': src.product.name,
                        'product_stock': src.product.stock_quantity,
                        'max_quantity': int(src.quantity or 0),
                        'unit_price': src.unit_price or Decimal('0.00'),
                        'gst_rate': src.gst_rate or Decimal('0.00'),
                    }
                else:
                    row['max_quantity'] += int(src.quantity or 0)

            source_bill_lines = list(line_map.values())
            source_bill = {
                'bill_id': source_entries[0].bill_id,
                'bill_number': source_entries[0].bill.bill_number if source_entries[0].bill_id else '',
                'invoice_number': source_invoice,
                'party_name': source_entries[0].party.name,
                'source_label': 'Purchase' if source_entry_type == 'purchase' else 'Sales',
            }
            auto_open_add_modal = True

    line_entry_error = None
    default_gst_rate = Decimal('18.00')
    bill_discount_value = '0.00'
    bill_notes_value = ''
    if request.method == 'POST':
        if request.POST.get('inventory_entry_submit') == entry_type:
            bill_discount_value = (request.POST.get('bill_discount_amount') or '').strip() or '0.00'
            bill_notes_value = (request.POST.get('bill_notes') or '').strip()
            entry_form = InventoryEntryForm(request.POST, entry_type=entry_type)
            if entry_form.is_valid():
                try:
                    entry_date = entry_form.cleaned_data['entry_date']
                    party = entry_form.cleaned_data['party']
                    invoice_number = ''
                    if entry_type != 'sale':
                        invoice_number = (entry_form.cleaned_data.get('invoice_number') or '').strip()
                    bill_notes = bill_notes_value
                    bill_discount_amount = _parse_inventory_decimal(
                        bill_discount_value,
                        "Invalid bill discount amount.",
                    )
                    if bill_discount_amount < 0:
                        raise ValueError("Bill discount cannot be negative.")
                    if entry_type != 'sale' and not invoice_number:
                        raise ValueError("Invoice number is required.")
                    if entry_type == 'sale' and invoice_number:
                        validate_sales_invoice_number_uniqueness(invoice_number)

                    line_items = _collect_inventory_bill_lines(
                        request.POST.getlist('line_product_id[]'),
                        request.POST.getlist('line_quantity[]'),
                        request.POST.getlist('line_unit_price[]'),
                        request.POST.getlist('line_gst_rate[]'),
                    )
                    final_line_items = _apply_inventory_bill_discount(
                        line_items,
                        bill_discount_amount,
                        bill_notes,
                    )

                    created_entries = _record_inventory_entries(
                        request=request,
                        entry_type=entry_type,
                        entry_date=entry_date,
                        party=party,
                        invoice_number=invoice_number,
                        line_items=final_line_items,
                    )
                    shared_bill_number = created_entries[0].invoice_number if created_entries else invoice_number
                    messages.success(
                        request,
                        (
                            f"{config['success_label']} saved with {len(created_entries)} line(s), "
                            f"invoice {shared_bill_number}."
                        ),
                    )
                    return redirect(config['url_name'])
                except ValueError as exc:
                    line_entry_error = str(exc)
                    messages.error(request, line_entry_error)
            if not line_entry_error:
                messages.error(request, f"{config['success_label']} was not saved. Please review the form.")
        elif request.POST.get('inventory_entry_edit_submit') == entry_type:
            try:
                result = _process_inventory_grouped_bill_edit(request, entry_type=entry_type)
                messages.success(request, result['message'])
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect(config['url_name'])

            entry_id = request.POST.get('entry_id')
            entry = InventoryEntry.objects.filter(pk=entry_id, entry_type=entry_type).first()
            if not entry:
                messages.error(request, 'Selected entry was not found.')
                return redirect(config['url_name'])

            if entry_type == 'sale':
                edit_entry_date_raw = (request.POST.get('edit_entry_date') or '').strip()
                requested_bill_id = (request.POST.get('bill_id') or '').strip()
                new_invoice_number = (request.POST.get('edit_invoice_number') or '').strip()
                edit_party_id = (request.POST.get('edit_party_id') or '').strip()
                bill_notes = (request.POST.get('edit_bill_notes') or '').strip()
                bill_discount_value = (request.POST.get('edit_bill_discount_amount') or '').strip() or '0.00'
                scope_invoice = (entry.invoice_number or '').strip()
                scope_bill_id = entry.bill_id
                if requested_bill_id.isdigit():
                    scope_bill_id = int(requested_bill_id)

                if not edit_entry_date_raw:
                    messages.error(request, 'Entry date is required.')
                    return redirect(config['url_name'])
                try:
                    new_entry_date = datetime.strptime(edit_entry_date_raw, '%Y-%m-%d').date()
                except ValueError:
                    messages.error(request, 'Entry date is invalid.')
                    return redirect(config['url_name'])

                if not new_invoice_number:
                    messages.error(request, 'Invoice number is required.')
                    return redirect(config['url_name'])

                scope_qs = InventoryEntry.objects.filter(entry_type='sale')
                if scope_bill_id:
                    scope_qs = scope_qs.filter(bill_id=scope_bill_id)
                elif scope_invoice:
                    scope_qs = scope_qs.filter(invoice_number__iexact=scope_invoice)
                else:
                    scope_qs = scope_qs.filter(pk=entry.pk)
                scoped_entries = list(scope_qs.select_related('bill', 'party', 'job_ticket').order_by('id'))
                if not scoped_entries:
                    messages.error(request, 'Selected sales bill was not found.')
                    return redirect(config['url_name'])

                linked_job_ids = {row.job_ticket_id for row in scoped_entries if row.job_ticket_id}
                if len(linked_job_ids) > 1:
                    messages.error(request, 'Cannot edit a sales bill linked to multiple jobs.')
                    return redirect(config['url_name'])
                if linked_job_ids:
                    messages.error(
                        request,
                        'Service-linked sales bills must be edited from the job billing screen.',
                    )
                    return redirect(config['url_name'])

                existing_bill = scoped_entries[0].bill if scoped_entries[0].bill_id else None
                new_party = InventoryParty.objects.filter(
                    is_active=True,
                    pk=edit_party_id,
                ).first()
                if not new_party:
                    messages.error(request, "Please select a valid party.")
                    return redirect(config['url_name'])

                def parse_decimal(raw_value, label):
                    text = (raw_value or '').strip()
                    if text == '':
                        return Decimal('0.00')
                    try:
                        return Decimal(text)
                    except (InvalidOperation, TypeError, ValueError):
                        raise ValueError(label)

                try:
                    bill_discount_amount = parse_decimal(
                        bill_discount_value,
                        "Invalid bill discount amount.",
                    )
                    if bill_discount_amount < 0:
                        raise ValueError("Bill discount cannot be negative.")

                    product_ids = request.POST.getlist('edit_line_product_id[]')
                    quantities = request.POST.getlist('edit_line_quantity[]')
                    unit_prices = request.POST.getlist('edit_line_unit_price[]')
                    gst_rates = request.POST.getlist('edit_line_gst_rate[]')

                    max_lines = max(
                        len(product_ids),
                        len(quantities),
                        len(unit_prices),
                        len(gst_rates),
                    )

                    def get_row_value(values, idx):
                        if idx < len(values):
                            return (values[idx] or '').strip()
                        return ''

                    line_items = []
                    seen_product_ids = set()
                    for idx in range(max_lines):
                        product_id = get_row_value(product_ids, idx)
                        qty_raw = get_row_value(quantities, idx)
                        unit_price_raw = get_row_value(unit_prices, idx)
                        gst_raw = get_row_value(gst_rates, idx)

                        if not any([product_id, qty_raw, unit_price_raw, gst_raw]):
                            continue

                        line_no = idx + 1
                        if not product_id:
                            raise ValueError(f"Line {line_no}: select a product.")

                        try:
                            quantity = int(qty_raw or '0')
                        except (TypeError, ValueError):
                            raise ValueError(f"Line {line_no}: quantity must be a whole number.")
                        if quantity <= 0:
                            raise ValueError(f"Line {line_no}: quantity must be greater than zero.")

                        unit_price = parse_decimal(unit_price_raw, f"Line {line_no}: invalid unit price.")
                        if unit_price < 0:
                            raise ValueError(f"Line {line_no}: unit price cannot be negative.")

                        gst_rate = parse_decimal(gst_raw, f"Line {line_no}: invalid GST rate.")
                        if gst_rate < 0:
                            raise ValueError(f"Line {line_no}: GST rate cannot be negative.")

                        product = Product.objects.filter(pk=product_id, is_active=True).first()
                        if not product:
                            raise ValueError(f"Line {line_no}: selected product was not found.")
                        if product.id in seen_product_ids:
                            raise ValueError(
                                f"Line {line_no}: duplicate product '{product.name}' is not allowed in the same bill."
                            )
                        seen_product_ids.add(product.id)

                        line_amount = Decimal(quantity) * unit_price
                        line_items.append(
                            {
                                'product': product,
                                'quantity': quantity,
                                'unit_price': unit_price,
                                'line_amount': line_amount,
                                'gst_rate': gst_rate,
                            }
                        )

                    if not line_items:
                        raise ValueError("Add at least one product line.")

                    subtotal_amount = sum((line['line_amount'] for line in line_items), Decimal('0.00'))
                    if bill_discount_amount > subtotal_amount:
                        raise ValueError("Bill discount cannot exceed subtotal amount.")

                    line_discounts = [Decimal('0.00') for _ in line_items]
                    if bill_discount_amount > 0 and subtotal_amount > 0:
                        for idx, line in enumerate(line_items):
                            provisional = (
                                (bill_discount_amount * line['line_amount']) / subtotal_amount
                            ).quantize(Decimal('0.01'))
                            if provisional > line['line_amount']:
                                provisional = line['line_amount']
                            line_discounts[idx] = provisional

                        allocated_discount = sum(line_discounts, Decimal('0.00'))
                        remaining_discount = (bill_discount_amount - allocated_discount).quantize(Decimal('0.01'))
                        step = Decimal('0.01')
                        reorder_indexes = sorted(
                            range(len(line_items)),
                            key=lambda row_idx: line_items[row_idx]['line_amount'],
                            reverse=True,
                        )
                        while remaining_discount != Decimal('0.00'):
                            changed = False
                            for row_idx in reorder_indexes:
                                if remaining_discount > 0:
                                    capacity = line_items[row_idx]['line_amount'] - line_discounts[row_idx]
                                    if capacity >= step:
                                        line_discounts[row_idx] += step
                                        remaining_discount -= step
                                        changed = True
                                else:
                                    if line_discounts[row_idx] >= step:
                                        line_discounts[row_idx] -= step
                                        remaining_discount += step
                                        changed = True
                                remaining_discount = remaining_discount.quantize(Decimal('0.01'))
                                if remaining_discount == Decimal('0.00'):
                                    break
                            if not changed:
                                break

                    final_line_items = []
                    for idx, line in enumerate(line_items):
                        final_line_items.append(
                            {
                                'product': line['product'],
                                'quantity': line['quantity'],
                                'unit_price': line['unit_price'],
                                'discount_amount': line_discounts[idx],
                                'gst_rate': line['gst_rate'],
                                'notes': bill_notes,
                            }
                        )
                except ValueError as exc:
                    messages.error(request, str(exc))
                    return redirect(config['url_name'])

                try:
                    with transaction.atomic():
                        locked_scope_qs = InventoryEntry.objects.select_for_update().filter(entry_type='sale')
                        if scope_bill_id:
                            locked_scope_qs = locked_scope_qs.filter(bill_id=scope_bill_id)
                        elif scope_invoice:
                            locked_scope_qs = locked_scope_qs.filter(invoice_number__iexact=scope_invoice)
                        else:
                            locked_scope_qs = locked_scope_qs.filter(pk=entry.pk)
                        locked_entries = list(locked_scope_qs.select_related('bill', 'party', 'job_ticket').order_by('id'))
                        if not locked_entries:
                            raise ValueError('Selected sales bill was not found.')

                        locked_bill = locked_entries[0].bill if locked_entries[0].bill_id else existing_bill
                        validate_sales_invoice_number_uniqueness(
                            new_invoice_number,
                            exclude_inventory_bill_id=locked_bill.id if locked_bill else None,
                        )

                        locked_products = {
                            product.id: product
                            for product in Product.objects.select_for_update().filter(
                                pk__in={row.product_id for row in locked_entries}
                            )
                        }
                        for old_entry in locked_entries:
                            product = locked_products.get(old_entry.product_id)
                            if not product:
                                raise ValueError(
                                    f"Product for voucher '{old_entry.entry_number}' was not found."
                                )
                            restored_stock = product.stock_quantity - old_entry.stock_effect
                            if restored_stock < 0:
                                raise ValueError(
                                    (
                                        f"Cannot edit bill '{scope_invoice or old_entry.entry_number}'. "
                                        f"Stock reconciliation failed for '{product.name}'."
                                    )
                                )
                            product.stock_quantity = restored_stock
                        for product in locked_products.values():
                            product.save(update_fields=['stock_quantity'])

                        InventoryEntry.objects.filter(pk__in=[row.id for row in locked_entries]).delete()
                        created_entries = _record_inventory_entries(
                            request=request,
                            entry_type='sale',
                            entry_date=new_entry_date,
                            party=new_party,
                            invoice_number=new_invoice_number,
                            line_items=final_line_items,
                            existing_bill=locked_bill,
                        )

                    saved_invoice = created_entries[0].invoice_number if created_entries else new_invoice_number
                    messages.success(
                        request,
                        f"Sales bill {saved_invoice} updated with {len(created_entries)} line(s).",
                    )
                except ValueError as exc:
                    messages.error(request, str(exc))
                return redirect(config['url_name'])

            new_invoice_number = (request.POST.get('edit_invoice_number') or '').strip()
            new_notes = (request.POST.get('edit_notes') or '').strip()
            edit_party_id = request.POST.get('edit_party_id')
            is_service_linked_sale = entry_type == 'sale' and bool(entry.job_ticket_id)
            new_unit_price = None
            new_quantity = None
            new_gst_rate = None
            new_product = None

            if entry_type in {'purchase', 'purchase_return'}:
                valid_party_qs = InventoryParty.objects.filter(is_active=True)
                product_id_raw = (request.POST.get('edit_product_id') or '').strip()
                quantity_raw = (request.POST.get('edit_quantity') or '').strip()
                unit_price_raw = (request.POST.get('edit_unit_price') or '').strip()
                gst_rate_raw = (request.POST.get('edit_gst_rate') or '').strip()

                if not product_id_raw:
                    messages.error(request, 'Product is required.')
                    return redirect(config['url_name'])
                new_product = Product.objects.filter(pk=product_id_raw, is_active=True).first()
                if not new_product:
                    messages.error(request, 'Selected product was not found.')
                    return redirect(config['url_name'])

                try:
                    new_quantity = int(quantity_raw or '0')
                except (TypeError, ValueError):
                    messages.error(request, 'Quantity must be a whole number.')
                    return redirect(config['url_name'])
                if new_quantity <= 0:
                    messages.error(request, 'Quantity must be greater than zero.')
                    return redirect(config['url_name'])

                if unit_price_raw == '':
                    messages.error(request, 'Rate is required.')
                    return redirect(config['url_name'])
                try:
                    new_unit_price = Decimal(unit_price_raw)
                except (InvalidOperation, TypeError, ValueError):
                    messages.error(request, 'Enter a valid rate.')
                    return redirect(config['url_name'])
                if new_unit_price < 0:
                    messages.error(request, 'Rate cannot be negative.')
                    return redirect(config['url_name'])

                if gst_rate_raw == '':
                    messages.error(request, 'GST rate is required.')
                    return redirect(config['url_name'])
                try:
                    new_gst_rate = Decimal(gst_rate_raw)
                except (InvalidOperation, TypeError, ValueError):
                    messages.error(request, 'Enter a valid GST rate.')
                    return redirect(config['url_name'])
                if new_gst_rate < 0:
                    messages.error(request, 'GST rate cannot be negative.')
                    return redirect(config['url_name'])
            else:
                valid_party_qs = InventoryParty.objects.filter(is_active=True)
            if is_service_linked_sale:
                new_party = entry.party
            else:
                new_party = valid_party_qs.filter(pk=edit_party_id).first()

            if not new_invoice_number:
                messages.error(request, 'Invoice number is required.')
                return redirect(config['url_name'])
            if entry_type == 'sale' and (entry.invoice_number or '') != new_invoice_number:
                try:
                    validate_sales_invoice_number_uniqueness(
                        new_invoice_number,
                        exclude_inventory_entry_id=entry.pk,
                    )
                except ValueError as exc:
                    messages.error(request, str(exc))
                    return redirect(config['url_name'])
            if is_service_linked_sale and edit_party_id and str(edit_party_id) != str(entry.party_id):
                messages.error(
                    request,
                    'Party is fixed for service-linked sales entries and cannot be changed.',
                )
                return redirect(config['url_name'])
            if not new_party:
                messages.error(request, f"Please select a valid {config['party_label_singular'].lower()}.")
                return redirect(config['url_name'])

            original_product_id = entry.product_id
            original_quantity = entry.quantity
            original_stock_effect = entry.stock_effect

            update_fields = []
            shared_bill_update = {
                'invoice_number': new_invoice_number,
                'party_id': new_party.id,
                'notes': new_notes,
            }
            if (entry.invoice_number or '') != new_invoice_number:
                entry.invoice_number = new_invoice_number
                update_fields.append('invoice_number')
            if entry.party_id != new_party.id:
                entry.party = new_party
                update_fields.append('party')
            if (entry.notes or '') != new_notes:
                entry.notes = new_notes
                update_fields.append('notes')
            if new_product is not None and entry.product_id != new_product.id:
                entry.product = new_product
                update_fields.append('product')
            if new_quantity is not None and entry.quantity != new_quantity:
                entry.quantity = new_quantity
                update_fields.append('quantity')
            if new_unit_price is not None:
                line_amount = Decimal(entry.quantity) * new_unit_price
                if (entry.discount_amount or Decimal('0.00')) > line_amount:
                    messages.error(
                        request,
                        (
                            f"Rate is too low for voucher {entry.entry_number}. "
                            "Existing discount exceeds line amount."
                        ),
                    )
                    return redirect(config['url_name'])
                taxable_amount = line_amount - (entry.discount_amount or Decimal('0.00'))
                effective_gst_rate = new_gst_rate if new_gst_rate is not None else (entry.gst_rate or Decimal('0.00'))
                gst_amount = (taxable_amount * effective_gst_rate) / Decimal('100')
                total_amount = taxable_amount + gst_amount
                taxable_amount = taxable_amount.quantize(Decimal('0.01'))
                gst_amount = gst_amount.quantize(Decimal('0.01'))
                total_amount = total_amount.quantize(Decimal('0.01'))

                if entry.unit_price != new_unit_price:
                    entry.unit_price = new_unit_price
                    update_fields.append('unit_price')
                if new_gst_rate is not None and entry.gst_rate != new_gst_rate:
                    entry.gst_rate = new_gst_rate
                    update_fields.append('gst_rate')
                if entry.taxable_amount != taxable_amount:
                    entry.taxable_amount = taxable_amount
                    update_fields.append('taxable_amount')
                if entry.gst_amount != gst_amount:
                    entry.gst_amount = gst_amount
                    update_fields.append('gst_amount')
                if entry.total_amount != total_amount:
                    entry.total_amount = total_amount
                    update_fields.append('total_amount')

            if update_fields:
                with transaction.atomic():
                    locked_bill = None
                    if entry.bill_id:
                        locked_bill = InventoryBill.objects.select_for_update().filter(pk=entry.bill_id).first()

                    if entry_type in {'purchase', 'purchase_return'} and ('product' in update_fields or 'quantity' in update_fields):
                        original_product = Product.objects.select_for_update().filter(pk=original_product_id).first()
                        if not original_product:
                            messages.error(request, 'Original product for this voucher is missing.')
                            return redirect(config['url_name'])

                        updated_stock_effect = entry.stock_effect
                        if entry.product_id == original_product_id:
                            adjusted_stock = original_product.stock_quantity + (updated_stock_effect - original_stock_effect)
                            if adjusted_stock < 0:
                                messages.error(
                                    request,
                                    f"Cannot update voucher {entry.entry_number}. Stock would become negative for '{original_product.name}'.",
                                )
                                return redirect(config['url_name'])

                            original_product.stock_quantity = adjusted_stock
                            original_product.save(update_fields=['stock_quantity'])
                            stock_before = adjusted_stock - updated_stock_effect
                            stock_after = adjusted_stock
                        else:
                            updated_product = Product.objects.select_for_update().filter(pk=entry.product_id).first()
                            if not updated_product:
                                messages.error(request, 'Selected product was not found.')
                                return redirect(config['url_name'])

                            reverted_stock = original_product.stock_quantity - original_stock_effect
                            if reverted_stock < 0:
                                messages.error(
                                    request,
                                    (
                                        f"Cannot switch product for voucher {entry.entry_number}. "
                                        f"Current stock of '{original_product.name}' is too low to reverse old quantity ({original_quantity})."
                                    ),
                                )
                                return redirect(config['url_name'])

                            applied_stock = updated_product.stock_quantity + updated_stock_effect
                            if applied_stock < 0:
                                messages.error(
                                    request,
                                    (
                                        f"Cannot update voucher {entry.entry_number}. "
                                        f"Only {updated_product.stock_quantity} unit(s) available for '{updated_product.name}'."
                                    ),
                                )
                                return redirect(config['url_name'])

                            original_product.stock_quantity = reverted_stock
                            original_product.save(update_fields=['stock_quantity'])
                            updated_product.stock_quantity = applied_stock
                            updated_product.save(update_fields=['stock_quantity'])
                            stock_before = applied_stock - updated_stock_effect
                            stock_after = applied_stock

                        entry.stock_before = stock_before
                        entry.stock_after = stock_after
                        for field_name in ['stock_before', 'stock_after']:
                            if field_name not in update_fields:
                                update_fields.append(field_name)

                    entry.save(update_fields=update_fields)
                    if locked_bill:
                        bill_update_fields = []
                        if (locked_bill.invoice_number or '') != new_invoice_number:
                            locked_bill.invoice_number = new_invoice_number
                            bill_update_fields.append('invoice_number')
                        if locked_bill.party_id != new_party.id:
                            locked_bill.party = new_party
                            bill_update_fields.append('party')
                        if (locked_bill.notes or '') != new_notes:
                            locked_bill.notes = new_notes
                            bill_update_fields.append('notes')
                        if bill_update_fields:
                            locked_bill.save(update_fields=bill_update_fields + ['updated_at'])
                        InventoryEntry.objects.filter(bill_id=locked_bill.id).exclude(pk=entry.pk).update(
                            invoice_number=shared_bill_update['invoice_number'],
                            party_id=shared_bill_update['party_id'],
                            notes=shared_bill_update['notes'],
                        )
                    if (
                        entry_type in {'purchase', 'purchase_return'}
                        and new_unit_price is not None
                        and ('unit_price' in update_fields or 'product' in update_fields)
                    ):
                        product = Product.objects.select_for_update().filter(pk=entry.product_id).first()
                        if product and product.cost_price != new_unit_price:
                            product.cost_price = new_unit_price
                            product.save(update_fields=['cost_price'])
                messages.success(request, f"{config['success_label']} voucher {entry.entry_number} updated successfully.")
            else:
                messages.info(request, f"No changes detected for voucher {entry.entry_number}.")
            return redirect(config['url_name'])

    try:
        default_gst_rate = CompanyProfile.get_profile().gst_rate
    except Exception:
        default_gst_rate = Decimal('18.00')

    if request.method == 'POST' and request.POST.get('inventory_entry_submit') == entry_type:
        entry_form = InventoryEntryForm(request.POST, entry_type=entry_type)
    else:
        initial_data = {
            'entry_date': timezone.localdate(),
        }
        if entry_type in {'purchase_return', 'sale_return'} and source_party_id:
            initial_data['party'] = source_party_id
        if entry_type in {'purchase_return', 'sale_return'} and source_bill:
            initial_data['invoice_number'] = source_bill['invoice_number']

        entry_form = InventoryEntryForm(
            entry_type=entry_type,
            initial=initial_data,
        )

    sale_invoice_preview = ''
    if entry_type == 'sale':
        preview_entry_date = timezone.localdate()
        raw_preview_date = ''

        if request.method == 'POST' and request.POST.get('inventory_entry_submit') == entry_type:
            raw_preview_date = (request.POST.get('entry_date') or '').strip()
        else:
            initial_entry_date = entry_form.initial.get('entry_date')
            if isinstance(initial_entry_date, date):
                preview_entry_date = initial_entry_date

        if raw_preview_date:
            try:
                preview_entry_date = datetime.strptime(raw_preview_date, '%Y-%m-%d').date()
            except ValueError:
                preview_entry_date = timezone.localdate()

        sale_invoice_preview = _generate_inventory_invoice_number('sale', preview_entry_date)

    edit_party_options = InventoryParty.objects.filter(is_active=True).order_by('name')

    ordered_entries = entries.order_by('-entry_date', '-id')
    register_is_grouped = True
    register_rows = _build_inventory_bill_summaries(ordered_entries)
    entry_count_value = len(register_rows)
    register_empty_colspan = 9

    def money_text(amount):
        return format((amount or Decimal('0.00')).quantize(Decimal('0.01')), 'f')

    inventory_bill_payload = {}
    for bill in register_rows:
        payload_key = str(bill['bill_id'] or bill['bill_key'])
        lines = sorted(bill['lines'], key=lambda row: row.id)
        inventory_bill_payload[payload_key] = {
            'bill_id': bill['bill_id'] or '',
            'bill_number': bill['bill_number'],
            'invoice_number': bill['invoice_number'],
            'entry_date': bill['entry_date'].isoformat() if bill['entry_date'] else '',
            'party_id': bill['party_id'],
            'party_name': bill['party'].name,
            'job_code': bill['job_code'] or '',
            'party_locked': bool(bill['job_ticket']),
            'bill_notes': bill['notes'] or '',
            'bill_discount_amount': money_text(
                sum((row.discount_amount or Decimal('0.00') for row in lines), Decimal('0.00'))
            ),
            'lines': [
                {
                    'entry_id': row.id,
                    'entry_number': row.entry_number,
                    'product_id': row.product_id,
                    'quantity': int(row.quantity or 0),
                    'unit_price': money_text(row.unit_price),
                    'gst_rate': money_text(row.gst_rate),
                    'taxable_amount': money_text(row.taxable_amount),
                    'gst_amount': money_text(row.gst_amount),
                    'total_amount': money_text(row.total_amount),
                }
                for row in lines
            ],
        }

    context = {
        'config': config,
        'entry_type': entry_type,
        'entry_form': entry_form,
        'edit_party_options': edit_party_options,
        'line_products': Product.objects.filter(is_active=True).order_by('name'),
        'default_gst_rate': default_gst_rate,
        'line_entry_error': line_entry_error,
        'entries': ordered_entries,
        'register_rows': register_rows,
        'register_is_grouped': register_is_grouped,
        'register_empty_colspan': register_empty_colspan,
        'query': query,
        'entry_count': entry_count_value,
        'total_quantity': entries.aggregate(total=Coalesce(Sum('quantity'), 0))['total'],
        'total_amount': entries.aggregate(total=Coalesce(Sum('total_amount', output_field=DecimalField()), Decimal('0.00')))['total'],
        'bill_discount_value': bill_discount_value,
        'bill_notes_value': bill_notes_value,
        'source_bill': source_bill,
        'source_bill_lines': source_bill_lines,
        'source_bill_mode': bool(source_bill_lines),
        'auto_open_add_modal': auto_open_add_modal,
        'sale_invoice_preview': sale_invoice_preview,
        'inventory_bill_payload': inventory_bill_payload,
        'show_add_entry_button': entry_type not in {'purchase_return', 'sale_return'},
    }
    return render(request, 'job_tickets/inventory_entry_dashboard.html', context)

def get_company_start_date():
    """Finds the creation date of the very first job ticket."""
    first_job = JobTicket.objects.order_by('created_at').first()
    return first_job.created_at.date() if first_job else timezone.localdate()

__all__ = [name for name in globals() if not name.startswith("__") and name != "__all__"]
