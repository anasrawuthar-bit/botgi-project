# job_tickets/templatetags/job_tickets_extras.py
from django import template
from django.utils.safestring import mark_safe
import json
import re

register = template.Library()
PRODUCT_SALE_DISPLAY_PATTERN = re.compile(
    r'^Product Sale - (?P<name>.+?) \(Qty: (?P<qty>\d+)\)(?: \[PROD#(?P<product_id>\d+)\])?$'
)


@register.filter(name='add_class')
def add_class(value, arg):
    """
    Adds a CSS class to a form field's widget.
    """
    return value.as_widget(attrs={'class': arg})


@register.filter(name='as_json')
def as_json(value):
    """Safely serialise Python objects to JSON for injection into JS in templates."""
    try:
        return mark_safe(json.dumps(value, default=str))
    except Exception:
        return mark_safe('null')


@register.filter(name='display_service_description')
def display_service_description(description):
    """
    Hide internal product marker tokens like [PROD#123] from staff UI while
    preserving the canonical DB description format used by backend logic.
    """
    text = (description or '').strip()
    match = PRODUCT_SALE_DISPLAY_PATTERN.match(text)
    if not match:
        return text
    return f"Product Sale - {match.group('name').strip()} (Qty: {match.group('qty')})"


@register.filter(name='user_initials')
def user_initials(user):
    """Returns 1-2 uppercase initials for a user (e.g. 'ans ptb' -> 'AP')."""
    if not user:
        return 'U'
    first = getattr(user, 'first_name', '') or ''
    last = getattr(user, 'last_name', '') or ''
    if first and last:
        return f"{first[0]}{last[0]}".upper()
    name = (user.get_full_name() if hasattr(user, 'get_full_name') else '') or getattr(user, 'username', '') or ''
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[1][0]}".upper()
    elif len(parts) == 1 and parts[0]:
        return parts[0][:2].upper()
    return 'U'
