import os
import sys

from django.apps import AppConfig
from django.conf import settings


class JobTicketsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'job_tickets'

    def ready(self):
        from . import signals  # noqa: F401

        if not getattr(settings, 'WHATSAPP_BRIDGE_AUTO_START', True):
            return
        if not any(arg.endswith('runserver') or arg == 'runserver' for arg in sys.argv):
            return
        if os.environ.get('RUN_MAIN') != 'true' and '--noreload' not in sys.argv:
            return

        try:
            from .whatsapp_bridge_manager import ensure_bridge_running

            ensure_bridge_running()
        except Exception:
            # Bridge startup should never prevent Django from booting.
            pass
