import json
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from ..bulk_messaging_service import (
    build_client_context,
    create_bulk_campaign_and_queue,
    generate_clients_csv,
    generate_clients_vcf,
    render_bulk_message,
    start_campaign_dispatcher,
)
from ..models import BulkCampaign, Client, InventoryParty, JobTicket
from ..phone_utils import phone_lookup_variants
from .helpers import (
    _money_or_zero,
    _net_amount_after_discount,
    _staff_access_required,
    calculate_job_totals,
    scope_to_workspace,
)


def _load_clients_with_financials(current_workspace, clients_qs=None):
    """
    Helper to enrich clients with their job counts and balance due.
    """
    if clients_qs is None:
        clients_qs = scope_to_workspace(Client.objects.all(), current_workspace)

    client_rows = list(clients_qs)
    jobs_scope = scope_to_workspace(JobTicket.objects.all(), current_workspace)

    phone_to_client_id = {}
    all_lookup_phones = set()
    for c in client_rows:
        if c.phone:
            variants = phone_lookup_variants(c.phone)
            if c.phone not in variants:
                variants.append(c.phone)
            for v in variants:
                phone_to_client_id[v] = c.id
                all_lookup_phones.add(v)

    jobs_by_client_id = {c.id: [] for c in client_rows}
    jobs_by_phone = {}
    if all_lookup_phones:
        job_rows = list(
            jobs_scope.filter(customer_phone__in=all_lookup_phones)
            .defer('technician_notes', 'technician_checklist', 'feedback_followup_note')
            .order_by('-created_at')
        )
        calculate_job_totals(job_rows)
        for job in job_rows:
            job.discount_total = _money_or_zero(job.discount_amount)
            job.net_total = _net_amount_after_discount(job.total, job.discount_total)
            job.current_paid = job.amount_paid or Decimal('0.00')

            cid = phone_to_client_id.get(job.customer_phone)
            if cid and cid in jobs_by_client_id:
                jobs_by_client_id[cid].append(job)

            if job.customer_phone not in jobs_by_phone:
                jobs_by_phone[job.customer_phone] = []
            jobs_by_phone[job.customer_phone].append(job)

    for client in client_rows:
        client.jobs = jobs_by_client_id.get(client.id, [])
        client.total_jobs = len(client.jobs)
        c_billed = sum(getattr(j, 'net_total', Decimal('0.00')) for j in client.jobs)
        c_paid = sum(getattr(j, 'current_paid', Decimal('0.00')) for j in client.jobs)
        client.total_billed = c_billed
        client.amount_paid = c_paid
        client.balance_due = max(Decimal('0.00'), c_billed - c_paid)

    return client_rows, jobs_by_phone


@login_required
@require_POST
def sync_historical_contacts(request):
    """
    Scans past JobTickets and InventoryParties and aggregates any missing
    customers into the Client directory.
    """
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    current_workspace = getattr(request, 'current_workspace', None)
    jobs_scope = scope_to_workspace(JobTicket.objects.all(), current_workspace)
    parties_scope = scope_to_workspace(InventoryParty.objects.all(), current_workspace)
    existing_clients = scope_to_workspace(Client.objects.all(), current_workspace)

    existing_phones = set()
    for c in existing_clients.only('phone'):
        if c.phone:
            for v in phone_lookup_variants(c.phone):
                existing_phones.add(v)
            existing_phones.add(c.phone)

    created_count = 0

    # 1. Sync from JobTickets
    job_customers = (
        jobs_scope.exclude(customer_phone='')
        .values('customer_phone', 'customer_name')
        .distinct()
    )
    for item in job_customers:
        raw_phone = (item.get('customer_phone') or '').strip()
        raw_name = (item.get('customer_name') or '').strip() or 'Customer'
        if not raw_phone:
            continue
        is_known = any(v in existing_phones for v in phone_lookup_variants(raw_phone)) or raw_phone in existing_phones
        if not is_known:
            Client.objects.create(
                workspace=current_workspace,
                name=raw_name,
                phone=raw_phone,
            )
            for v in phone_lookup_variants(raw_phone):
                existing_phones.add(v)
            existing_phones.add(raw_phone)
            created_count += 1

    # 2. Sync from InventoryParties
    party_customers = (
        parties_scope.exclude(phone='')
        .values('name', 'phone', 'legal_name', 'email', 'address')
        .distinct()
    )
    for p in party_customers:
        raw_phone = (p.get('phone') or '').strip()
        raw_name = (p.get('name') or '').strip() or 'Customer'
        if not raw_phone:
            continue
        is_known = any(v in existing_phones for v in phone_lookup_variants(raw_phone)) or raw_phone in existing_phones
        if not is_known:
            Client.objects.create(
                workspace=current_workspace,
                name=raw_name,
                phone=raw_phone,
                company_name=p.get('legal_name') or '',
                email=p.get('email') or '',
                address=p.get('address') or '',
            )
            for v in phone_lookup_variants(raw_phone):
                existing_phones.add(v)
            existing_phones.add(raw_phone)
            created_count += 1

    if created_count > 0:
        messages.success(request, f"Successfully aggregated {created_count} new customer(s) from past repair tickets and invoices into Client Directory.")
    else:
        messages.info(request, "All past customer contacts are already up to date in the directory.")

    return redirect('client_dashboard')


@login_required
def export_clients_vcf(request):
    """
    Exports workspace clients to standard vCard 3.0 (.vcf) format for 1-click
    import into Google Contacts, Apple iCloud, and Android phone address books.
    """
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    current_workspace = getattr(request, 'current_workspace', None)
    clients_qs = scope_to_workspace(Client.objects.filter(is_active=True), current_workspace).order_by('name')

    tab = (request.GET.get('tab') or '').strip().lower()
    if tab in {'credit_due', 'repeat'}:
        client_rows, _ = _load_clients_with_financials(current_workspace, clients_qs)
        if tab == 'credit_due':
            clients_to_export = [c for c in client_rows if getattr(c, 'balance_due', Decimal('0.00')) > Decimal('0.00')]
        else:
            clients_to_export = [c for c in client_rows if getattr(c, 'total_jobs', 0) >= 2]
    else:
        clients_to_export = list(clients_qs)

    vcf_content = generate_clients_vcf(clients_to_export)
    filename = f"botgi_contacts_{timezone.now().strftime('%Y%m%d')}.vcf"

    response = HttpResponse(vcf_content, content_type='text/vcard; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def export_clients_csv(request):
    """
    Exports workspace clients with financial balances and job counts to CSV.
    """
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    current_workspace = getattr(request, 'current_workspace', None)
    clients_qs = scope_to_workspace(Client.objects.all(), current_workspace).order_by('-created_at')
    client_rows, _ = _load_clients_with_financials(current_workspace, clients_qs)

    tab = (request.GET.get('tab') or '').strip().lower()
    if tab == 'credit_due':
        client_rows = [c for c in client_rows if getattr(c, 'balance_due', Decimal('0.00')) > Decimal('0.00')]
    elif tab == 'repeat':
        client_rows = [c for c in client_rows if getattr(c, 'total_jobs', 0) >= 2]

    export_data = []
    for c in client_rows:
        export_data.append({
            'id': c.id,
            'name': c.name,
            'phone': c.phone,
            'email': c.email,
            'company_name': c.company_name,
            'total_jobs': getattr(c, 'total_jobs', 0),
            'total_billed': getattr(c, 'total_billed', Decimal('0.00')),
            'amount_paid': getattr(c, 'amount_paid', Decimal('0.00')),
            'balance_due': getattr(c, 'balance_due', Decimal('0.00')),
            'created_at': c.created_at.strftime('%Y-%m-%d %H:%M') if c.created_at else '',
        })

    csv_content = generate_clients_csv(export_data)
    filename = f"botgi_clients_{timezone.now().strftime('%Y%m%d')}.csv"

    response = HttpResponse(csv_content, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _resolve_target_recipients(request, current_workspace, target_filter: str, selected_ids: list[int] | None = None):
    """
    Filters and returns the list of Client records matching target_filter.
    Supports session persistence fallback for 'selected'.
    """
    clients_qs = scope_to_workspace(Client.objects.filter(is_active=True), current_workspace)
    client_rows, jobs_by_phone = _load_clients_with_financials(current_workspace, clients_qs)

    if target_filter == 'selected':
        if not selected_ids and request:
            selected_ids = request.session.get('selected_client_ids', [])
        selected_set = {int(x) for x in (selected_ids or []) if str(x).isdigit()}
        recipients = [c for c in client_rows if c.id in selected_set]
    elif target_filter == 'credit_due':
        recipients = [c for c in client_rows if getattr(c, 'balance_due', Decimal('0.00')) > Decimal('0.00')]
    elif target_filter == 'repeat':
        recipients = [c for c in client_rows if getattr(c, 'total_jobs', 0) >= 2]
    else:  # 'all'
        recipients = client_rows

    # Filter out clients without phones
    recipients = [c for c in recipients if (c.phone or '').strip()]
    return recipients, jobs_by_phone


@login_required
@require_POST
def update_client_selection_api(request):
    """
    Saves and updates selected clients in the session so selection persists
    across tabs, filters, and searches.
    """
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        data = request.POST

    action = (data.get('action') or 'set').strip().lower()
    incoming_ids = data.get('selected_ids') or []
    if isinstance(incoming_ids, str):
        incoming_ids = [s.strip() for s in incoming_ids.split(',') if s.strip()]

    valid_incoming = {int(x) for x in incoming_ids if str(x).isdigit()}
    current_saved = set(request.session.get('selected_client_ids', []))

    if action == 'clear':
        current_saved.clear()
    elif action == 'add':
        current_saved.update(valid_incoming)
    elif action == 'remove':
        current_saved.difference_update(valid_incoming)
    elif action == 'toggle':
        for x in valid_incoming:
            if x in current_saved:
                current_saved.remove(x)
            else:
                current_saved.add(x)
    else:  # 'set'
        current_saved = valid_incoming

    current_workspace = getattr(request, 'current_workspace', None)
    valid_db_ids = list(
        scope_to_workspace(Client.objects.filter(id__in=current_saved), current_workspace)
        .values_list('id', flat=True)
    )

    request.session['selected_client_ids'] = valid_db_ids
    request.session.modified = True

    return JsonResponse({
        'ok': True,
        'count': len(valid_db_ids),
        'selected_ids': valid_db_ids,
    })


@login_required
@require_POST
def preview_bulk_campaign_view(request):
    """
    AJAX endpoint to preview the message with dynamic tags and Spintax,
    plus calculate recipient count and estimated anti-ban duration.
    """
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        data = request.POST

    raw_template = (data.get('template') or '').strip()
    target_filter = (data.get('target_filter') or 'all').strip()
    selected_ids = data.get('selected_ids') or []
    if isinstance(selected_ids, str):
        selected_ids = [s.strip() for s in selected_ids.split(',') if s.strip()]

    current_workspace = getattr(request, 'current_workspace', None)
    recipients, jobs_by_phone = _resolve_target_recipients(request, current_workspace, target_filter, selected_ids)

    recipient_count = len(recipients)
    sample_preview = ''
    sample_recipient_name = ''

    # Default template if empty
    template_text = raw_template or "{Hello|Hi|Dear} {{name}}, greetings from {{company}}! Your pending balance is Rs {{balance}}. Please let us know if you need any assistance."

    if recipients:
        sample_client = recipients[0]
        ctx = build_client_context(sample_client, jobs_by_phone)
        sample_preview = render_bulk_message(template_text, ctx)
        sample_recipient_name = sample_client.name
    else:
        dummy_ctx = {
            'name': 'Rahul Sharma',
            'phone': '9876543210',
            'company': getattr(current_workspace, 'name', '') or 'our service center',
            'balance': '1250.00',
            'total_jobs': '3',
            'device': 'Dell Inspiron 15',
            'ticket_no': 'GI-261005-015',
        }
        sample_preview = render_bulk_message(template_text, dummy_ctx)
        sample_recipient_name = 'Sample Customer'

    # Anti-ban pacing estimate: ~20 seconds per message + 3-min breather every 20 messages
    breathers = recipient_count // 20
    estimated_seconds = (recipient_count * 20) + (breathers * 180)
    estimated_minutes = max(1, round(estimated_seconds / 60))

    return JsonResponse({
        'ok': True,
        'recipient_count': recipient_count,
        'sample_preview': sample_preview,
        'sample_recipient': sample_recipient_name,
        'estimated_minutes': estimated_minutes,
    })


@login_required
@require_POST
def create_bulk_campaign_view(request):
    """
    Creates a new bulk campaign, populates MessageQueue, and kicks off
    the paced anti-ban background dispatcher.
    """
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        data = request.POST

    title = (data.get('title') or '').strip()
    template_text = (data.get('template') or '').strip()
    target_filter = (data.get('target_filter') or 'all').strip()
    selected_ids = data.get('selected_ids') or []
    if isinstance(selected_ids, str):
        selected_ids = [s.strip() for s in selected_ids.split(',') if s.strip()]

    if not template_text:
        return JsonResponse({'ok': False, 'error': 'Message template cannot be empty.'}, status=400)

    current_workspace = getattr(request, 'current_workspace', None)
    recipients, jobs_by_phone = _resolve_target_recipients(request, current_workspace, target_filter, selected_ids)

    if not recipients:
        return JsonResponse({'ok': False, 'error': 'No eligible recipients found for this selection.'}, status=400)

    campaign = create_bulk_campaign_and_queue(
        workspace=current_workspace,
        user=request.user,
        title=title or f"Campaign - {timezone.now().strftime('%b %d, %H:%M')}",
        target_filter=target_filter,
        template_text=template_text,
        recipient_clients=recipients,
        jobs_by_phone=jobs_by_phone,
    )

    # Launch background anti-ban dispatcher
    start_campaign_dispatcher(campaign.id)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
        return JsonResponse({
            'ok': True,
            'campaign_id': campaign.id,
            'total_recipients': campaign.total_recipients,
            'message': f"Broadcast '{campaign.title}' queued for {campaign.total_recipients} recipients.",
        })

    messages.success(request, f"Broadcast campaign '{campaign.title}' started for {campaign.total_recipients} recipient(s) with anti-ban pacing.")
    return redirect('client_dashboard')


@login_required
@require_GET
def bulk_campaign_status_api(request, campaign_id: int):
    """
    Polling endpoint returning live progress of a bulk messaging campaign.
    """
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    current_workspace = getattr(request, 'current_workspace', None)
    campaign = get_object_or_404(BulkCampaign, pk=campaign_id)
    if campaign.workspace_id and current_workspace and campaign.workspace_id != current_workspace.id:
        return JsonResponse({'ok': False, 'error': 'Unauthorized'}, status=403)

    total = max(1, campaign.total_recipients)
    processed = campaign.sent_count + campaign.failed_count
    percent = min(100, int((processed / total) * 100))

    return JsonResponse({
        'ok': True,
        'id': campaign.id,
        'title': campaign.title,
        'status': campaign.status,
        'status_display': campaign.get_status_display(),
        'total': campaign.total_recipients,
        'sent': campaign.sent_count,
        'failed': campaign.failed_count,
        'processed': processed,
        'percent': percent,
    })


@login_required
@require_POST
def bulk_campaign_pause_api(request, campaign_id: int):
    """
    Allows user to pause, resume, or cancel a campaign.
    """
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    current_workspace = getattr(request, 'current_workspace', None)
    campaign = get_object_or_404(BulkCampaign, pk=campaign_id)
    if campaign.workspace_id and current_workspace and campaign.workspace_id != current_workspace.id:
        return JsonResponse({'ok': False, 'error': 'Unauthorized'}, status=403)

    action = (request.POST.get('action') or '').strip().lower()
    if action == 'pause':
        campaign.status = BulkCampaign.STATUS_PAUSED
        campaign.save(update_fields=['status', 'updated_at'])
    elif action == 'resume':
        campaign.status = BulkCampaign.STATUS_IN_PROGRESS
        campaign.save(update_fields=['status', 'updated_at'])
        start_campaign_dispatcher(campaign.id)
    elif action == 'cancel':
        campaign.status = BulkCampaign.STATUS_CANCELLED
        campaign.save(update_fields=['status', 'updated_at'])

    return JsonResponse({
        'ok': True,
        'id': campaign.id,
        'status': campaign.status,
        'status_display': campaign.get_status_display(),
    })
