import logging
from django.core.management.base import BaseCommand
from django.db.models import F, Q
from django.utils import timezone

from job_tickets.models import MessageQueue, WhatsAppIntegrationSettings
from job_tickets.whatsapp_service import _deliver_message_queue, update_message_queue_status

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Process pending and retryable failed WhatsApp messages in MessageQueue.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Maximum number of queued messages to process in one run (default 50).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show queued messages eligible for processing without actually sending them.',
        )

    def handle(self, *args, **options):
        limit = options['limit']
        dry_run = options['dry_run']
        now = timezone.now()

        settings_obj = WhatsAppIntegrationSettings.get_settings()
        if not settings_obj.is_enabled and not dry_run:
            self.stdout.write(self.style.WARNING('WhatsApp integration is currently disabled in settings.'))

        eligible_filter = Q(status=MessageQueue.STATUS_PENDING) | (
            Q(status=MessageQueue.STATUS_FAILED)
            & Q(retry_count__lt=F('max_retries'))
            & (Q(next_retry_at__lte=now) | Q(next_retry_at__isnull=True))
        )

        queues = (
            MessageQueue.objects.filter(eligible_filter)
            .select_related('job_ticket')
            .order_by('created_at')[:limit]
        )

        total_count = queues.count()
        if total_count == 0:
            self.stdout.write(self.style.SUCCESS('No WhatsApp messages currently pending or eligible for retry.'))
            return

        self.stdout.write(f"Found {total_count} WhatsApp message(s) to process (limit={limit}).")

        if dry_run:
            for item in queues:
                job_code = item.job_ticket.job_code if item.job_ticket else 'NO-JOB'
                self.stdout.write(
                    f" [DRY-RUN] ID={item.id} Job={job_code} Event={item.event_type} "
                    f"Status={item.status} Retries={item.retry_count}/{item.max_retries} Phone={item.target_phone}"
                )
            return

        sent_count = 0
        failed_count = 0

        for queue in queues:
            queue.retry_count += 1
            queue.save(update_fields=['retry_count', 'updated_at'])

            try:
                result, transport = _deliver_message_queue(queue)
                if result.get('ok'):
                    update_message_queue_status(
                        queue.id,
                        MessageQueue.STATUS_SENT,
                        bridge_message_id=result.get('message_id', ''),
                        bridge_status_code=result.get('status'),
                        bridge_response=result.get('data'),
                        transport=transport,
                    )
                    sent_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f" Sent queue ID={queue.id} (transport={transport}, msg_id={result.get('message_id', '')})"
                        )
                    )
                else:
                    update_message_queue_status(
                        queue.id,
                        MessageQueue.STATUS_FAILED,
                        bridge_status_code=result.get('status'),
                        bridge_response=result.get('data'),
                        error_message=result.get('error', 'Delivery failed.'),
                        transport=transport,
                    )
                    failed_count += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f" Failed queue ID={queue.id} (error={result.get('error', '')})"
                        )
                    )
            except Exception as exc:
                logger.exception('Exception while processing message queue %s', queue.id)
                update_message_queue_status(
                    queue.id,
                    MessageQueue.STATUS_FAILED,
                    error_message=str(exc),
                )
                failed_count += 1
                self.stdout.write(
                    self.style.ERROR(f" Unexpected error on queue ID={queue.id}: {exc}")
                )

        self.stdout.write(
            self.style.SUCCESS(f"Finished processing. Succeeded: {sent_count}, Failed: {failed_count}.")
        )
