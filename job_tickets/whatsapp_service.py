import base64
import hashlib
import hmac
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests
from django.conf import settings as django_settings
from django.db import connection, transaction
from django.urls import reverse
from django.utils import timezone

from .models import JobTicket, MessageQueue, WhatsAppIntegrationSettings, WhatsAppNotificationLog

logger = logging.getLogger(__name__)

_dispatch_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='wa_dispatcher')

RECEIPT_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24
GRAPH_API_BASE_URL = 'https://graph.facebook.com'
DEFAULT_API_TIMEOUT = 15
DEFAULT_BRIDGE_TIMEOUT = 20
DEFAULT_TEMPLATE_LANGUAGE_CODE = 'en_US'
DEFAULT_GRAPH_API_VERSION = 'v23.0'
PLACEHOLDER_PATTERN = re.compile(r'{([a-zA-Z_][a-zA-Z0-9_]*)}')


def _settings() -> WhatsAppIntegrationSettings:
    return WhatsAppIntegrationSettings.get_settings()


def _b64url_encode(raw_bytes: bytes) -> str:
    return base64.urlsafe_b64encode(raw_bytes).decode('utf-8').rstrip('=')


def _b64url_decode(encoded_text: str) -> bytes:
    padding = '=' * (-len(encoded_text) % 4)
    return base64.urlsafe_b64decode(f"{encoded_text}{padding}")


def _public_base_url(settings_obj: WhatsAppIntegrationSettings) -> str:
    raw_url = (settings_obj.public_site_url or '').strip()
    if not raw_url:
        raw_url = getattr(django_settings, 'PUBLIC_BASE_URL', '') or 'http://127.0.0.1:8000'
    if raw_url.startswith('http://') or raw_url.startswith('https://'):
        return raw_url.rstrip('/')
    return f"http://{raw_url}".rstrip('/')


def _build_status_link(settings_obj: WhatsAppIntegrationSettings, job: JobTicket) -> str:
    base_url = _public_base_url(settings_obj)
    if not base_url:
        return ''
    token = create_receipt_access_token(job)
    return f"{base_url}{reverse('client_status', args=[job.job_code])}?token={token}"


def _build_receipt_link(settings_obj: WhatsAppIntegrationSettings, job: JobTicket) -> str:
    base_url = _public_base_url(settings_obj)
    if not base_url:
        return ''
    token = create_receipt_access_token(job)
    return f"{base_url}{reverse('job_creation_receipt_public', args=[job.job_code])}?token={token}&autoprint=0"


def _build_receipt_pdf_link(settings_obj: WhatsAppIntegrationSettings, job: JobTicket) -> str:
    base_url = _public_base_url(settings_obj)
    if not base_url:
        return ''
    token = create_receipt_access_token(job)
    return f"{base_url}{reverse('job_creation_receipt_pdf_public', args=[job.job_code])}?token={token}"


def _build_job_ticket_pdf_url(settings_obj: WhatsAppIntegrationSettings, job: JobTicket) -> str:
    if settings_obj.delivery_method == WhatsAppIntegrationSettings.DELIVERY_BRIDGE:
        return _build_receipt_link(settings_obj, job)
    return _build_receipt_pdf_link(settings_obj, job)


def _job_ticket_pdf_filename(job: JobTicket) -> str:
    safe_job_code = re.sub(r'[^a-zA-Z0-9_.-]+', '-', job.job_code).strip('-') or 'job-ticket'
    return f"{safe_job_code}.pdf"


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
        if issued_ts > now_ts + 60 or now_ts - issued_ts > max_age_seconds:
            return False

    return True


def _phone_to_international(raw_phone: str, default_country_code: str) -> str:
    digits = ''.join(ch for ch in (raw_phone or '') if ch.isdigit())
    if not digits or len(digits) < 7:
        return ''
    if digits.startswith('00'):
        digits = digits[2:]

    country_code = ''.join(ch for ch in (default_country_code or '') if ch.isdigit())
    # Handle domestic trunk zero (e.g. 09876543210 -> 9876543210 in India / 10-digit systems)
    if digits.startswith('0') and len(digits) == 11 and (not country_code or country_code == '91'):
        digits = digits[1:]
    elif digits.startswith('0') and len(digits) > 10:
        digits = digits.lstrip('0')

    if len(digits) >= 11:
        return digits

    if country_code:
        return f"{country_code}{digits}"
    return digits


def _graph_api_url(settings_obj: WhatsAppIntegrationSettings, path: str) -> str:
    version = (settings_obj.api_version or DEFAULT_GRAPH_API_VERSION).strip() or DEFAULT_GRAPH_API_VERSION
    return f"{GRAPH_API_BASE_URL}/{version}/{path.lstrip('/')}"


def _cloud_api_request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    settings_obj: WhatsAppIntegrationSettings | None = None,
) -> dict[str, Any]:
    settings_obj = settings_obj or _settings()
    access_token = (settings_obj.access_token or '').strip()
    if not access_token:
        return {
            'ok': False,
            'status': 400,
            'error': 'WhatsApp Cloud API access token is missing.',
            'data': None,
        }

    try:
        response = requests.request(
            method.upper(),
            _graph_api_url(settings_obj, path),
            headers={
                'Authorization': f"Bearer {access_token}",
                'Content-Type': 'application/json',
            },
            json=payload,
            params=params,
            timeout=DEFAULT_API_TIMEOUT,
        )
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

    error_message = ''
    if not response.ok:
        if isinstance(data, dict) and isinstance(data.get('error'), dict):
            error_message = data['error'].get('message') or json.dumps(data['error'], default=str)
        else:
            error_message = json.dumps(data, default=str) if data else response.text

    return {
        'ok': response.ok,
        'status': response.status_code,
        'error': error_message,
        'data': data,
    }


def _bridge_base_url(settings_obj: WhatsAppIntegrationSettings) -> str:
    raw_url = (settings_obj.bridge_base_url or '').strip()
    if not raw_url:
        return ''
    if raw_url.startswith('http://') or raw_url.startswith('https://'):
        return raw_url.rstrip('/')
    return f"http://{raw_url}".rstrip('/')


def _bridge_api_request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    settings_obj: WhatsAppIntegrationSettings | None = None,
) -> dict[str, Any]:
    settings_obj = settings_obj or _settings()
    base_url = _bridge_base_url(settings_obj)
    if not base_url:
        return {
            'ok': False,
            'status': 400,
            'error': 'WhatsApp bridge base URL is missing.',
            'data': None,
        }

    try:
        response = requests.request(
            method.upper(),
            f"{base_url}/{path.lstrip('/')}",
            json=payload,
            timeout=DEFAULT_BRIDGE_TIMEOUT,
        )
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

    payload_ok = data.get('ok') if isinstance(data, dict) else None
    ok = response.ok and payload_ok is not False
    error_message = ''
    if not ok:
        if isinstance(data, dict):
            error_message = data.get('message') or data.get('error') or json.dumps(data, default=str)
        else:
            error_message = response.text

    return {
        'ok': ok,
        'status': response.status_code,
        'error': error_message,
        'data': data,
    }


def _extract_graph_message_id(data: Any) -> str:
    if not isinstance(data, dict):
        return ''
    messages = data.get('messages')
    if isinstance(messages, list) and messages:
        first_message = messages[0] or {}
        if isinstance(first_message, dict):
            return (first_message.get('id') or '').strip()
    return ''


def _extract_bridge_message_id(data: Any) -> str:
    if not isinstance(data, dict):
        return ''
    for key in ('messageId', 'message_id', 'id'):
        value = data.get(key)
        if value:
            return str(value).strip()
    delivery = data.get('delivery')
    if isinstance(delivery, dict):
        for key in ('messageId', 'message_id', 'id'):
            value = delivery.get(key)
            if value:
                return str(value).strip()
    return ''


def get_cloud_status() -> dict[str, Any]:
    settings_obj = _settings()
    missing = [
        field_name
        for field_name in ('api_version', 'phone_number_id', 'access_token')
        if not getattr(settings_obj, field_name, '').strip()
    ]
    if missing:
        return {
            'ok': False,
            'status': 400,
            'error': f"Missing required WhatsApp Cloud API settings: {', '.join(missing)}.",
            'data': {'configured': False, 'missing': missing},
        }

    result = _cloud_api_request(
        'GET',
        settings_obj.phone_number_id,
        params={'fields': 'display_phone_number,verified_name,quality_rating,code_verification_status'},
        settings_obj=settings_obj,
    )
    if isinstance(result.get('data'), dict):
        result['data']['configured'] = True
        result['data']['missing'] = []
    return result


def get_bridge_status() -> dict[str, Any]:
    settings_obj = _settings()
    from .whatsapp_bridge_manager import bridge_process_snapshot, ensure_bridge_running

    process_info = ensure_bridge_running(settings_obj)
    result = _bridge_api_request('GET', '/api/session/status', settings_obj=settings_obj)
    if not isinstance(result.get('data'), dict):
        result['data'] = {}
    result['data']['configured'] = bool(_bridge_base_url(settings_obj))
    result['data']['baseUrl'] = _bridge_base_url(settings_obj)
    result['data']['process'] = process_info or bridge_process_snapshot(settings_obj)
    return result


def restart_bridge_session() -> dict[str, Any]:
    settings_obj = _settings()
    from .whatsapp_bridge_manager import can_manage_bridge, restart_bridge

    if can_manage_bridge(settings_obj):
        process_result = restart_bridge(settings_obj)
        if not process_result.get('ok'):
            return {
                'ok': False,
                'status': None,
                'error': process_result.get('error') or 'Failed to restart WhatsApp bridge process.',
                'data': process_result,
            }
        time.sleep(1)
        status_result = _bridge_api_request('GET', '/api/session/status', settings_obj=settings_obj)
        if not isinstance(status_result.get('data'), dict):
            status_result['data'] = {}
        status_result['data']['process'] = process_result.get('process') or {}
        status_result['ok'] = True
        return status_result

    return _bridge_api_request('POST', '/api/session/restart')


def logout_bridge_session() -> dict[str, Any]:
    settings_obj = _settings()
    result = _bridge_api_request('POST', '/api/session/logout', settings_obj=settings_obj)
    if result.get('ok'):
        return result

    from .whatsapp_bridge_manager import can_manage_bridge, restart_bridge

    if not can_manage_bridge(settings_obj):
        return result

    process_result = restart_bridge(settings_obj, clear_session=True)
    return {
        'ok': bool(process_result.get('ok')),
        'status': result.get('status'),
        'error': '' if process_result.get('ok') else (process_result.get('error') or result.get('error', '')),
        'data': process_result,
    }


def send_cloud_text_message(phone_number: str, message: str) -> dict[str, Any]:
    settings_obj = _settings()
    phone_number_id = (settings_obj.phone_number_id or '').strip()
    target = _phone_to_international(phone_number, settings_obj.default_country_code)
    message = (message or '').strip()

    if not phone_number_id:
        return {'ok': False, 'status': 400, 'error': 'Phone Number ID is missing.', 'data': None}
    if not target:
        return {'ok': False, 'status': 400, 'error': 'Invalid target phone number.', 'data': None}
    if not message:
        return {'ok': False, 'status': 400, 'error': 'Message is required.', 'data': None}

    result = _cloud_api_request(
        'POST',
        f"{phone_number_id}/messages",
        payload={
            'messaging_product': 'whatsapp',
            'to': target,
            'type': 'text',
            'text': {
                'body': message,
                'preview_url': False,
            },
        },
        settings_obj=settings_obj,
    )
    result['message_id'] = _extract_graph_message_id(result.get('data'))
    return result


def send_cloud_template_message(
    phone_number: str,
    template_name: str,
    language_code: str,
    body_parameters: list[dict[str, str]] | None = None,
    button_url_suffix: str = '',
    button_index: str = '0',
) -> dict[str, Any]:
    settings_obj = _settings()
    phone_number_id = (settings_obj.phone_number_id or '').strip()
    target = _phone_to_international(phone_number, settings_obj.default_country_code)
    template_name = (template_name or '').strip()
    language_code = (language_code or settings_obj.template_language_code or DEFAULT_TEMPLATE_LANGUAGE_CODE).strip()

    if not phone_number_id:
        return {'ok': False, 'status': 400, 'error': 'Phone Number ID is missing.', 'data': None}
    if not target:
        return {'ok': False, 'status': 400, 'error': 'Invalid target phone number.', 'data': None}
    if not template_name:
        return {'ok': False, 'status': 400, 'error': 'Template name is required.', 'data': None}

    def build_template_payload(current_language_code: str, current_button_url_suffix: str = '') -> dict[str, Any]:
        template_payload: dict[str, Any] = {
            'name': template_name,
            'language': {'code': current_language_code or DEFAULT_TEMPLATE_LANGUAGE_CODE},
        }
        if body_parameters:
            template_payload['components'] = [{'type': 'body', 'parameters': body_parameters}]
        if current_button_url_suffix:
            components = template_payload.setdefault('components', [])
            components.append(
                {
                    'type': 'button',
                    'sub_type': 'url',
                    'index': str(button_index),
                    'parameters': [
                        {
                            'type': 'text',
                            'text': current_button_url_suffix,
                        }
                    ],
                }
            )
        return template_payload

    def send_once(current_language_code: str, current_button_url_suffix: str = '') -> dict[str, Any]:
        result = _cloud_api_request(
            'POST',
            f"{phone_number_id}/messages",
            payload={
                'messaging_product': 'whatsapp',
                'to': target,
                'type': 'template',
                'template': build_template_payload(current_language_code, current_button_url_suffix),
            },
            settings_obj=settings_obj,
        )
        result['message_id'] = _extract_graph_message_id(result.get('data'))
        return result

    def error_text(result: dict[str, Any]) -> str:
        parts: list[str] = []
        if result.get('error'):
            parts.append(str(result['error']))
        data = result.get('data')
        if isinstance(data, dict):
            error_payload = data.get('error')
            if isinstance(error_payload, dict):
                for key in ('message', 'type', 'code'):
                    value = error_payload.get(key)
                    if value not in (None, ''):
                        parts.append(str(value))
                error_data = error_payload.get('error_data')
                if isinstance(error_data, dict):
                    details = error_data.get('details')
                    if details:
                        parts.append(str(details))
        return ' '.join(parts).strip().lower()

    def is_translation_missing(result: dict[str, Any]) -> bool:
        if result.get('ok'):
            return False
        return 'template name' in error_text(result) and 'does not exist in' in error_text(result)

    def is_button_mismatch(result: dict[str, Any]) -> bool:
        if result.get('ok'):
            return False
        text = error_text(result)
        if 'button' not in text:
            return False
        return any(
            token in text
            for token in (
                'localizable_params',
                'parameter',
                'component',
                'sub_type',
                'buttons',
            )
        )

    candidate_language_codes: list[str] = []
    for candidate in (
        language_code,
        language_code.split('_', 1)[0] if '_' in language_code else '',
        DEFAULT_TEMPLATE_LANGUAGE_CODE if language_code == 'en' else '',
    ):
        candidate = (candidate or '').strip()
        if candidate and candidate not in candidate_language_codes:
            candidate_language_codes.append(candidate)

    last_result: dict[str, Any] | None = None
    for index, candidate_language_code in enumerate(candidate_language_codes):
        result = send_once(candidate_language_code, button_url_suffix)
        if result.get('ok'):
            return result

        last_result = result
        has_more_languages = index < len(candidate_language_codes) - 1
        if is_translation_missing(result) and has_more_languages:
            continue

        if button_url_suffix and is_button_mismatch(result):
            retry_without_button = send_once(candidate_language_code, '')
            if retry_without_button.get('ok'):
                return retry_without_button

            last_result = retry_without_button
            if is_translation_missing(retry_without_button) and has_more_languages:
                continue
            return retry_without_button

        if not is_translation_missing(result) or not has_more_languages:
            return result

    return last_result or send_once(language_code, button_url_suffix)


def send_cloud_document_message(
    phone_number: str,
    pdf_url: str,
    caption: str = '',
    filename: str = 'job-ticket.pdf',
) -> dict[str, Any]:
    settings_obj = _settings()
    phone_number_id = (settings_obj.phone_number_id or '').strip()
    target = _phone_to_international(phone_number, settings_obj.default_country_code)
    pdf_url = (pdf_url or '').strip()

    if not phone_number_id:
        return {'ok': False, 'status': 400, 'error': 'Phone Number ID is missing.', 'data': None}
    if not target:
        return {'ok': False, 'status': 400, 'error': 'Invalid target phone number.', 'data': None}
    if not pdf_url:
        return {'ok': False, 'status': 400, 'error': 'Document URL is required.', 'data': None}

    result = _cloud_api_request(
        'POST',
        f"{phone_number_id}/messages",
        payload={
            'messaging_product': 'whatsapp',
            'to': target,
            'type': 'document',
            'document': {
                'link': pdf_url,
                'caption': caption or '',
                'filename': filename or 'job-ticket.pdf',
            },
        },
        settings_obj=settings_obj,
    )
    result['message_id'] = _extract_graph_message_id(result.get('data'))
    return result


def send_bridge_text_message(phone_number: str, message: str) -> dict[str, Any]:
    settings_obj = _settings()
    target = _phone_to_international(phone_number, settings_obj.default_country_code)
    message = (message or '').strip()

    if not target:
        return {'ok': False, 'status': 400, 'error': 'Invalid target phone number.', 'data': None}
    if not message:
        return {'ok': False, 'status': 400, 'error': 'Message is required.', 'data': None}

    result = _bridge_api_request(
        'POST',
        '/api/messages/send',
        payload={
            'to': target,
            'message': message,
        },
        settings_obj=settings_obj,
    )
    result['message_id'] = _extract_bridge_message_id(result.get('data'))
    return result


def send_bridge_document_message(
    phone_number: str,
    pdf_url: str,
    caption: str = '',
    filename: str = 'job-ticket.pdf',
) -> dict[str, Any]:
    settings_obj = _settings()
    target = _phone_to_international(phone_number, settings_obj.default_country_code)
    pdf_url = (pdf_url or '').strip()

    if not target:
        return {'ok': False, 'status': 400, 'error': 'Invalid target phone number.', 'data': None}
    if not pdf_url:
        return {'ok': False, 'status': 400, 'error': 'Document URL is required.', 'data': None}

    result = _bridge_api_request(
        'POST',
        '/api/messages/send-pdf',
        payload={
            'to': target,
            'pdf_url': pdf_url,
            'caption': caption or '',
            'filename': filename or 'job-ticket.pdf',
        },
        settings_obj=settings_obj,
    )
    result['message_id'] = _extract_bridge_message_id(result.get('data'))
    return result


def _queue_log_event_type(event_type: str) -> str:
    valid_choices = {choice[0] for choice in WhatsAppNotificationLog.EVENT_CHOICES}
    return event_type if event_type in valid_choices else 'manual'


def _queue_response_payload(raw_payload: Any, error_message: str = '') -> dict[str, Any]:
    if isinstance(raw_payload, dict):
        payload = dict(raw_payload)
    elif raw_payload in (None, ''):
        payload = {}
    else:
        payload = {'raw': raw_payload}

    if error_message and 'error' not in payload:
        payload['error'] = error_message
    return payload


def create_message_queue(
    phone_number: str,
    *,
    job: JobTicket | None = None,
    event_type: str = MessageQueue.EVENT_MANUAL,
    message: str = '',
    pdf_url: str = '',
    caption: str = '',
    filename: str = 'job-ticket.pdf',
) -> dict[str, Any]:
    settings_obj = _settings()
    target = _phone_to_international(phone_number, settings_obj.default_country_code)
    if not target:
        return {
            'ok': False,
            'status': 400,
            'error': 'Invalid target phone number.',
            'data': None,
        }

    message = (message or '').strip()
    pdf_url = (pdf_url or '').strip()
    caption = (caption or '').strip()
    filename = (filename or 'job-ticket.pdf').strip() or 'job-ticket.pdf'

    if not message and not pdf_url:
        return {
            'ok': False,
            'status': 400,
            'error': 'Message or pdf_url is required.',
            'data': None,
        }

    queue = MessageQueue.objects.create(
        job_ticket=job,
        channel=MessageQueue.CHANNEL_WHATSAPP,
        event_type=event_type,
        target_phone=target,
        message=message,
        pdf_url=pdf_url,
        caption=caption,
        filename=filename,
        status=MessageQueue.STATUS_PENDING,
    )

    transaction.on_commit(lambda queue_id=queue.id: dispatch_message_queue_task(queue_id))

    return {
        'ok': True,
        'status': 202,
        'error': '',
        'queued': True,
        'data': {
            'message_queue_id': queue.id,
            'status': queue.status,
            'event_type': queue.event_type,
            'to': queue.target_phone,
        },
    }


def update_message_queue_status(
    queue_id: int,
    status: str,
    *,
    bridge_message_id: str = '',
    bridge_status_code: int | None = None,
    bridge_response: Any = None,
    error_message: str = '',
    transport: str = 'whatsapp-cloud-api',
) -> MessageQueue:
    queue = MessageQueue.objects.select_related('job_ticket').get(pk=queue_id)
    normalized_status = (status or '').strip().lower()
    valid_statuses = {
        MessageQueue.STATUS_PENDING,
        MessageQueue.STATUS_SENT,
        MessageQueue.STATUS_DELIVERED,
        MessageQueue.STATUS_READ,
        MessageQueue.STATUS_FAILED,
    }
    if normalized_status not in valid_statuses:
        raise ValueError('Invalid queue status.')

    now = timezone.now()
    queue.status = normalized_status
    queue.transport = (transport or queue.transport or 'whatsapp-cloud-api').strip()
    queue.bridge_message_id = (bridge_message_id or queue.bridge_message_id or '').strip()
    queue.bridge_status_code = bridge_status_code if bridge_status_code is not None else queue.bridge_status_code
    queue.response_payload = _queue_response_payload(bridge_response, error_message=error_message)
    queue.error_message = (error_message or '').strip()

    update_fields = [
        'status',
        'transport',
        'bridge_message_id',
        'bridge_status_code',
        'response_payload',
        'error_message',
        'updated_at',
    ]

    is_success = normalized_status in {
        MessageQueue.STATUS_SENT,
        MessageQueue.STATUS_DELIVERED,
        MessageQueue.STATUS_READ,
    }

    if is_success:
        if not queue.sent_at:
            queue.sent_at = now
            update_fields.append('sent_at')
        queue.failed_at = None
        queue.next_retry_at = None
        update_fields.extend(['failed_at', 'next_retry_at'])
        if not queue.error_message:
            queue.error_message = ''
    elif normalized_status == MessageQueue.STATUS_FAILED:
        queue.failed_at = now
        update_fields.append('failed_at')
        if queue.retry_count < queue.max_retries:
            backoff_secs = (2 ** queue.retry_count) * 60
            queue.next_retry_at = now + timezone.timedelta(seconds=backoff_secs)
            update_fields.append('next_retry_at')

    queue.save(update_fields=update_fields)

    if queue.job_ticket_id:
        log_message = queue.message or queue.caption or ''
        log_payload = queue.response_payload or {}
        if queue.bridge_message_id and 'bridge_message_id' not in log_payload:
            log_payload['bridge_message_id'] = queue.bridge_message_id
        if queue.bridge_status_code is not None and 'bridge_status_code' not in log_payload:
            log_payload['bridge_status_code'] = queue.bridge_status_code
        if queue.error_message and 'error' not in log_payload:
            log_payload['error'] = queue.error_message

        WhatsAppNotificationLog.objects.update_or_create(
            message_queue=queue,
            defaults={
                'job_ticket': queue.job_ticket,
                'event_type': _queue_log_event_type(queue.event_type),
                'target_phone': queue.target_phone,
                'message': log_message,
                'was_successful': is_success,
                'response_text': json.dumps(log_payload, default=str)[:4000],
            },
        )

    return queue


def update_message_queue_status_by_message_id(
    external_message_id: str,
    status: str,
    *,
    bridge_status_code: int | None = None,
    bridge_response: Any = None,
    error_message: str = '',
    transport: str = 'whatsapp-cloud-api-webhook',
) -> MessageQueue | None:
    external_message_id = (external_message_id or '').strip()
    if not external_message_id:
        return None

    queue = MessageQueue.objects.filter(bridge_message_id=external_message_id).order_by('-created_at').first()
    if not queue:
        return None

    return update_message_queue_status(
        queue.id,
        status,
        bridge_message_id=external_message_id,
        bridge_status_code=bridge_status_code,
        bridge_response=bridge_response,
        error_message=error_message,
        transport=transport,
    )


def _template_for_event(settings_obj: WhatsAppIntegrationSettings, event_type: str) -> str:
    if event_type == MessageQueue.EVENT_CREATED:
        return settings_obj.created_template
    if event_type == MessageQueue.EVENT_COMPLETED:
        return settings_obj.completed_template
    if event_type == MessageQueue.EVENT_ESTIMATE:
        return settings_obj.estimate_template
    if event_type == MessageQueue.EVENT_FEEDBACK:
        return settings_obj.feedback_template
    return settings_obj.delivered_template


def _template_name_for_event(settings_obj: WhatsAppIntegrationSettings, event_type: str) -> str:
    if event_type == MessageQueue.EVENT_CREATED:
        return (settings_obj.created_template_name or '').strip()
    if event_type == MessageQueue.EVENT_COMPLETED:
        return (settings_obj.completed_template_name or '').strip()
    if event_type == MessageQueue.EVENT_DELIVERED:
        return (settings_obj.delivered_template_name or '').strip()
    if event_type == MessageQueue.EVENT_ESTIMATE:
        return (settings_obj.estimate_template_name or '').strip()
    if event_type == MessageQueue.EVENT_FEEDBACK:
        return (settings_obj.feedback_template_name or '').strip()
    return ''


def _message_context(job: JobTicket, settings_obj: WhatsAppIntegrationSettings) -> dict[str, Any]:
    return {
        'job_code': job.job_code,
        'customer_name': job.customer_name,
        'customer_phone': job.customer_phone,
        'device_type': job.device_type,
        'device_brand': job.device_brand,
        'device_model': job.device_model,
        'reported_issue': job.reported_issue,
        'status': job.get_status_display(),
        'status_link': _build_status_link(settings_obj, job),
        'receipt_link': _build_receipt_link(settings_obj, job),
        'updated_at': timezone.localtime(job.updated_at).strftime('%d-%m-%Y %I:%M %p'),
        'estimated_delivery': job.estimated_delivery.strftime('%d-%m-%Y') if job.estimated_delivery else '-',
        'estimated_amount': f"Rs {job.estimated_amount:.2f}" if job.estimated_amount is not None else '-',
        'estimation_note': (job.estimation_note or '').strip() or '-',
    }


def _render_message(template: str, job: JobTicket, settings_obj: WhatsAppIntegrationSettings) -> str:
    context = _message_context(job, settings_obj)
    try:
        return template.format(**context).strip()
    except KeyError as exc:
        logger.warning('WhatsApp template placeholder missing: %s', exc)
        return (
            f"Hello {job.customer_name}, your ticket {job.job_code} update:\n"
            f"Status: {job.get_status_display()}"
        )


def _render_created_pdf_caption(job: JobTicket, settings_obj: WhatsAppIntegrationSettings) -> str:
    caption_template = (
        settings_obj.created_pdf_caption_template
        or "Job Ticket {job_code}"
    )
    caption = _render_message(caption_template, job, settings_obj)
    context = _message_context(job, settings_obj)

    receipt_link = context.get('receipt_link') or ''
    status_link = context.get('status_link') or ''
    additions = []
    if receipt_link and receipt_link not in caption:
        additions.append(f"Receipt: {receipt_link}")
    if status_link and status_link not in caption:
        additions.append(f"Track status: {status_link}")
    if additions:
        caption = f"{caption}\n" + "\n".join(additions)
    return caption.strip()


def _template_body_parameters(template: str, context: dict[str, Any]) -> list[dict[str, str]]:
    parameters: list[dict[str, str]] = []
    for placeholder_name in PLACEHOLDER_PATTERN.findall(template or ''):
        value = str(context.get(placeholder_name, '') or '').strip()
        parameters.append({'type': 'text', 'text': value[:1024] or '-'})
    return parameters


def _status_button_suffix(job: JobTicket) -> str:
    return f"{job.job_code}/"


def _deliver_template_queue(queue: MessageQueue) -> tuple[dict[str, Any], str]:
    settings_obj = _settings()
    if not queue.job_ticket_id:
        return (
            {'ok': False, 'status': 400, 'error': 'Template delivery requires an attached job ticket.', 'data': None},
            'whatsapp-cloud-api-template',
        )

    template_name = _template_name_for_event(settings_obj, queue.event_type)
    if not template_name:
        return (
            {'ok': False, 'status': 400, 'error': 'Approved template name is not configured for this event.', 'data': None},
            'whatsapp-cloud-api-template',
        )

    context = _message_context(queue.job_ticket, settings_obj)
    body_parameters = _template_body_parameters(_template_for_event(settings_obj, queue.event_type), context)
    return (
        send_cloud_template_message(
            queue.target_phone,
            template_name,
            settings_obj.template_language_code,
            body_parameters=body_parameters,
            button_url_suffix=_status_button_suffix(queue.job_ticket),
        ),
        'whatsapp-cloud-api-template',
    )


def _deliver_bridge_queue(queue: MessageQueue) -> tuple[dict[str, Any], str]:
    if queue.pdf_url:
        return (
            send_bridge_document_message(queue.target_phone, queue.pdf_url, queue.caption, queue.filename),
            'whatsapp-bridge-document',
        )
    return (
        send_bridge_text_message(queue.target_phone, queue.message),
        'whatsapp-bridge-text',
    )


def _deliver_message_queue(queue: MessageQueue) -> tuple[dict[str, Any], str]:
    settings_obj = _settings()
    if settings_obj.delivery_method == WhatsAppIntegrationSettings.DELIVERY_BRIDGE:
        return _deliver_bridge_queue(queue)
    if queue.pdf_url:
        doc_result = send_cloud_document_message(queue.target_phone, queue.pdf_url, queue.caption, queue.filename)
        if doc_result.get('ok'):
            return (doc_result, 'whatsapp-cloud-api-document')
        err_msg = str(doc_result.get('error') or '').lower()
        # If Meta blocks document outside 24h window and template is configured, fall back to template
        if (
            ('24 hours' in err_msg or '131047' in err_msg or 'outside' in err_msg)
            and queue.event_type == MessageQueue.EVENT_CREATED
            and settings_obj.created_template_name
        ):
            template_result, transport = _deliver_template_queue(queue)
            if template_result.get('ok'):
                return (template_result, transport)
        return (doc_result, 'whatsapp-cloud-api-document')
    if queue.event_type in {
        MessageQueue.EVENT_CREATED,
        MessageQueue.EVENT_COMPLETED,
        MessageQueue.EVENT_DELIVERED,
        MessageQueue.EVENT_ESTIMATE,
        MessageQueue.EVENT_FEEDBACK,
    }:
        return _deliver_template_queue(queue)
    return (
        send_cloud_text_message(queue.target_phone, queue.message),
        'whatsapp-cloud-api-text',
    )


def _dispatch_message_queue_after_commit(queue_id: int) -> None:
    queue = (
        MessageQueue.objects.filter(pk=queue_id)
        .select_related('job_ticket')
        .first()
    )
    if not queue:
        return

    try:
        result, transport = _deliver_message_queue(queue)
        if result.get('ok'):
            update_message_queue_status(
                queue.id,
                MessageQueue.STATUS_SENT,
                bridge_message_id=result.get('message_id', ''),
                bridge_status_code=result.get('status'),
                bridge_response=result.get('data'),
                transport=transport,
            )
        else:
            update_message_queue_status(
                queue.id,
                MessageQueue.STATUS_FAILED,
                bridge_status_code=result.get('status'),
                bridge_response=result.get('data'),
                error_message=result.get('error', 'WhatsApp Cloud API request failed.'),
                transport=transport,
            )
    except Exception:
        logger.exception('Failed to dispatch WhatsApp message queue %s', queue_id)
        settings_obj = _settings()
        transport = (
            'whatsapp-bridge'
            if settings_obj.delivery_method == WhatsAppIntegrationSettings.DELIVERY_BRIDGE
            else 'whatsapp-cloud-api'
        )
        update_message_queue_status(
            queue_id,
            MessageQueue.STATUS_FAILED,
            error_message='Unexpected error while sending WhatsApp message.',
            transport=transport,
        )


def _safe_dispatch_worker(queue_id: int) -> None:
    try:
        _dispatch_message_queue_after_commit(queue_id)
    finally:
        connection.close()


def dispatch_message_queue_task(queue_id: int) -> None:
    is_sync = getattr(django_settings, 'TESTING', False) or 'test' in sys.argv or getattr(django_settings, 'WHATSAPP_DISPATCH_SYNC', False)
    if is_sync:
        _dispatch_message_queue_after_commit(queue_id)
    else:
        _dispatch_executor.submit(_safe_dispatch_worker, queue_id)


def _should_send(settings_obj: WhatsAppIntegrationSettings, event_type: str) -> bool:
    if not settings_obj.is_enabled:
        return False
    if event_type == MessageQueue.EVENT_CREATED:
        return settings_obj.notify_on_created
    if event_type == MessageQueue.EVENT_COMPLETED:
        return settings_obj.notify_on_completed
    if event_type == MessageQueue.EVENT_DELIVERED:
        return settings_obj.notify_on_delivered
    if event_type == MessageQueue.EVENT_FEEDBACK:
        return settings_obj.notify_on_feedback
    return False


def queue_job_whatsapp_message(job: JobTicket, event_type: str) -> dict[str, Any]:
    settings_obj = _settings()
    message = _render_message(_template_for_event(settings_obj, event_type), job, settings_obj)
    pdf_url = ''
    caption = ''
    filename = 'job-ticket.pdf'
    if event_type == MessageQueue.EVENT_CREATED:
        pdf_url = _build_job_ticket_pdf_url(settings_obj, job)
        caption = _render_created_pdf_caption(job, settings_obj)
        filename = _job_ticket_pdf_filename(job)
    return create_message_queue(
        job.customer_phone,
        job=job,
        event_type=event_type,
        message=message,
        pdf_url=pdf_url,
        caption=caption,
        filename=filename,
    )


def _map_webhook_status(status_value: str) -> str | None:
    normalized = (status_value or '').strip().lower()
    if normalized in {'sent', 'delivered', 'read'}:
        return MessageQueue.STATUS_SENT
    if normalized in {'failed', 'undeliverable'}:
        return MessageQueue.STATUS_FAILED
    return None


def process_whatsapp_webhook_payload(payload: dict[str, Any]) -> dict[str, Any]:
    updated_queue_ids: list[int] = []
    incoming_messages = 0
    inbound_captured = 0
    ignored_status_updates = 0

    for entry in payload.get('entry', []) or []:
        for change in entry.get('changes', []) or []:
            value = change.get('value') or {}
            raw_messages = value.get('messages') or []
            incoming_messages += len(raw_messages)

            for incoming in raw_messages:
                from_phone = (incoming.get('from') or '').strip()
                msg_type = incoming.get('type')
                text_body = ''
                if msg_type == 'text':
                    text_body = ((incoming.get('text') or {}).get('body') or '').strip()
                elif msg_type == 'button':
                    text_body = ((incoming.get('button') or {}).get('text') or '').strip()
                elif msg_type == 'interactive':
                    interactive = incoming.get('interactive') or {}
                    btn = interactive.get('button_reply') or {}
                    lst = interactive.get('list_reply') or {}
                    text_body = (btn.get('title') or lst.get('title') or '').strip()

                if from_phone and text_body:
                    clean_phone = ''.join(ch for ch in from_phone if ch.isdigit())
                    if len(clean_phone) >= 10:
                        last_10 = clean_phone[-10:]
                        matched_job = (
                            JobTicket.objects.filter(customer_phone__endswith=last_10)
                            .exclude(status='Closed')
                            .order_by('-updated_at')
                            .first()
                        )
                        if not matched_job:
                            matched_job = (
                                JobTicket.objects.filter(customer_phone__endswith=last_10)
                                .order_by('-created_at')
                                .first()
                            )
                        if matched_job:
                            from .models import JobTicketLog
                            JobTicketLog.objects.create(
                                job_ticket=matched_job,
                                user=None,
                                action='NOTE',
                                details=f"[WhatsApp Customer Reply]: {text_body[:500]}",
                            )
                            inbound_captured += 1

            for status_payload in value.get('statuses', []) or []:
                mapped_status = _map_webhook_status(status_payload.get('status'))
                if not mapped_status:
                    ignored_status_updates += 1
                    continue

                errors = status_payload.get('errors') or []
                error_message = ''
                if errors:
                    parts = []
                    for item in errors:
                        if isinstance(item, dict):
                            parts.append(item.get('title') or item.get('message') or json.dumps(item, default=str))
                        else:
                            parts.append(str(item))
                    error_message = '; '.join(part for part in parts if part)

                queue = update_message_queue_status_by_message_id(
                    status_payload.get('id') or '',
                    mapped_status,
                    bridge_response=status_payload,
                    error_message=error_message,
                    transport='whatsapp-cloud-api-webhook',
                )
                if queue:
                    updated_queue_ids.append(queue.id)
                else:
                    ignored_status_updates += 1

    return {
        'ok': True,
        'inbound_captured': inbound_captured,
        'status_updates': len(updated_queue_ids),
        'updated_queue_ids': updated_queue_ids,
        'incoming_messages': incoming_messages,
        'ignored_status_updates': ignored_status_updates,
    }


def verify_whatsapp_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    settings_obj = _settings()
    app_secret = (settings_obj.app_secret or '').strip()
    if not app_secret:
        return True

    signature_header = (signature_header or '').strip()
    if not signature_header.startswith('sha256='):
        return False

    provided_signature = signature_header.split('=', 1)[1].strip()
    expected_signature = hmac.new(app_secret.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided_signature, expected_signature)


def send_job_whatsapp_notification(job: JobTicket, event_type: str) -> dict[str, Any]:
    settings_obj = _settings()
    if not _should_send(settings_obj, event_type):
        return {'ok': False, 'skipped': True, 'reason': 'Event disabled or integration not enabled.'}

    is_cloud_delivery = settings_obj.delivery_method == WhatsAppIntegrationSettings.DELIVERY_CLOUD_API
    template_name = _template_name_for_event(settings_obj, event_type)
    if is_cloud_delivery and event_type != MessageQueue.EVENT_CREATED and not template_name:
        return {
            'ok': False,
            'skipped': True,
            'reason': 'Approved WhatsApp template name is missing for this event.',
        }

    return queue_job_whatsapp_message(job, event_type)
