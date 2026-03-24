import json
import logging
from typing import Any

import requests
import base64
import hashlib
import hmac
from django.conf import settings as django_settings
from django.urls import reverse
from django.utils import timezone

from .models import JobTicket, WhatsAppIntegrationSettings, WhatsAppNotificationLog

logger = logging.getLogger(__name__)

RECEIPT_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24


def _settings() -> WhatsAppIntegrationSettings:
    return WhatsAppIntegrationSettings.get_settings()


def _b64url_encode(raw_bytes: bytes) -> str:
    return base64.urlsafe_b64encode(raw_bytes).decode('utf-8').rstrip('=')


def _b64url_decode(encoded_text: str) -> bytes:
    padding = '=' * (-len(encoded_text) % 4)
    return base64.urlsafe_b64decode(f"{encoded_text}{padding}")


def _public_base_url(settings: WhatsAppIntegrationSettings) -> str:
    raw_url = (settings.public_site_url or '').strip()
    if not raw_url:
        raw_url = getattr(django_settings, 'PUBLIC_BASE_URL', '') or 'http://127.0.0.1:8000'
    if raw_url.startswith('http://') or raw_url.startswith('https://'):
        return raw_url.rstrip('/')
    return f"http://{raw_url}".rstrip('/')


def _build_status_link(settings: WhatsAppIntegrationSettings, job: JobTicket) -> str:
    base_url = _public_base_url(settings)
    if not base_url:
        return ''
    return f"{base_url}{reverse('client_status', args=[job.job_code])}"


def _build_receipt_link(settings: WhatsAppIntegrationSettings, job: JobTicket) -> str:
    base_url = _public_base_url(settings)
    if not base_url:
        return ''
    token = create_receipt_access_token(job)
    return f"{base_url}{reverse('job_creation_receipt_public', args=[job.job_code])}?token={token}&autoprint=0"


def create_receipt_access_token(job: JobTicket, issued_at=None) -> str:
    issued_ts = int((issued_at or timezone.now()).timestamp())
    payload = f"{job.job_code}:{job.customer_phone}:{issued_ts}".encode('utf-8')
    signature = hmac.new(django_settings.SECRET_KEY.encode('utf-8'), payload, hashlib.sha256).digest()
    return f"{_b64url_encode(payload)}.{_b64url_encode(signature)}"


def verify_receipt_access_token(
    job: JobTicket,
    token: str,
    max_age_seconds: int | None = RECEIPT_TOKEN_MAX_AGE_SECONDS,
) -> bool:
    if not token:
        return False
    parts = token.split('.')
    if len(parts) != 2:
        return False

    payload_b64, signature_b64 = parts
    try:
        payload = _b64url_decode(payload_b64)
    except (ValueError, TypeError):
        return False

    expected_signature = hmac.new(django_settings.SECRET_KEY.encode('utf-8'), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(_b64url_encode(expected_signature), signature_b64):
        return False

    try:
        payload_text = payload.decode('utf-8')
        job_code, phone, issued_raw = payload_text.split(':', 2)
        issued_ts = int(issued_raw)
    except (ValueError, UnicodeDecodeError):
        return False

    if job_code != job.job_code:
        return False
    if phone != job.customer_phone:
        return False

    if max_age_seconds is not None and max_age_seconds > 0:
        now_ts = int(timezone.now().timestamp())
        if now_ts - issued_ts > max_age_seconds:
            return False

    return True


def _phone_to_international(raw_phone: str, default_country_code: str) -> str:
    digits = ''.join(ch for ch in (raw_phone or '') if ch.isdigit())
    if not digits:
        return ''

    # Keep already international-like numbers (>=11 digits and starts with country prefix).
    if len(digits) >= 11:
        return digits

    if default_country_code:
        cc = ''.join(ch for ch in default_country_code if ch.isdigit())
        if cc:
            return f"{cc}{digits}"

    return digits


def _safe_bridge_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _bridge_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = _settings()
    url = _safe_bridge_url(settings.bridge_base_url, path)

    try:
        if method == 'GET':
            response = requests.get(url, timeout=8)
        else:
            response = requests.post(url, json=payload or {}, timeout=10)
    except requests.RequestException as exc:
        return {
            'ok': False,
            'status': None,
            'error': str(exc),
            'data': None,
        }

    try:
        data = response.json()
    except ValueError:
        data = {'raw': response.text}

    return {
        'ok': response.ok,
        'status': response.status_code,
        'error': '' if response.ok else str(data),
        'data': data,
    }


def get_bridge_status() -> dict[str, Any]:
    return _bridge_request('GET', '/api/session/status')


def logout_bridge_session() -> dict[str, Any]:
    return _bridge_request('POST', '/api/session/logout')


def send_bridge_message(phone_number: str, message: str) -> dict[str, Any]:
    settings = _settings()
    target = _phone_to_international(phone_number, settings.default_country_code)
    if not target:
        return {
            'ok': False,
            'status': 400,
            'error': 'Invalid target phone number.',
            'data': None,
        }

    return _bridge_request('POST', '/api/messages/send', payload={'to': target, 'message': message})


def send_bridge_document(phone_number: str, pdf_url: str, caption: str = '', filename: str = 'job-ticket.pdf') -> dict[str, Any]:
    settings = _settings()
    target = _phone_to_international(phone_number, settings.default_country_code)
    if not target:
        return {
            'ok': False,
            'status': 400,
            'error': 'Invalid target phone number.',
            'data': None,
        }

    payload = {
        'to': target,
        'pdf_url': pdf_url,
        'caption': caption or '',
        'filename': filename or 'job-ticket.pdf',
    }
    return _bridge_request('POST', '/api/messages/send-pdf', payload=payload)


def _template_for_event(settings: WhatsAppIntegrationSettings, event_type: str) -> str:
    if event_type == 'created':
        return settings.created_template
    if event_type == 'completed':
        return settings.completed_template
    return settings.delivered_template


def _render_message(template: str, job: JobTicket, extra_context: dict[str, Any] | None = None) -> str:
    context = {
        'job_code': job.job_code,
        'customer_name': job.customer_name,
        'customer_phone': job.customer_phone,
        'device_type': job.device_type,
        'device_brand': job.device_brand,
        'device_model': job.device_model,
        'reported_issue': job.reported_issue,
        'status': job.get_status_display(),
        'status_link': '',
        'updated_at': timezone.localtime(job.updated_at).strftime('%d-%m-%Y %I:%M %p'),
        'estimated_delivery': job.estimated_delivery.strftime('%d-%m-%Y') if job.estimated_delivery else '-',
    }
    if extra_context:
        context.update(extra_context)

    try:
        return template.format(**context).strip()
    except KeyError as exc:
        # Fail safely if template has unknown placeholders.
        logger.warning('WhatsApp template placeholder missing: %s', exc)
        return (
            f"Hello {job.customer_name}, your ticket {job.job_code} update:\n"
            f"Status: {job.get_status_display()}"
        )


def _should_send(settings: WhatsAppIntegrationSettings, event_type: str) -> bool:
    if not settings.is_enabled:
        return False

    if event_type == 'created':
        return settings.notify_on_created
    if event_type == 'completed':
        return settings.notify_on_completed
    if event_type == 'delivered':
        return settings.notify_on_delivered
    return False


def send_job_whatsapp_notification(job: JobTicket, event_type: str) -> dict[str, Any]:
    settings = _settings()
    if not _should_send(settings, event_type):
        return {'ok': False, 'skipped': True, 'reason': 'Event disabled or integration not enabled.'}

    status_link = _build_status_link(settings, job)
    message = _render_message(_template_for_event(settings, event_type), job, {'status_link': status_link})

    send_result = send_bridge_message(job.customer_phone, message)

    normalized_phone = _phone_to_international(job.customer_phone, settings.default_country_code)
    response_payload = send_result.get('data') if isinstance(send_result.get('data'), dict) else {'data': send_result.get('data')}

    WhatsAppNotificationLog.objects.create(
        job_ticket=job,
        event_type=event_type,
        target_phone=normalized_phone or job.customer_phone,
        message=message,
        was_successful=bool(send_result.get('ok')),
        response_text=json.dumps(response_payload, default=str)[:4000],
    )

    return send_result
