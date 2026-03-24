# job_tickets/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from .forms import TechnicianCreationForm
from .access_control import (
    ACCESS_OPTIONS,
    apply_staff_access,
    clear_staff_access,
    get_staff_access,
    parse_access_keys,
    user_has_staff_access,
)
from datetime import datetime, timedelta, date
from django.db.models import Max, Q, Sum, Count, F, DecimalField, Value, OuterRef, Subquery, IntegerField
from .models import (
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
from .forms import JobTicketForm, AssignJobForm, ServiceLogForm, ReworkForm, DiscountForm, AssignVendorForm, ReturnVendorServiceForm, ReassignTechnicianForm, VendorForm, FeedbackForm, CompanyProfileForm, ClientForm, ProductForm, InventoryPartyForm, InventoryEntryForm, WhatsAppIntegrationSettingsForm
from .phone_utils import normalize_indian_phone, phone_lookup_variants
from .whatsapp_service import verify_receipt_access_token
from django.db import transaction, OperationalError, ProgrammingError
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseBadRequest, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.contrib import messages
from django.db.models.functions import Coalesce
from decimal import Decimal, InvalidOperation
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from uuid import uuid4 
from django.urls import reverse
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
from urllib.parse import urlencode

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

        return schema, checklist_title, checklist_notes

    if 'laptop' in normalized_type:
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

    overall_revenue = service_revenue + stock_sales_income + vendor_revenue
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
        from .consumers import STAFF_GROUP, TECH_GROUP
        
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

def home(request):
    context = {
        'total_jobs': JobTicket.objects.count(),
        'total_clients': Client.objects.count(),
        'total_products': Product.objects.count(),
    }
    return render(request, 'job_tickets/home.html', context)

def unauthorized(request):
    return render(request, 'job_tickets/unauthorized.html')

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

@never_cache
def login_view(request):
    next_url = _get_safe_next_url(request)
    if request.user.is_authenticated:
        if next_url:
            return redirect(next_url)
        return _get_post_login_redirect(request.user)

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        
        # Rate limiting check
        client_ip = request.META.get('REMOTE_ADDR')
        cache_key = f'login_attempts_{client_ip}'
        attempts = cache.get(cache_key, 0)
        
        if attempts >= 5:
            return render(request, 'job_tickets/login.html', {
                'error': 'Too many failed attempts. Please try again in 15 minutes.',
                'locked': True
            })
        
        user = authenticate(request, username=username, password=password)
        if user is not None:
            # Clear failed attempts on successful login
            cache.delete(cache_key)
            login(request, user)
            request.session.set_expiry(settings.SESSION_IDLE_TIMEOUT_SECONDS)
            if next_url:
                return redirect(next_url)
            return _get_post_login_redirect(user)
        else:
            # Increment failed attempts
            cache.set(cache_key, attempts + 1, 900)  # 15 minutes
            return render(request, 'job_tickets/login.html', {
                'error': 'Invalid username or password',
                'username': username,
                'next': next_url,
                'attempts_left': 4 - attempts
            })
    return render(request, 'job_tickets/login.html', {'next': next_url})

@never_cache
def logout_view(request):
    request._audit_session_key = request.session.session_key
    request._session_logout_reason = UserSessionActivity.STATUS_LOGGED_OUT
    request._session_was_terminated = True
    logout(request)
    return redirect('home')

def job_creation_success(request, job_code):
    job_ticket = get_object_or_404(JobTicket, job_code=job_code)
    context = {
        'job_ticket': job_ticket
    }
    return render(request, 'job_tickets/job_creation_success.html', context)

# job_tickets/views.py (def get_report_period(request))

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

@login_required
def staff_dashboard(request):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    
    # Ensure Decimal is imported
    from decimal import Decimal, InvalidOperation
    period = get_report_period(request)
    start_of_period = period['start']
    end_of_period = period['end']
    
    # --- START: REWRITTEN JOB CREATION POST HANDLER FOR MULTI-DEVICE ---
    if request.method == 'POST' and 'job_ticket_form_submit' in request.POST:

        is_ajax_request = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        # CRITICAL STEP: Generate one group ID for this entire customer submission batch
        submission_group_id = str(uuid4())

        # 1. Extract static customer data from the form.
        customer_name = (request.POST.get('customer_name') or '').strip()
        customer_phone, customer_phone_error = normalize_indian_phone(
            request.POST.get('customer_phone'),
            field_label='Customer Phone',
        )

        estimated_amount_raw = (request.POST.get('estimated_amount') or '').strip()
        estimated_delivery_raw = request.POST.get('estimated_delivery')
        
        # Basic Validation
        basic_errors = []
        field_errors = {}
        if not customer_name:
            field_errors['customer_name'] = "Customer Name is required."
            basic_errors.append(field_errors['customer_name'])
        if customer_phone_error:
            field_errors['customer_phone'] = customer_phone_error
            basic_errors.append(customer_phone_error)

        if basic_errors:
            if is_ajax_request:
                return JsonResponse(
                    {'success': False, 'message': " ".join(basic_errors), 'field_errors': field_errors},
                    status=400,
                )
            request.session['show_create_job_modal'] = True
            for error in basic_errors:
                messages.error(request, error)
            return redirect('staff_dashboard')

        # Auto-create or refresh the client directory.
        try:
            existing_client = Client.objects.filter(phone__in=phone_lookup_variants(customer_phone)).order_by('id').first()
            if existing_client:
                client_updated_fields = []
                if existing_client.name != customer_name:
                    existing_client.name = customer_name
                    client_updated_fields.append('name')
                if existing_client.phone != customer_phone:
                    existing_client.phone = customer_phone
                    client_updated_fields.append('phone')
                if client_updated_fields:
                    existing_client.save(update_fields=client_updated_fields)
            else:
                Client.objects.create(phone=customer_phone, name=customer_name)
        except Exception:
            # Client directory sync should not block ticket creation.
            pass

        try:
            estimated_amount = Decimal(estimated_amount_raw) if estimated_amount_raw else None
        except InvalidOperation:
            error_message = "Invalid input for Estimated Amount. Please enter a valid number."
            if is_ajax_request:
                return JsonResponse({'success': False, 'message': error_message}, status=400)
            request.session['show_create_job_modal'] = True
            messages.error(request, error_message)
            return redirect('staff_dashboard')

        estimated_delivery = None
        
        if estimated_delivery_raw:
            try:
                # The browser sends date input as YYYY-MM-DD
                estimated_delivery = datetime.strptime(estimated_delivery_raw, '%Y-%m-%d').date()
            except ValueError:
                error_message = "Invalid Estimated Delivery date format."
                if is_ajax_request:
                    return JsonResponse({'success': False, 'message': error_message}, status=400)
                request.session['show_create_job_modal'] = True
                messages.error(request, error_message)
                return redirect('staff_dashboard')
        
        # 2. Identify and collect all device submissions using JavaScript's array naming
        device_submissions = []
        device_photo_payloads = []
        validation_errors = []
        i = 0
        # This loop correctly parses the dynamic fields sent by the frontend
        while request.POST.get(f'device_forms[{i}].device_type'):
            
            device_type = (request.POST.get(f'device_forms[{i}].device_type') or '').strip()
            device_brand = (request.POST.get(f'device_forms[{i}].device_brand') or '').strip()
            device_model = (request.POST.get(f'device_forms[{i}].device_model') or '').strip()
            device_serial = (request.POST.get(f'device_forms[{i}].device_serial') or '').strip()
            reported_issue = (request.POST.get(f'device_forms[{i}].reported_issue') or '').strip()
            additional_items = (request.POST.get(f'device_forms[{i}].additional_items') or '').strip()
            photo_files = request.FILES.getlist(f'device_forms[{i}].device_photos')

            required_fields = [
                ('device_type', device_type, 'Device type'),
                ('device_brand', device_brand, 'Device brand'),
                ('device_model', device_model, 'Device model'),
                ('reported_issue', reported_issue, 'Reported issue'),
            ]

            missing_fields = [label for _, value, label in required_fields if not value]
            if missing_fields:
                for field_name, value, label in required_fields:
                    if not value:
                        validation_errors.append({
                            'device_index': i,
                            'field': field_name,
                            'message': f'{label} is required.'
                        })
            else:
                # Checkbox sends 'on' if checked, otherwise it's absent
                is_under_warranty_val = request.POST.get(f'device_forms[{i}].is_under_warranty')
                is_under_warranty = True if is_under_warranty_val == 'on' else False

                device_submissions.append({
                    'device_type': device_type,
                    'device_brand': device_brand,
                    'device_model': device_model,
                    'device_serial': device_serial,
                    'reported_issue': reported_issue,
                    'additional_items': additional_items,
                    'is_under_warranty': is_under_warranty,
                })
                device_photo_payloads.append(photo_files)
            i += 1

        if validation_errors:
            if is_ajax_request:
                return JsonResponse({'success': False, 'errors': validation_errors}, status=400)
            request.session['show_create_job_modal'] = True
            for error in validation_errors:
                messages.error(request, f"Device #{error['device_index'] + 1}: {error['message']}")
            return redirect('staff_dashboard')

        if not device_submissions:
            error_message = "Please add at least one device to create a job ticket."
            if is_ajax_request:
                return JsonResponse({'success': False, 'message': error_message}, status=400)
            request.session['show_create_job_modal'] = True
            messages.error(request, error_message)
            return redirect('staff_dashboard')

        # 3. Create Jobs in a Transaction
        with transaction.atomic():
            created_job_codes = []
            created_jobs_payload = []
            
            for idx, device_data in enumerate(device_submissions):
                photo_files = device_photo_payloads[idx] if idx < len(device_photo_payloads) else []
                # CRITICAL: Call the helper function to get a unique, simple job code
                new_job_code = get_next_job_code() 
                
                new_job = JobTicket.objects.create(
                    job_code=new_job_code,
                    customer_name=customer_name,
                    customer_phone=customer_phone,
                    created_by=request.user,
                    estimated_amount=estimated_amount,
                    estimated_delivery=estimated_delivery,
                    customer_group_id=submission_group_id, 
                    **device_data 
                )

                if photo_files:
                    for photo_file in photo_files:
                        if photo_file:
                            content_type = (getattr(photo_file, 'content_type', '') or '').strip()
                            if not content_type:
                                guessed_type, _ = mimetypes.guess_type(getattr(photo_file, 'name', ''))
                                content_type = guessed_type or 'application/octet-stream'

                            JobTicketPhoto.objects.create(
                                job_ticket=new_job,
                                image_name=(getattr(photo_file, 'name', '') or 'device-photo').strip()[:255],
                                image_content_type=content_type[:100],
                                image_data=photo_file.read(),
                            )
                
                JobTicketLog.objects.create(job_ticket=new_job, user=request.user, action='CREATED', details=f"Job ticket created for device: {device_data['device_type']}.")
                
                created_job_codes.append(new_job.job_code)
                created_jobs_payload.append({
                    'job_code': new_job.job_code,
                    'customer_name': new_job.customer_name,
                    'customer_phone': new_job.customer_phone,
                    'device_type': new_job.device_type,
                    'detail_url': reverse('staff_job_detail', args=[new_job.job_code]),
                    'receipt_url': reverse('job_creation_receipt_print', args=[new_job.job_code]),
                })

        success_message = (
            f"Successfully created {len(created_job_codes)} new job ticket(s) for {customer_name}."
            if len(created_job_codes) > 1
            else f"Job {created_job_codes[0]} created successfully."
        )

        # Keep preset lists useful by learning values from created tickets.
        try:
            sync_job_field_presets(device_submissions)
        except Exception:
            pass

        if is_ajax_request:
            response_data = {
                'success': True,
                'message': success_message,
                'job_codes': created_job_codes,
                'jobs': created_jobs_payload,
            }
            if len(created_job_codes) == 1:
                response_data['redirect_url'] = reverse('job_creation_success', args=[created_job_codes[0]])
            return JsonResponse(response_data)

        # 4. Success Redirection (non-AJAX)
        if len(created_job_codes) == 1:
            return redirect('job_creation_success', job_code=created_job_codes[0])
        else:
            messages.success(request, success_message)
            return redirect('staff_dashboard')
    # --- END: REWRITTEN JOB CREATION POST HANDLER ---

    # --- START: NON-CREATION POST HANDLERS & GET LOGIC (Code is kept identical to yours below) ---

    # Handle Job Assignment Form (Logic retained)
    else: # This 'else' catches the GET request for the dashboard initially
        form = JobTicketForm()
        
    if request.method == 'POST' and 'assign_job_form_submit' in request.POST:
        assign_form = AssignJobForm(request.POST)
        if assign_form.is_valid():
            job_code = assign_form.cleaned_data['job_code']
            technician = assign_form.cleaned_data['technician']
            job_to_assign = get_object_or_404(JobTicket, job_code=job_code)
        
            old_status = job_to_assign.get_status_display()
            job_to_assign.assigned_to = technician
            job_to_assign.status = 'Under Inspection'
            # mark as new assignment so the technician sees a notification/badge
            job_to_assign.is_new_assignment = True
            job_to_assign.save(update_fields=['assigned_to', 'status', 'updated_at', 'is_new_assignment'])

            details = f"Assigned to technician '{technician.user.username}' and status changed from '{old_status}' to 'Under Inspection'."
            JobTicketLog.objects.create(job_ticket=job_to_assign, user=request.user, action='ASSIGNED', details=details)
            
            # Send WebSocket update for real-time job assignment notification
            send_job_update_message(job_to_assign.job_code, job_to_assign.status)
            
            messages.success(request, f"Job {job_to_assign.job_code} assigned to {technician.user.username}.")
            return redirect('staff_dashboard')
    else:
        assign_form = AssignJobForm()
    
    # START: NEW VENDOR ASSIGNMENT LOGIC (Logic retained)
    if request.method == 'POST' and 'assign_vendor_form_submit' in request.POST:
        assign_vendor_form = AssignVendorForm(request.POST)
        if assign_vendor_form.is_valid():
            data = assign_vendor_form.cleaned_data
            service = get_object_or_404(SpecializedService, id=data['specialized_service_id'])
            
            with transaction.atomic():
                service.vendor = data['vendor']
                # Costs will be entered when device returns from vendor
                service.status = 'Sent to Vendor'
                service.sent_date = timezone.now()
                service.save()
                
                details = f"Assigned to vendor '{service.vendor.company_name}' and sent for service."
                JobTicketLog.objects.create(job_ticket=service.job_ticket, user=request.user, action='STATUS', details=details)

            messages.success(request, f"Job {service.job_ticket.job_code} assigned to {service.vendor.company_name}.")
            
            # CHANNELS: Send update (removed - Django Channels no longer used)
            
            return redirect('staff_dashboard')

    # GET QUERY AND LIST FETCHING (Logic retained)
    query = request.GET.get('q')
    search_results = []
    if query:
        search_results = list(JobTicket.objects.filter(
            Q(job_code__icontains=query) |
            Q(customer_name__icontains=query) |
            Q(customer_phone__icontains=query)
        ).select_related(
            'assigned_to__user'
        ).prefetch_related(
            'service_logs'
        ).order_by('-created_at'))
        
        try:
            # Calculate totals for search results
            calculate_job_totals(search_results)
        except InvalidOperation:
            messages.error(request, "Error calculating job totals. Some values may be incorrect.")
        
        # Use search results for all status filters
        job_tickets = JobTicket.objects.filter(
            Q(job_code__icontains=query) |
            Q(customer_name__icontains=query) |
            Q(customer_phone__icontains=query)
        ).order_by('-created_at')
    else:
        job_tickets = JobTicket.objects.all().order_by('-created_at')
    
    pending_jobs = job_tickets.filter(status='Pending')
    returned_jobs = job_tickets.filter(status='Returned')
    ready_for_pickup_jobs = job_tickets.filter(status='Ready for Pickup')
    completed_jobs = job_tickets.filter(status='Completed')
    awaiting_assignment = SpecializedService.objects.filter(status='Awaiting Assignment').select_related('job_ticket')

    # Fetch and group in-progress jobs by technician (Logic retained)
    in_progress_jobs_qs = job_tickets.filter(
        Q(status='Under Inspection') | Q(status='Repairing')
    ).select_related('assigned_to__user')

    grouped_in_progress_jobs = {}
    for job in in_progress_jobs_qs:
        key = job.assigned_to.user.username if job.assigned_to and job.assigned_to.user else "Unassigned"
        if key not in grouped_in_progress_jobs:
            grouped_in_progress_jobs[key] = []
        grouped_in_progress_jobs[key].append(job)

    # Create a form instance for each of these jobs (Logic retained)
    for service in awaiting_assignment:
        service.form = AssignVendorForm(initial={'specialized_service_id': service.id})

    sent_to_vendor = SpecializedService.objects.filter(status='Sent to Vendor').select_related('job_ticket', 'vendor')

    # assignment lists for staff to review (Logic retained)
    pending_assignments = Assignment.objects.filter(
        status='pending'
    ).select_related('job', 'technician__user').order_by('-created_at')

    rejected_assignments = Assignment.objects.filter(
        status='rejected'
    ).select_related('job', 'technician__user').order_by('-responded_at')

    accepted_assignments = Assignment.objects.filter(
        status='accepted'
    ).select_related('job', 'technician__user').order_by('-responded_at')

    # FINAL CONTEXT
    context = {
        'form': JobTicketForm(), # Use an empty form here for any generic field access in the template
        'assign_form': assign_form,
        'job_field_presets': get_job_field_presets(),
        'show_create_job_modal': request.session.pop('show_create_job_modal', False),
        'pending_jobs': pending_jobs,
        'grouped_in_progress_jobs': grouped_in_progress_jobs,
        'in_progress_jobs_count': in_progress_jobs_qs.count(),
        'returned_jobs': returned_jobs,
        'ready_for_pickup_jobs': ready_for_pickup_jobs,
        'completed_jobs': completed_jobs,
        'username': request.user.username,
        'query': query,
        'search_results': search_results,
        'search_count': len(search_results) if query else 0,
        'pending_assignments': pending_assignments,
        'rejected_assignments': rejected_assignments,
        'accepted_assignments': accepted_assignments,
        'awaiting_assignment_jobs': awaiting_assignment,
        'sent_to_vendor_jobs': sent_to_vendor,
        'pending_count': pending_jobs.count(),
        'ready_count': ready_for_pickup_jobs.count(),
        'completed_count': completed_jobs.count(),
        'returned_count': returned_jobs.count(),
    }
    return render(request, 'job_tickets/staff_dashboard.html', context)

# job_tickets/views.py

# job_tickets/views.py

@login_required
def technician_dashboard(request):
    if not request.user.groups.filter(name='Technicians').exists():
        return redirect('unauthorized')

    technician = TechnicianProfile.objects.filter(user=request.user).first()
    if not technician:
        # ... (Handle missing profile) ...
        return render(request, 'job_tickets/technician_dashboard.html', {
            'active_jobs': [], 'history_jobs': [], 'username': request.user.username, 
            'warning': 'No technician profile found. Contact admin.'
        })
    
    # Handle search query
    query = request.GET.get('q', '').strip()
    search_results = []
    if query:
        search_results = list(JobTicket.objects.filter(
            Q(assigned_to=technician) &
            (Q(job_code__icontains=query) |
             Q(customer_name__icontains=query) |
             Q(customer_phone__icontains=query) |
             Q(device_type__icontains=query))
        ).prefetch_related('service_logs').order_by('-created_at'))
        calculate_job_totals(search_results, exclude_vendor_charges=True)

    # --- 1. GET DATE FILTERS (Year and Month) ---
    report_month_param = request.GET.get('report_month')
    preset = request.GET.get('preset') # NEW: Get preset parameter
    
    history_filter = Q(assigned_to=technician)  # Start with assigned technician filter
    current_year = None
    current_month = None

    # Get the current local date once
    today = timezone.localdate()

    # NEW: Handle presets first
    if preset == 'this_month':
        current_year = today.year
        current_month = today.month
        report_month_param = None # Clear report_month_param if preset is used
    elif preset == 'last_month':
        first_day_of_current_month = today.replace(day=1)
        last_month_date = first_day_of_current_month - timedelta(days=1)
        current_year = last_month_date.year
        current_month = last_month_date.month
        report_month_param = None # Clear report_month_param if preset is used
    
    if report_month_param:
        try:
            year_str, month_str = report_month_param.split('-')
            year = int(year_str)
            month = int(month_str)
            
            start_of_period = timezone.make_aware(datetime(year, month, 1, 0, 0, 0))
            
            if month == 12:
                end_of_period = start_of_period.replace(year=year + 1, month=1)
            else:
                end_of_period = start_of_period.replace(month=month + 1)
            
            # Apply time filter to history jobs
            history_filter &= Q(updated_at__gte=start_of_period, updated_at__lt=end_of_period)
            
            current_year = year
            current_month = month
            
        except (ValueError, TypeError):
            messages.error(request, "Invalid month or year provided for filtering history.")
            # If invalid, default to current month/year
            current_year = today.year
            current_month = today.month
            start_of_period = timezone.make_aware(datetime(current_year, current_month, 1, 0, 0, 0))
            if current_month == 12:
                end_of_period = start_of_period.replace(year=current_year + 1, month=1)
            else:
                end_of_period = start_of_period.replace(month=current_month + 1)
            history_filter &= Q(updated_at__gte=start_of_period, updated_at__lt=end_of_period)
    else:
        # Default to the current month and year if no filter is applied or if a preset was used
        if current_year is None or current_month is None: # Only if not set by preset
            current_year = today.year
            current_month = today.month
        
        start_of_period = timezone.make_aware(datetime(current_year, current_month, 1, 0, 0, 0))
        if current_month == 12:
            end_of_period = start_of_period.replace(year=current_year + 1, month=1)
        else:
            end_of_period = start_of_period.replace(month=current_month + 1)
            
        history_filter &= Q(updated_at__gte=start_of_period, updated_at__lt=end_of_period)


    # --- 2. DEFINE JOB LISTS ---
    # Treat these statuses as finished for the technician's "active" view so they don't appear
    # in the technician active jobs list. 'Ready for Pickup' is a customer-facing state and
    # should not be shown in the technician's active work queue.
    # Also exclude 'Returned' jobs as they are no longer with technician
    finished_statuses = ['Completed', 'Closed', 'Ready for Pickup', 'Returned']
    
    # Active Jobs (Unfiltered by date, exclude returned jobs)
    active_jobs_query = JobTicket.objects.filter(assigned_to=technician).prefetch_related('service_logs', 'specialized_service').exclude(status__in=finished_statuses).order_by('created_at')
    
    active_jobs = list(active_jobs_query)
    
    # Add vendor return indicator to each job
    for job in active_jobs:
        job.returned_from_vendor = False
        if hasattr(job, 'specialized_service') and job.specialized_service:
            job.returned_from_vendor = job.specialized_service.status == 'Returned from Vendor'
    
    # History Jobs (Filtered by date, status, and assigned technician)
    # Remove 'Returned' from history as these jobs are not completed by technician
    history_finished_statuses = ['Completed', 'Closed', 'Ready for Pickup']
    history_jobs = list(
        JobTicket.objects.filter(history_filter)
        .filter(status__in=history_finished_statuses)
        .prefetch_related('service_logs')
        .order_by('-updated_at')
    )

    # 3. Calculate totals excluding vendor charges for technician view
    calculate_job_totals(active_jobs, exclude_vendor_charges=True)
    calculate_job_totals(history_jobs, exclude_vendor_charges=True)

    # 4. Calculate history summary totals (Footer totals)
    history_parts_total = sum(j.part_total for j in history_jobs)
    history_service_total = sum(j.service_total for j in history_jobs)
    history_grand_total = history_parts_total + history_service_total
    
    # 5. Render context
    context = {
        'technician': technician,
        'active_jobs': active_jobs,
        'history_jobs': history_jobs,
        'username': request.user.username,
        'history_parts_total': history_parts_total,
        'history_service_total': history_service_total,
        'history_grand_total': history_grand_total,
        
        # Search functionality
        'query': query,
        'search_results': search_results,
        'search_count': len(search_results) if query else 0,
        
        # Dates for the filter inputs
        'current_year': current_year,
        'current_month': current_month,
        'current_month_filter': f"{current_year:04d}-{current_month:02d}", # YYYY-MM format for input value
        'technician_join_month': technician.user.date_joined.strftime('%Y-%m'), # YYYY-MM
        'current_month_year': today.strftime('%Y-%m'), # YYYY-MM
        'month_options': [(i, date(2000, i, 1).strftime('%B')) for i in range(1, 13)],
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        # Return both history table and active jobs table for AJAX updates
        history_html = render_to_string('job_tickets/_history_table.html', context, request=request)
        
        # Also render active jobs table rows
        active_jobs_html = render_to_string('job_tickets/_active_jobs_table.html', {
            'active_jobs': active_jobs,
            'request': request,
        }, request=request)
        
        return JsonResponse({
            'html': history_html,
            'active_jobs_html': active_jobs_html
        })

    return render(request, 'job_tickets/technician_dashboard.html', context)

@login_required
def job_detail_technician(request, job_code):
    # only technicians allowed
    if not request.user.groups.filter(name='Technicians').exists():
        return redirect('unauthorized')

    # safe lookup of TechnicianProfile (avoids AttributeError if profile missing)
    technician = TechnicianProfile.objects.filter(user=request.user).first()
    if not technician:
        messages.warning(request, "No technician profile found. Contact admin.")
        return redirect('unauthorized')

    # fetch job assigned to this technician
    job = get_object_or_404(JobTicket, job_code=job_code, assigned_to=technician)

    # ----------------------------------------------------
    # CORE CHANGE: Filter Status Choices for Technicians
    # ----------------------------------------------------
    EXCLUDED_STATUSES = ['Ready for Pickup', 'Closed']
    
    # Create a filtered list from the model's choices
    technician_status_choices = [
        (value, label) for value, label in job.STATUS_CHOICES # Access choices from the JobTicket model
        if label not in EXCLUDED_STATUSES
    ]
    
    # Additional restriction: If job is in Specialized Service, check if it's returned from vendor
    can_change_status = True
    if job.status == 'Specialized Service':
        # Check if there's a specialized service record and if it's returned from vendor
        specialized_service = getattr(job, 'specialized_service', None)
        if specialized_service and specialized_service.status != 'Returned from Vendor':
            can_change_status = False
    checklist_schema, checklist_title, checklist_notes = _build_checklist_schema_for_job(job)
    # ----------------------------------------------------

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_status':
            new_status = (request.POST.get('status') or '').strip()
            technician_notes = request.POST.get('technician_notes', '')
            posted_answers, missing_required_labels, invalid_option_labels = _extract_checklist_answers_from_post(
                request.POST,
                checklist_schema,
            )
            existing_answers = _get_job_checklist_answers(job)
            merged_answers = _merge_checklist_answers(existing_answers, posted_answers)

            # VALIDATION: Ensure the technician didn't somehow post an excluded status
            if new_status in EXCLUDED_STATUSES:
                 messages.error(request, 'Invalid status update attempt.')
                 return redirect('job_detail_technician', job_code=job_code)

            if invalid_option_labels:
                error_message = (
                    "Invalid checklist selection for: "
                    + ', '.join(invalid_option_labels[:6])
                    + ('...' if len(invalid_option_labels) > 6 else '')
                )
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse(
                        {
                            'ok': False,
                            'message': error_message,
                            'invalid_checklist_fields': invalid_option_labels,
                        },
                        status=400,
                    )
                messages.error(request, error_message)
                return redirect('job_detail_technician', job_code=job_code)

            if new_status == 'Completed' and missing_required_labels:
                error_message = _format_checklist_required_error(missing_required_labels)
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse(
                        {
                            'ok': False,
                            'message': error_message,
                            'missing_checklist_fields': missing_required_labels,
                        },
                        status=400,
                    )
                messages.error(request, error_message)
                return redirect('job_detail_technician', job_code=job_code)
            
            # VALIDATION: Check if job is in specialized service and not returned from vendor
            if job.status == 'Specialized Service':
                specialized_service = getattr(job, 'specialized_service', None)
                if specialized_service and specialized_service.status != 'Returned from Vendor':
                    error_message = 'Cannot change status while job is with vendor. Wait for vendor to return the device.'
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'ok': False, 'message': error_message}, status=403)
                    messages.error(request, error_message)
                    return redirect('job_detail_technician', job_code=job_code)

            # GET OLD VALUES BEFORE SAVING
            old_status = job.get_status_display()
            old_notes = job.technician_notes
            old_answers = _get_job_checklist_answers(job)

            job.status = new_status
            job.technician_notes = technician_notes
            job.technician_checklist = merged_answers
            job.save()

            if old_status != new_status:
                details = f"Status changed from '{old_status}' to '{job.get_status_display()}'."
                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='STATUS', details=details)
                # Send WebSocket update
                send_job_update_message(job.job_code, job.status)

            if old_notes != technician_notes:
                details = f"Technician notes updated: \"{technician_notes}\""
                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='NOTE', details=details)

            if old_answers != merged_answers:
                changed_labels = []
                for field in checklist_schema:
                    key = field['key']
                    old_value = _normalize_checklist_answer(old_answers.get(key, ''))
                    new_value = _normalize_checklist_answer(merged_answers.get(key, ''))
                    if old_value != new_value:
                        changed_labels.append(field['label'])
                if changed_labels:
                    summary = ', '.join(changed_labels[:8])
                    if len(changed_labels) > 8:
                        summary += '...'
                    details = f"Technician checklist updated: {summary}"
                else:
                    details = "Technician checklist updated."
                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='NOTE', details=details)

            # Return JSON response for AJAX requests (no page reload)
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'ok': True,
                    'message': 'Status and notes updated successfully.',
                    'status': job.status,
                    'status_display': job.get_status_display(),
                    'technician_notes': job.technician_notes,
                })
            
            messages.success(request, 'Status updated.')
            return redirect('job_detail_technician', job_code=job_code)

        elif action == 'add_service_log':
            # Check if job is in specialized service - prevent manual service charge entry
            if job.status == 'Specialized Service':
                error_message = 'Cannot add service logs while job is in Specialized Service. Service charges will be automatically added when returned from vendor.'
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({
                        'ok': False,
                        'message': error_message,
                    }, status=400)
                messages.error(request, error_message)
                return redirect('job_detail_technician', job_code=job_code)
            
            service_form = ServiceLogForm(request.POST)
            if service_form.is_valid():
                new_service = service_form.save(commit=False)
                new_service.job_ticket = job
                new_service.save()
                details = f"Added service: '{new_service.description}' (Part: {new_service.part_cost}, Service: {new_service.service_charge})"
                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='SERVICE', details=details)
                
                # Send WebSocket update
                send_job_update_message(job.job_code, job.status)
                
                # Return JSON response for AJAX requests (no page reload)
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    # Re-fetch service logs to include the new one
                    service_logs = job.service_logs.all()
                    html = render_to_string('job_tickets/_service_logs_table.html', {
                        'job': job,
                        'service_logs': service_logs,
                    }, request=request)
                    return JsonResponse({
                        'ok': True,
                        'message': 'Service log added successfully.',
                        'html': html,
                    })
                
                messages.success(request, 'Service log added.')
                return redirect('job_detail_technician', job_code=job_code)
            else:
                # Return JSON with errors for AJAX requests
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    errors = {field: [str(e) for e in service_form.errors[field]] for field in service_form.errors}
                    return JsonResponse({
                        'ok': False,
                        'message': 'Please correct the errors in the form.',
                        'errors': errors,
                    }, status=400)
                messages.error(request, 'Please correct the errors in the form.')

        elif action == 'update_service_logs':
            # Technician updated existing service log rows (description, part_cost, service_charge)
            # Prevent edits if job is finalized, billed, or in specialized service
            if job.status in ['Ready for Pickup', 'Completed', 'Closed', 'Specialized Service'] or job.vyapar_invoice_number:
                error_msg = 'Cannot edit logs after billing or completion.' if job.status in ['Ready for Pickup', 'Completed', 'Closed'] or job.vyapar_invoice_number else 'Cannot edit service logs while job is in Specialized Service.'
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'ok': False, 'error': 'editing_not_allowed', 'message': error_msg}, status=403)
                messages.error(request, error_msg)
                return redirect('job_detail_technician', job_code=job_code)
            updated_any = False
            for log in job.service_logs.all():
                try:
                    desc_key = f'description_{log.id}'
                    part_key = f'part_cost_{log.id}'
                    service_key = f'service_charge_{log.id}'

                    new_desc = request.POST.get(desc_key, '').strip()
                    new_part_raw = request.POST.get(part_key, '')
                    new_service_raw = request.POST.get(service_key, '')

                    # Parse decimals safely
                    try:
                        new_part = Decimal(new_part_raw) if new_part_raw not in (None, '') else None
                    except (InvalidOperation, ValueError, TypeError):
                        new_part = log.part_cost

                    try:
                        new_service = Decimal(new_service_raw) if new_service_raw not in (None, '') else log.service_charge
                    except (InvalidOperation, ValueError, TypeError):
                        new_service = log.service_charge

                    changed = False
                    details_parts = []
                    if new_desc and new_desc != log.description:
                        details_parts.append(f"description: '{log.description}' -> '{new_desc}'")
                        log.description = new_desc
                        changed = True

                    # Compare decimals as Decimal for accuracy
                    if new_part is not None and (log.part_cost != new_part):
                        details_parts.append(f"part_cost: ₹{log.part_cost or 0} -> ₹{new_part}")
                        log.part_cost = new_part
                        changed = True

                    if new_service is not None and (log.service_charge != new_service):
                        details_parts.append(f"service_charge: ₹{log.service_charge or 0} -> ₹{new_service}")
                        log.service_charge = new_service
                        changed = True

                    if changed:
                        log.save()
                        updated_any = True
                        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='SERVICE', details='; '.join(details_parts))

                except Exception as e:
                    # Log error but continue processing other rows
                    # (Don't expose internals to user)
                    continue

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                # Render updated table HTML and return as snapshot
                html = render_to_string('job_tickets/_service_logs_table.html', {
                    'job': job,
                    'service_logs': job.service_logs.all(),
                }, request=request)
                return JsonResponse({'ok': True, 'updated': updated_any, 'message': updated_any and 'Service logs updated.' or 'No changes detected.', 'html': html})

            if updated_any:
                messages.success(request, 'Service logs updated.')
            else:
                messages.info(request, 'No changes detected in service logs.')
            return redirect('job_detail_technician', job_code=job_code)


    # GET (or invalid POST) -> render page
    service_form = ServiceLogForm()
    service_logs = job.service_logs.all()
    calculate_job_totals([job])
    subtotal = job.total
    discount = job.discount_amount or Decimal('0.00')
    grand_total = subtotal - discount

    context = {
        'job': job,
        'service_logs': service_logs,
        'service_form': service_form,
        'total_parts_cost': job.part_total,
        'total_service_charges': job.service_total,
        'subtotal': subtotal,
        'discount': discount,
        'grand_total': grand_total,
        # Pass the filtered choices to the template
        'status_choices': technician_status_choices,
        'can_change_status': can_change_status,
        'checklist_schema': checklist_schema,
        'checklist_title': checklist_title,
        'checklist_notes': checklist_notes,
    }
    return render(request, 'job_tickets/job_detail_technician.html', context)

def client_login(request):
    if request.method == 'POST':
        job_code = (request.POST.get('job_code') or '').strip()
        customer_phone, customer_phone_error = normalize_indian_phone(
            request.POST.get('phone_number'),
            field_label='Phone Number',
        )

        if not job_code:
            return render(request, 'job_tickets/client_login.html', {
                'error': 'Job Ticket Number is required.',
            })
        if customer_phone_error:
            return render(request, 'job_tickets/client_login.html', {
                'error': customer_phone_error,
            })
        
        # Rate limiting for client login
        client_ip = request.META.get('REMOTE_ADDR')
        cache_key = f'client_login_attempts_{client_ip}'
        attempts = cache.get(cache_key, 0)
        
        if attempts >= 10:
            return render(request, 'job_tickets/client_login.html', {
                'error': 'Too many failed attempts. Please try again in 30 minutes.',
                'locked': True
            })
        
        try:
            job_ticket = JobTicket.objects.get(
                job_code=job_code,
                customer_phone__in=phone_lookup_variants(customer_phone),
            )
            cache.delete(cache_key)  # Clear attempts on success
            return redirect('client_status', job_code=job_code)
        except JobTicket.DoesNotExist:
            cache.set(cache_key, attempts + 1, 1800)  # 30 minutes
            return render(request, 'job_tickets/client_login.html', {
                'error': 'Invalid Job Ticket Number or Phone Number.',
                'attempts_left': 9 - attempts
            })
    return render(request, 'job_tickets/client_login.html')

def client_status(request, job_code):
    job_ticket = get_object_or_404(JobTicket, job_code=job_code)
    job_tickets = [job_ticket]
    calculate_job_totals(job_tickets)
    checklist_schema, checklist_title, checklist_notes = _build_checklist_schema_for_job(job_ticket)
    
    bill_available = job_ticket.status in ['Ready for Pickup', 'Closed']
    can_give_feedback = job_ticket.status == 'Closed' and not job_ticket.feedback_rating
    
    if request.method == 'POST' and can_give_feedback:
        feedback_form = FeedbackForm(request.POST)
        if feedback_form.is_valid():
            job_ticket.feedback_rating = int(feedback_form.cleaned_data['rating'])
            job_ticket.feedback_comment = feedback_form.cleaned_data['comment']
            job_ticket.feedback_date = timezone.now()
            job_ticket.save()
            
            JobTicketLog.objects.create(
                job_ticket=job_ticket,
                user=None,
                action='FEEDBACK',
                details=f"Customer feedback: {job_ticket.feedback_rating}/10"
            )
            
            messages.success(request, 'Thank you for your feedback!')
            return redirect('client_status', job_code=job_code)
    else:
        feedback_form = FeedbackForm()
    
    context = {
        'job_ticket': job_ticket,
        'service_logs': job_ticket.service_logs.all(),
        'total_parts_cost': job_ticket.part_total,
        'total_service_charges': job_ticket.service_total,
        'grand_total': job_ticket.total - job_ticket.discount_amount,
        'bill_available': bill_available,
        'can_give_feedback': can_give_feedback,
        'feedback_form': feedback_form,
        'checklist_schema': checklist_schema,
        'checklist_title': checklist_title,
        'checklist_notes': checklist_notes,
    }
    return render(request, 'job_tickets/client_status.html', context)


@login_required
def client_phone_lookup(request):
    if not request.user.is_staff or not user_has_staff_access(request.user, "staff_dashboard"):
        return JsonResponse({'ok': False, 'message': 'Unauthorized'}, status=403)

    phone = request.GET.get('phone')
    snapshot = get_phone_service_snapshot(phone)
    return JsonResponse({'ok': True, **snapshot})

def client_bill_view(request, job_code):
    job_ticket = get_object_or_404(JobTicket, job_code=job_code)
    
    # Only allow bill access if job is ready for pickup or closed
    if job_ticket.status not in ['Ready for Pickup', 'Closed']:
        return render(request, 'job_tickets/client_login.html', {
            'error': 'Bill is not yet available. Please check back when your device is ready for pickup.'
        })
    
    job_tickets = [job_ticket]
    calculate_job_totals(job_tickets)
    
    subtotal = job_ticket.total
    discount = job_ticket.discount_amount
    grand_total = subtotal - discount
    
    # Clean service logs to remove vendor names
    service_logs = job_ticket.service_logs.all()
    cleaned_service_logs = []
    for log in service_logs:
        # Replace specialized service descriptions with generic terms
        if 'Specialized Service' in log.description:
            description = 'Specialized Service'
        else:
            description = log.description
            
        cleaned_log = {
            'description': description,
            'part_cost': log.part_cost,
            'service_charge': log.service_charge,
        }
        cleaned_service_logs.append(cleaned_log)
    
    context = {
        'job': job_ticket,
        'service_logs': cleaned_service_logs,
        'subtotal': subtotal,
        'discount': discount,
        'grand_total': grand_total,
        'technician_id': job_ticket.assigned_to.unique_id if job_ticket.assigned_to else 'N/A',
        'created_by_id': job_ticket.created_by.id if job_ticket.created_by else 'N/A',
    }
    return render(request, 'job_tickets/job_billing_print.html', context)
    
@login_required
def job_billing_staff(request, job_code):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    
    job = get_object_or_404(JobTicket, job_code=job_code)
    
    if request.method == 'POST':
        # --- Handle Billing/Invoice Submission (Includes Job and Log Updates) ---
        if 'update_amounts_submit' in request.POST:
            try:
                with transaction.atomic():
                    raw_delete_service_ids = request.POST.getlist('delete_service_ids[]')
                    delete_service_ids = []
                    seen_delete_ids = set()
                    for raw_service_id in raw_delete_service_ids:
                        try:
                            service_id_int = int(raw_service_id)
                        except (TypeError, ValueError):
                            continue
                        if service_id_int in seen_delete_ids:
                            continue
                        seen_delete_ids.add(service_id_int)
                        delete_service_ids.append(service_id_int)
                    delete_service_ids_set = set(delete_service_ids)

                    # 1. HANDLE JOB-LEVEL INVOICE NUMBER (shared across service + inventory sales)
                    submitted_invoice = (request.POST.get('job_sales_invoice_number') or '').strip()
                    old_vyapar_invoice = job.vyapar_invoice_number or ""
                    sale_entry_date = timezone.localdate()

                    if submitted_invoice:
                        validate_sales_invoice_number_uniqueness(
                            submitted_invoice,
                            exclude_job_id=job.id,
                            allow_inventory_job_id=job.id,
                        )
                        new_vyapar_invoice = submitted_invoice
                    elif old_vyapar_invoice:
                        new_vyapar_invoice = old_vyapar_invoice
                    else:
                        # Auto-generate from the shared sales invoice sequence.
                        for _ in range(20):
                            candidate_invoice = _generate_inventory_invoice_number('sale', sale_entry_date)
                            try:
                                validate_sales_invoice_number_uniqueness(
                                    candidate_invoice,
                                    exclude_job_id=job.id,
                                    allow_inventory_job_id=job.id,
                                )
                                new_vyapar_invoice = candidate_invoice
                                break
                            except ValueError:
                                continue
                        else:
                            raise ValueError("Unable to generate a unique invoice number. Please try again.")

                    if old_vyapar_invoice != new_vyapar_invoice:
                        details = f"Sales Invoice No. updated from '{old_vyapar_invoice}' to '{new_vyapar_invoice}'."
                        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='BILLING', details=details)
                        job.vyapar_invoice_number = new_vyapar_invoice or None

                    # Keep existing linked inventory sales entries and bill header on the same shared invoice.
                    updated_invoice_rows = (
                        InventoryEntry.objects.filter(entry_type='sale', job_ticket=job)
                        .exclude(invoice_number=new_vyapar_invoice)
                        .update(invoice_number=new_vyapar_invoice)
                    )
                    InventoryBill.objects.filter(entry_type='sale', job_ticket=job).exclude(
                        invoice_number=new_vyapar_invoice
                    ).update(invoice_number=new_vyapar_invoice)
                    if updated_invoice_rows:
                        JobTicketLog.objects.create(
                            job_ticket=job,
                            user=request.user,
                            action='BILLING',
                            details=(
                                f"Updated {updated_invoice_rows} linked inventory sale line(s) "
                                f"to invoice '{new_vyapar_invoice}'."
                            ),
                        )
                    
                    # 2. UPDATE EXISTING SERVICE LOGS (skip lines queued for deletion)
                    product_sales_by_log_id = {
                        sale.service_log_id: sale
                        for sale in ProductSale.objects.select_related('product', 'inventory_entry').filter(
                            job_ticket=job,
                            service_log__isnull=False,
                        )
                    }
                    for log in job.service_logs.all():
                        log_id = log.id
                        if log_id in delete_service_ids_set:
                            continue

                        is_updated = False
                        product_sale_entry = product_sales_by_log_id.get(log_id)
                        try:
                            new_part_cost = Decimal(request.POST.get(f'part_cost_{log_id}', 0) or 0)
                            new_service_charge = Decimal(request.POST.get(f'service_charge_{log_id}', 0) or 0)
                        except InvalidOperation:
                            raise ValueError(f"Invalid amount entered for '{log.description}'.")

                        old_part_cost = log.part_cost or Decimal('0')
                        old_service_charge = log.service_charge or Decimal('0')

                        if product_sale_entry:
                            if new_part_cost < 0:
                                raise ValueError(
                                    f"Product amount cannot be negative for '{product_sale_entry.product.name}'."
                                )

                            if old_part_cost != new_part_cost:
                                quantity = product_sale_entry.quantity or 0
                                if quantity <= 0:
                                    raise ValueError(
                                        f"Product sale quantity is invalid for '{product_sale_entry.product.name}'."
                                    )

                                quantized_part_cost = new_part_cost.quantize(Decimal('0.01'))
                                new_unit_price = (
                                    quantized_part_cost / Decimal(quantity)
                                ).quantize(Decimal('0.01'))
                                line_cost = (
                                    (product_sale_entry.cost_price or Decimal('0.00')) * Decimal(quantity)
                                ).quantize(Decimal('0.01'))
                                line_profit = (quantized_part_cost - line_cost).quantize(Decimal('0.01'))

                                log.part_cost = quantized_part_cost
                                product_sale_entry.unit_price = new_unit_price
                                product_sale_entry.line_total = quantized_part_cost
                                product_sale_entry.line_profit = line_profit

                                if product_sale_entry.inventory_entry_id:
                                    inv_entry = product_sale_entry.inventory_entry
                                    inv_entry.unit_price = new_unit_price
                                    inv_entry.taxable_amount = quantized_part_cost
                                    inv_gst_rate = inv_entry.gst_rate or Decimal('0.00')
                                    inv_gst_amount = (quantized_part_cost * inv_gst_rate / Decimal('100')).quantize(Decimal('0.01'))
                                    inv_entry.gst_amount = inv_gst_amount
                                    inv_entry.total_amount = (quantized_part_cost + inv_gst_amount).quantize(Decimal('0.01'))
                                    inv_entry.save(update_fields=['unit_price', 'taxable_amount', 'gst_amount', 'total_amount'])
                                is_updated = True

                                details = (
                                    f"Updated product sale '{product_sale_entry.product.name}' amount "
                                    f"from Rs {old_part_cost} to Rs {quantized_part_cost}."
                                )
                                JobTicketLog.objects.create(
                                    job_ticket=job,
                                    user=request.user,
                                    action='BILLING',
                                    details=details,
                                )
                            if old_service_charge != new_service_charge:
                                log.service_charge = new_service_charge
                                is_updated = True
                                JobTicketLog.objects.create(
                                    job_ticket=job,
                                    user=request.user,
                                    action='BILLING',
                                    details=(
                                        f"Updated product sale '{product_sale_entry.product.name}' service charge "
                                        f"from Rs {old_service_charge} to Rs {new_service_charge}."
                                    ),
                                )
                        else:
                            if old_part_cost != new_part_cost:
                                log.part_cost = new_part_cost
                                is_updated = True
                                details = f"Updated '{log.description}' part cost from Rs {old_part_cost} to Rs {new_part_cost}."
                                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='BILLING', details=details)

                            if old_service_charge != new_service_charge:
                                log.service_charge = new_service_charge
                                is_updated = True
                                details = f"Updated '{log.description}' service charge from Rs {old_service_charge} to Rs {new_service_charge}."
                                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='BILLING', details=details)
                        
                        log_invoice_field = f'sales_invoice_number_{log_id}'
                        if log_invoice_field in request.POST:
                            old_log_invoice = log.sales_invoice_number or ""
                            new_log_invoice = request.POST.get(log_invoice_field, '').strip()
                            if old_log_invoice != new_log_invoice:
                                log.sales_invoice_number = new_log_invoice
                                is_updated = True
                                details = f"Log Invoice updated for '{log.description}' from '{old_log_invoice}' to '{new_log_invoice}'."
                                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='BILLING', details=details)
                            
                        if is_updated:
                            if product_sale_entry:
                                product_sale_entry.save(update_fields=['unit_price', 'line_total', 'line_profit'])
                            log.save()
                    
                    # 3. HANDLE NEW MANUAL SERVICE LINES
                    new_descriptions = request.POST.getlist('new_description[]')
                    new_part_costs = request.POST.getlist('new_part_cost[]')
                    new_service_charges = request.POST.getlist('new_service_charge[]')

                    for i in range(len(new_descriptions)):
                        description = (new_descriptions[i] or '').strip()
                        if not description:
                            continue
                        try:
                            part_cost = Decimal((new_part_costs[i] if i < len(new_part_costs) else 0) or 0)
                            service_charge = Decimal((new_service_charges[i] if i < len(new_service_charges) else 0) or 0)
                        except InvalidOperation:
                            raise ValueError(f"Invalid amount for new service line '{description}'.")

                        ServiceLog.objects.create(
                            job_ticket=job,
                            description=description,
                            part_cost=part_cost,
                            service_charge=service_charge
                        )
                        details = f"Added new service: '{description}' (Part: Rs {part_cost}, Service: Rs {service_charge})."
                        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='SERVICE', details=details)

                    # 4. HANDLE DELETIONS (restock product if product-line deleted)
                    for service_id in delete_service_ids:
                        try:
                            service_log = ServiceLog.objects.select_for_update().get(id=service_id, job_ticket=job)
                        except ServiceLog.DoesNotExist:
                            continue

                        product_sale_entry = ProductSale.objects.filter(service_log=service_log).select_related('product').first()
                        parsed_product_sale = parse_product_sale_log(service_log.description) if not product_sale_entry else None

                        if product_sale_entry:
                            product = Product.objects.select_for_update().filter(id=product_sale_entry.product_id).first()
                            if product:
                                product.stock_quantity += product_sale_entry.quantity
                                product.save(update_fields=['stock_quantity', 'updated_at'])
                                JobTicketLog.objects.create(
                                    job_ticket=job,
                                    user=request.user,
                                    action='SERVICE',
                                    details=f"Restocked {product.name} by {product_sale_entry.quantity} after deleting product sale line.",
                                )
                            if product_sale_entry.inventory_entry_id:
                                product_sale_entry.inventory_entry.delete()
                        elif parsed_product_sale:
                            product = Product.objects.select_for_update().filter(id=parsed_product_sale['product_id']).first()
                            if product:
                                product.stock_quantity += parsed_product_sale['quantity']
                                product.save(update_fields=['stock_quantity', 'updated_at'])
                                JobTicketLog.objects.create(
                                    job_ticket=job,
                                    user=request.user,
                                    action='SERVICE',
                                    details=f"Restocked {product.name} by {parsed_product_sale['quantity']} after deleting legacy product sale line.",
                                )

                        details = f"Deleted service: '{service_log.description}' (Part: Rs {service_log.part_cost}, Service: Rs {service_log.service_charge})"
                        service_log.delete()
                        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='SERVICE', details=details)

                    # 5. HANDLE PRODUCT SALES (service + product in one bill)
                    # Keep this after deletions so stock released by deleted lines is immediately reusable.
                    product_ids = request.POST.getlist('product_id[]')
                    product_quantities = request.POST.getlist('product_qty[]')
                    product_service_charges = request.POST.getlist('product_service_charge[]')
                    customer_party = _get_or_create_inventory_customer_party_for_job(job)
                    inventory_sale_bill = (
                        InventoryBill.objects.select_for_update()
                        .filter(entry_type='sale', job_ticket=job)
                        .first()
                    )
                    if inventory_sale_bill:
                        inventory_bill_updates = []
                        if inventory_sale_bill.entry_date != sale_entry_date:
                            inventory_sale_bill.entry_date = sale_entry_date
                            inventory_bill_updates.append('entry_date')
                        if (inventory_sale_bill.invoice_number or '') != new_vyapar_invoice:
                            inventory_sale_bill.invoice_number = new_vyapar_invoice
                            inventory_bill_updates.append('invoice_number')
                        if inventory_sale_bill.party_id != customer_party.id:
                            inventory_sale_bill.party = customer_party
                            inventory_bill_updates.append('party')
                        expected_bill_note = f"Auto product sale entries from job {job.job_code}."
                        if inventory_sale_bill.notes != expected_bill_note:
                            inventory_sale_bill.notes = expected_bill_note
                            inventory_bill_updates.append('notes')
                        if inventory_sale_bill.created_by_id is None:
                            inventory_sale_bill.created_by = request.user
                            inventory_bill_updates.append('created_by')
                        if inventory_bill_updates:
                            inventory_sale_bill.save(update_fields=inventory_bill_updates + ['updated_at'])
                    else:
                        inventory_sale_bill = InventoryBill.objects.create(
                            bill_number=_generate_inventory_bill_number('sale', sale_entry_date),
                            entry_type='sale',
                            entry_date=sale_entry_date,
                            invoice_number=new_vyapar_invoice,
                            job_ticket=job,
                            party=customer_party,
                            notes=f"Auto product sale entries from job {job.job_code}.",
                            created_by=request.user,
                        )

                    for index, raw_product_id in enumerate(product_ids):
                        product_id = (raw_product_id or '').strip()
                        raw_qty = (product_quantities[index] if index < len(product_quantities) else '').strip()
                        raw_service_charge = (
                            product_service_charges[index] if index < len(product_service_charges) else ''
                        ).strip()

                        if not product_id:
                            continue

                        try:
                            quantity = int(raw_qty)
                        except (TypeError, ValueError):
                            raise ValueError("Product quantity must be a valid whole number.")

                        try:
                            product_service_charge = Decimal(raw_service_charge or 0)
                        except InvalidOperation:
                            raise ValueError("Product service charge must be a valid amount.")

                        if quantity <= 0:
                            raise ValueError("Product quantity must be greater than zero.")
                        if product_service_charge < 0:
                            raise ValueError("Product service charge cannot be negative.")

                        product = Product.objects.select_for_update().filter(pk=product_id).first()
                        if not product:
                            raise ValueError("Selected product no longer exists.")
                        if product.stock_quantity < quantity:
                            raise ValueError(f"Insufficient stock for '{product.name}'. Available: {product.stock_quantity}.")
                        stock_before = product.stock_quantity
                        stock_after = stock_before - quantity

                        line_total = (product.unit_price or Decimal('0')) * Decimal(quantity)
                        line_description = f"Product Sale - {product.name} (Qty: {quantity})"

                        created_sale_log = ServiceLog.objects.create(
                            job_ticket=job,
                            description=line_description,
                            part_cost=line_total,
                            service_charge=product_service_charge.quantize(Decimal('0.01')),
                        )

                        line_cost = (product.cost_price or Decimal('0')) * Decimal(quantity)
                        line_profit = line_total - line_cost
                        inventory_sale_entry = InventoryEntry.objects.create(
                            bill=inventory_sale_bill,
                            entry_number=_generate_inventory_entry_number('sale', sale_entry_date),
                            entry_type='sale',
                            entry_date=sale_entry_date,
                            invoice_number=new_vyapar_invoice,
                            job_ticket=job,
                            party=customer_party,
                            product=product,
                            quantity=quantity,
                            unit_price=product.unit_price or Decimal('0.00'),
                            discount_amount=Decimal('0.00'),
                            gst_rate=Decimal('0.00'),
                            taxable_amount=line_total.quantize(Decimal('0.01')),
                            gst_amount=Decimal('0.00'),
                            total_amount=line_total.quantize(Decimal('0.01')),
                            stock_before=stock_before,
                            stock_after=stock_after,
                            notes=f"Auto product sale entry from job {job.job_code}.",
                            created_by=request.user,
                        )

                        ProductSale.objects.create(
                            job_ticket=job,
                            product=product,
                            service_log=created_sale_log,
                            inventory_entry=inventory_sale_entry,
                            quantity=quantity,
                            unit_price=product.unit_price or Decimal('0.00'),
                            cost_price=product.cost_price or Decimal('0.00'),
                            line_total=line_total,
                            line_cost=line_cost,
                            line_profit=line_profit,
                            sold_by=request.user,
                        )

                        product.stock_quantity = stock_after
                        product.save(update_fields=['stock_quantity', 'updated_at'])

                        JobTicketLog.objects.create(
                            job_ticket=job,
                            user=request.user,
                            action='SERVICE',
                            details=(
                                f"Added product sale: {product.name} x{quantity} at Rs {product.unit_price} each "
                                f"(Revenue: Rs {line_total}, Service Charge: Rs {product_service_charge}, "
                                f"Cost: Rs {line_cost}, Profit: Rs {line_profit}, "
                                f"Sale Invoice: {new_vyapar_invoice})."
                            ),
                        )

                    InventoryBill.objects.filter(
                        entry_type='sale',
                        job_ticket=job,
                        lines__isnull=True,
                    ).delete()

                    # 6. HANDLE DISCOUNT + FINAL SAVE
                    old_discount = job.discount_amount
                    try:
                        new_discount = Decimal(request.POST.get('discount_amount', 0) or 0)
                    except InvalidOperation:
                        raise ValueError("Invalid discount amount.")

                    if old_discount != new_discount:
                        job.discount_amount = new_discount
                        details = f"Discount updated from Rs {old_discount} to Rs {new_discount}."
                        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='BILLING', details=details)

                    job.save(update_fields=['vyapar_invoice_number', 'discount_amount', 'updated_at'])
                
                messages.success(request, f"Billing and Invoice details for Job {job_code} updated successfully.")
            except ValueError as exc:
                messages.error(request, str(exc))
            except InvalidOperation:
                messages.error(request, "Invalid amount format found in billing form.")
            except Exception:
                messages.error(request, "Unable to update billing details right now. Please try again.")

            return redirect('job_billing_staff', job_code=job_code)
        
        # --- Handle Rework Form Submission ---
        if 'rework_form_submit' in request.POST:
            rework_form = ReworkForm(request.POST)
            if rework_form.is_valid():
                rework_reason = rework_form.cleaned_data['rework_reason']
                new_job_code = get_next_job_code()
                
                new_job = JobTicket.objects.create(
                    job_code=new_job_code,
                    customer_name=job.customer_name,
                    customer_phone=job.customer_phone,
                    device_type=job.device_type,
                    device_brand=job.device_brand,
                    device_model=job.device_model,
                    device_serial=job.device_serial,
                    reported_issue=f"Rework from original ticket {job.job_code}: {rework_reason}",
                    original_job_ticket=job,
                    status='Pending',
                    created_by=request.user
                )
                
                return redirect('job_creation_success', job_code=new_job.job_code)

    # --- GET / RENDERING PATH ---
    job_tickets = [job]
    calculate_job_totals(job_tickets)
    
    subtotal = job.total
    discount = job.discount_amount
    grand_total = subtotal - discount
    
    rework_form = ReworkForm()
    discount_form = DiscountForm(initial={'discount_amount': job.discount_amount})
    technician_id = job.assigned_to.unique_id if job.assigned_to else 'N/A'
    sold_product_ids = ProductSale.objects.filter(job_ticket=job).values_list('product_id', flat=True)
    product_sale_log_ids = list(
        ProductSale.objects.filter(job_ticket=job, service_log__isnull=False).values_list('service_log_id', flat=True)
    )
    
    context = {
        'job': job,
        'service_logs': job.service_logs.all(),
        'total_parts_cost': job.part_total,
        'total_service_charges': job.service_total,
        'subtotal': subtotal,
        'discount': discount,
        'grand_total': grand_total,
        'rework_form': rework_form,
        'discount_form': discount_form,
        'technician_id': technician_id,
        'product_sale_log_ids': product_sale_log_ids,
        'products_for_sale': Product.objects.filter(
            Q(stock_quantity__gt=0) | Q(id__in=sold_product_ids)
        ).distinct().order_by('name'),
    }
    return render(request, 'job_tickets/job_billing_staff.html', context)

@login_required
def reports_dashboard(request):
    denied = _staff_access_required(request, "reports_dashboard")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')
    
    # 1. UNIFIED PERIOD DETERMINATION (The ONLY call needed)
    period = get_report_period(request)
    start_of_period = period['start']
    end_of_period = period['end']
    status_filter = request.GET.get('status_filter')
    all_jobs = JobTicket.objects.all()
    all_jobs_count = all_jobs.count()
    pending_count = all_jobs.filter(status='Pending').count()

    in_progress_count = all_jobs.filter(
        Q(status='Under Inspection') | Q(status='Repairing') | Q(status='Specialized Service')
    ).count()

    completed_awaiting_billing_count = all_jobs.filter(
        Q(status='Completed') | Q(status='Ready for Pickup')
    ).count()

    # Get accurate count of all jobs that have been returned (including those now closed)
    returned_job_ids = JobTicketLog.objects.filter(
        action='STATUS',
        details__icontains="'Returned'"
    ).values_list('job_ticket_id', flat=True).distinct()
    returned_count = JobTicket.objects.filter(id__in=returned_job_ids).count()
    closed_count = all_jobs.filter(status='Closed').count()
    
    # Static data for HTML limits
    company_start_date = get_company_start_date()
    today_date_str = timezone.localdate().strftime('%Y-%m-%d')


    # --- 2. QUERIES setup ---
    finished_statuses = ['Completed', 'Closed']
    
    # Base filter for time window
    q_filter = Q(updated_at__gte=start_of_period, updated_at__lt=end_of_period)

    # Apply Status Filter if selected by the user
    if status_filter == 'ALL_FINISHED':
        q_filter &= Q(status__in=finished_statuses)
    elif status_filter == 'ACTIVE_WORKLOAD':
        q_filter &= Q(status__in=['Under Inspection', 'Repairing', 'Specialized Service'])
    elif status_filter and status_filter != 'ALL':
        # Filter for a specific status (e.g., 'Completed', 'Returned')
        q_filter &= Q(status=status_filter)

    # 2a. Monthly/Period Finished Jobs (Using vendor concept)
    monthly_finished_jobs_list = get_jobs_for_report_period(start_of_period, end_of_period, status_filter)
    monthly_finished_jobs = JobTicket.objects.filter(
        id__in=[job.id for job in monthly_finished_jobs_list]
    )
    
    # 2b. Jobs Created (IN) - Filtered ONLY by date, NOT status
    jobs_in_period = JobTicket.objects.filter(
        created_at__gte=start_of_period,
        created_at__lt=end_of_period
    ).count()

    jobs_out_period = monthly_finished_jobs.count() # Count reflects the status filter

    # Query logs related to jobs finished in the selected period
    logs_in_period = ServiceLog.objects.filter(job_ticket__in=monthly_finished_jobs)
    
    # 2c. Income Calculations
    monthly_income_parts = logs_in_period.aggregate(
        total=Coalesce(Sum('part_cost', output_field=DecimalField()), Decimal('0.00'))
    )['total']
    
    monthly_income_service = logs_in_period.aggregate(
        total=Coalesce(Sum('service_charge', output_field=DecimalField()), Decimal('0.00'))
    )['total']
    
    monthly_total_income = monthly_income_parts + monthly_income_service

    # 2d. Expense Calculations
    vendor_services_in_period = SpecializedService.objects.filter(job_ticket__in=monthly_finished_jobs)
    monthly_vendor_expense = vendor_services_in_period.aggregate(
        total=Coalesce(Sum('vendor_cost', output_field=DecimalField()), Decimal('0.00'))
    )['total']
    
    monthly_net_profit = monthly_total_income - monthly_vendor_expense

    # --- 2e. Per-section custom date ranges (Technician / Vendor) ---
    # Accept GET params: tech_start_date, tech_end_date, vendor_start_date, vendor_end_date
    def parse_section_dates(start_str, end_str):
        if start_str and end_str:
            try:
                sd = datetime.strptime(start_str, '%Y-%m-%d').date()
                ed = datetime.strptime(end_str, '%Y-%m-%d').date()
                sd_aware = timezone.make_aware(datetime(sd.year, sd.month, sd.day))
                # inclusive end -> set to 23:59:59
                ed_aware = timezone.make_aware(datetime(ed.year, ed.month, ed.day, 23, 59, 59))
                return sd_aware, ed_aware, start_str, end_str
            except Exception:
                # fallback to global period
                return start_of_period, end_of_period, period['start_date_str'], period['end_date_str']
        return start_of_period, end_of_period, period['start_date_str'], period['end_date_str']

    tech_start_str = request.GET.get('tech_start_date') or request.GET.get('perf_start_date')
    tech_end_str = request.GET.get('tech_end_date') or request.GET.get('perf_end_date')
    tech_start, tech_end, tech_start_date_str, tech_end_date_str = parse_section_dates(tech_start_str, tech_end_str)

    vendor_start_str = request.GET.get('vendor_start_date')
    vendor_end_str = request.GET.get('vendor_end_date')
    vendor_start, vendor_end, vendor_start_date_str, vendor_end_date_str = parse_section_dates(vendor_start_str, vendor_end_str)


    # --- 3. ALL-TIME STATS (Remain unfiltered by date/status) ---

    all_jobs = JobTicket.objects.all()
    completed_jobs_all_time = all_jobs.filter(status='Completed')
    pending_jobs_all_time = all_jobs.filter(status='Pending')
    in_progress_jobs_all_time = all_jobs.filter(Q(status='Under Inspection') | Q(status='Repairing'))
    ready_for_pickup_jobs_all_time = all_jobs.filter(status='Ready for Pickup')
    returned_jobs_all_time = all_jobs.filter(status='Returned')
    closed_jobs = all_jobs.filter(status='Closed').order_by('-updated_at')

    # Technician-level performance (Filtered by per-section period)
    # Build the set of finished jobs for the technician filter period using vendor concept
    tech_finished_jobs_list = get_jobs_for_report_period(tech_start, tech_end)
    tech_finished_jobs = JobTicket.objects.filter(
        id__in=[job.id for job in tech_finished_jobs_list]
    )

    tech_job_count_subquery = JobTicket.objects.filter(
        assigned_to=OuterRef('pk'),
        id__in=tech_finished_jobs.values('id')
    ).values('assigned_to').annotate(
        count=Count('id', distinct=True)
    ).values('count')

    monthly_tech_performance = TechnicianProfile.objects.filter(
        user__groups__name='Technicians'
    ).annotate(
        jobs_done=Coalesce(
            Subquery(tech_job_count_subquery),
            0,
            output_field=IntegerField()
        ),
        monthly_parts_sales=Coalesce(
            Sum('jobticket__service_logs__part_cost',
                filter=Q(jobticket__in=tech_finished_jobs.values('id')) & ~Q(jobticket__service_logs__description__icontains='Specialized Service'),
                output_field=DecimalField()
            ), Decimal('0.00'), output_field=DecimalField()
        ),
        monthly_service_sales=Coalesce(
            Sum('jobticket__service_logs__service_charge',
                filter=Q(jobticket__in=tech_finished_jobs.values('id')) & ~Q(jobticket__service_logs__description__icontains='Specialized Service'),
                output_field=DecimalField()
            ), Decimal('0.00'), output_field=DecimalField()
        )
    ).order_by('-jobs_done')

    # VENDOR PERFORMANCE QUERY (Using vendor concept)
    # Get vendor jobs that were returned in the specified period
    vendor_jobs_list = get_jobs_for_report_period(vendor_start, vendor_end)
    vendor_finished_jobs = JobTicket.objects.filter(
        id__in=[job.id for job in vendor_jobs_list],
        specialized_service__isnull=False
    )
    
    vendor_performance = Vendor.objects.annotate(
        total_jobs_given=Count('services', filter=Q(
            services__job_ticket__in=vendor_finished_jobs
        )),
        total_vendor_cost=Coalesce(Sum('services__vendor_cost', filter=Q(
            services__job_ticket__in=vendor_finished_jobs
        ), output_field=DecimalField()), Decimal('0.00')),
        total_client_charge=Coalesce(Sum('services__client_charge', filter=Q(
            services__job_ticket__in=vendor_finished_jobs
        ), output_field=DecimalField()), Decimal('0.00'))
    ).annotate(
        profit=F('total_client_charge') - F('total_vendor_cost')
    ).order_by('-total_jobs_given')

    # --- 3.5 TODAY'S STATS ---
    today = timezone.localdate()
    start_of_day = timezone.make_aware(datetime.combine(today, datetime.min.time()))
    end_of_day = timezone.make_aware(datetime.combine(today, datetime.max.time()))

    todays_jobs_in = JobTicket.objects.filter(created_at__range=(start_of_day, end_of_day)).count()
    
    todays_jobs_out_qs = JobTicket.objects.filter(
        status='Closed',
        updated_at__range=(start_of_day, end_of_day)
    )
    todays_jobs_out = todays_jobs_out_qs.count()

    todays_completed_jobs_qs = JobTicket.objects.filter(
        status='Completed',
        updated_at__range=(start_of_day, end_of_day)
    )
    todays_jobs_completed = todays_completed_jobs_qs.count()

    todays_finished_jobs_qs = JobTicket.objects.filter(
        status__in=['Completed', 'Closed'],
        updated_at__range=(start_of_day, end_of_day)
    )

    # Calculate income from jobs completed/closed *today*
    todays_logs = ServiceLog.objects.filter(job_ticket__in=todays_finished_jobs_qs)
    todays_total_spare = todays_logs.aggregate(total=Coalesce(Sum('part_cost', output_field=DecimalField()), Decimal('0.00')))['total']
    todays_total_service = todays_logs.aggregate(total=Coalesce(Sum('service_charge', output_field=DecimalField()), Decimal('0.00')))['total']


    # --- 4. CONTEXT BUILDING ---
    context = {
        # Today's Stats
        'todays_jobs_in': todays_jobs_in,
        'todays_jobs_out': todays_jobs_out,
        'todays_jobs_completed': todays_jobs_completed,
        'todays_total_spare': todays_total_spare,
        'todays_total_service': todays_total_service,

        'company_start_date': company_start_date.strftime('%Y-%m-%d'),
        'today_date_str': today_date_str,
        'current_report_start': period['start_date_str'],
        'current_report_end': period['end_date_str'],
        'tech_start_date': tech_start_date_str,
        'tech_end_date': tech_end_date_str,
        'vendor_start_date': vendor_start_date_str,
        'vendor_end_date': vendor_end_date_str,
        'status_filter': status_filter or 'ALL',
        'jobs_created_in_period': jobs_in_period,
        'jobs_finished_in_period': jobs_out_period,
        'current_report_date': start_of_period,
        'monthly_total_income': monthly_total_income,
        'monthly_income_parts': monthly_income_parts,
        'monthly_income_service': monthly_income_service,
        'monthly_vendor_expense': monthly_vendor_expense,
        'monthly_net_profit': monthly_net_profit,
        'monthly_completed_jobs_count': monthly_finished_jobs.count(),

        # All-Time Stats
        'all_jobs_count': all_jobs.count(),
        'completed_count': completed_jobs_all_time.count(),
        'pending_count': pending_jobs_all_time.count(),
        'in_progress_count': in_progress_jobs_all_time.count(),
        'ready_for_pickup_count': ready_for_pickup_jobs_all_time.count(),
        'returned_count': returned_jobs_all_time.count(),
        'closed_jobs': closed_jobs,
        
        # Performance
        'monthly_tech_performance': monthly_tech_performance,
        'vendor_performance': vendor_performance,
        'all_jobs_count': all_jobs_count,
        'pending_count': pending_count,
        'in_progress_count': in_progress_count,
        'completed_awaiting_billing_count': completed_awaiting_billing_count,
        'returned_count': returned_count,
        'closed_count': closed_count,

    }
    return render(request, 'job_tickets/reports_dashboard.html', context)


@login_required
def reports_chart_data(request):
    """Return JSON aggregates (monthly + yearly) for the Reports Dashboard charts.

    Accepts the same query params as `reports_dashboard` (start_date, end_date, status_filter, preset).
    Uses `get_report_period()` so it shares the same defaults and timezone handling.
    """
    access = get_staff_access(request.user)
    if not request.user.is_staff or not access.get("reports_overview"):
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    period = get_report_period(request)
    start_of_period = period['start']
    end_of_period = period['end']
    status_filter = request.GET.get('status_filter')

    finished_statuses = ['Completed', 'Closed']

    # Helper to apply status filter onto a base Q
    def apply_status_filter(q):
        if status_filter == 'ALL_FINISHED':
            q &= Q(status__in=finished_statuses)
        elif status_filter == 'ACTIVE_WORKLOAD':
            q &= Q(status__in=['Under Inspection', 'Repairing', 'Specialized Service'])
        elif status_filter and status_filter != 'ALL':
            q &= Q(status=status_filter)
        return q

    # Iterate month-by-month from start_of_period (inclusive) to end_of_period (exclusive)
    monthly = []
    current = start_of_period
    while current < end_of_period:
        # month start is current
        month_start = current
        # compute next month start
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1, day=1)

        # Get jobs for this month using vendor concept
        monthly_jobs_list = get_jobs_for_report_period(month_start, next_month, status_filter)
        jobs_qs = JobTicket.objects.filter(id__in=[job.id for job in monthly_jobs_list])
        jobs_count = len(monthly_jobs_list)

        logs_qs = ServiceLog.objects.filter(job_ticket__in=jobs_qs)
        parts_total = logs_qs.aggregate(total=Coalesce(Sum('part_cost', output_field=DecimalField()), Decimal('0.00')))['total']
        service_total = logs_qs.aggregate(total=Coalesce(Sum('service_charge', output_field=DecimalField()), Decimal('0.00')))['total']
        total_income = parts_total + service_total

        vendor_qs = SpecializedService.objects.filter(job_ticket__in=jobs_qs)
        vendor_expense = vendor_qs.aggregate(total=Coalesce(Sum('vendor_cost', output_field=DecimalField()), Decimal('0.00')))['total']

        monthly.append({
            'label': month_start.strftime('%Y-%m'),
            'jobs_finished': int(jobs_count),
            'parts_income': float(parts_total),
            'service_income': float(service_total),
            'total_income': float(total_income),
            'vendor_expense': float(vendor_expense),
            'net_profit': float(total_income - vendor_expense),
        })

        current = next_month

    # Yearly aggregates: compute year by year in the same range
    yearly = []
    start_year = start_of_period.year
    end_year = (end_of_period - timedelta(seconds=1)).year
    for yr in range(start_year, end_year + 1):
        y_start = timezone.make_aware(datetime(yr, 1, 1))
        y_end = timezone.make_aware(datetime(yr + 1, 1, 1))
        
        # Get jobs for this year using vendor concept
        yearly_jobs_list = get_jobs_for_report_period(y_start, y_end, status_filter)
        jobs_qs = JobTicket.objects.filter(id__in=[job.id for job in yearly_jobs_list])
        jobs_count = len(yearly_jobs_list)

        logs_qs = ServiceLog.objects.filter(job_ticket__in=jobs_qs)
        parts_total = logs_qs.aggregate(total=Coalesce(Sum('part_cost', output_field=DecimalField()), Decimal('0.00')))['total']
        service_total = logs_qs.aggregate(total=Coalesce(Sum('service_charge', output_field=DecimalField()), Decimal('0.00')))['total']
        total_income = parts_total + service_total

        vendor_qs = SpecializedService.objects.filter(job_ticket__in=jobs_qs)
        vendor_expense = vendor_qs.aggregate(total=Coalesce(Sum('vendor_cost', output_field=DecimalField()), Decimal('0.00')))['total']

        yearly.append({
            'year': yr,
            'jobs_finished': int(jobs_count),
            'total_income': float(total_income),
            'vendor_expense': float(vendor_expense),
            'net_profit': float(total_income - vendor_expense),
        })

    return JsonResponse({'monthly': monthly, 'yearly': yearly})

# job_tickets/views.py

# job_tickets/views.py

@login_required
def technician_report_print(request, tech_id):
    denied = _staff_access_required(request, "reports_technician")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')

    finished_statuses = ['Completed', 'Closed']
    technician = get_object_or_404(TechnicianProfile, id=tech_id)
    
    # 1. GET DATE FILTERS from URL (These are passed from the Reports Dashboard)
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    # Start with base filters: assigned technician and finished statuses
    jobs_filter = Q(assigned_to=technician, status__in=finished_statuses)
    
    # 2. APPLY DATE FILTERING
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            # Create Timezone-Aware Boundaries
            start_of_period = timezone.make_aware(datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0))
            end_of_period = timezone.make_aware(datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59))
            
            # Filter jobs by the date they were last updated (completion/closure date)
            jobs_filter &= Q(updated_at__gte=start_of_period, updated_at__lte=end_of_period)
            
        except ValueError:
            messages.error(request, "Invalid date format provided for report filtering.")
            # If dates are bad, the report defaults to All Time (jobs_filter remains simple)
            start_date_str = None
            end_date_str = None
    else:
        # If no dates provided, ensure variables are None to display 'All Time' header
        start_date_str = None
        end_date_str = None
    
    # 3. Fetch Jobs
    jobs = list(JobTicket.objects.filter(jobs_filter).prefetch_related('service_logs').order_by('-updated_at'))

    # 4. Calculate Totals excluding vendor service charges
    calculate_job_totals(jobs, exclude_vendor_charges=True)
    
    total_parts_all = sum(job.part_total for job in jobs)
    total_services_all = sum(job.service_total for job in jobs)
    total_income = total_parts_all + total_services_all

    context = {
        'company': CompanyProfile.get_profile(),
        'technician': technician,
        'jobs': jobs,
        'total_parts': total_parts_all,
        'total_services': total_services_all,
        'total_income': total_income,
        # Pass dates for display in the report header
        'report_start_date': start_date_str, 
        'report_end_date': end_date_str,
    }
    return render(request, 'job_tickets/technician_report_print.html', context)

def get_job_status_data(request):
    if not request.user.is_staff or not user_has_staff_access(request.user, "staff_dashboard"):
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    pending_jobs = list(JobTicket.objects.filter(status='Pending').values('job_code', 'customer_name', 'device_type'))
    in_progress_jobs = list(JobTicket.objects.filter(Q(status='Under Inspection') | Q(status='Repairing')).values('job_code', 'customer_name', 'device_type', 'status', 'assigned_to__user__username'))
    ready_for_pickup_jobs = list(JobTicket.objects.filter(status='Ready for Pickup').values('job_code', 'customer_name', 'device_type', 'status'))
    completed_jobs = list(JobTicket.objects.filter(status='Completed').values('job_code', 'customer_name', 'device_type', 'status'))

    data = {
        'pending_jobs': pending_jobs,
        'in_progress_jobs': in_progress_jobs,
        'ready_for_pickup_jobs': ready_for_pickup_jobs,
        'completed_jobs': completed_jobs,
    }
    return JsonResponse(data)

def _parse_autoprint_flag(request, default=True):
    raw_value = (request.GET.get('autoprint') or '').strip().lower()
    if not raw_value:
        return default
    return raw_value not in {'0', 'false', 'no', 'off'}

@login_required
def job_creation_receipt_print_view(request, job_code):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    job_ticket = get_object_or_404(JobTicket, job_code=job_code)

    if job_ticket.customer_group_id:
        grouped_jobs = list(
            JobTicket.objects.filter(customer_group_id=job_ticket.customer_group_id).order_by('created_at')
        )
    else:
        grouped_jobs = [job_ticket]

    estimated_amount = job_ticket.estimated_amount if job_ticket.estimated_amount is not None else 0
    estimated_delivery = job_ticket.estimated_delivery or (job_ticket.created_at + timedelta(days=3))
    autoprint = _parse_autoprint_flag(request, default=True)

    context = {
        'job_ticket': job_ticket,
        'grouped_jobs': grouped_jobs,
        'estimated_amount': estimated_amount,
        'estimated_delivery': estimated_delivery,
        'autoprint': autoprint,
    }
    return render(request, 'job_tickets/job_creation_receipt_print.html', context)

def job_creation_receipt_public_view(request, job_code):
    job_ticket = get_object_or_404(JobTicket, job_code=job_code)
    token = (request.GET.get('token') or '').strip()
    if not verify_receipt_access_token(job_ticket, token):
        return HttpResponseForbidden("Invalid or expired receipt link.")

    if job_ticket.customer_group_id:
        grouped_jobs = list(
            JobTicket.objects.filter(customer_group_id=job_ticket.customer_group_id).order_by('created_at')
        )
    else:
        grouped_jobs = [job_ticket]

    estimated_amount = job_ticket.estimated_amount if job_ticket.estimated_amount is not None else 0
    estimated_delivery = job_ticket.estimated_delivery or (job_ticket.created_at + timedelta(days=3))
    autoprint = _parse_autoprint_flag(request, default=False)

    context = {
        'job_ticket': job_ticket,
        'grouped_jobs': grouped_jobs,
        'estimated_amount': estimated_amount,
        'estimated_delivery': estimated_delivery,
        'autoprint': autoprint,
    }
    return render(request, 'job_tickets/job_creation_receipt_print.html', context)

@login_required
def mark_ready_for_pickup(request, job_code):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    
    job = get_object_or_404(JobTicket, job_code=job_code)
    old_status = job.get_status_display()
    job.status = 'Ready for Pickup'
    job.save()
    
    # Send WebSocket update
    send_job_update_message(job.job_code, job.status)
    details = f"Status changed from '{old_status}' to '{job.get_status_display()}'."
    JobTicketLog.objects.create(job_ticket=job, user=request.user, action='STATUS', details=details)
    
    return redirect('staff_dashboard')

@login_required
def print_pending_jobs_report(request):
    access = get_staff_access(request.user)
    if not request.user.is_staff or not access.get("reports_overview"):
        return redirect('unauthorized')
    
    pending_jobs = JobTicket.objects.filter(status='Pending').order_by('created_at')
    company = CompanyProfile.get_profile()
    
    context = {
        'pending_jobs': pending_jobs,
        'report_date': datetime.now(),
        'company': company,
    }
    return render(request, 'job_tickets/print_pending_jobs_report.html', context)

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


@login_required
def print_monthly_summary_report(request):
    denied = _staff_access_required(request, "reports_financial")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')

    period = resolve_monthly_summary_period(request)
    context = get_monthly_summary_context(
        period['start_of_period'],
        period['end_of_period'],
        period['start_date_str'],
        period['end_date_str'],
        preset=period['preset'],
        show_jobs=period['show_jobs'],
    )
    return render(request, 'job_tickets/print_monthly_summary_report.html', context)


@login_required
def export_monthly_summary_csv(request):
    denied = _staff_access_required(request, "reports_financial")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')

    period = resolve_monthly_summary_period(request)
    context = get_monthly_summary_context(
        period['start_of_period'],
        period['end_of_period'],
        period['start_date_str'],
        period['end_date_str'],
        preset=period['preset'],
        show_jobs='',
    )

    def money(value):
        return f"{(value or Decimal('0.00')):.2f}"

    filename = f"financial_summary_{period['start_date_str']}_to_{period['end_date_str']}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow(['Financial Summary Report'])
    writer.writerow(['Period', f"{period['start_date_str']} to {period['end_date_str']}"])
    writer.writerow([])
    writer.writerow(['Job Statistics'])
    writer.writerow(['Jobs Created', context['jobs_created_count']])
    writer.writerow(['Jobs Finished', context['jobs_finished_count']])
    writer.writerow(['Jobs Returned', context['jobs_returned_count']])
    writer.writerow(['Vendor Jobs', context['vendor_jobs_count']])
    writer.writerow([])

    writer.writerow(['Financial Blocks'])
    writer.writerow(['Block', 'Revenue', 'Expense', 'Profit'])
    writer.writerow(['Service', money(context['service_revenue']), money(context['service_expense']), money(context['service_profit'])])
    writer.writerow(['Stock Sales', money(context['stock_sales_income']), money(context['stock_sales_cogs']), money(context['stock_sales_profit'])])
    writer.writerow(['Vendor', money(context['vendor_revenue']), money(context['vendor_expense']), money(context['vendor_profit'])])
    writer.writerow(['Overall', money(context['overall_revenue']), money(context['overall_expense']), money(context['overall_profit'])])
    writer.writerow(['Overall Margin %', f"{(context['overall_margin'] or Decimal('0.00')):.2f}"])
    writer.writerow([])

    writer.writerow(['Stock Sales Summary'])
    writer.writerow(['Units Sold', context['stock_sales_units']])
    writer.writerow(['Sale Lines', context['stock_sale_lines_count']])
    writer.writerow(['Unique Products', context['stock_products_count']])
    writer.writerow(['Average Sale Value', money(context['stock_avg_sale_value'])])
    writer.writerow([])

    writer.writerow(['Product-wise Stock Sales'])
    writer.writerow(['Product', 'SKU', 'Category', 'Units Sold', 'Sale Lines', 'Avg Unit Price', 'Revenue', 'COGS', 'Profit'])
    for product_row in context['stock_products_breakdown']:
        writer.writerow([
            product_row['name'],
            product_row['sku'],
            product_row['category'],
            product_row['units_sold'],
            product_row['sale_lines'],
            money(product_row['average_unit_price']),
            money(product_row['revenue']),
            money(product_row['cogs']),
            money(product_row['profit']),
        ])

    return response


@login_required
def print_monthly_summary_pdf(request):
    denied = _staff_access_required(request, "reports_financial")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')

    period = resolve_monthly_summary_period(request)
    context = get_monthly_summary_context(
        period['start_of_period'],
        period['end_of_period'],
        period['start_date_str'],
        period['end_date_str'],
        preset=period['preset'],
        show_jobs='',
    )
    context['pdf_layout'] = True
    return render(request, 'job_tickets/print_monthly_summary_pdf.html', context)

# in job_tickets/views.py

@login_required
def close_job(request, job_code):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    job = get_object_or_404(JobTicket, job_code=job_code)
    old_status = job.get_status_display()
    job.status = 'Closed'
    job.save()

    details = f"Status changed from '{old_status}' to 'Closed'."
    JobTicketLog.objects.create(job_ticket=job, user=request.user, action='CLOSED', details=details)

    send_job_update_message(job.job_code, job.status)
    
    next_url = (request.GET.get('next') or request.META.get('HTTP_REFERER') or '').strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect('staff_dashboard')

def qr_access(request, job_code):
    """Direct access to job status via QR code without login"""
    job_ticket = get_object_or_404(JobTicket, job_code=job_code)
    return redirect('client_status', job_code=job_code)
    
@login_required
@require_POST
def assignment_respond(request, pk):
    """
    POST endpoint for technician to accept/reject an Assignment.
    Expects POST: action=accept|reject, note (optional).
    Returns JSON.
    """
    action = request.POST.get("action")
    note = request.POST.get("note", "").strip()

    if action not in ("accept", "reject"):
        return HttpResponseBadRequest("invalid action")

    try:
        with transaction.atomic():
            # Lock the assignment row to avoid race conditions
            assignment = (
                Assignment.objects.select_for_update()
                .select_related("technician__user", "job")
                .get(pk=pk)
            )

            # Only the assigned technician may respond
            if assignment.technician.user != request.user:
                return HttpResponseForbidden("You are not the assigned technician for this assignment.")

            # Prevent double response
            if assignment.status != "pending":
                return JsonResponse({"ok": False, "error": "already_responded", "status": assignment.status}, status=400)

            if action == "accept":
                assignment.accept(note=note)
            else:
                assignment.reject(note=note)
            
            # CHANNELS: Send update after assignment response changes job status (removed - Django Channels no longer used)

            return JsonResponse({"ok": True, "status": assignment.status})
    except Assignment.DoesNotExist:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)
    except ValueError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)

@login_required
@require_POST
def job_mark_started(request, job_code):
    """
    Mark a job as started (e.g., set to 'Repairing' or 'Under Inspection').
    Only the assigned technician (or staff) may perform this.
    """
    job = get_object_or_404(JobTicket, job_code=job_code)

    # Permission: allow assigned technician or staff
    is_assigned_tech = job.assigned_to and getattr(job.assigned_to, "user", None) == request.user
    is_staff_actor = bool(request.user.is_staff and user_has_staff_access(request.user, "staff_dashboard"))
    if not (is_assigned_tech or is_staff_actor):
        return HttpResponseForbidden("You are not permitted to mark this job as started.")

    # Decide the status you want when "started"
    old_status = job.get_status_display()
    new_status = "Repairing" if job.status != "Repairing" else job.status
    job.status = new_status
    job.save(update_fields=["status", "updated_at"])
    
    # Send WebSocket update
    if old_status != job.get_status_display():
        send_job_update_message(job.job_code, job.status)
        details = f"Status changed from '{old_status}' to '{job.get_status_display()}'."
        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='STATUS', details=details)
        
    messages.success(request, f"Job {job.job_code} marked as started ({new_status}).")
    return redirect("job_detail_technician", job_code=job.job_code)


@login_required
@require_POST
def job_mark_completed(request, job_code):
    """
    Mark a job as completed. Only the assigned technician or staff can do this.
    """
    job = get_object_or_404(JobTicket, job_code=job_code)

    is_assigned_tech = job.assigned_to and getattr(job.assigned_to, "user", None) == request.user
    is_staff_actor = bool(request.user.is_staff and user_has_staff_access(request.user, "staff_dashboard"))
    if not (is_assigned_tech or is_staff_actor):
        return HttpResponseForbidden("You are not permitted to mark this job as completed.")

    if not is_staff_actor:
        checklist_schema, _, _ = _build_checklist_schema_for_job(job)
        missing_required = _missing_required_checklist_labels(job, checklist_schema)
        if missing_required:
            messages.error(request, _format_checklist_required_error(missing_required))
            return redirect("job_detail_technician", job_code=job.job_code)

    old_status = job.get_status_display()
    job.status = "Completed"
    job.save(update_fields=["status", "updated_at"])
    
    # Send WebSocket update
    if old_status != job.get_status_display():
        send_job_update_message(job.job_code, job.status)
        details = f"Status changed from '{old_status}' to '{job.get_status_display()}'."
        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='STATUS', details=details)
        
    messages.success(request, f"Job {job.job_code} marked as Completed.")
    return redirect("job_detail_technician", job_code=job.job_code)


@login_required
def job_billing_print_view(request, job_code):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    
    job = get_object_or_404(JobTicket, job_code=job_code)
    job_tickets = [job]
    calculate_job_totals(job_tickets)
    
    subtotal = job.total
    discount = job.discount_amount
    grand_total = subtotal - discount
    
    technician_id = job.assigned_to.unique_id if job.assigned_to else 'N/A'
    
    # Corrected: Use a fallback value if created_by is None
    created_by_id = job.created_by.id if job.created_by else 'N/A'
    
    # Clean service logs to remove vendor names
    service_logs = job.service_logs.all()
    cleaned_service_logs = []
    for log in service_logs:
        # Replace specialized service descriptions with generic terms
        if 'Specialized Service' in log.description:
            description = 'Specialized Service'
        else:
            description = log.description
            
        cleaned_log = {
            'description': description,
            'part_cost': log.part_cost,
            'service_charge': log.service_charge,
        }
        cleaned_service_logs.append(cleaned_log)
    
    context = {
        'job': job,
        'service_logs': cleaned_service_logs,
        'subtotal': subtotal,
        'discount': discount,
        'grand_total': grand_total,
        'technician_id': technician_id,
        'created_by_id': created_by_id,
        'company': CompanyProfile.get_profile(),
    }
    return render(request, 'job_tickets/job_billing_print.html', context)


@login_required
def staff_technician_reports(request):
    # only staff allowed
    denied = _staff_access_required(request, "reports_technician")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')

    # get all technicians
    techs = TechnicianProfile.objects.select_related('user').all()

    # optionally: annotate some simple counts/totals for display
    tech_rows = []
    for tech in techs:
        jobs = JobTicket.objects.filter(assigned_to=tech).prefetch_related('service_logs')
        
        completed_jobs = [j for j in jobs if j.status == 'Completed']
        
        completed_count = len(completed_jobs)
        
        # Exclude vendor service charges from technician totals
        total_parts = Decimal('0.00')
        total_services = Decimal('0.00')
        
        for job in completed_jobs:
            for log in job.service_logs.all():
                if 'Specialized Service' not in log.description:
                    total_parts += log.part_cost or Decimal('0.00')
                    total_services += log.service_charge or Decimal('0.00')
        
        tech_rows.append({
            'tech': tech,
            'completed_count': completed_count,
            'parts_total': total_parts,
            'service_total': total_services,
        })

    return render(request, 'job_tickets/staff_technician_reports.html', {'tech_rows': tech_rows})


@login_required
def staff_job_detail(request, job_code):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    job = get_object_or_404(JobTicket.objects.prefetch_related('photos'), job_code=job_code)
    checklist_schema, checklist_title, checklist_notes = _build_checklist_schema_for_job(job)

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        if action == 'update_checklist':
            posted_answers, missing_required_labels, invalid_option_labels = _extract_checklist_answers_from_post(
                request.POST,
                checklist_schema,
            )

            if invalid_option_labels:
                messages.error(
                    request,
                    "Invalid checklist selection for: "
                    + ', '.join(invalid_option_labels[:6])
                    + ('...' if len(invalid_option_labels) > 6 else ''),
                )
                return redirect('staff_job_detail', job_code=job_code)

            if missing_required_labels:
                messages.error(request, _format_checklist_required_error(missing_required_labels))
                return redirect('staff_job_detail', job_code=job_code)

            old_answers = _get_job_checklist_answers(job)
            merged_answers = _merge_checklist_answers(old_answers, posted_answers)

            if merged_answers == old_answers:
                messages.info(request, 'No checklist changes detected.')
                return redirect('staff_job_detail', job_code=job_code)

            job.technician_checklist = merged_answers
            job.save(update_fields=['technician_checklist', 'updated_at'])

            change_details = []
            for field in checklist_schema:
                key = field['key']
                field_type = field.get('type')
                if field_type == 'checkbox':
                    old_value = _normalize_checkbox_answer(old_answers.get(key, ''))
                    new_value = _normalize_checkbox_answer(merged_answers.get(key, ''))
                    old_text = 'Verified' if old_value == '1' else 'Not Verified'
                    new_text = 'Verified' if new_value == '1' else 'Not Verified'
                else:
                    old_value = _normalize_checklist_answer(old_answers.get(key, ''))
                    new_value = _normalize_checklist_answer(merged_answers.get(key, ''))
                    old_text = old_value or 'blank'
                    new_text = new_value or 'blank'

                if old_value != new_value:
                    change_details.append(f"{field['label']}: '{old_text}' -> '{new_text}'")

            if change_details:
                details = "Staff updated inspection checklist: " + "; ".join(change_details[:10])
                if len(change_details) > 10:
                    details += "..."
            else:
                details = "Staff updated inspection checklist."

            JobTicketLog.objects.create(
                job_ticket=job,
                user=request.user,
                action='NOTE',
                details=details,
            )
            messages.success(request, 'Inspection checklist updated.')
            return redirect('staff_job_detail', job_code=job_code)

    job_tickets = [job]
    calculate_job_totals(job_tickets)
    
    history_logs = job.logs.all().select_related('user')
    specialized_service = SpecializedService.objects.filter(job_ticket=job).first()
    technician_list = TechnicianProfile.objects.all().select_related('user')
    
    if job.customer_group_id:
        related_jobs = JobTicket.objects.filter(
            customer_group_id=job.customer_group_id
        ).exclude(job_code=job.job_code).order_by('-created_at')
    else:
        related_jobs = JobTicket.objects.none()
    
    all_jobs = JobTicket.objects.all().select_related(
        'assigned_to__user', 'created_by'
    ).prefetch_related('service_logs').order_by('-created_at')
    calculate_job_totals(all_jobs)
    
    subtotal = job.total
    grand_total = subtotal - job.discount_amount
    
    # Generate QR code URL
    qr_url = request.build_absolute_uri(f'/qr/{job.job_code}/')

    context = {
        'job': job,
        'service_logs': job.service_logs.all(),
        'history_logs': history_logs,
        'total_parts_cost': job.part_total,
        'total_service_charges': job.service_total,
        'subtotal': subtotal,
        'discount_amount': job.discount_amount,
        'grand_total': grand_total,
        'specialized_service': specialized_service,
        'related_jobs': related_jobs,
        'all_jobs': all_jobs,
        'technician_list': technician_list,
        'ReassignTechnicianForm': ReassignTechnicianForm(),
        'qr_url': qr_url,
        'checklist_schema': checklist_schema,
        'checklist_title': checklist_title,
        'checklist_notes': checklist_notes,
    }
    return render(request, 'job_tickets/staff_job_detail.html', context)


@login_required
@require_POST
def staff_delete_job_photo(request, job_code, photo_id):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    job = get_object_or_404(JobTicket, job_code=job_code)
    photo = get_object_or_404(JobTicketPhoto, id=photo_id, job_ticket=job)

    try:
        if photo.image:
            photo.image.delete(save=False)
    except Exception:
        pass

    photo.delete()
    messages.success(request, 'Photo deleted successfully.')
    return redirect('staff_job_detail', job_code=job_code)


@login_required
def staff_job_photo_file(request, job_code, photo_id):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    job = get_object_or_404(JobTicket, job_code=job_code)
    photo = get_object_or_404(JobTicketPhoto, id=photo_id, job_ticket=job)

    if photo.image_data:
        response = HttpResponse(photo.image_data, content_type=photo.image_content_type or 'application/octet-stream')
        response['Content-Disposition'] = f'inline; filename="{photo.image_name or f"{job.job_code}-photo-{photo.id}.jpg"}"'
        return response

    if photo.image:
        return redirect(photo.image.url)

    return HttpResponse(status=404)


@login_required
@require_POST
def unlock_vendor_details(request, job_code):
    """Unlock vendor details section with password verification."""
    if not request.user.is_staff or not user_has_staff_access(request.user, "staff_dashboard"):
        return JsonResponse({'ok': False, 'error': 'Unauthorized'}, status=403)
    
    password = request.POST.get('vendor_password', '').strip()
    
    # Check against user's own password or default
    from django.contrib.auth import authenticate
    user_auth = authenticate(username=request.user.username, password=password)
    
    if user_auth is not None or password.lower() == 'vendor123':
        request.session['vendor_details_unlocked'] = True
        request.session.modified = True
        request.session.set_expiry(3600)
        
        # Get specialized service data for AJAX response
        job = get_object_or_404(JobTicket, job_code=job_code)
        specialized_service = SpecializedService.objects.filter(job_ticket=job).first()
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'ok': True, 
                'message': 'Vendor details unlocked.',
                'vendor_name': str(specialized_service.vendor) if specialized_service and specialized_service.vendor else 'N/A',
                'status': specialized_service.get_status_display() if specialized_service else 'N/A',
                'vendor_cost': float(specialized_service.vendor_cost) if specialized_service and specialized_service.vendor_cost else 0,
                'client_charge': float(specialized_service.client_charge) if specialized_service and specialized_service.client_charge else 0,
                'sent_date': specialized_service.sent_date.strftime('%Y-%m-%d') if specialized_service and specialized_service.sent_date else None,
                'returned_date': specialized_service.returned_date.strftime('%Y-%m-%d') if specialized_service and specialized_service.returned_date else None
            })
        messages.success(request, 'Vendor details unlocked.')
    else:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': 'Incorrect password.'}, status=400)
        messages.error(request, 'Incorrect password.')
    
    return redirect('staff_job_detail', job_code=job_code)


@login_required
@require_POST
def lock_vendor_details(request, job_code):
    """Lock vendor details section."""
    if not request.user.is_staff or not user_has_staff_access(request.user, "staff_dashboard"):
        return JsonResponse({'ok': False, 'error': 'Unauthorized'}, status=403)
    
    request.session['vendor_details_unlocked'] = False
    request.session.modified = True  # Ensure session is saved
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'message': 'Vendor details locked.'})
    
    messages.info(request, 'Vendor details locked.')
    return redirect('staff_job_detail', job_code=job_code)


@csrf_exempt
@require_POST
def mobile_api_login(request):
    """JWT login endpoint for the Flutter mobile app."""
    payload = {}
    if 'application/json' in (request.content_type or ''):
        try:
            payload = json.loads((request.body or b'{}').decode('utf-8'))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)
    else:
        payload = request.POST

    username = (payload.get('username') or '').strip()
    password = (payload.get('password') or '').strip()
    if not username or not password:
        return JsonResponse(
            {'error': 'missing_credentials', 'message': 'Username and password are required.'},
            status=400,
        )

    user = authenticate(request, username=username, password=password)
    if not user or not user.is_active:
        return JsonResponse({'error': 'invalid_credentials', 'message': 'Invalid username or password.'}, status=401)

    access_token = issue_mobile_jwt(user)
    role = 'staff' if user.is_staff else 'technician'
    tech_id = ''
    if hasattr(user, 'technician_profile'):
        tech_id = user.technician_profile.unique_id or ''

    return JsonResponse(
        {
            'access_token': access_token,
            'token_type': 'Bearer',
            'expires_in': MOBILE_JWT_EXP_SECONDS,
            'user': {
                'id': user.id,
                'username': user.username,
                'is_staff': user.is_staff,
                'role': role,
                'technician_id': tech_id,
            },
        }
    )


def mobile_api_me(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    role = 'staff' if user.is_staff else 'technician'
    tech_id = ''
    if hasattr(user, 'technician_profile'):
        tech_id = user.technician_profile.unique_id or ''

    return JsonResponse(
        {
            'user': {
                'id': user.id,
                'username': user.username,
                'is_staff': user.is_staff,
                'role': role,
                'technician_id': tech_id,
            }
        }
    )


def mobile_api_jobs(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    if user.is_staff:
        if not user_has_staff_access(user, "staff_dashboard"):
            return JsonResponse({'error': 'forbidden', 'message': 'Staff dashboard access required.'}, status=403)
        jobs_qs = JobTicket.objects.all()
    elif hasattr(user, 'technician_profile'):
        jobs_qs = JobTicket.objects.filter(assigned_to=user.technician_profile)
    else:
        jobs_qs = JobTicket.objects.none()

    jobs = list(
        jobs_qs.select_related('assigned_to__user').prefetch_related('service_logs').order_by('-updated_at')[:30]
    )
    calculate_job_totals(jobs, exclude_vendor_charges=True)

    jobs_data = []
    for job in jobs:
        jobs_data.append(
            {
                'job_code': job.job_code,
                'customer_name': job.customer_name,
                'customer_phone': job.customer_phone,
                'device': f"{job.device_type} {job.device_brand or ''} {job.device_model or ''}".strip(),
                'status': job.status,
                'updated_at': timezone.localtime(job.updated_at).strftime('%Y-%m-%d %H:%M'),
                'total': str(job.total or Decimal('0.00')),
                'part_total': str(job.part_total or Decimal('0.00')),
                'service_total': str(job.service_total or Decimal('0.00')),
                'discount_amount': str(job.discount_amount or Decimal('0.00')),
                'assigned_to': (
                    job.assigned_to.user.username
                    if job.assigned_to and getattr(job.assigned_to, 'user', None)
                    else ''
                ),
            }
        )

    return JsonResponse({'count': len(jobs_data), 'jobs': jobs_data})


def mobile_api_job_detail(request, job_code):
    if request.method != 'GET':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    job = get_object_or_404(
        JobTicket.objects.select_related('assigned_to__user', 'created_by').prefetch_related(
            'service_logs__product_sale__product',
            'logs__user',
        ),
        job_code=job_code,
    )

    permissions = get_mobile_job_permissions(user, job)
    if not permissions['can_access']:
        return JsonResponse(
            {'error': 'forbidden', 'message': 'You are not allowed to access this job.'},
            status=403,
        )

    calculate_job_totals([job], exclude_vendor_charges=True)
    grand_total = (job.total or Decimal('0.00')) - (job.discount_amount or Decimal('0.00'))

    service_logs_data = []
    for service_log in job.service_logs.all().order_by('created_at'):
        product_sale = getattr(service_log, 'product_sale', None)
        service_logs_data.append(
            {
                'id': service_log.id,
                'description': service_log.description,
                'part_cost': str(service_log.part_cost or Decimal('0.00')),
                'service_charge': str(service_log.service_charge or Decimal('0.00')),
                'sales_invoice_number': service_log.sales_invoice_number or '',
                'created_at': timezone.localtime(service_log.created_at).strftime('%Y-%m-%d %H:%M'),
                'is_product_sale': bool(product_sale),
                'product_name': product_sale.product.name if product_sale and product_sale.product else '',
                'product_quantity': int(product_sale.quantity) if product_sale else 0,
                'product_unit_price': str(product_sale.unit_price or Decimal('0.00')) if product_sale else '0.00',
                'product_line_total': str(product_sale.line_total or Decimal('0.00')) if product_sale else '0.00',
            }
        )

    action_labels = {
        'CREATED': 'Job Created',
        'ASSIGNED': 'Technician Assigned',
        'STATUS': 'Status Updated',
        'NOTE': 'Note Updated',
        'SERVICE': 'Service Updated',
        'BILLING': 'Billing Updated',
        'CLOSED': 'Job Closed',
    }
    timeline_queryset = job.logs.select_related('user').order_by('-timestamp')[:60]
    timeline = []
    for entry in reversed(list(timeline_queryset)):
        timeline.append(
            {
                'action': entry.action,
                'label': action_labels.get(entry.action, entry.action.title()),
                'details': entry.details,
                'timestamp': timezone.localtime(entry.timestamp).strftime('%Y-%m-%d %H:%M'),
                'user': entry.user.username if entry.user else 'System',
            }
        )

    if not timeline:
        timeline.append(
            {
                'action': 'CREATED',
                'label': 'Job Created',
                'details': f"Job {job.job_code} created.",
                'timestamp': timezone.localtime(job.created_at).strftime('%Y-%m-%d %H:%M'),
                'user': job.created_by.username if job.created_by else 'System',
            }
        )

    checklist_schema, checklist_title, checklist_notes = _build_checklist_schema_for_job(job)

    return JsonResponse(
        {
            'job': {
                'job_code': job.job_code,
                'status': job.status,
                'status_display': job.get_status_display(),
                'customer_name': job.customer_name,
                'customer_phone': job.customer_phone,
                'device_type': job.device_type or '',
                'device_brand': job.device_brand or '',
                'device_model': job.device_model or '',
                'device_serial': job.device_serial or '',
                'reported_issue': job.reported_issue or '',
                'additional_items': job.additional_items or '',
                'technician_notes': job.technician_notes or '',
                'is_under_warranty': bool(job.is_under_warranty),
                'estimated_amount': str(job.estimated_amount or Decimal('0.00')) if job.estimated_amount else '',
                'estimated_delivery': job.estimated_delivery.strftime('%Y-%m-%d') if job.estimated_delivery else '',
                'vyapar_invoice_number': job.vyapar_invoice_number or '',
                'feedback_rating': int(job.feedback_rating) if job.feedback_rating else 0,
                'feedback_comment': job.feedback_comment or '',
                'feedback_date': timezone.localtime(job.feedback_date).strftime('%Y-%m-%d %H:%M')
                if job.feedback_date
                else '',
                'created_by': job.created_by.username if job.created_by else '',
                'assigned_to': (
                    job.assigned_to.user.username
                    if job.assigned_to and getattr(job.assigned_to, 'user', None)
                    else ''
                ),
                'updated_at': timezone.localtime(job.updated_at).strftime('%Y-%m-%d %H:%M'),
                'created_at': timezone.localtime(job.created_at).strftime('%Y-%m-%d %H:%M'),
                'technician_checklist': _get_job_checklist_answers(job),
            },
            'financials': {
                'part_total': str(job.part_total or Decimal('0.00')),
                'service_total': str(job.service_total or Decimal('0.00')),
                'subtotal': str(job.total or Decimal('0.00')),
                'discount_amount': str(job.discount_amount or Decimal('0.00')),
                'grand_total': str(grand_total),
            },
            'service_logs': service_logs_data,
            'timeline': timeline,
            'available_actions': get_mobile_job_available_actions(user, job),
            'permissions': {
                'can_edit_notes': mobile_can_edit_notes(user, job),
                'can_manage_service_logs': mobile_can_manage_service_lines(user, job),
            },
            'technician_checklist_schema': checklist_schema,
            'technician_checklist_title': checklist_title,
            'technician_checklist_notes': checklist_notes,
        }
    )


@csrf_exempt
@require_POST
def mobile_api_job_action(request, job_code):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    action_key = (payload.get('action') or '').strip()
    if not action_key:
        return JsonResponse({'error': 'missing_action', 'message': 'Action is required.'}, status=400)

    with transaction.atomic():
        job = get_object_or_404(
            JobTicket.objects.select_for_update().select_related('assigned_to__user'),
            job_code=job_code,
        )

        permissions = get_mobile_job_permissions(user, job)
        if not permissions['can_access']:
            return JsonResponse(
                {'error': 'forbidden', 'message': 'You are not allowed to update this job.'},
                status=403,
            )

        old_status_display = job.get_status_display()
        target_status = None
        log_action = 'STATUS'

        if action_key == 'start':
            if job.status not in ['Pending', 'Under Inspection']:
                return JsonResponse(
                    {'error': 'invalid_transition', 'message': 'Job cannot be marked started from current status.'},
                    status=400,
                )
            target_status = 'Repairing'
        elif action_key == 'complete':
            if job.status not in ['Under Inspection', 'Repairing', 'Specialized Service']:
                return JsonResponse(
                    {'error': 'invalid_transition', 'message': 'Job cannot be completed from current status.'},
                    status=400,
                )
            if not permissions['is_staff']:
                checklist_schema, _, _ = _build_checklist_schema_for_job(job)
                missing_required = _missing_required_checklist_labels(job, checklist_schema)
                if missing_required:
                    return JsonResponse(
                        {
                            'error': 'checklist_incomplete',
                            'message': _format_checklist_required_error(missing_required),
                            'missing_checklist_fields': missing_required,
                        },
                        status=400,
                    )
            target_status = 'Completed'
        elif action_key == 'ready_for_pickup':
            if not permissions['is_staff']:
                return JsonResponse({'error': 'forbidden', 'message': 'Only staff can perform this action.'}, status=403)
            if job.status != 'Completed':
                return JsonResponse(
                    {'error': 'invalid_transition', 'message': 'Only completed jobs can be marked ready for pickup.'},
                    status=400,
                )
            target_status = 'Ready for Pickup'
        elif action_key == 'close':
            if not permissions['is_staff']:
                return JsonResponse({'error': 'forbidden', 'message': 'Only staff can perform this action.'}, status=403)
            if job.status not in ['Completed', 'Ready for Pickup']:
                return JsonResponse(
                    {'error': 'invalid_transition', 'message': 'Job cannot be closed from current status.'},
                    status=400,
                )
            target_status = 'Closed'
            log_action = 'CLOSED'
        else:
            return JsonResponse({'error': 'invalid_action', 'message': 'Unsupported action.'}, status=400)

        job.status = target_status
        job.save(update_fields=['status', 'updated_at'])

        send_job_update_message(job.job_code, job.status)
        details = f"Status changed from '{old_status_display}' to '{job.get_status_display()}'."
        JobTicketLog.objects.create(job_ticket=job, user=user, action=log_action, details=details)

    return JsonResponse(
        {
            'ok': True,
            'message': f"Job {job.job_code} updated to {job.get_status_display()}.",
            'status': job.status,
            'status_display': job.get_status_display(),
            'available_actions': get_mobile_job_available_actions(user, job),
        }
    )


@csrf_exempt
@require_POST
def mobile_api_job_notes(request, job_code):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    new_notes = (payload.get('technician_notes') or '').strip()

    with transaction.atomic():
        job = get_object_or_404(JobTicket.objects.select_for_update(), job_code=job_code)

        permissions = get_mobile_job_permissions(user, job)
        if not permissions['can_access']:
            return JsonResponse(
                {'error': 'forbidden', 'message': 'You are not allowed to update this job.'},
                status=403,
            )

        old_notes = (job.technician_notes or '').strip()
        if old_notes == new_notes:
            return JsonResponse(
                {
                    'ok': True,
                    'message': 'No changes detected.',
                    'technician_notes': job.technician_notes or '',
                }
            )

        job.technician_notes = new_notes
        job.save(update_fields=['technician_notes', 'updated_at'])

        if new_notes:
            details = f'Technician notes updated: "{new_notes}"'
        else:
            details = 'Technician notes cleared.'
        JobTicketLog.objects.create(job_ticket=job, user=user, action='NOTE', details=details)

    send_job_update_message(job.job_code, job.status)
    return JsonResponse(
        {
            'ok': True,
            'message': 'Notes saved successfully.',
            'technician_notes': job.technician_notes or '',
        }
    )


@csrf_exempt
@require_POST
def mobile_api_service_line_create(request, job_code):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    description = (payload.get('description') or '').strip()
    if not description:
        return JsonResponse({'error': 'missing_description', 'message': 'Description is required.'}, status=400)

    part_cost, part_error = _mobile_parse_decimal(payload.get('part_cost'), 'part cost')
    if part_error:
        return JsonResponse({'error': 'invalid_part_cost', 'message': part_error}, status=400)

    service_charge, service_error = _mobile_parse_decimal(payload.get('service_charge'), 'service charge')
    if service_error:
        return JsonResponse({'error': 'invalid_service_charge', 'message': service_error}, status=400)

    sales_invoice_number = (payload.get('sales_invoice_number') or '').strip()

    with transaction.atomic():
        job = get_object_or_404(JobTicket.objects.select_for_update(), job_code=job_code)

        if not mobile_can_manage_service_lines(user, job):
            return JsonResponse(
                {'error': 'forbidden', 'message': 'You are not allowed to manage service lines for this job.'},
                status=403,
            )

        created_line = ServiceLog.objects.create(
            job_ticket=job,
            description=description,
            part_cost=part_cost,
            service_charge=service_charge,
            sales_invoice_number=sales_invoice_number or None,
        )
        details = f"Added service: '{created_line.description}' (Part: Rs {part_cost}, Service: Rs {service_charge})"
        JobTicketLog.objects.create(job_ticket=job, user=user, action='SERVICE', details=details)

    send_job_update_message(job.job_code, job.status)
    return JsonResponse(
        {
            'ok': True,
            'message': 'Service line added successfully.',
            'service_line_id': created_line.id,
        }
    )


@csrf_exempt
@require_POST
def mobile_api_service_line_update(request, job_code, line_id):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    with transaction.atomic():
        job = get_object_or_404(JobTicket.objects.select_for_update(), job_code=job_code)
        if not mobile_can_manage_service_lines(user, job):
            return JsonResponse(
                {'error': 'forbidden', 'message': 'You are not allowed to manage service lines for this job.'},
                status=403,
            )

        service_log = get_object_or_404(ServiceLog.objects.select_for_update(), id=line_id, job_ticket=job)

        if hasattr(service_log, 'product_sale'):
            return JsonResponse(
                {
                    'error': 'product_sale_locked',
                    'message': 'Product sale lines cannot be edited directly. Delete and re-add with the correct quantity.',
                },
                status=400,
            )

        new_description = (payload.get('description') or '').strip()
        if not new_description:
            return JsonResponse({'error': 'missing_description', 'message': 'Description is required.'}, status=400)

        new_part_cost, part_error = _mobile_parse_decimal(payload.get('part_cost'), 'part cost')
        if part_error:
            return JsonResponse({'error': 'invalid_part_cost', 'message': part_error}, status=400)

        new_service_charge, service_error = _mobile_parse_decimal(payload.get('service_charge'), 'service charge')
        if service_error:
            return JsonResponse({'error': 'invalid_service_charge', 'message': service_error}, status=400)

        new_invoice_number = (payload.get('sales_invoice_number') or '').strip()

        change_parts = []
        if service_log.description != new_description:
            change_parts.append(f"description: '{service_log.description}' -> '{new_description}'")
            service_log.description = new_description
        old_part_cost = service_log.part_cost or Decimal('0.00')
        if old_part_cost != new_part_cost:
            change_parts.append(f"part_cost: Rs {old_part_cost} -> Rs {new_part_cost}")
            service_log.part_cost = new_part_cost
        old_service_charge = service_log.service_charge or Decimal('0.00')
        if old_service_charge != new_service_charge:
            change_parts.append(f"service_charge: Rs {old_service_charge} -> Rs {new_service_charge}")
            service_log.service_charge = new_service_charge
        old_invoice_number = service_log.sales_invoice_number or ''
        if old_invoice_number != new_invoice_number:
            change_parts.append(f"sales_invoice_number: '{old_invoice_number}' -> '{new_invoice_number}'")
            service_log.sales_invoice_number = new_invoice_number or None

        if not change_parts:
            return JsonResponse({'ok': True, 'message': 'No changes detected.'})

        service_log.save(update_fields=['description', 'part_cost', 'service_charge', 'sales_invoice_number'])
        JobTicketLog.objects.create(job_ticket=job, user=user, action='SERVICE', details='; '.join(change_parts))

    send_job_update_message(job.job_code, job.status)
    return JsonResponse({'ok': True, 'message': 'Service line updated successfully.'})


@csrf_exempt
@require_http_methods(['POST', 'DELETE'])
def mobile_api_service_line_delete(request, job_code, line_id):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    with transaction.atomic():
        job = get_object_or_404(JobTicket.objects.select_for_update(), job_code=job_code)
        if not mobile_can_manage_service_lines(user, job):
            return JsonResponse(
                {'error': 'forbidden', 'message': 'You are not allowed to manage service lines for this job.'},
                status=403,
            )

        service_log = get_object_or_404(ServiceLog.objects.select_for_update(), id=line_id, job_ticket=job)
        line_description = service_log.description
        line_part_cost = service_log.part_cost or Decimal('0.00')
        line_service_charge = service_log.service_charge or Decimal('0.00')

        product_sale_entry = ProductSale.objects.filter(service_log=service_log).select_related('product').first()
        parsed_product_sale = parse_product_sale_log(service_log.description) if not product_sale_entry else None

        if product_sale_entry:
            product = Product.objects.select_for_update().filter(id=product_sale_entry.product_id).first()
            if product:
                product.stock_quantity += product_sale_entry.quantity
                product.save(update_fields=['stock_quantity', 'updated_at'])
                JobTicketLog.objects.create(
                    job_ticket=job,
                    user=user,
                    action='SERVICE',
                    details=(
                        f"Restocked {product.name} by {product_sale_entry.quantity} "
                        'after deleting product sale line.'
                    ),
                )
        elif parsed_product_sale:
            product = Product.objects.select_for_update().filter(id=parsed_product_sale['product_id']).first()
            if product:
                product.stock_quantity += parsed_product_sale['quantity']
                product.save(update_fields=['stock_quantity', 'updated_at'])
                JobTicketLog.objects.create(
                    job_ticket=job,
                    user=user,
                    action='SERVICE',
                    details=(
                        f"Restocked {product.name} by {parsed_product_sale['quantity']} "
                        'after deleting legacy product sale line.'
                    ),
                )

        service_log.delete()
        JobTicketLog.objects.create(
            job_ticket=job,
            user=user,
            action='SERVICE',
            details=(
                f"Deleted service: '{line_description}' "
                f"(Part: Rs {line_part_cost}, Service: Rs {line_service_charge})"
            ),
        )

    send_job_update_message(job.job_code, job.status)
    return JsonResponse({'ok': True, 'message': 'Service line deleted successfully.'})


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def mobile_api_products(request):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response
    if user.is_staff and not user_has_staff_access(user, "inventory"):
        return JsonResponse({'error': 'forbidden', 'message': 'Inventory access required.'}, status=403)

    if request.method == 'GET':
        query = (request.GET.get('q') or '').strip()
        products_qs = Product.objects.all().order_by('name')
        if query:
            products_qs = products_qs.filter(
                Q(name__icontains=query)
                | Q(sku__icontains=query)
                | Q(brand__icontains=query)
                | Q(category__icontains=query)
            )

        products_data = []
        for product in products_qs[:200]:
            products_data.append(
                {
                    'id': product.id,
                    'name': product.name,
                    'sku': product.sku or '',
                    'category': product.category or '',
                    'brand': product.brand or '',
                    'unit_price': str(product.unit_price or Decimal('0.00')),
                    'cost_price': str(product.cost_price or Decimal('0.00')),
                    'stock_quantity': int(product.stock_quantity or 0),
                    'reserved_stock': int(product.reserved_stock or 0),
                    'description': product.description or '',
                    'is_active': bool(product.is_active),
                    'updated_at': timezone.localtime(product.updated_at).strftime('%Y-%m-%d %H:%M'),
                }
            )

        return JsonResponse(
            {
                'count': len(products_data),
                'products': products_data,
                'can_edit': bool(user.is_staff and user_has_staff_access(user, "inventory")),
            }
        )

    if not user.is_staff or not user_has_staff_access(user, "inventory"):
        return JsonResponse({'error': 'forbidden', 'message': 'Only staff can create products.'}, status=403)

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    name = (payload.get('name') or '').strip()
    if not name:
        return JsonResponse({'error': 'missing_name', 'message': 'Product name is required.'}, status=400)

    unit_price, unit_error = _mobile_parse_decimal(payload.get('unit_price'), 'unit price')
    if unit_error:
        return JsonResponse({'error': 'invalid_unit_price', 'message': unit_error}, status=400)

    cost_price, cost_error = _mobile_parse_decimal(payload.get('cost_price'), 'cost price')
    if cost_error:
        return JsonResponse({'error': 'invalid_cost_price', 'message': cost_error}, status=400)

    try:
        stock_quantity = int(payload.get('stock_quantity', 0) or 0)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'invalid_stock_quantity', 'message': 'Stock quantity must be a whole number.'}, status=400)
    if stock_quantity < 0:
        return JsonResponse({'error': 'invalid_stock_quantity', 'message': 'Stock quantity cannot be negative.'}, status=400)

    try:
        reserved_stock = int(payload.get('reserved_stock', 0) or 0)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'invalid_reserved_stock', 'message': 'Reserved stock must be a whole number.'}, status=400)
    if reserved_stock < 0:
        return JsonResponse({'error': 'invalid_reserved_stock', 'message': 'Reserved stock cannot be negative.'}, status=400)

    product = Product.objects.create(
        name=name,
        sku=(payload.get('sku') or '').strip() or None,
        category=(payload.get('category') or '').strip(),
        brand=(payload.get('brand') or '').strip(),
        unit_price=unit_price,
        cost_price=cost_price,
        stock_quantity=stock_quantity,
        reserved_stock=reserved_stock,
        description=(payload.get('description') or '').strip(),
        is_active=_mobile_parse_bool(payload.get('is_active', True)),
    )
    return JsonResponse(
        {
            'ok': True,
            'message': f"Product '{product.name}' created successfully.",
            'product_id': product.id,
        }
    )


@csrf_exempt
@require_POST
def mobile_api_product_update(request, product_id):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response
    if not user.is_staff or not user_has_staff_access(user, "inventory"):
        return JsonResponse({'error': 'forbidden', 'message': 'Only staff can update products.'}, status=403)

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    product = get_object_or_404(Product, pk=product_id)
    update_fields = []

    if 'name' in payload:
        name = (payload.get('name') or '').strip()
        if not name:
            return JsonResponse({'error': 'missing_name', 'message': 'Product name is required.'}, status=400)
        if product.name != name:
            product.name = name
            update_fields.append('name')

    if 'sku' in payload:
        sku = (payload.get('sku') or '').strip()
        normalized_sku = sku or None
        if product.sku != normalized_sku:
            product.sku = normalized_sku
            update_fields.append('sku')

    for text_field in ('category', 'brand', 'description'):
        if text_field in payload:
            new_value = (payload.get(text_field) or '').strip()
            if getattr(product, text_field) != new_value:
                setattr(product, text_field, new_value)
                update_fields.append(text_field)

    if 'unit_price' in payload:
        unit_price, unit_error = _mobile_parse_decimal(payload.get('unit_price'), 'unit price')
        if unit_error:
            return JsonResponse({'error': 'invalid_unit_price', 'message': unit_error}, status=400)
        if product.unit_price != unit_price:
            product.unit_price = unit_price
            update_fields.append('unit_price')

    if 'cost_price' in payload:
        cost_price, cost_error = _mobile_parse_decimal(payload.get('cost_price'), 'cost price')
        if cost_error:
            return JsonResponse({'error': 'invalid_cost_price', 'message': cost_error}, status=400)
        if product.cost_price != cost_price:
            product.cost_price = cost_price
            update_fields.append('cost_price')

    if 'stock_quantity' in payload:
        try:
            stock_quantity = int(payload.get('stock_quantity', 0) or 0)
        except (TypeError, ValueError):
            return JsonResponse(
                {'error': 'invalid_stock_quantity', 'message': 'Stock quantity must be a whole number.'},
                status=400,
            )
        if stock_quantity < 0:
            return JsonResponse({'error': 'invalid_stock_quantity', 'message': 'Stock quantity cannot be negative.'}, status=400)
        if product.stock_quantity != stock_quantity:
            product.stock_quantity = stock_quantity
            update_fields.append('stock_quantity')

    if 'reserved_stock' in payload:
        try:
            reserved_stock = int(payload.get('reserved_stock', 0) or 0)
        except (TypeError, ValueError):
            return JsonResponse(
                {'error': 'invalid_reserved_stock', 'message': 'Reserved stock must be a whole number.'},
                status=400,
            )
        if reserved_stock < 0:
            return JsonResponse({'error': 'invalid_reserved_stock', 'message': 'Reserved stock cannot be negative.'}, status=400)
        if product.reserved_stock != reserved_stock:
            product.reserved_stock = reserved_stock
            update_fields.append('reserved_stock')

    if 'is_active' in payload:
        new_is_active = _mobile_parse_bool(payload.get('is_active'))
        if product.is_active != new_is_active:
            product.is_active = new_is_active
            update_fields.append('is_active')

    if not update_fields:
        return JsonResponse({'ok': True, 'message': 'No changes detected.'})

    update_fields.append('updated_at')
    product.save(update_fields=update_fields)
    return JsonResponse({'ok': True, 'message': f"Product '{product.name}' updated successfully."})


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def mobile_api_clients(request):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response
    if user.is_staff and not user_has_staff_access(user, "staff_dashboard"):
        return JsonResponse({'error': 'forbidden', 'message': 'Staff dashboard access required.'}, status=403)

    if request.method == 'GET':
        query = (request.GET.get('q') or '').strip()
        clients_qs = Client.objects.all().order_by('name')
        if query:
            clients_qs = clients_qs.filter(
                Q(name__icontains=query)
                | Q(phone__icontains=query)
                | Q(email__icontains=query)
                | Q(company_name__icontains=query)
            )

        clients_data = []
        for client in clients_qs[:200]:
            clients_data.append(
                {
                    'id': client.id,
                    'name': client.name,
                    'phone': client.phone,
                    'email': client.email or '',
                    'company_name': client.company_name or '',
                    'address': client.address or '',
                    'notes': client.notes or '',
                    'is_active': bool(client.is_active),
                    'updated_at': timezone.localtime(client.updated_at).strftime('%Y-%m-%d %H:%M'),
                }
            )

        return JsonResponse(
            {
                'count': len(clients_data),
                'clients': clients_data,
                'can_edit': bool(user.is_staff and user_has_staff_access(user, "staff_dashboard")),
            }
        )

    if not user.is_staff or not user_has_staff_access(user, "staff_dashboard"):
        return JsonResponse({'error': 'forbidden', 'message': 'Only staff can create clients.'}, status=403)

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    name = (payload.get('name') or '').strip()
    phone, phone_error = normalize_indian_phone(payload.get('phone'), field_label='Phone number')
    if not name:
        return JsonResponse({'error': 'missing_name', 'message': 'Client name is required.'}, status=400)
    if phone_error:
        return JsonResponse({'error': 'invalid_phone', 'message': phone_error}, status=400)
    if Client.objects.filter(phone__in=phone_lookup_variants(phone)).exists():
        return JsonResponse({'error': 'duplicate_phone', 'message': 'A client with this phone already exists.'}, status=400)

    client = Client.objects.create(
        name=name,
        phone=phone,
        email=(payload.get('email') or '').strip(),
        company_name=(payload.get('company_name') or '').strip(),
        address=(payload.get('address') or '').strip(),
        notes=(payload.get('notes') or '').strip(),
        is_active=_mobile_parse_bool(payload.get('is_active', True)),
    )
    return JsonResponse(
        {
            'ok': True,
            'message': f"Client '{client.name}' created successfully.",
            'client_id': client.id,
        }
    )


@csrf_exempt
@require_POST
def mobile_api_client_update(request, client_id):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response
    if not user.is_staff or not user_has_staff_access(user, "staff_dashboard"):
        return JsonResponse({'error': 'forbidden', 'message': 'Only staff can update clients.'}, status=403)

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    client = get_object_or_404(Client, pk=client_id)
    update_fields = []

    if 'name' in payload:
        name = (payload.get('name') or '').strip()
        if not name:
            return JsonResponse({'error': 'missing_name', 'message': 'Client name is required.'}, status=400)
        if client.name != name:
            client.name = name
            update_fields.append('name')

    if 'phone' in payload:
        phone, phone_error = normalize_indian_phone(payload.get('phone'), field_label='Phone number')
        if phone_error:
            return JsonResponse({'error': 'invalid_phone', 'message': phone_error}, status=400)
        if Client.objects.filter(phone__in=phone_lookup_variants(phone)).exclude(id=client.id).exists():
            return JsonResponse({'error': 'duplicate_phone', 'message': 'A client with this phone already exists.'}, status=400)
        if client.phone != phone:
            client.phone = phone
            update_fields.append('phone')

    for text_field in ('email', 'company_name', 'address', 'notes'):
        if text_field in payload:
            new_value = (payload.get(text_field) or '').strip()
            if getattr(client, text_field) != new_value:
                setattr(client, text_field, new_value)
                update_fields.append(text_field)

    if 'is_active' in payload:
        is_active = _mobile_parse_bool(payload.get('is_active'))
        if client.is_active != is_active:
            client.is_active = is_active
            update_fields.append('is_active')

    if not update_fields:
        return JsonResponse({'ok': True, 'message': 'No changes detected.'})

    update_fields.append('updated_at')
    client.save(update_fields=update_fields)
    return JsonResponse({'ok': True, 'message': f"Client '{client.name}' updated successfully."})


@require_http_methods(['GET'])
def mobile_api_pending_approvals(request):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response
    if user.is_staff and not user_has_staff_access(user, "staff_dashboard"):
        return JsonResponse({'error': 'forbidden', 'message': 'Staff dashboard access required.'}, status=403)

    is_technician = hasattr(user, 'technician_profile')
    can_act = bool(is_technician and not user.is_staff)

    if user.is_staff:
        approvals_qs = Assignment.objects.filter(status='pending').select_related('job', 'technician__user').order_by('-created_at')
    elif is_technician:
        approvals_qs = Assignment.objects.filter(
            status='pending',
            technician=user.technician_profile,
        ).select_related('job', 'technician__user').order_by('-created_at')
    else:
        approvals_qs = Assignment.objects.none()

    approvals_data = []
    for assignment in approvals_qs[:200]:
        job = assignment.job
        approvals_data.append(
            {
                'id': assignment.id,
                'job_code': job.job_code,
                'job_status': job.status,
                'customer_name': job.customer_name,
                'customer_phone': job.customer_phone,
                'device': f"{job.device_type} {job.device_brand or ''} {job.device_model or ''}".strip(),
                'technician': assignment.technician.user.username if assignment.technician and assignment.technician.user else '',
                'created_at': timezone.localtime(assignment.created_at).strftime('%Y-%m-%d %H:%M'),
            }
        )

    return JsonResponse({'count': len(approvals_data), 'can_act': can_act, 'approvals': approvals_data})


@csrf_exempt
@require_POST
def mobile_api_pending_approval_action(request, assignment_id):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    if not hasattr(user, 'technician_profile'):
        return JsonResponse({'error': 'forbidden', 'message': 'Only technicians can respond to approvals.'}, status=403)

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    action_key = (payload.get('action') or '').strip().lower()
    note = (payload.get('note') or '').strip()
    if action_key not in {'accept', 'reject'}:
        return JsonResponse({'error': 'invalid_action', 'message': 'Action must be accept or reject.'}, status=400)

    with transaction.atomic():
        assignment = get_object_or_404(
            Assignment.objects.select_for_update().select_related('job', 'technician__user'),
            pk=assignment_id,
        )

        if assignment.technician_id != user.technician_profile.id:
            return JsonResponse({'error': 'forbidden', 'message': 'You are not assigned to this approval.'}, status=403)
        if assignment.status != 'pending':
            return JsonResponse({'error': 'already_responded', 'message': 'Approval already responded.'}, status=400)

        if action_key == 'accept':
            assignment.accept(note=note)
            details = f"Assignment accepted by technician '{user.username}'."
            message = 'Approval accepted.'
        else:
            assignment.reject(note=note)
            details = f"Assignment rejected by technician '{user.username}'."
            message = 'Approval rejected.'

        if note:
            details = f'{details} Note: {note}'

        JobTicketLog.objects.create(job_ticket=assignment.job, user=user, action='ASSIGNED', details=details)
        assignment.job.refresh_from_db(fields=['status', 'updated_at'])

    send_job_update_message(assignment.job.job_code, assignment.job.status)
    return JsonResponse(
        {
            'ok': True,
            'message': message,
            'job_code': assignment.job.job_code,
            'job_status': assignment.job.status,
            'job_status_display': assignment.job.get_status_display(),
        }
    )


@require_http_methods(['GET'])
def mobile_api_reports_summary(request):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response
    if not user.is_staff or not user_has_staff_access(user, "reports_financial"):
        return JsonResponse({'error': 'forbidden', 'message': 'Only staff can access reports.'}, status=403)

    period = resolve_monthly_summary_period(request)
    report_context = get_monthly_summary_context(
        period['start_of_period'],
        period['end_of_period'],
        period['start_date_str'],
        period['end_date_str'],
        preset=period['preset'],
        show_jobs='',
    )

    top_products = []
    for row in report_context['stock_products_breakdown'][:8]:
        top_products.append(
            {
                'product_id': row['product_id'],
                'name': row['name'],
                'sku': row['sku'],
                'units_sold': row['units_sold'],
                'sale_lines': row['sale_lines'],
                'average_unit_price': str(row['average_unit_price']),
                'revenue': str(row['revenue']),
                'cogs': str(row['cogs']),
                'profit': str(row['profit']),
            }
        )

    return JsonResponse(
        {
            'period': {
                'start_date': period['start_date_str'],
                'end_date': period['end_date_str'],
                'preset': period['preset'],
            },
            'summary': {
                'jobs_created': report_context['jobs_created_count'],
                'jobs_finished': report_context['jobs_finished_count'],
                'jobs_returned': report_context['jobs_returned_count'],
                'vendor_jobs': report_context['vendor_jobs_count'],
                'overall_revenue': str(report_context['overall_revenue']),
                'overall_expense': str(report_context['overall_expense']),
                'overall_profit': str(report_context['overall_profit']),
                'overall_margin': str(report_context['overall_margin']),
                'service_revenue': str(report_context['service_revenue']),
                'service_profit': str(report_context['service_profit']),
                'stock_sales_income': str(report_context['stock_sales_income']),
                'stock_sales_cogs': str(report_context['stock_sales_cogs']),
                'stock_sales_profit': str(report_context['stock_sales_profit']),
                'stock_sales_units': report_context['stock_sales_units'],
                'stock_products_count': report_context['stock_products_count'],
                'vendor_revenue': str(report_context['vendor_revenue']),
                'vendor_expense': str(report_context['vendor_expense']),
                'vendor_profit': str(report_context['vendor_profit']),
            },
            'top_products': top_products,
        }
    )


@login_required
def api_all_jobs(request):
    """API endpoint to fetch all jobs as JSON for real-time updates"""
    if not request.user.is_staff or not user_has_staff_access(request.user, "staff_dashboard"):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    jobs = JobTicket.objects.all().select_related(
        'assigned_to__user', 'created_by'
    ).prefetch_related('service_logs').order_by('-created_at')
    
    calculate_job_totals(jobs)
    
    jobs_data = []
    for job in jobs:
        jobs_data.append({
            'job_code': job.job_code,
            'customer_name': job.customer_name,
            'customer_phone': job.customer_phone,
            'device_type': job.device_type,
            'device_brand': job.device_brand or '',
            'device_model': job.device_model or '',
            'status': job.status,
            'status_display': job.get_status_display(),
            'assigned_to': job.assigned_to.user.username if job.assigned_to and job.assigned_to.user else None,
            'created_at': job.created_at.strftime('%Y-%m-%d %H:%M'),
            'updated_at': job.updated_at.strftime('%Y-%m-%d %H:%M'),
            'total': str(job.total) if job.total else '0.00',
            'part_total': str(job.part_total) if job.part_total else '0.00',
            'service_total': str(job.service_total) if job.service_total else '0.00',
            'discount_amount': str(job.discount_amount) if job.discount_amount else '0.00',
            'technician_notes': job.technician_notes or '',
            'url': f'/staff/job/{job.job_code}/',
        })
    
    return JsonResponse({'jobs': jobs_data})


@login_required
@require_POST
def request_specialized_service(request, job_code):
    if not request.user.groups.filter(name='Technicians').exists():
        return redirect('unauthorized')
        
    job = get_object_or_404(JobTicket, job_code=job_code)
    
    with transaction.atomic():
        # Check if a SpecializedService already exists
        if hasattr(job, 'specialized_service'):
            service = job.specialized_service
            
            # If status is 'Returned from Vendor', reset it to allow re-assignment
            if service.status == 'Returned from Vendor':
                old_status = job.get_status_display()
                job.status = 'Specialized Service'
                job.save()
                
                # Send WebSocket update
                send_job_update_message(job.job_code, job.status)
                
                # Reset the specialized service record to await new vendor assignment
                service.status = 'Awaiting Assignment'
                service.vendor = None
                service.vendor_cost = None
                service.client_charge = None
                service.sent_date = None
                service.returned_date = None
                service.save()
                
                details = f"Status changed from '{old_status}' to 'Specialized Service'. Re-requested specialized service. Service charges will be automatically handled when returned from vendor."
                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='STATUS', details=details)
                
                messages.success(request, f"Job {job.job_code} has been re-sent to staff for specialized service assignment. Service charges will be automatically added when returned.")
                return redirect('technician_dashboard')
            else:
                # Already awaiting assignment or sent to vendor - prevent duplicate
                messages.warning(request, 'This job has already been marked for specialized service.')
                return redirect('job_detail_technician', job_code=job.job_code)

        # No existing SpecializedService - create a new one
        old_status = job.get_status_display()
        job.status = 'Specialized Service'
        job.save()

        # Create the tracking record for the specialized service
        SpecializedService.objects.create(job_ticket=job)

        # Log this important action
        details = f"Status changed from '{old_status}' to 'Specialized Service'. Awaiting vendor assignment by staff. Service charges will be automatically handled when returned from vendor."
        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='STATUS', details=details)
        
        # Send WebSocket update
        send_job_update_message(job.job_code, job.status)

    messages.success(request, f"Job {job.job_code} has been sent to staff for specialized service assignment. Service charges will be automatically added when the job returns from the vendor.")
    return redirect('technician_dashboard')


@login_required
def mark_service_returned(request, service_id):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    service = get_object_or_404(SpecializedService, id=service_id)
    job = service.job_ticket

    # Handle POST request with cost data
    if request.method == 'POST':
        vendor_cost = request.POST.get('vendor_cost')
        client_charge = request.POST.get('client_charge')
        
        # Validate that costs are provided
        if not vendor_cost or not client_charge:
            messages.error(request, "Both Vendor Cost and Client Charge are required.")
            return redirect('vendor_dashboard')
        
        try:
            vendor_cost = Decimal(vendor_cost)
            client_charge = Decimal(client_charge)
        except (ValueError, TypeError):
            messages.error(request, "Invalid cost values. Please enter valid numbers.")
            return redirect('vendor_dashboard')
        
        with transaction.atomic():
            # Step 1: Update the SpecializedService record with costs
            service.status = 'Returned from Vendor'
            service.returned_date = timezone.now()
            service.vendor_cost = vendor_cost
            service.client_charge = client_charge
            service.save()

            # Step 2: Automatically create ServiceLog with the client charge
            # This eliminates the need for technicians to manually add service charges
            ServiceLog.objects.update_or_create(
                job_ticket=service.job_ticket,
                description=f"Specialized Service - {service.vendor.company_name}",
                defaults={
                    'part_cost': Decimal('0.00'),
                    'service_charge': client_charge
                }
            )

            # Step 3: Update the main JobTicket status to put it back in the technician's queue
            old_status = job.get_status_display()
            job.status = 'Repairing' 
            job.save()

            # Step 4: Log this important event
            details = f"Device returned from vendor '{service.vendor.company_name}'. Costs: Vendor ₹{vendor_cost}, Client ₹{client_charge}. Service charge automatically added. Status changed from '{old_status}' to 'Repairing'."
            JobTicketLog.objects.create(job_ticket=job, user=request.user, action='STATUS', details=details)
            
            # Send WebSocket update
            send_job_update_message(job.job_code, job.status)

        messages.success(request, f"Job {job.job_code} marked as returned with costs recorded and service charge automatically added. Job is now back in the technician's queue.")
        return redirect('vendor_dashboard')
    
    # GET request should not happen, redirect to vendor dashboard
    return redirect('vendor_dashboard')


INVENTORY_ENTRY_CONFIG = {
    'purchase': {
        'title': 'Purchase',
        'icon': 'fa-cart-arrow-down',
        'description': 'Add supplier purchases to increase stock.',
        'url_name': 'inventory_purchase_dashboard',
        'submit_label': 'Record Purchase',
        'success_label': 'Purchase',
        'party_label': 'Suppliers',
    },
    'purchase_return': {
        'title': 'Purchase Return',
        'icon': 'fa-rotate-left',
        'description': 'Review purchase return bills created from the purchase register.',
        'url_name': 'inventory_purchase_return_dashboard',
        'submit_label': 'Record Purchase Return',
        'success_label': 'Purchase return',
        'party_label': 'Suppliers',
    },
    'sale': {
        'title': 'Sales',
        'icon': 'fa-cart-shopping',
        'description': 'Create sales entries that reduce stock.',
        'url_name': 'inventory_sales_dashboard',
        'submit_label': 'Record Sale',
        'success_label': 'Sale',
        'party_label': 'Customers',
    },
    'sale_return': {
        'title': 'Sales Return',
        'icon': 'fa-rotate-right',
        'description': 'Review sales return bills created from the sales register.',
        'url_name': 'inventory_sales_return_dashboard',
        'submit_label': 'Record Sales Return',
        'success_label': 'Sales return',
        'party_label': 'Customers',
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

    if entry_type in {'purchase', 'purchase_return'}:
        valid_party_qs = InventoryParty.objects.filter(is_active=True, party_type='supplier')
    else:
        valid_party_qs = InventoryParty.objects.filter(is_active=True, party_type='customer')

    if linked_job_ids:
        new_party = scoped_entries[0].party
    else:
        edit_party_id = (request.POST.get('edit_party_id') or '').strip()
        new_party = valid_party_qs.filter(pk=edit_party_id).first()
    if not new_party:
        raise ValueError(f"Please select a valid {config['party_label'][:-1].lower()}.")

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

    party_qs = InventoryParty.objects.filter(party_type='customer')
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
        party_type='customer',
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

            if stock_after < 0:
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


@login_required
def inventory_dashboard(request):
    denied = _staff_access_required(request, "inventory")
    if denied:
        return denied

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

    reserved_stock_products = Product.objects.filter(
        reserved_stock__gt=0,
        stock_quantity__lte=F('reserved_stock'),
    ).order_by('stock_quantity', 'reserved_stock', 'name')[:8]
    reserved_alert_count = Product.objects.filter(
        reserved_stock__gt=0,
        stock_quantity__lte=F('reserved_stock'),
    ).count()

    context = {
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
        'recent_entries': InventoryEntry.objects.select_related('party', 'product', 'created_by')[:10],
    }
    return render(request, 'job_tickets/inventory_dashboard.html', context)


@login_required
def inventory_party_dashboard(request):
    denied = _staff_access_required(request, "inventory")
    if denied:
        return denied

    query = (request.GET.get('q') or '').strip()
    start_date = None
    end_date = None
    start_date_raw = (request.GET.get('start_date') or '').strip()
    end_date_raw = (request.GET.get('end_date') or '').strip()
    active_tab = (request.GET.get('tab') or request.POST.get('tab') or 'suppliers').strip().lower()
    if active_tab not in {'suppliers', 'customers'}:
        active_tab = 'suppliers'

    if start_date_raw:
        try:
            start_date = datetime.strptime(start_date_raw, '%Y-%m-%d').date()
        except ValueError:
            start_date = None
    if end_date_raw:
        try:
            end_date = datetime.strptime(end_date_raw, '%Y-%m-%d').date()
        except ValueError:
            end_date = None
    if start_date and end_date and start_date > end_date:
        start_date, end_date = end_date, start_date

    posted_entry_type = (request.POST.get('inventory_entry_edit_submit') or '').strip()
    if request.method == 'POST' and posted_entry_type in INVENTORY_ENTRY_CONFIG:
        try:
            result = _process_inventory_grouped_bill_edit(request, entry_type=posted_entry_type)
            return _inventory_post_response(
                request,
                'inventory_party_dashboard',
                True,
                result['message'],
                extra_params={'tab': active_tab},
            )
        except ValueError as exc:
            return _inventory_post_response(
                request,
                'inventory_party_dashboard',
                False,
                str(exc),
                extra_params={'tab': active_tab},
            )

    parties = InventoryParty.objects.all()

    if query:
        parties = parties.filter(
            Q(name__icontains=query)
            | Q(phone__icontains=query)
            | Q(gstin__icontains=query)
            | Q(city__icontains=query)
        )

    if request.method == 'POST' and 'add_inventory_party_submit' in request.POST:
        party_form = InventoryPartyForm(request.POST)
        if party_form.is_valid():
            party = party_form.save()
            messages.success(request, f"Party '{party.name}' added successfully.")
            return redirect('inventory_party_dashboard')
        messages.error(request, 'Please fix the highlighted errors and try again.')
    else:
        party_form = InventoryPartyForm(initial={'party_type': 'supplier', 'is_active': True})

    suppliers = list(parties.filter(party_type='supplier').order_by('name'))
    customers = list(parties.filter(party_type='customer').order_by('name'))
    legacy_both_count = parties.filter(party_type='both').count()

    party_ids = [party.id for party in suppliers + customers]
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

    attach_party_history(suppliers)
    attach_party_history(customers)

    try:
        default_gst_rate = CompanyProfile.get_profile().gst_rate
    except Exception:
        default_gst_rate = Decimal('18.00')

    def money_text(amount):
        return format((amount or Decimal('0.00')).quantize(Decimal('0.01')), 'f')

    supplier_edit_options = InventoryParty.objects.filter(
        is_active=True,
        party_type='supplier',
    ).order_by('name')
    customer_edit_options = InventoryParty.objects.filter(
        is_active=True,
        party_type='customer',
    ).order_by('name')

    def serialize_party_options(option_qs):
        return [
            {
                'id': party.id,
                'label': f"{party.name} ({party.phone})" if party.phone else party.name,
            }
            for party in option_qs
        ]

    inventory_party_bill_payload = {}
    for party in suppliers + customers:
        for bill in party.combined_history:
            payload_key = str(bill['bill_id'] or bill['bill_key'])
            if payload_key in inventory_party_bill_payload:
                continue

            lines = sorted(bill['lines'], key=lambda row: row.id)
            inventory_party_bill_payload[payload_key] = {
                'bill_id': bill['bill_id'] or '',
                'bill_key': bill['bill_key'],
                'entry_type': bill['entry_type'],
                'entry_type_label': bill['entry_type_label'],
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
        'party_form': party_form,
        'suppliers': suppliers,
        'customers': customers,
        'legacy_both_count': legacy_both_count,
        'query': query,
        'total_parties': InventoryParty.objects.filter(party_type__in=['supplier', 'customer']).count(),
        'supplier_count': InventoryParty.objects.filter(party_type='supplier').count(),
        'customer_count': InventoryParty.objects.filter(party_type='customer').count(),
        'active_tab': active_tab,
        'start_date': start_date.isoformat() if start_date else '',
        'end_date': end_date.isoformat() if end_date else '',
        'default_gst_rate': default_gst_rate,
        'line_products': Product.objects.filter(is_active=True).order_by('name'),
        'inventory_party_bill_payload': inventory_party_bill_payload,
        'inventory_party_edit_options': {
            'purchase': serialize_party_options(supplier_edit_options),
            'purchase_return': serialize_party_options(supplier_edit_options),
            'sale': serialize_party_options(customer_edit_options),
            'sale_return': serialize_party_options(customer_edit_options),
        },
    }
    return render(request, 'job_tickets/inventory_party_dashboard.html', context)


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


@login_required
@require_POST
def inventory_quick_add_party(request):
    if not request.user.is_staff or not user_has_staff_access(request.user, "inventory"):
        return JsonResponse({'ok': False, 'error': 'Unauthorized'}, status=403)

    party_type = (request.POST.get('party_type') or 'supplier').strip().lower()
    if party_type not in {'supplier', 'customer'}:
        party_type = 'supplier'

    payload = request.POST.copy()
    payload['party_type'] = party_type
    payload['is_active'] = 'on'
    payload.setdefault('opening_balance', '0')

    party_form = InventoryPartyForm(payload)
    if not party_form.is_valid():
        return JsonResponse({'ok': False, 'errors': _inventory_form_errors(party_form)}, status=400)

    party = party_form.save(commit=False)
    party.party_type = party_type
    party.is_active = True
    party.save()

    label = f"{party.name} ({party.phone})" if (party.phone or '').strip() else party.name
    return JsonResponse(
        {
            'ok': True,
            'party': {
                'id': party.id,
                'name': party.name,
                'phone': party.phone or '',
                'label': label,
            },
        }
    )


@login_required
@require_http_methods(["GET"])
def inventory_invoice_preview(request):
    if not request.user.is_staff or not user_has_staff_access(request.user, "inventory"):
        return JsonResponse({'ok': False, 'error': 'Unauthorized'}, status=403)

    entry_type = (request.GET.get('entry_type') or 'sale').strip().lower()
    if entry_type != 'sale':
        return JsonResponse({'ok': False, 'error': 'Unsupported entry type'}, status=400)

    raw_entry_date = (request.GET.get('entry_date') or '').strip()
    entry_date = timezone.localdate()
    if raw_entry_date:
        try:
            entry_date = datetime.strptime(raw_entry_date, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'ok': False, 'error': 'Invalid entry date'}, status=400)

    return JsonResponse(
        {
            'ok': True,
            'invoice_number': _generate_inventory_invoice_number(entry_type, entry_date),
        }
    )


@login_required
@require_POST
def inventory_quick_add_product(request):
    if not request.user.is_staff or not user_has_staff_access(request.user, "inventory"):
        return JsonResponse({'ok': False, 'error': 'Unauthorized'}, status=403)

    payload = request.POST.copy()
    payload.setdefault('stock_quantity', '0')
    payload.setdefault('reserved_stock', '0')
    payload.setdefault('description', '')
    payload.setdefault('purchase_price_tax_mode', 'without_tax')
    payload.setdefault('sales_price_tax_mode', 'without_tax')

    product_form = ProductForm(payload)
    if not product_form.is_valid():
        return JsonResponse({'ok': False, 'errors': _inventory_form_errors(product_form)}, status=400)

    try:
        gst_rate = CompanyProfile.get_profile().gst_rate or Decimal('0.00')
    except Exception:
        gst_rate = Decimal('0.00')

    product = product_form.save(commit=False)
    product.cost_price = _normalize_tax_mode_price(
        product_form.cleaned_data.get('cost_price'),
        product_form.cleaned_data.get('purchase_price_tax_mode'),
        gst_rate,
    )
    product.unit_price = _normalize_tax_mode_price(
        product_form.cleaned_data.get('unit_price'),
        product_form.cleaned_data.get('sales_price_tax_mode'),
        gst_rate,
    )
    product.stock_quantity = 0
    product.save()

    return JsonResponse(
        {
            'ok': True,
            'product': {
                'id': product.id,
                'name': product.name,
                'stock_quantity': int(product.stock_quantity or 0),
                'label': f"{product.name} (Stock: {int(product.stock_quantity or 0)})",
                'cost_price': format(product.cost_price, '.2f'),
                'unit_price': format(product.unit_price, '.2f'),
            },
        }
    )


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
                    party_type='customer',
                    pk=edit_party_id,
                ).first()
                if not new_party:
                    messages.error(request, "Please select a valid customer.")
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
                valid_party_qs = InventoryParty.objects.filter(is_active=True, party_type='supplier')
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
                valid_party_qs = InventoryParty.objects.filter(is_active=True, party_type='customer')
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
                    'Customer is fixed for service-linked sales entries and cannot be changed.',
                )
                return redirect(config['url_name'])
            if not new_party:
                messages.error(request, f"Please select a valid {config['party_label'][:-1].lower()}.")
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

    if entry_type in {'purchase', 'purchase_return'}:
        edit_party_options = InventoryParty.objects.filter(is_active=True, party_type='supplier').order_by('name')
    else:
        edit_party_options = InventoryParty.objects.filter(is_active=True, party_type='customer').order_by('name')

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


@login_required
def inventory_purchase_dashboard(request):
    return _inventory_entry_dashboard(request, 'purchase')


@login_required
def inventory_purchase_return_dashboard(request):
    return _inventory_entry_dashboard(request, 'purchase_return')


@login_required
def inventory_sales_dashboard(request):
    return _inventory_entry_dashboard(request, 'sale')


@login_required
def inventory_sales_return_dashboard(request):
    return _inventory_entry_dashboard(request, 'sale_return')


@login_required
def inventory_sales_print_bill_view(request, bill_id):
    denied = _staff_access_required(request, "inventory")
    if denied:
        return denied

    sale_bill = (
        InventoryBill.objects.filter(pk=bill_id, entry_type='sale')
        .select_related('party', 'job_ticket')
        .first()
    )
    if not sale_bill:
        messages.error(request, 'Selected sales bill was not found.')
        return redirect('inventory_sales_dashboard')

    sale_entries = list(
        sale_bill.lines.select_related('bill', 'party', 'product', 'created_by', 'job_ticket')
        .order_by('id')
    )

    if not sale_entries:
        messages.error(request, f"Sales bill '{sale_bill.bill_number}' has no line items.")
        return redirect('inventory_sales_dashboard')

    context = _prepare_inventory_sale_bill_print_context(sale_bill, sale_entries)
    return render(request, 'job_tickets/inventory_sales_print.html', context)


@login_required
def inventory_sales_print_view(request, invoice_number):
    denied = _staff_access_required(request, "inventory")
    if denied:
        return denied

    normalized_invoice = (invoice_number or '').strip()
    sale_bill = (
        InventoryBill.objects.filter(
            entry_type='sale',
            invoice_number__iexact=normalized_invoice,
        )
        .select_related('party', 'job_ticket')
        .first()
    )
    if sale_bill:
        sale_entries = list(
            sale_bill.lines.select_related('bill', 'party', 'product', 'created_by', 'job_ticket')
            .order_by('id')
        )
        if sale_entries:
            context = _prepare_inventory_sale_bill_print_context(
                sale_bill,
                sale_entries,
                invoice_label=normalized_invoice,
            )
            return render(request, 'job_tickets/inventory_sales_print.html', context)

    messages.error(request, f"Sales invoice '{normalized_invoice}' was not found.")
    return redirect('inventory_sales_dashboard')


@login_required
def client_dashboard(request):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    query = (request.GET.get('q') or '').strip()
    clients = Client.objects.all()

    if query:
        clients = clients.filter(
            Q(name__icontains=query) |
            Q(phone__icontains=query)
        )

    if request.method == 'POST' and 'add_client_submit' in request.POST:
        client_form = ClientForm(request.POST)
        if client_form.is_valid():
            client = client_form.save()
            messages.success(request, f"Client '{client.name}' added successfully.")
            return redirect('client_dashboard')
        messages.error(request, "Please fix the errors and try again.")
    else:
        client_form = ClientForm()

    phone_job_counts = {
        row['customer_phone']: row['total_jobs']
        for row in JobTicket.objects.values('customer_phone').annotate(total_jobs=Count('id'))
    }
    phone_device_rows = JobTicket.objects.values('customer_phone', 'device_type').annotate(total_jobs=Count('id')).order_by('customer_phone', '-total_jobs')
    device_map = {}
    for row in phone_device_rows:
        phone_key = row['customer_phone']
        device_label = (row['device_type'] or '').strip() or 'Unknown Device'
        device_map.setdefault(phone_key, []).append({
            'device_type': device_label,
            'count': row['total_jobs'],
        })

    client_rows = list(clients.order_by('-created_at'))
    client_phones = [client.phone for client in client_rows if client.phone]
    jobs_by_phone = {phone: [] for phone in client_phones}
    if client_phones:
        job_rows = (
            JobTicket.objects
            .filter(customer_phone__in=client_phones)
            .values('customer_phone', 'job_code', 'device_type', 'status', 'created_at')
            .order_by('-created_at')
        )
        for row in job_rows:
            phone_key = row['customer_phone']
            if phone_key in jobs_by_phone:
                jobs_by_phone[phone_key].append(row)
    for client in client_rows:
        client.total_jobs = phone_job_counts.get(client.phone, 0)
        client.device_breakdown = device_map.get(client.phone, [])
        client.jobs = jobs_by_phone.get(client.phone, [])

    context = {
        'clients': client_rows,
        'client_form': client_form,
        'query': query,
        'total_clients': Client.objects.count(),
    }
    return render(request, 'job_tickets/client_dashboard.html', context)


@login_required
def product_dashboard(request):
    denied = _staff_access_required(request, "inventory")
    if denied:
        return denied

    current_url_name = getattr(getattr(request, 'resolver_match', None), 'url_name', '')
    redirect_target = 'inventory_product_dashboard' if current_url_name == 'inventory_product_dashboard' else 'product_dashboard'

    query = (request.GET.get('q') or '').strip()
    products = Product.objects.all()

    if query:
        products = products.filter(
            Q(name__icontains=query) |
            Q(sku__icontains=query) |
            Q(category__icontains=query) |
            Q(brand__icontains=query)
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

    if request.method == 'POST':
        if 'update_reserved_stock_submit' in request.POST:
            is_async_request = request.headers.get('X-Botgi-Async') == '1'
            reload_url = request.get_full_path()
            product = Product.objects.filter(pk=request.POST.get('product_id')).first()
            if not product:
                if is_async_request:
                    return JsonResponse({'ok': False, 'message': 'Selected product was not found.'}, status=404)
                messages.error(request, 'Selected product was not found.')
                return redirect(redirect_target)

            try:
                reserved_stock = int((request.POST.get('reserved_stock') or '0').strip() or '0')
            except (TypeError, ValueError):
                if is_async_request:
                    return JsonResponse({'ok': False, 'message': 'Reserved stock must be a whole number.'}, status=400)
                messages.error(request, 'Reserved stock must be a whole number.')
                return redirect(redirect_target)

            if reserved_stock < 0:
                if is_async_request:
                    return JsonResponse({'ok': False, 'message': 'Reserved stock cannot be negative.'}, status=400)
                messages.error(request, 'Reserved stock cannot be negative.')
                return redirect(redirect_target)

            if product.reserved_stock != reserved_stock:
                product.reserved_stock = reserved_stock
                product.save(update_fields=['reserved_stock', 'updated_at'])
                if is_async_request:
                    return JsonResponse(
                        {
                            'ok': True,
                            'message': f"Reserved stock updated for '{product.name}'.",
                            'reload_url': reload_url,
                        }
                    )
                messages.success(request, f"Reserved stock updated for '{product.name}'.")
            else:
                if is_async_request:
                    return JsonResponse(
                        {
                            'ok': True,
                            'message': f"No reserved stock change for '{product.name}'.",
                            'reload_url': reload_url,
                        }
                    )
                messages.info(request, f"No reserved stock change for '{product.name}'.")
            return redirect(redirect_target)

        if 'add_product_submit' in request.POST:
            product_form = ProductForm(request.POST)
            if product_form.is_valid():
                try:
                    gst_rate = CompanyProfile.get_profile().gst_rate or Decimal('0.00')
                except Exception:
                    gst_rate = Decimal('0.00')

                def _normalize_tax_mode_price(raw_price, price_mode):
                    price = raw_price or Decimal('0.00')
                    if price_mode == 'with_tax' and gst_rate > 0:
                        divisor = Decimal('100.00') + gst_rate
                        if divisor > 0:
                            price = (price * Decimal('100.00')) / divisor
                    return price.quantize(Decimal('0.01'))

                product = product_form.save(commit=False)
                product.cost_price = _normalize_tax_mode_price(
                    product_form.cleaned_data.get('cost_price'),
                    product_form.cleaned_data.get('purchase_price_tax_mode'),
                )
                product.unit_price = _normalize_tax_mode_price(
                    product_form.cleaned_data.get('unit_price'),
                    product_form.cleaned_data.get('sales_price_tax_mode'),
                )
                product.save()
                messages.success(request, f"Product '{product.name}' added successfully.")
                return redirect(redirect_target)
            messages.error(request, "Please fix the errors and try again.")
        else:
            product_form = ProductForm()
    else:
        product_form = ProductForm()

    out_of_stock_count = Product.objects.filter(stock_quantity=0).count()
    reserved_alert_count = Product.objects.filter(
        reserved_stock__gt=0,
        stock_quantity__lte=F('reserved_stock'),
    ).count()
    context = {
        'products': product_rows,
        'product_form': product_form,
        'query': query,
        'total_products': Product.objects.count(),
        'reserved_alert_count': reserved_alert_count,
        'out_of_stock_count': out_of_stock_count,
        'from_inventory': current_url_name == 'inventory_product_dashboard',
    }
    return render(request, 'job_tickets/product_dashboard.html', context)


@login_required
def vendor_dashboard(request):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    
    if request.method == 'POST' and 'add_vendor_submit' in request.POST:
        vendor_form = VendorForm(request.POST)
        if vendor_form.is_valid():
            vendor_form.save()
            messages.success(request, f"Vendor '{vendor_form.cleaned_data['company_name']}' added successfully.")
            return redirect('vendor_dashboard')
        else:
            messages.error(request, "Error adding vendor. Please check inputs.")
            # Fall through to GET context to display the form with errors

    else:
        vendor_form = VendorForm() # For GET request or error display

    # Get all vendors and annotate them with the count of jobs currently with them
    vendors = Vendor.objects.annotate(
        active_jobs_count=Count('services', filter=Q(services__status='Sent to Vendor'))
    ).order_by('company_name')

    # Get all jobs that are currently with any vendor, ordered for easy grouping in the template
    active_services = SpecializedService.objects.filter(status='Sent to Vendor').select_related('job_ticket', 'vendor').order_by('vendor__company_name', 'sent_date')

    context = {
        'vendors': vendors,
        'vendor_form': vendor_form,
        'active_services_by_vendor': active_services,
    }
    return render(request, 'job_tickets/vendor_dashboard.html', context)


@login_required
@require_POST
def edit_vendor(request, vendor_id):
    """Edit an existing vendor."""
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    
    vendor = get_object_or_404(Vendor, id=vendor_id)
    
    # Update vendor fields
    vendor.company_name = request.POST.get('company_name', vendor.company_name)
    vendor.name = request.POST.get('name', vendor.name)
    vendor.phone = request.POST.get('phone', vendor.phone)
    vendor.email = request.POST.get('email', vendor.email)
    vendor.address = request.POST.get('address', vendor.address)
    vendor.specialties = request.POST.get('specialties', vendor.specialties)
    
    try:
        vendor.save()
        messages.success(request, f"Vendor '{vendor.company_name}' updated successfully.")
    except Exception as e:
        messages.error(request, f"Error updating vendor: {str(e)}")
    
    return redirect('vendor_dashboard')


@login_required
@require_POST
def delete_vendor(request, vendor_id):
    """Delete a vendor (only if no active services)."""
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    
    vendor = get_object_or_404(Vendor, id=vendor_id)
    
    # Check if vendor has any active services
    active_services = SpecializedService.objects.filter(vendor=vendor, status='Sent to Vendor').count()
    
    if active_services > 0:
        messages.error(request, f"Cannot delete vendor '{vendor.company_name}' because they have {active_services} active job(s). Please mark those jobs as returned first.")
        return redirect('vendor_dashboard')
    
    vendor_name = vendor.company_name
    vendor.delete()
    messages.success(request, f"Vendor '{vendor_name}' deleted successfully.")
    
    return redirect('vendor_dashboard')

@login_required
def vendor_report_detail(request, vendor_id):
    denied = _staff_access_required(request, "reports_vendor")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')

    vendor = get_object_or_404(Vendor, id=vendor_id)
    
    # Get date filters from URL parameters
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    # Start with all services for this vendor
    services = SpecializedService.objects.filter(vendor=vendor).select_related('job_ticket')
    
    # Apply date filtering using vendor concept
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            start_of_period = timezone.make_aware(datetime(start_date.year, start_date.month, start_date.day))
            end_of_period = timezone.make_aware(datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59))
            
            # Filter using vendor concept: only jobs returned in the period
            services = services.filter(
                returned_date__gte=start_of_period,
                returned_date__lte=end_of_period
            )
        except ValueError:
            # If date parsing fails, show all services
            pass
    
    services = services.order_by('-sent_date')

    # Calculate financial totals
    totals = services.aggregate(
        total_cost=Coalesce(Sum('vendor_cost', output_field=DecimalField()), Decimal('0')),
        total_charge=Coalesce(Sum('client_charge', output_field=DecimalField()), Decimal('0'))
    )
    
    profit = totals['total_charge'] - totals['total_cost']

    context = {
        'vendor': vendor,
        'services': services,
        'total_jobs': services.count(),
        'total_vendor_cost': totals['total_cost'],
        'total_client_charge': totals['total_charge'],
        'total_profit': profit,
        'start_date': start_date_str,
        'end_date': end_date_str,
    }
    return render(request, 'job_tickets/vendor_report_detail.html', context)


@login_required
def print_active_workload_report(request):
    access = get_staff_access(request.user)
    if not request.user.is_staff or not access.get("reports_overview"):
        return redirect('unauthorized')
    
    # Define statuses that represent active work (In-Progress)
    active_statuses = ['Under Inspection', 'Repairing', 'Specialized Service', 'Returned']
    
    # 1. Fetch active jobs, excluding those that are ready for pickup or closed
    active_jobs_qs = JobTicket.objects.filter(
        status__in=active_statuses
    ).select_related('assigned_to__user').order_by('assigned_to__user__username', 'job_code')

    # 2. Group the jobs by Technician for clear reporting
    grouped_jobs = {}
    
    for job in active_jobs_qs:
        technician_name = job.assigned_to.user.username if job.assigned_to and job.assigned_to.user else "UNASSIGNED"
        
        if technician_name not in grouped_jobs:
            grouped_jobs[technician_name] = []
            
        grouped_jobs[technician_name].append(job)

    # 3. Prepare the final context
    company = CompanyProfile.get_profile()
    context = {
        'grouped_jobs': grouped_jobs,
        'report_date': datetime.now(),
        'company': company,
    }
    return render(request, 'job_tickets/print_active_workload_report.html', context)

def get_company_start_date():
    """Finds the creation date of the very first job ticket."""
    first_job = JobTicket.objects.order_by('created_at').first()
    return first_job.created_at.date() if first_job else timezone.localdate()


@login_required
@require_POST
def technician_delete_service_log(request, log_id):
    """Allow assigned technician to delete a service log row (with checks)."""
    # Find the service log and related job
    log = get_object_or_404(ServiceLog, id=log_id)
    job = log.job_ticket

    # Verify requester is the assigned technician
    tech = TechnicianProfile.objects.filter(user=request.user).first()
    if not tech or job.assigned_to != tech:
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    # Prevent deletion if job is billed/finalized
    if job.status in ['Ready for Pickup', 'Completed', 'Closed'] or job.vyapar_invoice_number:
        return JsonResponse({'ok': False, 'error': 'editing_not_allowed', 'message': 'Cannot delete logs after billing or completion.'}, status=403)

    # Delete and log
    details = f"Service log deleted: '{log.description}' (Part: {log.part_cost}, Service: {log.service_charge})"
    log.delete()
    JobTicketLog.objects.create(job_ticket=job, user=request.user, action='SERVICE', details=details)
    return JsonResponse({'ok': True, 'message': 'Service log deleted.'})

# job_tickets/views.py (Add this function)

@login_required
@require_POST
def job_reassign_staff(request, job_code):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    
    job = get_object_or_404(JobTicket, job_code=job_code)
    
    form = ReassignTechnicianForm(request.POST)
    # Note: We must validate the job_code field that is passed implicitly here, but trust the primary key validation
    
    if form.is_valid():
        new_technician = form.cleaned_data['new_technician']
        
        # Get old values for logging
        old_technician_name = job.assigned_to.user.username if job.assigned_to else "Unassigned"
        new_technician_name = new_technician.user.username if new_technician else "Unassigned"
        
        # Prevent assigning to the same person
        if job.assigned_to == new_technician:
            messages.warning(request, f"Job {job_code} is already assigned to {old_technician_name}.")
            return redirect('staff_job_detail', job_code=job_code)
            
        # Update the job and mark as new assignment for the technician
        job.assigned_to = new_technician
        job.is_new_assignment = True
        job.save(update_fields=['assigned_to', 'is_new_assignment', 'updated_at'])
        
        # Log the action
        details = f"Reassigned from '{old_technician_name}' to '{new_technician_name}' by staff."
        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='ASSIGNED', details=details)
        
        # Send WebSocket update (job assignment change may affect status display)
        send_job_update_message(job.job_code, job.status)
        
        messages.success(request, f"Job {job_code} successfully reassigned to {new_technician_name}.")
        return redirect('staff_job_detail', job_code=job_code)
    
    messages.error(request, "Invalid reassignment attempt.")
    return redirect('staff_job_detail', job_code=job_code)


@login_required
def technician_acknowledge_assignment(request, job_code):
    """Technician acknowledges a newly assigned job (clears is_new_assignment)."""
    # Ensure the user is a technician
    tech = TechnicianProfile.objects.filter(user=request.user).first()
    if not tech:
        return redirect('unauthorized')

    job = get_object_or_404(JobTicket, job_code=job_code)
    
    if request.method == 'POST':
        # Ensure the user is the assigned technician
        if job.assigned_to != tech:
            messages.error(request, "You are not assigned to this job.")
            return redirect('technician_dashboard') # Or return HttpResponseForbidden

        job.is_new_assignment = False
        job.save(update_fields=['is_new_assignment', 'updated_at'])

        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='ACKNOWLEDGED', details=f"Job {job.job_code} acknowledged by technician.")
        
        # Send WebSocket update
        send_job_update_message(job.job_code, job.status)

        # Re-fetch job with prefetched service_logs for rendering
        job = JobTicket.objects.filter(pk=job.pk).prefetch_related('service_logs').first()
        calculate_job_totals([job]) # Recalculate totals for the single job

        # Return JSON for AJAX requests, HTML for HTMX
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'ok': True,
                'message': 'Job acknowledged successfully.',
                'job_code': job.job_code,
            })
        
        # Render the updated job row HTML fragment for HTMX
        context = {'job': job, 'request': request} # Pass request to context for {% url %} and user checks
        updated_row_html = render_to_string('job_tickets/_job_row.html', context, request=request)
        return HttpResponse(updated_row_html)

    # For GET requests, or if not POST, redirect to dashboard
    return redirect('technician_dashboard')


@login_required
def technician_return_to_staff(request, job_code):
    """Technician returns the job to staff (unassigns and marks Pending)."""
    tech = TechnicianProfile.objects.filter(user=request.user).first()
    if not tech:
        return redirect('unauthorized')

    job = get_object_or_404(JobTicket, job_code=job_code)
    
    if request.method == 'POST': # Ensure this logic only runs for POST requests
        if job.assigned_to != tech:
            messages.error(request, "You are not assigned to this job.")
            return redirect('technician_dashboard') # Or return HttpResponseForbidden

        old_status = job.get_status_display()
        job.assigned_to = None
        job.status = 'Pending'
        job.is_new_assignment = False
        job.save(update_fields=['assigned_to', 'status', 'is_new_assignment', 'updated_at'])
        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='ASSIGNED', details=f"Technician returned job to staff. Previous status: {old_status}")
        
        # Send WebSocket update
        send_job_update_message(job.job_code, job.status)
        
        # messages.success(request, f"Job {job.job_code} returned to staff for reassignment.") # Messages won't show with htmx swap

        # Re-fetch job with prefetched service_logs for rendering
        job = JobTicket.objects.filter(pk=job.pk).prefetch_related('service_logs').first()
        calculate_job_totals([job]) # Recalculate totals for the single job

        # Return success response for AJAX
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'ok': True,
                'message': f'Job {job.job_code} returned to staff for reassignment.',
                'redirect': True
            })
        
        messages.success(request, f'Job {job.job_code} returned to staff for reassignment.')
        return redirect('technician_dashboard')

    # For GET requests, or if not POST, redirect to dashboard
    return redirect('technician_dashboard')


@login_required
def staff_job_archive_view(request):
    access = get_staff_access(request.user)
    if not request.user.is_staff or not access.get("reports_overview"):
        return redirect('unauthorized')

    # Get URL parameters for filtering
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    # Start with a queryset of ALL jobs, ordered by latest first
    jobs_queryset = JobTicket.objects.all().order_by('-created_at')

    # --- Date Filtering Logic ---
    start_date = None
    end_date = None
    
    if start_date_str and end_date_str:
        try:
            # 1. Parse Dates
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            # 2. Create Timezone-Aware Boundaries for Query
            start_of_period = timezone.make_aware(datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0))
            end_of_period = timezone.make_aware(datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59))
            
            # 3. Apply Filter to Queryset (Filtering by Created Date)
            jobs_queryset = jobs_queryset.filter(
                created_at__gte=start_of_period,
                created_at__lte=end_of_period
            )
            
        except ValueError:
            messages.error(request, "Invalid date format provided for filtering.")
            # Keep jobs_queryset unfiltered on error
    
    # --- Context Setup ---
    context = {
        'jobs': jobs_queryset,
        'current_start_date': start_date_str,
        'current_end_date': end_date_str,
        'today_date_str': timezone.localdate().strftime('%Y-%m-%d'),
        # Assuming you have a helper for company start date:
        'company_start_date': get_company_start_date().strftime('%Y-%m-%d'), 
    }
    return render(request, 'job_tickets/staff_job_archive.html', context)


@login_required
def staff_technicians(request):
    denied = _staff_access_required(request, "team_management")
    if denied:
        return denied
    
    # Ensure groups exist
    technicians_group, _ = Group.objects.get_or_create(name='Technicians')
    staff_group, _ = Group.objects.get_or_create(name='Staff')
    tech_form = TechnicianCreationForm(request.POST or None)
    access_keys = {option['key'] for option in ACCESS_OPTIONS}
    staff_access_options = [option for option in ACCESS_OPTIONS if option.get('section') == 'general']
    staff_report_access_options = [option for option in ACCESS_OPTIONS if option.get('section') == 'reports']
    selected_access_keys = set()

    if request.method == 'POST':
        # Handle user creation
        if 'add_technician_submit' in request.POST:
            selected_access_keys = parse_access_keys(request.POST)
            if tech_form.is_valid():
                user = tech_form.save(commit=False)
                role = tech_form.cleaned_data['role']
                unique_id = (tech_form.cleaned_data.get('unique_id') or '').strip()

                if role == 'technician' and not unique_id:
                    tech_form.add_error('unique_id', 'Unique ID is required for technicians.')
                else:
                    user.save()
                    if role == 'technician':
                        TechnicianProfile.objects.update_or_create(
                            user=user,
                            defaults={'unique_id': unique_id}
                        )
                        user.groups.add(technicians_group)
                        user.groups.remove(staff_group)
                        user.is_staff = False
                        user.save(update_fields=['is_staff'])
                        messages.success(request, 'Technician created successfully.')
                    else:
                        user.groups.add(staff_group)
                        user.groups.remove(technicians_group)
                        user.is_staff = True
                        user.save(update_fields=['is_staff'])
                        apply_staff_access(user, selected_access_keys)
                        messages.success(request, 'Staff member created successfully.')
                    return redirect('staff_technicians')

        # Handle user toggle (enable/disable)
        if 'toggle_technician' in request.POST:
            user_id = request.POST.get('toggle_technician')
            managed_user = User.objects.filter(id=user_id).first()
            if not managed_user:
                messages.error(request, 'User not found.')
                return redirect('staff_technicians')
            if managed_user.is_superuser:
                messages.error(request, 'Superuser status cannot be changed here.')
                return redirect('staff_technicians')
            if managed_user.id == request.user.id and managed_user.is_active:
                messages.error(request, 'You cannot disable your own account.')
                return redirect('staff_technicians')

            managed_user.is_active = not managed_user.is_active
            managed_user.save(update_fields=['is_active'])
            action = 'enabled' if managed_user.is_active else 'disabled'
            messages.success(request, f'User {managed_user.username} {action} successfully.')
            return redirect('staff_technicians')

    latest_session_activity = UserSessionActivity.objects.filter(user=OuterRef('pk')).order_by('-login_at')
    managed_users = (
        User.objects.filter(
            Q(groups__name='Technicians') | Q(groups__name='Staff') | Q(is_staff=True)
        )
        .exclude(is_superuser=True)
        .distinct()
        .order_by('username')
        .prefetch_related('groups')
        .select_related('technician_profile')
        .annotate(
            latest_session_login_at=Subquery(latest_session_activity.values('login_at')[:1]),
            latest_session_last_activity_at=Subquery(latest_session_activity.values('last_activity_at')[:1]),
            latest_session_status=Subquery(latest_session_activity.values('status')[:1]),
            latest_session_ip=Subquery(latest_session_activity.values('ip_address')[:1]),
            latest_session_user_agent=Subquery(latest_session_activity.values('user_agent')[:1]),
            active_session_count=Count(
                'session_activities',
                filter=Q(
                    session_activities__status=UserSessionActivity.STATUS_ACTIVE,
                    session_activities__expires_at__gt=timezone.now(),
                ),
                distinct=True,
            ),
        )
    )

    for managed_user in managed_users:
        try:
            profile = managed_user.technician_profile
        except TechnicianProfile.DoesNotExist:
            profile = None
        managed_user.display_unique_id = profile.unique_id if profile else ''
        managed_access = get_staff_access(managed_user, group_names=[g.name for g in managed_user.groups.all()])
        managed_user.staff_access_keys = {
            key for key in access_keys if managed_access.get(key)
        }
        managed_user.latest_session_device = _summarize_user_agent(getattr(managed_user, 'latest_session_user_agent', ''))

    context = {
        'tech_form': tech_form,
        'managed_users': managed_users,
        'staff_access_options': staff_access_options,
        'staff_report_access_options': staff_report_access_options,
        'selected_access_keys': selected_access_keys,
    }
    return render(request, 'job_tickets/staff_technicians.html', context)


@login_required
@require_POST
def edit_user(request, user_id):
    """Edit an existing user."""
    denied = _staff_access_required(request, "team_management")
    if denied:
        return denied
    
    user = User.objects.filter(id=user_id).first()
    if not user:
        messages.error(request, 'User not found.')
        return redirect('staff_technicians')
    if user.is_superuser and not request.user.is_superuser:
        messages.error(request, 'Superuser cannot be modified from this page.')
        return redirect('staff_technicians')
    
    # Update user fields
    new_username = request.POST.get('username', '').strip()
    if new_username and new_username != user.username:
        # Check if username is already taken
        if User.objects.filter(username=new_username).exclude(id=user.id).exists():
            messages.error(request, f'Username "{new_username}" is already taken.')
            return redirect('staff_technicians')
        user.username = new_username
    
    user.email = (request.POST.get('email', user.email) or '').strip()

    unique_id = (request.POST.get('unique_id', '') or '').strip()
    new_role = request.POST.get('role', 'technician')
    selected_access_keys = parse_access_keys(request.POST)
    technicians_group, _ = Group.objects.get_or_create(name='Technicians')
    staff_group, _ = Group.objects.get_or_create(name='Staff')
    
    if new_role == 'staff':
        if user.id == request.user.id and not request.user.is_superuser:
            user.is_staff = True
        user.groups.remove(technicians_group)
        user.groups.add(staff_group)
        user.is_staff = True
        if unique_id and hasattr(user, 'technician_profile'):
            conflict = TechnicianProfile.objects.filter(unique_id=unique_id).exclude(user=user).exists()
            if conflict:
                messages.error(request, f'Unique ID "{unique_id}" is already assigned to another user.')
                return redirect('staff_technicians')
            user.technician_profile.unique_id = unique_id
            user.technician_profile.save(update_fields=['unique_id'])
        apply_staff_access(user, selected_access_keys)
    else:  # technician
        if user.id == request.user.id:
            messages.error(request, 'You cannot change your own role to Technician.')
            return redirect('staff_technicians')
        if not unique_id:
            messages.error(request, 'Unique ID is required for technicians.')
            return redirect('staff_technicians')
        conflict = TechnicianProfile.objects.filter(unique_id=unique_id).exclude(user=user).exists()
        if conflict:
            messages.error(request, f'Unique ID "{unique_id}" is already assigned to another user.')
            return redirect('staff_technicians')
        TechnicianProfile.objects.update_or_create(
            user=user,
            defaults={'unique_id': unique_id}
        )
        user.groups.remove(staff_group)
        user.groups.add(technicians_group)
        user.is_staff = False
        clear_staff_access(user)
    
    user.save()
    
    messages.success(request, f'User "{user.username}" updated successfully.')
    return redirect('staff_technicians')


@login_required
@require_POST
def delete_user(request, user_id):
    """Delete a user."""
    denied = _staff_access_required(request, "team_management")
    if denied:
        return denied
    
    user = User.objects.filter(id=user_id).first()
    if not user:
        messages.error(request, 'User not found.')
        return redirect('staff_technicians')
    if user.is_superuser:
        messages.error(request, 'Superuser cannot be deleted from this page.')
        return redirect('staff_technicians')
    if user.id == request.user.id:
        messages.error(request, 'You cannot delete your own account.')
        return redirect('staff_technicians')

    username = user.username
    try:
        user.delete()
        messages.success(request, f'User "{username}" deleted successfully.')
    except Exception as e:
        messages.error(request, f'Error deleting user: {str(e)}')
    
    return redirect('staff_technicians')


@login_required
@require_POST
def change_user_password(request, user_id):
    """Change password for staff/technician user from team management page."""
    denied = _staff_access_required(request, "team_management")
    if denied:
        return denied

    user = User.objects.filter(id=user_id).first()
    if not user:
        messages.error(request, 'User not found.')
        return redirect('staff_technicians')
    if user.is_superuser and not request.user.is_superuser:
        messages.error(request, 'Superuser password cannot be changed from this page.')
        return redirect('staff_technicians')

    new_password = (request.POST.get('new_password') or '').strip()
    confirm_password = (request.POST.get('confirm_password') or '').strip()

    if not new_password or not confirm_password:
        messages.error(request, 'Both password fields are required.')
        return redirect('staff_technicians')
    if new_password != confirm_password:
        messages.error(request, 'Password and confirm password do not match.')
        return redirect('staff_technicians')

    try:
        validate_password(new_password, user=user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect('staff_technicians')

    user.set_password(new_password)
    user.save(update_fields=['password'])

    if request.user.id == user.id:
        update_session_auth_hash(request, user)

    messages.success(request, f'Password updated successfully for "{user.username}".')
    return redirect('staff_technicians')

@login_required
def daily_jobs_report(request, date_str, filter_type):
    access = get_staff_access(request.user)
    if not request.user.is_staff or not access.get("reports_overview"):
        return redirect('unauthorized')

    try:
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        messages.error(request, "Invalid date format provided.")
        return redirect('reports_dashboard')

    start_of_day = timezone.make_aware(datetime.combine(report_date, datetime.min.time()))
    end_of_day = timezone.make_aware(datetime.combine(report_date, datetime.max.time()))

    jobs_queryset = JobTicket.objects.all().order_by('-created_at')
    report_title = f"Jobs Report for {report_date.strftime('%B %d, %Y')}"

    if filter_type == 'in':
        jobs_queryset = jobs_queryset.filter(created_at__range=(start_of_day, end_of_day))
        report_title = f"Jobs Created On {date_str}"
    elif filter_type == 'out':
        jobs_queryset = jobs_queryset.filter(
            status='Closed',
            updated_at__range=(start_of_day, end_of_day)
        )
        report_title = f"Jobs Closed On {date_str}"
    elif filter_type == 'completed':
        jobs_queryset = jobs_queryset.filter(
            status='Completed',
            updated_at__range=(start_of_day, end_of_day)
        )
        report_title = f"Jobs Completed On {date_str}"
    else:
        messages.error(request, "Invalid filter type provided.")
        return redirect('reports_dashboard')

    context = {
        'jobs': jobs_queryset,
        'report_title': report_title,
    }
    return render(request, 'job_tickets/daily_jobs_report.html', context)

def custom_404(request, exception):
    """Custom 404 error page"""
    return render(request, '404.html', status=404)

def custom_500(request):
    """Custom 500 error page"""
    return render(request, '500.html', status=500)

@login_required
def feedback_analytics(request):
    """Feedback analytics dashboard for staff"""
    denied = _staff_access_required(request, "feedback_analytics")
    if denied:
        return denied

    start_date = (request.GET.get('start_date') or '').strip()
    end_date = (request.GET.get('end_date') or '').strip()
    selected_rating_raw = (request.GET.get('rating') or '').strip()
    selected_technician_raw = (request.GET.get('technician') or '').strip()

    jobs_with_feedback = JobTicket.objects.filter(
        feedback_rating__isnull=False
    ).select_related('assigned_to__user').order_by('-feedback_date')

    if start_date:
        try:
            parsed_start = datetime.strptime(start_date, '%Y-%m-%d').date()
            jobs_with_feedback = jobs_with_feedback.filter(feedback_date__date__gte=parsed_start)
        except ValueError:
            start_date = ''
            messages.error(request, 'Invalid start date.')

    if end_date:
        try:
            parsed_end = datetime.strptime(end_date, '%Y-%m-%d').date()
            jobs_with_feedback = jobs_with_feedback.filter(feedback_date__date__lte=parsed_end)
        except ValueError:
            end_date = ''
            messages.error(request, 'Invalid end date.')

    selected_rating = None
    if selected_rating_raw:
        try:
            parsed_rating = int(selected_rating_raw)
            if 1 <= parsed_rating <= 10:
                selected_rating = parsed_rating
        except ValueError:
            selected_rating = None

    selected_technician = None
    if selected_technician_raw:
        try:
            selected_technician = TechnicianProfile.objects.select_related('user').filter(
                pk=int(selected_technician_raw)
            ).first()
        except ValueError:
            selected_technician = None

    total_feedback = jobs_with_feedback.count()
    if total_feedback > 0:
        avg_rating = sum(j.feedback_rating for j in jobs_with_feedback) / total_feedback
        rating_distribution = []
        for i in range(1, 11):
            count = jobs_with_feedback.filter(feedback_rating=i).count()
            percentage = (count * 100 / total_feedback) if total_feedback > 0 else 0
            query_params = {}
            if start_date:
                query_params['start_date'] = start_date
            if end_date:
                query_params['end_date'] = end_date
            query_params['rating'] = i
            rating_distribution.append({
                'rating': i,
                'count': count,
                'percentage': round(percentage, 1),
                'is_active': selected_rating == i,
                'filter_url': f"{reverse('feedback_analytics')}?{urlencode(query_params)}",
            })
    else:
        avg_rating = 0
        rating_distribution = []
        for i in range(1, 11):
            query_params = {}
            if start_date:
                query_params['start_date'] = start_date
            if end_date:
                query_params['end_date'] = end_date
            query_params['rating'] = i
            rating_distribution.append({
                'rating': i,
                'count': 0,
                'percentage': 0,
                'is_active': selected_rating == i,
                'filter_url': f"{reverse('feedback_analytics')}?{urlencode(query_params)}",
            })

    tech_feedback = {}
    for tech in TechnicianProfile.objects.all().select_related('user'):
        tech_jobs = jobs_with_feedback.filter(assigned_to=tech)
        if tech_jobs.exists():
            tech_avg = sum(j.feedback_rating for j in tech_jobs) / tech_jobs.count()
            tech_query_params = {}
            if start_date:
                tech_query_params['start_date'] = start_date
            if end_date:
                tech_query_params['end_date'] = end_date
            if selected_rating is not None:
                tech_query_params['rating'] = selected_rating
            tech_query_params['technician'] = tech.pk
            tech_feedback[tech] = {
                'count': tech_jobs.count(),
                'avg_rating': round(tech_avg, 2),
                'percentage': round(tech_avg * 10, 1),  # Convert 10-point to 100%
                'jobs': list(tech_jobs[:5]),
                'filter_url': f"{reverse('feedback_analytics')}?{urlencode(tech_query_params)}",
                'is_active': bool(selected_technician and selected_technician.pk == tech.pk),
            }

    filtered_feedback = jobs_with_feedback
    if selected_rating is not None:
        filtered_feedback = filtered_feedback.filter(feedback_rating=selected_rating)
    if selected_technician is not None:
        filtered_feedback = filtered_feedback.filter(assigned_to=selected_technician)

    clear_rating_url = reverse('feedback_analytics')
    clear_rating_params = {}
    if start_date:
        clear_rating_params['start_date'] = start_date
    if end_date:
        clear_rating_params['end_date'] = end_date
    if selected_technician is not None:
        clear_rating_params['technician'] = selected_technician.pk
    if clear_rating_params:
        clear_rating_url = f"{clear_rating_url}?{urlencode(clear_rating_params)}"

    clear_technician_url = reverse('feedback_analytics')
    clear_technician_params = {}
    if start_date:
        clear_technician_params['start_date'] = start_date
    if end_date:
        clear_technician_params['end_date'] = end_date
    if selected_rating is not None:
        clear_technician_params['rating'] = selected_rating
    if clear_technician_params:
        clear_technician_url = f"{clear_technician_url}?{urlencode(clear_technician_params)}"

    context = {
        'total_feedback': total_feedback,
        'avg_rating': round(avg_rating, 2),
        'rating_distribution': rating_distribution,
        'tech_feedback': tech_feedback,
        'recent_feedback': list(filtered_feedback),
        'filtered_feedback_count': filtered_feedback.count(),
        'selected_rating': selected_rating,
        'selected_technician': selected_technician,
        'start_date': start_date,
        'end_date': end_date,
        'clear_rating_url': clear_rating_url,
        'clear_technician_url': clear_technician_url,
    }
    return render(request, 'job_tickets/feedback_analytics.html', context)

@login_required
def company_profile_settings(request):
    """Manage client company profile settings."""
    denied = _staff_access_required(request, "company_settings")
    if denied:
        return denied
    
    profile = CompanyProfile.get_profile()
    whatsapp_settings = WhatsAppIntegrationSettings.get_settings()
    
    if request.method == 'POST':
        active_tab = (request.POST.get('active_tab') or '#company-info').strip() or '#company-info'
        tab_query = active_tab.lstrip('#') or 'company-info'

        if 'whatsapp_settings_submit' in request.POST:
            form = CompanyProfileForm(instance=profile)
            whatsapp_form = WhatsAppIntegrationSettingsForm(request.POST, instance=whatsapp_settings)
            if whatsapp_form.is_valid():
                whatsapp_form.save()
                messages.success(request, 'WhatsApp integration settings updated successfully.')
                return redirect(f"{reverse('company_profile_settings')}?tab=whatsapp-integration")
            messages.error(request, 'Please fix WhatsApp settings errors and try again.')
        else:
            form = CompanyProfileForm(request.POST, instance=profile)
            whatsapp_form = WhatsAppIntegrationSettingsForm(instance=whatsapp_settings)
            if form.is_valid():
                form.save()
                messages.success(request, 'Profile updated successfully!')
                return redirect(f"{reverse('company_profile_settings')}?tab={tab_query}")
    else:
        form = CompanyProfileForm(instance=profile)
        whatsapp_form = WhatsAppIntegrationSettingsForm(instance=whatsapp_settings)
    
    requested_tab = (request.GET.get('tab') or '').strip()
    initial_tab = f"#{requested_tab}" if requested_tab else '#company-info'

    context = {
        'form': form,
        'profile': profile,
        'whatsapp_form': whatsapp_form,
        'initial_tab': initial_tab,
    }
    return render(request, 'job_tickets/company_profile_settings.html', context)



def staff_job_filtered_archive_view(request, status_code):
    access = get_staff_access(request.user)
    if not request.user.is_staff or not access.get("reports_overview"):
        return redirect('unauthorized')

    # Get optional date filters
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    status_filter = request.GET.get('status_filter')  # New: sub-status filter for returned jobs
    
    # Start with a queryset of ALL jobs, ordered by latest first
    jobs_queryset = JobTicket.objects.all().order_by('-created_at')
    
    # --- Status Filtering Logic ---
    report_title = "Filtered Job Archive"

    # Define Q object for filtering
    q_status_filter = Q()
    
    # Standard statuses for display clarity
    if status_code == 'Pending':
        q_status_filter = Q(status='Pending')
        report_title = "Pending Jobs Archive"
    elif status_code == 'Active':
        q_status_filter = Q(status__in=['Under Inspection', 'Repairing', 'Specialized Service'])
        report_title = "Active Workload Archive"
    elif status_code == 'CompletedReady':
        q_status_filter = Q(status__in=['Completed', 'Ready for Pickup'])
        report_title = "Completed/Ready Jobs Archive"
    elif status_code == 'Returned':
        # Enhanced filtering for returned jobs using job logs to track history
        # Get all jobs that have been marked as 'Returned' at some point
        returned_job_ids = JobTicketLog.objects.filter(
            action='STATUS',
            details__icontains="'Returned'"
        ).values_list('job_ticket_id', flat=True).distinct()
        
        if status_filter == 'closed':
            # Jobs that were returned and are now closed
            q_status_filter = Q(id__in=returned_job_ids, status='Closed')
            report_title = "Returned Jobs - Closed"
        elif status_filter == 'returned':
            # Jobs that are currently in returned status
            q_status_filter = Q(status='Returned')
            report_title = "Returned Jobs - Still Returned"
        else:
            # Show all jobs that have been returned at some point
            q_status_filter = Q(id__in=returned_job_ids)
            report_title = "Jobs Returned (Non-Repairable/Rework)"
    elif status_code == 'Closed':
        q_status_filter = Q(status='Closed')
        report_title = "Closed Jobs Archive"
    
    jobs_queryset = jobs_queryset.filter(q_status_filter)

    # --- Date Filtering Logic (Copied from staff_job_archive_view) ---
    start_date = None
    end_date = None
    
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            start_of_period = timezone.make_aware(datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0))
            end_of_period = timezone.make_aware(datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59))
            
            # Apply Filter by Created Date
            jobs_queryset = jobs_queryset.filter(
                created_at__gte=start_of_period,
                created_at__lte=end_of_period
            )
            
        except ValueError:
            messages.error(request, "Invalid date format provided for filtering.")

        # Fetch job objects (including prefetched service_logs) to calculate totals per job
    jobs_list = list(jobs_queryset) 
    
    # Reuse the helper function to calculate individual job totals (part_total, service_total, total)
    calculate_job_totals(jobs_list) 
    
    # Calculate the grand total and grand discount from the list
    total_amount_sum = sum(job.total for job in jobs_list)
    total_discount_sum = sum(job.discount_amount for job in jobs_list)
    
    # Grand Total (Subtotal - Discount)
    grand_total_amount = total_amount_sum - total_discount_sum if total_amount_sum > total_discount_sum else Decimal('0.00')
    total_jobs_count = jobs_queryset.count()
    
    # Calculate counts for returned jobs filtering
    returned_count = 0
    closed_returned_count = 0
    if status_code == 'Returned':
        # Get all jobs that have been marked as 'Returned' at some point
        returned_job_ids = JobTicketLog.objects.filter(
            action='STATUS',
            details__icontains="'Returned'"
        ).values_list('job_ticket_id', flat=True).distinct()
        
        # Count jobs currently in Returned status
        returned_count = JobTicket.objects.filter(status='Returned').count()
        # Count jobs that were returned and are now closed
        closed_returned_count = JobTicket.objects.filter(
            id__in=returned_job_ids, 
            status='Closed'
        ).count()
    
    # --- Context Setup ---
    context = {
        'jobs': jobs_queryset,
        'report_title': report_title,
        'current_start_date': start_date_str,
        'current_end_date': end_date_str,
        'today_date_str': timezone.localdate().strftime('%Y-%m-%d'),
        'company_start_date': get_company_start_date().strftime('%Y-%m-%d'), 
        'status_code': status_code, # Pass code back for form actions
        'status_filter': status_filter,  # Pass current sub-status filter
        'total_jobs_count': total_jobs_count,
        'total_jobs_amount': grand_total_amount,
        'returned_count': returned_count,
        'closed_returned_count': closed_returned_count,
    }
    return render(request, 'job_tickets/closed_job_archive.html', context)
