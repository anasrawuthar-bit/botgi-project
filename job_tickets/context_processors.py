# job_tickets/context_processors.py
from .models import CompanyProfile, PlatformSettings
from .access_control import get_staff_access

def company_profile(request):
    """Make company profile available in all templates"""
    return {
        'company': CompanyProfile.get_profile(),
        'platform': PlatformSettings.get_settings(),
        'staff_access': get_staff_access(getattr(request, 'user', None)),
    }
