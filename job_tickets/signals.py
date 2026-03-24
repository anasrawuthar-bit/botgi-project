from datetime import timedelta

from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db import transaction
from django.db.models.signals import post_migrate, pre_save, post_save
from django.dispatch import receiver
from django.utils import timezone

from .admin_roles import sync_admin_roles
from .models import JobTicket, UserSessionActivity
from .whatsapp_service import send_job_whatsapp_notification


SESSION_ACTIVITY_KEY = '_last_activity_ts'


def _get_request_ip(request):
    forwarded_for = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    return forwarded_for or request.META.get('REMOTE_ADDR') or ''


def _get_session_channel(request):
    path = (getattr(request, 'path', '') or '').lower()
    if path.startswith('/admin/'):
        return UserSessionActivity.CHANNEL_ADMIN
    if path.startswith('/api/'):
        return UserSessionActivity.CHANNEL_API
    return UserSessionActivity.CHANNEL_WEB


@receiver(post_migrate)
def ensure_admin_roles(sender, **kwargs):
    """Ensure production admin role groups/permissions exist after migrations."""
    if sender.label != 'job_tickets':
        return
    sync_admin_roles()


@receiver(pre_save, sender=JobTicket)
def capture_previous_job_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_status = None
        return
    instance._previous_status = sender.objects.filter(pk=instance.pk).values_list('status', flat=True).first()


@receiver(post_save, sender=JobTicket)
def send_whatsapp_notifications_on_job_events(sender, instance, created, **kwargs):
    events = []
    if created:
        events.append('created')
    else:
        previous_status = getattr(instance, '_previous_status', None)
        if previous_status != instance.status:
            if instance.status == 'Completed':
                events.append('completed')
            elif instance.status == 'Closed':
                events.append('delivered')

    if not events:
        return

    def dispatch(event_type):
        job = JobTicket.objects.filter(pk=instance.pk).first()
        if not job:
            return
        send_job_whatsapp_notification(job, event_type)

    for event_type in events:
        transaction.on_commit(lambda event_type=event_type: dispatch(event_type))


@receiver(user_logged_in)
def capture_user_login(sender, request, user, **kwargs):
    session_key = request.session.session_key
    if not session_key:
        request.session.save()
        session_key = request.session.session_key

    now = timezone.now()
    idle_timeout = int(getattr(settings, 'SESSION_IDLE_TIMEOUT_SECONDS', 1800))
    request.session[SESSION_ACTIVITY_KEY] = int(now.timestamp())
    request.session.set_expiry(idle_timeout)

    UserSessionActivity.objects.update_or_create(
        session_key=session_key,
        defaults={
            'user': user,
            'channel': _get_session_channel(request),
            'status': UserSessionActivity.STATUS_ACTIVE,
            'ip_address': _get_request_ip(request) or None,
            'user_agent': (request.META.get('HTTP_USER_AGENT') or '')[:1000],
            'login_at': now,
            'last_activity_at': now,
            'last_activity_path': (request.path or '')[:255],
            'expires_at': now + timedelta(seconds=idle_timeout),
            'logout_at': None,
            'logout_reason': '',
        },
    )


@receiver(user_logged_out)
def capture_user_logout(sender, request, user, **kwargs):
    if not request:
        return

    session_key = getattr(request, '_audit_session_key', None) or getattr(request.session, 'session_key', None)
    if not session_key:
        return

    logout_reason = getattr(request, '_session_logout_reason', UserSessionActivity.STATUS_LOGGED_OUT)
    status = (
        UserSessionActivity.STATUS_EXPIRED
        if logout_reason == UserSessionActivity.STATUS_EXPIRED
        else UserSessionActivity.STATUS_LOGGED_OUT
    )
    now = timezone.now()

    UserSessionActivity.objects.filter(
        session_key=session_key,
        status=UserSessionActivity.STATUS_ACTIVE,
    ).update(
        status=status,
        logout_reason=logout_reason,
        logout_at=now,
        expires_at=now,
    )
