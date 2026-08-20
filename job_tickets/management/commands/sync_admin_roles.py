from django.core.management.base import BaseCommand

from job_tickets.admin_roles import sync_admin_roles


class Command(BaseCommand):
    help = "Create/update production admin role groups and permissions."

    def handle(self, *args, **options):
        summary = sync_admin_roles()
        self.stdout.write(self.style.SUCCESS("Admin roles synchronized successfully."))
        for group_name, permission_count in summary.items():
            self.stdout.write(f"- {group_name}: {permission_count} permissions")
