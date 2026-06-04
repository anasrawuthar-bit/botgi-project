# job_tickets/context_processors.py
from django.conf import settings

from .access_control import get_staff_access
from .models import CompanyProfile, PlatformSettings
from .workspaces import get_current_workspace

def company_profile(request):
    """Make company profile available in all templates"""
    current_workspace = get_current_workspace(request)
    return {
        'current_workspace': current_workspace,
        'company': CompanyProfile.get_profile(current_workspace),
        'platform': PlatformSettings.get_settings(),
        'staff_access': get_staff_access(getattr(request, 'user', None)),
        'release_info': {
            'web_version': getattr(settings, 'WEB_RELEASE_VERSION', 'dev'),
            'poll_interval_ms': max(getattr(settings, 'WEB_RELEASE_POLL_INTERVAL_SECONDS', 300), 60) * 1000,
        },
    }
