"""
WSGI config for botgi_crm project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'botgi_crm.settings')
from botgi_crm import django_compat  # noqa: F401

application = get_wsgi_application()
