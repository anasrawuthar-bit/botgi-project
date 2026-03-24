from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from .models import UserSessionActivity
from .signals import SESSION_ACTIVITY_KEY


class SessionSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        now = timezone.now()
        idle_timeout = int(getattr(settings, 'SESSION_IDLE_TIMEOUT_SECONDS', getattr(settings, 'SESSION_COOKIE_AGE', 1800)))
        session_key = request.session.session_key

        if session_key:
            UserSessionActivity.objects.filter(
                status=UserSessionActivity.STATUS_ACTIVE,
                expires_at__lt=now,
            ).update(
                status=UserSessionActivity.STATUS_EXPIRED,
                logout_reason=UserSessionActivity.STATUS_EXPIRED,
                logout_at=now,
                expires_at=now,
            )

        if self._has_session_expired(request, now, idle_timeout):
            request._audit_session_key = session_key
            request._session_logout_reason = UserSessionActivity.STATUS_EXPIRED
            request._session_was_terminated = True
            logout(request)

            if self._expects_json(request):
                return JsonResponse(
                    {
                        'error': 'session_expired',
                        'message': 'Session expired due to inactivity. Please log in again.',
                    },
                    status=401,
                )

            messages.warning(request, 'Session expired due to inactivity. Please log in again.')
            query = urlencode({'next': request.get_full_path()})
            return redirect(f"{reverse('login')}?{query}")

        request.session[SESSION_ACTIVITY_KEY] = int(now.timestamp())
        request.session.set_expiry(idle_timeout)
        response = self.get_response(request)

        if session_key and not getattr(request, '_session_was_terminated', False):
            UserSessionActivity.objects.filter(
                session_key=session_key,
                user=request.user,
                status=UserSessionActivity.STATUS_ACTIVE,
            ).update(
                last_activity_at=now,
                last_activity_path=(request.path or '')[:255],
                expires_at=now + timedelta(seconds=idle_timeout),
            )

        return response

    def _has_session_expired(self, request, now, idle_timeout):
        raw_timestamp = request.session.get(SESSION_ACTIVITY_KEY)
        if raw_timestamp in (None, ''):
            return False

        try:
            last_activity = datetime.fromtimestamp(float(raw_timestamp), tz=dt_timezone.utc)
        except (TypeError, ValueError, OSError):
            return False

        return now - last_activity > timedelta(seconds=idle_timeout)

    def _expects_json(self, request):
        accept_header = (request.headers.get('Accept') or '').lower()
        requested_with = (request.headers.get('X-Requested-With') or '').lower()
        return (
            request.path.startswith('/api/')
            or requested_with == 'xmlhttprequest'
            or 'application/json' in accept_header
        )
