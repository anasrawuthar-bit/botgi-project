import csv
import io
import logging
import random
import re
import threading
import time
from decimal import Decimal
from typing import Any

from django.db import connection
from django.utils import timezone

from .models import BulkCampaign, Client, JobTicket, MessageQueue
from .phone_utils import phone_lookup_variants
from .whatsapp_service import _deliver_message_queue, update_message_queue_status

logger = logging.getLogger(__name__)

SPINTAX_PATTERN = re.compile(r'\{([^{}]*\|[^{}]*)\}')


def resolve_spintax(text: str) -> str:
    """
    Recursively resolves {choice1|choice2|choice3} spintax strings.
    Example: "{Hello|Hi|Greetings} {friend|customer}!" -> "Hello friend!"
    """
    if not text:
        return ""
    rendered = text
    for _ in range(25):  # Safety limit to avoid infinite loops
        match = SPINTAX_PATTERN.search(rendered)
        if not match:
            break
        options = [opt.strip() for opt in match.group(1).split('|')]
        chosen = random.choice(options)
        rendered = rendered[:match.start()] + chosen + rendered[match.end():]
    return rendered


def render_bulk_message(template: str, context: dict[str, Any]) -> str:
    """
    Substitutes merge tags (e.g. {{name}}, {{balance}}, {{device}}) and
    then resolves spintax {Hi|Hello|Dear} to give each recipient a uniquely
    formatted message that evades spam hash filters.
    """
    rendered = template or ""
    for key, value in context.items():
        placeholder = f"{{{{{key}}}}}"
        rendered = rendered.replace(placeholder, str(value or ''))

    return resolve_spintax(rendered).strip()


def build_client_context(client: Client, jobs_by_phone: dict[str, list[JobTicket]] | None = None) -> dict[str, Any]:
    """
    Builds the substitution dictionary for a client given their historical jobs.
    """
    client_jobs = []
    if jobs_by_phone and client.phone:
        for v in phone_lookup_variants(client.phone):
            if v in jobs_by_phone:
                client_jobs = jobs_by_phone[v]
                break

    latest_job = client_jobs[0] if client_jobs else None
    latest_device = getattr(latest_job, 'device_type', '') if latest_job else ''
    latest_ticket = getattr(latest_job, 'job_code', '') if latest_job else ''

    # Calculate balance due across client jobs if present
    c_billed = sum(getattr(j, 'net_total', getattr(j, 'total', Decimal('0.00'))) for j in client_jobs)
    c_paid = sum(getattr(j, 'current_paid', getattr(j, 'amount_paid', Decimal('0.00'))) or Decimal('0.00') for j in client_jobs)
    balance = max(Decimal('0.00'), c_billed - c_paid)

    company_name = (client.company_name or '').strip()
    if not company_name and getattr(client, 'workspace', None):
        company_name = getattr(client.workspace, 'name', '').strip()

    return {
        'name': client.name or 'Valued Customer',
        'phone': client.phone or '',
        'company': company_name or 'our service center',
        'balance': f"{balance:.2f}" if balance > Decimal('0.00') else '0.00',
        'total_jobs': str(len(client_jobs)),
        'device': latest_device or 'your device',
        'ticket_no': latest_ticket or '',
    }


def generate_clients_vcf(clients_qs) -> str:
    """
    Generates standard RFC 2426 vCard 3.0 string formatted for Google Contacts,
    Apple iCloud, and Android phone address books.
    """
    lines = []
    for client in clients_qs:
        name = (client.name or 'Customer').strip()
        phone = (client.phone or '').strip()
        if not phone:
            continue

        clean_digits = ''.join(ch for ch in phone if ch.isdigit())
        if len(clean_digits) == 10:
            formatted_phone = f"+91{clean_digits}"
        elif len(clean_digits) > 10 and not phone.startswith('+'):
            formatted_phone = f"+{clean_digits}"
        else:
            formatted_phone = phone

        company = (client.company_name or '').strip()

        lines.append("BEGIN:VCARD")
        lines.append("VERSION:3.0")
        lines.append(f"FN:BotGI - {name}")
        lines.append(f"N:{name};;;;")
        lines.append(f"TEL;TYPE=CELL:{formatted_phone}")
        if company:
            lines.append(f"ORG:{company}")
        if client.notes:
            sanitized_note = client.notes.replace('\r', ' ').replace('\n', ' ')[:200]
            lines.append(f"NOTE:{sanitized_note}")
        lines.append("END:VCARD")

    return "\r\n".join(lines) + "\r\n"


def generate_clients_csv(clients_data: list[dict[str, Any]]) -> str:
    """
    Generates a full CSV string from enriched client dictionaries.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'ID',
        'Name',
        'Phone',
        'Email',
        'Company',
        'Total Jobs',
        'Total Billed (Rs)',
        'Amount Paid (Rs)',
        'Balance Due (Rs)',
        'Created At',
    ])
    for item in clients_data:
        writer.writerow([
            item.get('id', ''),
            item.get('name', ''),
            item.get('phone', ''),
            item.get('email', ''),
            item.get('company_name', ''),
            item.get('total_jobs', 0),
            f"{item.get('total_billed', Decimal('0.00')):.2f}",
            f"{item.get('amount_paid', Decimal('0.00')):.2f}",
            f"{item.get('balance_due', Decimal('0.00')):.2f}",
            item.get('created_at', ''),
        ])
    return output.getvalue()


def create_bulk_campaign_and_queue(
    *,
    workspace,
    user,
    title: str,
    target_filter: str,
    template_text: str,
    recipient_clients: list[Client],
    jobs_by_phone: dict[str, list[JobTicket]] | None = None,
) -> BulkCampaign:
    """
    Creates the BulkCampaign record and pre-populates MessageQueue rows for each recipient.
    Does NOT trigger the messages simultaneously to prevent bridge overflow.
    """
    recipient_ids = [c.id for c in recipient_clients if getattr(c, 'id', None)]
    campaign = BulkCampaign.objects.create(
        workspace=workspace,
        title=title or f"Broadcast - {timezone.now().strftime('%Y-%m-%d %H:%M')}",
        target_filter=target_filter,
        message_template=template_text,
        selected_client_ids=recipient_ids,
        total_recipients=len(recipient_clients),
        sent_count=0,
        failed_count=0,
        status=BulkCampaign.STATUS_PENDING,
        created_by=user if getattr(user, 'is_authenticated', False) else None,
    )

    queue_entries = []
    for client in recipient_clients:
        if not client.phone:
            continue
        ctx = build_client_context(client, jobs_by_phone)
        rendered_body = render_bulk_message(template_text, ctx)
        queue_entries.append(
            MessageQueue(
                bulk_campaign=campaign,
                channel=MessageQueue.CHANNEL_WHATSAPP,
                event_type=MessageQueue.EVENT_BULK,
                target_phone=client.phone,
                message=rendered_body,
                status=MessageQueue.STATUS_PENDING,
            )
        )

    if queue_entries:
        MessageQueue.objects.bulk_create(queue_entries)

    return campaign


def start_campaign_dispatcher(campaign_id: int) -> None:
    """
    Spawns a dedicated background thread to execute the campaign with anti-ban pacing.
    """
    thread = threading.Thread(
        target=_run_bulk_campaign_worker,
        args=(campaign_id,),
        name=f"BulkCampaignWorker-{campaign_id}",
        daemon=True,
    )
    thread.start()


def _run_bulk_campaign_worker(campaign_id: int) -> None:
    """
    Background worker that iterates through queued messages for a campaign.
    Enforces:
    - 15s to 28s randomized jitter delay between consecutive messages.
    - 3-minute breather pause after every 20 messages.
    - Live tracking of sent and failed counts on BulkCampaign.
    - Respects user-triggered pause or cancellation.
    - Automatic auto-pause if 5 consecutive errors occur.
    """
    try:
        campaign = BulkCampaign.objects.filter(pk=campaign_id).first()
        if not campaign:
            return

        campaign.status = BulkCampaign.STATUS_IN_PROGRESS
        campaign.save(update_fields=['status', 'updated_at'])

        consecutive_errors = 0
        messages_sent_in_batch = 0

        while True:
            # Check if campaign was paused or cancelled by user
            campaign.refresh_from_db()
            if campaign.status in [BulkCampaign.STATUS_PAUSED, BulkCampaign.STATUS_CANCELLED]:
                logger.info("Campaign %s stopped by user status=%s", campaign_id, campaign.status)
                break

            # Fetch next pending message
            pending_msg = (
                MessageQueue.objects.filter(bulk_campaign_id=campaign_id, status=MessageQueue.STATUS_PENDING)
                .order_by('id')
                .first()
            )
            if not pending_msg:
                # No more pending messages!
                campaign.status = BulkCampaign.STATUS_COMPLETED
                campaign.save(update_fields=['status', 'updated_at'])
                logger.info("Campaign %s finished successfully. Sent: %s, Failed: %s", campaign_id, campaign.sent_count, campaign.failed_count)
                break

            pending_msg.retry_count += 1
            pending_msg.save(update_fields=['retry_count', 'updated_at'])

            try:
                result, transport = _deliver_message_queue(pending_msg)
                if result.get('ok'):
                    update_message_queue_status(
                        pending_msg.id,
                        MessageQueue.STATUS_SENT,
                        bridge_message_id=result.get('message_id', ''),
                        bridge_status_code=result.get('status'),
                        bridge_response=result.get('data'),
                        transport=transport,
                    )
                    campaign.sent_count += 1
                    consecutive_errors = 0
                    messages_sent_in_batch += 1
                else:
                    error_msg = result.get('error') or 'Bridge delivery failed'
                    update_message_queue_status(
                        pending_msg.id,
                        MessageQueue.STATUS_FAILED,
                        bridge_status_code=result.get('status'),
                        bridge_response=result.get('data'),
                        error_message=error_msg,
                        transport=transport,
                    )
                    campaign.failed_count += 1
                    consecutive_errors += 1
            except Exception as e:
                logger.exception("Error dispatching bulk queue %s", pending_msg.id)
                update_message_queue_status(
                    pending_msg.id,
                    MessageQueue.STATUS_FAILED,
                    error_message=str(e),
                )
                campaign.failed_count += 1
                consecutive_errors += 1

            campaign.save(update_fields=['sent_count', 'failed_count', 'updated_at'])

            # Safety Auto-Pause if bridge goes offline
            if consecutive_errors >= 5:
                logger.warning("Campaign %s auto-paused due to 5 consecutive bridge errors.", campaign_id)
                campaign.status = BulkCampaign.STATUS_PAUSED
                campaign.save(update_fields=['status', 'updated_at'])
                break

            # Check if there are more pending messages before sleeping
            has_more = MessageQueue.objects.filter(bulk_campaign_id=campaign_id, status=MessageQueue.STATUS_PENDING).exists()
            if not has_more:
                campaign.status = BulkCampaign.STATUS_COMPLETED
                campaign.save(update_fields=['status', 'updated_at'])
                break

            # Batch Breather: Pause 3 minutes every 20 messages
            if messages_sent_in_batch >= 20:
                logger.info("Campaign %s taking 3-minute breather after 20 messages...", campaign_id)
                messages_sent_in_batch = 0
                time.sleep(180)
            else:
                # Anti-ban inter-message jitter: 15s to 28s
                jitter_sleep = random.uniform(15.0, 28.0)
                logger.debug("Campaign %s pacing sleep: %0.1fs", campaign_id, jitter_sleep)
                time.sleep(jitter_sleep)

    except Exception:
        logger.exception("Fatal error in bulk campaign worker %s", campaign_id)
    finally:
        connection.close()
