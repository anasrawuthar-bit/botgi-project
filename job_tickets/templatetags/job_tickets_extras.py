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
