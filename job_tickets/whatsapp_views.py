import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .whatsapp_service import get_bridge_status, logout_bridge_session, send_bridge_message


def _forbidden_json():
    return JsonResponse({'ok': False, 'error': 'forbidden', 'message': 'Only staff can access this endpoint.'}, status=403)


@login_required
@require_GET
def whatsapp_bridge_status_api(request):
    if not request.user.is_staff:
        return _forbidden_json()

    result = get_bridge_status()
    status_code = 200 if result.get('ok') else 503
    return JsonResponse(
        {
            'ok': bool(result.get('ok')),
            'bridge_status_code': result.get('status'),
            'bridge': result.get('data') or {},
            'error': result.get('error', ''),
        },
        status=status_code,
    )


@login_required
@require_POST
def whatsapp_bridge_logout_api(request):
    if not request.user.is_staff:
        return _forbidden_json()

    result = logout_bridge_session()
    status_code = 200 if result.get('ok') else 503
    return JsonResponse(
        {
            'ok': bool(result.get('ok')),
            'bridge_status_code': result.get('status'),
            'bridge': result.get('data') or {},
            'error': result.get('error', ''),
        },
        status=status_code,
    )


@login_required
@require_POST
def whatsapp_bridge_test_send_api(request):
    if not request.user.is_staff:
        return _forbidden_json()

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'invalid_payload', 'message': 'Invalid JSON payload.'}, status=400)

    phone = (payload.get('phone') or '').strip()
    message = (payload.get('message') or '').strip()

    if not phone:
        return JsonResponse({'ok': False, 'error': 'missing_phone', 'message': 'Phone is required.'}, status=400)
    if not message:
        return JsonResponse({'ok': False, 'error': 'missing_message', 'message': 'Message is required.'}, status=400)

    result = send_bridge_message(phone, message)
    status_code = 200 if result.get('ok') else 503
    return JsonResponse(
        {
            'ok': bool(result.get('ok')),
            'bridge_status_code': result.get('status'),
            'bridge': result.get('data') or {},
            'error': result.get('error', ''),
        },
        status=status_code,
    )
