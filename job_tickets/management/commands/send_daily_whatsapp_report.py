import logging
from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone

from job_tickets.models import CompanyWorkspace, WhatsAppIntegrationSettings
from job_tickets.whatsapp_service import render_daily_report_message, send_daily_whatsapp_report

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Automatically send the daily business summary report via WhatsApp (for cron / Coolify scheduled tasks).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            default='',
            help='Target report date in YYYY-MM-DD format (defaults to current date).',
        )
        parser.add_argument(
            '--phone',
            type=str,
            default='',
            help='Override recipient phone number (comma-separated for multiple).',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force send regardless of scheduled closing time or whether already sent today.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Render and display the daily report message without delivering via WhatsApp.',
        )

    def handle(self, *args, **options):
        date_str = options['date'].strip()
        override_phone = options['phone'].strip()
        force = options['force']
        dry_run = options['dry_run']

        if date_str:
            try:
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                self.stderr.write(self.style.ERROR(f"Invalid date format: {date_str}. Expected YYYY-MM-DD."))
                return
        else:
            target_date = timezone.localdate()

        current_time = timezone.localtime().time()

        # Collect applicable WhatsApp settings
        workspaces = list(CompanyWorkspace.objects.filter(status=CompanyWorkspace.STATUS_ACTIVE))
        if not workspaces:
            targets = [(None, WhatsAppIntegrationSettings.get_settings())]
        else:
            targets = []
            for ws in workspaces:
                targets.append((ws, WhatsAppIntegrationSettings.get_settings(workspace=ws)))

        total_sent = 0
        total_skipped = 0

        for ws, settings_obj in targets:
            ws_label = ws.name if ws else 'Default / Global'

            if not settings_obj.is_enabled and not (force and dry_run):
                self.stdout.write(f"[{ws_label}] WhatsApp messaging engine is disabled. Skipping.")
                total_skipped += 1
                continue

            if not settings_obj.notify_daily_report and not force:
                self.stdout.write(f"[{ws_label}] Daily report notification is not enabled. Skipping.")
                total_skipped += 1
                continue

            # Time check
            scheduled_time = settings_obj.daily_report_time
            if not force and scheduled_time and current_time < scheduled_time:
                self.stdout.write(
                    f"[{ws_label}] Scheduled time is {scheduled_time.strftime('%H:%M')}, "
                    f"current time is {current_time.strftime('%H:%M')}. Skipping until closing time."
                )
                total_skipped += 1
                continue

            # Duplicate date check
            if not force and settings_obj.daily_report_last_sent_date == target_date:
                self.stdout.write(
                    f"[{ws_label}] Daily report already sent for {target_date}. Skipping duplicate send."
                )
                total_skipped += 1
                continue

            if dry_run:
                msg, ctx = render_daily_report_message(target_date=target_date, workspace=ws)
                self.stdout.write(self.style.SUCCESS(f"\n--- [DRY-RUN] Daily Report for {ws_label} ({target_date}) ---"))
                try:
                    self.stdout.write(msg)
                except UnicodeEncodeError:
                    self.stdout.write(msg.encode('ascii', errors='replace').decode('ascii'))
                self.stdout.write("---------------------------------------------------\n")
                continue

            self.stdout.write(f"[{ws_label}] Dispatching daily report for {target_date}...")
            result = send_daily_whatsapp_report(
                target_date=target_date,
                target_phone=override_phone,
                workspace=ws,
                is_automatic=True,
            )

            if result.get('ok'):
                sent_phones = ', '.join(result.get('sent_phones', []))
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[{ws_label}] Successfully sent daily report to: {sent_phones} "
                        f"(Transport: {result.get('transport')})"
                    )
                )
                total_sent += 1
            else:
                err = result.get('error') or '; '.join(result.get('errors', []))
                self.stderr.write(self.style.ERROR(f"[{ws_label}] Failed to send daily report: {err}"))

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry-run complete."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Daily report process finished. Sent: {total_sent}, Skipped: {total_skipped}."
                )
            )
