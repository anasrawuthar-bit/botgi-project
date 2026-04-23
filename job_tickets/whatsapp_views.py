import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import WhatsAppIntegrationSettings
from .whatsapp_service import (
    get_cloud_status,
    process_whatsapp_webhook_payload,
    send_cloud_template_message,
    send_cloud_text_message,
    verify_whatsapp_webhook_signature,
)


def _forbidden_json():
    return JsonResponse({'ok': False, 'error': 'forbidden', 'message': 'Only staff can access this endpoint.'}, status=403)


@login_required
@require_GET
def whatsapp_cloud_status_api(request):
    if not request.user.is_staff:
        return _forbidden_json()

    settings_obj = WhatsAppIntegrationSettings.get_settings()
    result = get_cloud_status()
    missing = [
        field_name
        for field_name in ('api_version', 'phone_number_id', 'access_token', 'template_language_code')
        if not getattr(settings_obj, field_name, '').strip()
    ]
    configured = not missing
    profile = result.get('data') or {}
    status_code = 200 if result.get('ok') or not configured else 503

    return JsonResponse(
        {
            'ok': bool(result.get('ok')),
            'configured': configured,
            'missing': missing,
            'api_status_code': result.get('status'),
            'profile': profile if result.get('ok') else {},
            'webhook_verify_token_configured': bool((settings_obj.webhook_verify_token or '').strip()),
            'error': result.get('error', ''),
        },
        status=status_code,
    )


@login_required
@require_POST
def whatsapp_cloud_test_send_api(request):
    if not request.user.is_staff:
        return _forbidden_json()

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'invalid_payload', 'message': 'Invalid JSON payload.'}, status=400)

    settings_obj = WhatsAppIntegrationSettings.get_settings()
    phone = (payload.get('phone') or '').strip()
    mode = (payload.get('mode') or 'template').strip().lower()
    message = (payload.get('message') or '').strip()

    if not phone:
        return JsonResponse({'ok': False, 'error': 'missing_phone', 'message': 'Phone is required.'}, status=400)

    if mode == 'text':
        if not message:
            return JsonResponse({'ok': False, 'error': 'missing_message', 'message': 'Message is required for text mode.'}, status=400)
        result = send_cloud_text_message(phone, message)
    else:
        template_name = (payload.get('template_name') or settings_obj.test_template_name or 'hello_world').strip()
        if not template_name:
            return JsonResponse(
                {
                    'ok': False,
                    'error': 'missing_template_name',
                    'message': 'Template name is required for template mode.',
                },
                status=400,
            )
        result = send_cloud_template_message(phone, template_name, settings_obj.template_language_code)

    status_code = 200 if result.get('ok') else 503
    return JsonResponse(
        {
            'ok': bool(result.get('ok')),
            'api_status_code': result.get('status'),
            'message_id': result.get('message_id', ''),
            'response': result.get('data') or {},
            'error': result.get('error', ''),
        },
        status=status_code,
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_cloud_webhook_api(request):
    settings_obj = WhatsAppIntegrationSettings.get_settings()

    if request.method == 'GET':
        mode = (request.GET.get('hub.mode') or '').strip()
        verify_token = (request.GET.get('hub.verify_token') or '').strip()
        challenge = request.GET.get('hub.challenge') or ''
        expected_token = (settings_obj.webhook_verify_token or '').strip()

        if mode == 'subscribe' and expected_token and verify_token == expected_token:
            return HttpResponse(challenge)
        return HttpResponse('Forbidden', status=403)

    signature = (request.headers.get('X-Hub-Signature-256') or '').strip()
    if not verify_whatsapp_webhook_signature(request.body, signature):
        return JsonResponse({'ok': False, 'error': 'invalid_signature', 'message': 'Invalid webhook signature.'}, status=403)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'invalid_payload', 'message': 'Invalid JSON payload.'}, status=400)

    summary = process_whatsapp_webhook_payload(payload)
    return JsonResponse({'ok': True, **summary})
