from django.apps import AppConfig


class JobTicketsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'job_tickets'

    def ready(self):
        from . import signals  # noqa: F401
