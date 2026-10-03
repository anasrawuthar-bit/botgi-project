from .helpers import *  # noqa: F401,F403
from .helpers import (
    _money_or_zero,
    _net_amount_after_discount,
    _staff_access_required,
)
from django.db.models import Avg, Count, Prefetch, Q
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from django.utils.text import slugify


@login_required
def feedback_analytics(request):
    """Feedback analytics dashboard for staff"""
    denied = _staff_access_required(request, "feedback_analytics")
    if denied:
        return denied

    from .staff_views import _auto_send_due_feedback_messages, _prepare_feedback_followups

    # Run background tasks at most once per 5 minutes using cache lock
    cache_key = 'feedback_auto_send_last_run'
    if not cache.get(cache_key):
        _auto_send_due_feedback_messages()
        _prepare_feedback_followups()
        cache.set(cache_key, 1, 300)  # 5 minutes

    workspace = getattr(request, 'current_workspace', None)
    start_date = (request.GET.get('start_date') or '').strip()
    end_date = (request.GET.get('end_date') or '').strip()
    selected_rating_raw = (request.GET.get('rating') or '').strip()
    selected_technician_raw = (request.GET.get('technician') or '').strip()
    queue_status = (request.GET.get('queue_status') or 'all').strip().lower()
    active_tab = (request.GET.get('tab') or 'queue').strip().lower()

    jobs_with_feedback = scope_to_workspace(JobTicket.objects, workspace).filter(
        feedback_rating__isnull=False
    ).select_related('assigned_to__user').order_by('-feedback_date')

    if start_date:
        try:
            parsed_start = datetime.strptime(start_date, '%Y-%m-%d').date()
            jobs_with_feedback = jobs_with_feedback.filter(feedback_date__date__gte=parsed_start)
        except ValueError:
            start_date = ''
            messages.error(request, 'Invalid start date.')

    if end_date:
        try:
            parsed_end = datetime.strptime(end_date, '%Y-%m-%d').date()
            jobs_with_feedback = jobs_with_feedback.filter(feedback_date__date__lte=parsed_end)
        except ValueError:
            end_date = ''
            messages.error(request, 'Invalid end date.')

    selected_rating = None
    if selected_rating_raw:
        try:
            parsed_rating = int(selected_rating_raw)
            if 1 <= parsed_rating <= 10:
                selected_rating = parsed_rating
        except ValueError:
            selected_rating = None

    selected_technician = None
    if selected_technician_raw:
        try:
            selected_technician = TechnicianProfile.objects.select_related('user').filter(
                pk=int(selected_technician_raw)
            ).first()
        except ValueError:
            selected_technician = None

    # Single aggregated query for total + avg instead of Python loop
    feedback_agg = jobs_with_feedback.aggregate(
        total=Count('id'),
        avg=Avg('feedback_rating'),
    )
    total_feedback = feedback_agg['total'] or 0
    avg_rating = feedback_agg['avg'] or 0

    # Single query for all rating counts instead of 10 separate queries
    rating_counts_qs = (
        jobs_with_feedback
        .values('feedback_rating')
        .annotate(count=Count('id'))
    )
    rating_counts = {row['feedback_rating']: row['count'] for row in rating_counts_qs}

    rating_distribution = []
    for i in range(1, 11):
        count = rating_counts.get(i, 0)
        percentage = (count * 100 / total_feedback) if total_feedback > 0 else 0
        query_params = {}
        if start_date:
            query_params['start_date'] = start_date
        if end_date:
            query_params['end_date'] = end_date
        query_params['rating'] = i
        rating_distribution.append({
            'rating': i,
            'count': count,
            'percentage': round(percentage, 1),
            'is_active': selected_rating == i,
            'filter_url': f"{reverse('feedback_analytics')}?{urlencode(query_params)}",
        })

    # Single aggregated query for all technician stats instead of N+1 loop
    tech_agg = (
        jobs_with_feedback
        .filter(assigned_to__isnull=False)
        .values('assigned_to')
        .annotate(count=Count('id'), avg=Avg('feedback_rating'))
    )
    tech_agg_map = {row['assigned_to']: row for row in tech_agg}

    # Fetch recent jobs per tech in one query
    tech_recent_jobs_qs = (
        jobs_with_feedback
        .filter(assigned_to__isnull=False, assigned_to__in=tech_agg_map.keys())
        .order_by('assigned_to', '-feedback_date')
    )
    tech_recent_map = {}
    for job in tech_recent_jobs_qs:
        tech_id = job.assigned_to_id
        if tech_id not in tech_recent_map:
            tech_recent_map[tech_id] = []
        if len(tech_recent_map[tech_id]) < 5:
            tech_recent_map[tech_id].append(job)

    tech_feedback = {}
    for tech in TechnicianProfile.objects.filter(id__in=tech_agg_map.keys()).select_related('user'):
        agg = tech_agg_map.get(tech.id)
        if not agg:
            continue
        tech_avg = agg['avg'] or 0
        tech_count = agg['count'] or 0
        tech_query_params = {}
        if start_date:
            tech_query_params['start_date'] = start_date
        if end_date:
            tech_query_params['end_date'] = end_date
        if selected_rating is not None:
            tech_query_params['rating'] = selected_rating
        tech_query_params['technician'] = tech.pk
        tech_feedback[tech] = {
            'count': tech_count,
            'avg_rating': round(tech_avg, 2),
            'percentage': round(tech_avg * 10, 1),
            'jobs': tech_recent_map.get(tech.id, []),
            'filter_url': f"{reverse('feedback_analytics')}?{urlencode(tech_query_params)}",
            'is_active': bool(selected_technician and selected_technician.pk == tech.pk),
        }

    filtered_feedback = jobs_with_feedback
    if selected_rating is not None:
        filtered_feedback = filtered_feedback.filter(feedback_rating=selected_rating)
    if selected_technician is not None:
        filtered_feedback = filtered_feedback.filter(assigned_to=selected_technician)

    clear_rating_url = reverse('feedback_analytics')
    clear_rating_params = {}
    if start_date:
        clear_rating_params['start_date'] = start_date
    if end_date:
        clear_rating_params['end_date'] = end_date
    if selected_technician is not None:
        clear_rating_params['technician'] = selected_technician.pk
    if clear_rating_params:
        clear_rating_url = f"{clear_rating_url}?{urlencode(clear_rating_params)}"

    clear_technician_url = reverse('feedback_analytics')
    clear_technician_params = {}
    if start_date:
        clear_technician_params['start_date'] = start_date
    if end_date:
        clear_technician_params['end_date'] = end_date
    if selected_rating is not None:
        clear_technician_params['rating'] = selected_rating
    if clear_technician_params:
        clear_technician_url = f"{clear_technician_url}?{urlencode(clear_technician_params)}"

    feedback_done_statuses = [
        JobTicket.FEEDBACK_RECEIVED,
        JobTicket.FEEDBACK_CALLED_HAPPY,
        JobTicket.FEEDBACK_UNREACHABLE,
    ]

    # Base queryset for followup stats — reused to avoid repeating filters
    followup_base = scope_to_workspace(JobTicket.objects, workspace).filter(
        status='Closed',
        feedback_followup_enabled=True,
        feedback_due_at__lte=timezone.now(),
        feedback_rating__isnull=True,
    ).exclude(feedback_followup_status__in=feedback_done_statuses)

    # Single aggregated query for all followup counts instead of 6 separate queries
    followup_counts = followup_base.aggregate(
        total=Count('id'),
        need_call=Count('id', filter=Q(feedback_followup_status=JobTicket.FEEDBACK_PENDING, feedback_message_sent_at__isnull=True)),
        message_sent=Count('id', filter=Q(feedback_message_sent_at__isnull=False)),
        call_later=Count('id', filter=Q(feedback_followup_status=JobTicket.FEEDBACK_CALL_LATER)),
        no_answer=Count('id', filter=Q(feedback_followup_status=JobTicket.FEEDBACK_NO_ANSWER)),
    )
    feedback_followup_count = followup_counts['total'] or 0
    feedback_need_call_count = followup_counts['need_call'] or 0
    feedback_message_sent_count = followup_counts['message_sent'] or 0
    feedback_call_later_count = followup_counts['call_later'] or 0
    feedback_no_answer_count = followup_counts['no_answer'] or 0

    # These don't share the same base filter — keep separate but they're simple counts
    feedback_issue_count = scope_to_workspace(JobTicket.objects, workspace).filter(
        status='Closed',
        feedback_followup_status=JobTicket.FEEDBACK_CALLED_ISSUE,
    ).count()
    feedback_received_count = scope_to_workspace(JobTicket.objects, workspace).filter(
        status='Closed',
        feedback_followup_status=JobTicket.FEEDBACK_RECEIVED,
    ).count()
    feedback_unreachable_count = scope_to_workspace(JobTicket.objects, workspace).filter(
        status='Closed',
        feedback_followup_status=JobTicket.FEEDBACK_UNREACHABLE,
    ).count()

    filtered_followup_qs = followup_base
    if queue_status == 'need_call':
        filtered_followup_qs = followup_base.filter(
            feedback_followup_status=JobTicket.FEEDBACK_PENDING,
            feedback_message_sent_at__isnull=True,
        )
    elif queue_status == 'message_sent':
        filtered_followup_qs = followup_base.filter(feedback_message_sent_at__isnull=False)
    elif queue_status == 'call_later':
        filtered_followup_qs = followup_base.filter(feedback_followup_status=JobTicket.FEEDBACK_CALL_LATER)
    elif queue_status == 'no_answer':
        filtered_followup_qs = followup_base.filter(feedback_followup_status=JobTicket.FEEDBACK_NO_ANSWER)
    elif queue_status == 'issue':
        filtered_followup_qs = scope_to_workspace(JobTicket.objects, workspace).filter(
            status='Closed',
            feedback_followup_status=JobTicket.FEEDBACK_CALLED_ISSUE,
        )
    elif queue_status == 'received':
        filtered_followup_qs = scope_to_workspace(JobTicket.objects, workspace).filter(
            status='Closed',
            feedback_followup_status=JobTicket.FEEDBACK_RECEIVED,
        )
    elif queue_status == 'unreachable':
        filtered_followup_qs = scope_to_workspace(JobTicket.objects, workspace).filter(
            status='Closed',
            feedback_followup_status=JobTicket.FEEDBACK_UNREACHABLE,
        )

    company_profile = CompanyProfile.get_profile(workspace=workspace)
    auto_whatsapp_enabled = bool(company_profile and getattr(company_profile, 'notify_on_feedback', False))

    feedback_followup_jobs = list(
        filtered_followup_qs
        .select_related('assigned_to__user', 'feedback_followup_marked_by')
        .prefetch_related('service_logs')
        .order_by('feedback_due_at', 'id')[:100]
    )

    feedback_followup_history = list(
        scope_to_workspace(JobTicket.objects, workspace).filter(status='Closed')
        .filter(Q(feedback_followup_enabled=True) | Q(feedback_rating__isnull=False))
        .exclude(feedback_followup_status=JobTicket.FEEDBACK_PENDING)
        .select_related('feedback_followup_marked_by')
        .prefetch_related('service_logs')
        .order_by('-feedback_followup_called_at', '-feedback_date', '-updated_at')[:30]
    )

    recent_feedback = list(filtered_feedback.prefetch_related('service_logs'))

    feedback_amount_jobs = feedback_followup_jobs + feedback_followup_history + recent_feedback
    calculate_job_totals(feedback_amount_jobs)
    for job in feedback_amount_jobs:
        job.discount_total = _money_or_zero(job.discount_amount)
        job.net_total = _net_amount_after_discount(job.total, job.discount_total)

    context = {
        'total_feedback': total_feedback,
        'avg_rating': round(avg_rating, 2),
        'rating_distribution': rating_distribution,
        'tech_feedback': tech_feedback,
        'recent_feedback': recent_feedback,
        'filtered_feedback_count': filtered_feedback.count(),
        'selected_rating': selected_rating,
        'selected_technician': selected_technician,
        'start_date': start_date,
        'end_date': end_date,
        'clear_rating_url': clear_rating_url,
        'clear_technician_url': clear_technician_url,
        'queue_status': queue_status,
        'active_tab': active_tab,
        'feedback_followup_jobs': feedback_followup_jobs,
        'feedback_followup_count': feedback_followup_count,
        'feedback_need_call_count': feedback_need_call_count,
        'feedback_message_sent_count': feedback_message_sent_count,
        'feedback_call_later_count': feedback_call_later_count,
        'feedback_no_answer_count': feedback_no_answer_count,
        'feedback_issue_count': feedback_issue_count,
        'feedback_received_count': feedback_received_count,
        'feedback_unreachable_count': feedback_unreachable_count,
        'auto_whatsapp_enabled': auto_whatsapp_enabled,
        'feedback_followup_history': feedback_followup_history,
    }
    return render(request, 'job_tickets/feedback_analytics.html', context)

@login_required
def company_profile_settings(request):
    """Manage client company profile settings."""
    denied = _staff_access_required(request, "company_settings")
    if denied:
        return denied
    
    workspace = getattr(request, 'current_workspace', None)
    profile = CompanyProfile.get_profile(workspace=workspace)
    whatsapp_settings = WhatsAppIntegrationSettings.get_settings()

    # Racks data for #rack-management tab
    active_jobs_prefetch = Prefetch(
        'job_tickets',
        queryset=JobTicket.objects.exclude(status__in=['Closed', 'Returned'])
            .select_related('assigned_to__user')
            .order_by('-created_at'),
        to_attr='prefetched_active_jobs'
    )
    racks_qs = DeviceRack.objects.all()
    if workspace:
        racks_qs = racks_qs.filter(workspace=workspace)
    racks = list(racks_qs.prefetch_related(active_jobs_prefetch).order_by('group', 'name'))

    total_racks = len(racks)
    occupied_racks = sum(1 for r in racks if len(getattr(r, 'prefetched_active_jobs', [])) > 0)
    empty_racks = total_racks - occupied_racks
    total_devices_stored = sum(len(getattr(r, 'prefetched_active_jobs', [])) for r in racks)
    rack_groups = sorted(list({r.group for r in racks if r.group}))

    unassigned_jobs_qs = JobTicket.objects.exclude(status__in=['Closed', 'Returned']).filter(
        Q(rack__isnull=True) | Q(rack_column__isnull=True)
    ).order_by('-created_at')
    if workspace:
        unassigned_jobs_qs = unassigned_jobs_qs.filter(workspace=workspace)
    unassigned_jobs = list(unassigned_jobs_qs[:50])
    
    if request.method == 'POST':
        active_tab = (request.POST.get('active_tab') or '#company-info').strip() or '#company-info'
        tab_query = active_tab.lstrip('#') or 'company-info'

        if 'whatsapp_settings_submit' in request.POST:
            form = CompanyProfileForm(instance=profile)
            whatsapp_post = request.POST.copy()
            if not (whatsapp_post.get('public_site_url') or '').strip():
                whatsapp_post['public_site_url'] = (
                    whatsapp_settings.public_site_url
                    or request.build_absolute_uri('/').rstrip('/')
                )
            if not (whatsapp_post.get('bridge_base_url') or '').strip():
                whatsapp_post['bridge_base_url'] = (
                    whatsapp_settings.bridge_base_url
                    or 'http://127.0.0.1:3001'
                )
            whatsapp_form = WhatsAppIntegrationSettingsForm(whatsapp_post, instance=whatsapp_settings)
            if whatsapp_form.is_valid():
                whatsapp_form.save()
                messages.success(request, 'WhatsApp integration settings updated successfully.')
                return redirect(f"{reverse('company_profile_settings')}?tab=whatsapp-integration")
            messages.error(request, 'Please fix WhatsApp settings errors and try again.')
        else:
            form = CompanyProfileForm(request.POST, instance=profile)
            whatsapp_form = WhatsAppIntegrationSettingsForm(instance=whatsapp_settings)
            if form.is_valid():
                form.save()
                messages.success(request, 'Profile updated successfully!')
                return redirect(f"{reverse('company_profile_settings')}?tab={tab_query}")
            messages.error(request, 'Please fix the company profile errors and try again.')
    else:
        form = CompanyProfileForm(instance=profile)
        whatsapp_form = WhatsAppIntegrationSettingsForm(instance=whatsapp_settings)
    
    if request.method == 'POST':
        initial_tab = (request.POST.get('active_tab') or '#company-info').strip() or '#company-info'
    else:
        requested_tab = (request.GET.get('tab') or '').strip()
        initial_tab = f"#{requested_tab}" if requested_tab else ''

    # Financial Accounts data (shared with accounts_dashboard)
    accounts_context = _build_accounts_context(request, workspace)

    # Intake Presets & Device Checklists data
    presets_context = _build_presets_and_checklists_context(request, workspace)

    # Keep active tab on bank-details if any transaction ledger filter is used
    if (
        accounts_context.get('selected_account_id')
        or (accounts_context.get('selected_txn_type') and accounts_context.get('selected_txn_type') != 'all')
        or accounts_context.get('start_date_raw')
        or accounts_context.get('end_date_raw')
        or accounts_context.get('search_query')
    ):
        if not initial_tab:
            initial_tab = '#bank-details'
    elif not initial_tab and (request.GET.get('preset_field') or request.GET.get('checklist_template_id')):
        initial_tab = '#intake-presets'

    context = {
        'form': form,
        'profile': profile,
        'whatsapp_form': whatsapp_form,
        'initial_tab': initial_tab,
        'wa_recommended_public_site_url': request.build_absolute_uri('/').rstrip('/'),
        'whatsapp_webhook_url': request.build_absolute_uri(reverse('whatsapp_cloud_webhook_api')),
        'racks': racks,
        'total_racks': total_racks,
        'occupied_racks': occupied_racks,
        'empty_racks': empty_racks,
        'total_devices_stored': total_devices_stored,
        'rack_groups': rack_groups,
        'unassigned_jobs': unassigned_jobs,
        **accounts_context,
        **presets_context,
    }
    return render(request, 'job_tickets/company_profile_settings.html', context)


def _build_accounts_context(request, workspace):
    """Reusable accounts, balances, and ledger context builder."""
    FinancialAccount.ensure_default_accounts(workspace)
    accounts_qs = FinancialAccount.objects.all()
    if workspace:
        accounts_qs = accounts_qs.filter(workspace=workspace)
    accounts = list(accounts_qs.filter(is_active=True).order_by('-is_default_cash', '-is_default_bank', 'name'))
    archived_accounts = list(accounts_qs.filter(is_active=False).order_by('name'))
    total_liquid_balance = sum((acc.current_balance for acc in accounts), Decimal('0.00'))
    total_cash_balance = sum((acc.current_balance for acc in accounts if acc.account_type == FinancialAccount.ACCOUNT_TYPE_CASH), Decimal('0.00'))
    total_bank_balance = sum((acc.current_balance for acc in accounts if acc.account_type in [FinancialAccount.ACCOUNT_TYPE_BANK, FinancialAccount.ACCOUNT_TYPE_UPI]), Decimal('0.00'))

    # All Account Transactions Ledger
    txns_base = AccountTransaction.objects.all()
    if workspace:
        txns_base = txns_base.filter(account__workspace=workspace)

    # Filtering parameters
    selected_account_id = (request.GET.get('account_id') or '').strip()
    selected_txn_type = (request.GET.get('txn_type') or 'all').strip().lower()
    start_date_raw = (request.GET.get('start_date') or '').strip()
    end_date_raw = (request.GET.get('end_date') or '').strip()
    search_query = (request.GET.get('q') or '').strip()

    filtered_txns = txns_base
    if selected_account_id.isdigit():
        filtered_txns = filtered_txns.filter(account_id=int(selected_account_id))

    if selected_txn_type == 'inflow':
        filtered_txns = filtered_txns.filter(transaction_type=AccountTransaction.TYPE_INFLOW)
    elif selected_txn_type == 'outflow':
        filtered_txns = filtered_txns.filter(transaction_type=AccountTransaction.TYPE_OUTFLOW)
    elif selected_txn_type == 'transfer':
        filtered_txns = filtered_txns.filter(transaction_type__in=[AccountTransaction.TYPE_TRANSFER_IN, AccountTransaction.TYPE_TRANSFER_OUT])

    if start_date_raw:
        try:
            start_date = datetime.strptime(start_date_raw, '%Y-%m-%d').date()
            filtered_txns = filtered_txns.filter(transaction_date__gte=start_date)
        except ValueError:
            start_date_raw = ''

    if end_date_raw:
        try:
            end_date = datetime.strptime(end_date_raw, '%Y-%m-%d').date()
            filtered_txns = filtered_txns.filter(transaction_date__lte=end_date)
        except ValueError:
            end_date_raw = ''

    if search_query:
        filtered_txns = filtered_txns.filter(
            Q(description__icontains=search_query)
            | Q(reference_no__icontains=search_query)
            | Q(account__name__icontains=search_query)
            | Q(job_ticket__job_code__icontains=search_query)
        )

    # Filtered sums
    filtered_inflows = filtered_txns.filter(transaction_type=AccountTransaction.TYPE_INFLOW).aggregate(
        total=Coalesce(Sum('amount', output_field=DecimalField()), Decimal('0.00'))
    )['total'] or Decimal('0.00')
    filtered_outflows = filtered_txns.filter(transaction_type=AccountTransaction.TYPE_OUTFLOW).aggregate(
        total=Coalesce(Sum('amount', output_field=DecimalField()), Decimal('0.00'))
    )['total'] or Decimal('0.00')
    filtered_transfers = filtered_txns.filter(transaction_type=AccountTransaction.TYPE_TRANSFER_OUT).aggregate(
        total=Coalesce(Sum('amount', output_field=DecimalField()), Decimal('0.00'))
    )['total'] or Decimal('0.00')
    net_flow = filtered_inflows - filtered_outflows
    total_txns_count = filtered_txns.count()

    # Pagination
    paginator = Paginator(
        filtered_txns.select_related(
            'account',
            'transfer_counterpart__account',
            'job_ticket',
            'expense',
            'vendor_payment__vendor',
            'inventory_credit_payment__party',
            'created_by'
        ).order_by('-transaction_date', '-id'),
        50
    )
    page_number = request.GET.get('page') or 1
    transactions_page = paginator.get_page(page_number)

    # Self-transfers audit log (for modal and backward-compat)
    contra_qs = txns_base.filter(transaction_type=AccountTransaction.TYPE_TRANSFER_OUT)
    self_transfers = list(
        contra_qs.select_related('account', 'transfer_counterpart__account', 'created_by').order_by('-transaction_date', '-id')[:50]
    )

    account_form = FinancialAccountForm()
    transfer_form = AccountTransferForm(workspace=workspace)

    return {
        'financial_accounts': accounts,
        'archived_accounts': archived_accounts,
        'total_liquid_balance': total_liquid_balance,
        'total_cash_balance': total_cash_balance,
        'total_bank_balance': total_bank_balance,
        'self_transfers': self_transfers,
        'transactions_page': transactions_page,
        'selected_account_id': selected_account_id,
        'selected_txn_type': selected_txn_type,
        'start_date_raw': start_date_raw,
        'end_date_raw': end_date_raw,
        'search_query': search_query,
        'filtered_inflows': filtered_inflows,
        'filtered_outflows': filtered_outflows,
        'filtered_transfers': filtered_transfers,
        'net_flow': net_flow,
        'total_txns_count': total_txns_count,
        'account_form': account_form,
        'transfer_form': transfer_form,
    }


@login_required
def accounts_dashboard(request):
    """Primary dashboard for Bank & Financial Accounts and Cash Drawers."""
    denied = _staff_access_required(request, "account_management")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    context = _build_accounts_context(request, workspace)
    return render(request, 'job_tickets/accounts_dashboard.html', context)


@login_required
@require_POST
def rack_create(request):
    """Create a new physical storage rack/shelf."""
    denied = _staff_access_required(request, "company_settings")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    name = (request.POST.get('name') or '').strip()
    group = (request.POST.get('group') or 'Shop').strip() or 'Shop'
    description = (request.POST.get('description') or '').strip()
    total_columns_raw = (request.POST.get('total_columns') or '10').strip()
    try:
        total_columns = max(1, min(100, int(total_columns_raw)))
    except (ValueError, TypeError):
        total_columns = 10

    is_active = (request.POST.get('is_active') == 'on' or request.POST.get('is_active') == '1'
                 or 'is_active' not in request.POST)

    if not name:
        messages.error(request, "Rack name is required.")
        return redirect(f"{reverse('company_profile_settings')}?tab=rack-management")

    existing = DeviceRack.objects.filter(workspace=workspace, name__iexact=name, group__iexact=group).first()
    if existing:
        messages.error(request, f"A rack with name '{name}' already exists in group '{group}'.")
        return redirect(f"{reverse('company_profile_settings')}?tab=rack-management")

    rack = DeviceRack.objects.create(
        workspace=workspace,
        name=name,
        group=group,
        description=description,
        total_columns=total_columns,
        is_active=is_active,
    )
    messages.success(request, f"Rack '{rack.name}' ({rack.group}) created successfully with {rack.total_columns} columns.")
    return redirect(f"{reverse('company_profile_settings')}?tab=rack-management")


@login_required
@require_POST
def rack_edit(request, rack_id):
    """Edit an existing physical storage rack/shelf."""
    denied = _staff_access_required(request, "company_settings")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    rack_qs = DeviceRack.objects.all()
    if workspace:
        rack_qs = rack_qs.filter(workspace=workspace)
    rack = get_object_or_404(rack_qs, id=rack_id)

    name = (request.POST.get('name') or '').strip()
    group = (request.POST.get('group') or 'Shop').strip() or 'Shop'
    description = (request.POST.get('description') or '').strip()
    total_columns_raw = (request.POST.get('total_columns') or '').strip()
    if total_columns_raw:
        try:
            rack.total_columns = max(1, min(100, int(total_columns_raw)))
        except (ValueError, TypeError):
            pass

    is_active = (request.POST.get('is_active') == 'on' or request.POST.get('is_active') == '1')

    if not name:
        messages.error(request, "Rack name cannot be empty.")
        return redirect(f"{reverse('company_profile_settings')}?tab=rack-management")

    existing = DeviceRack.objects.filter(
        workspace=workspace,
        name__iexact=name,
        group__iexact=group
    ).exclude(id=rack.id).first()
    if existing:
        messages.error(request, f"Another rack with name '{name}' already exists in group '{group}'.")
        return redirect(f"{reverse('company_profile_settings')}?tab=rack-management")

    rack.name = name
    rack.group = group
    rack.description = description
    rack.is_active = is_active
    rack.save(update_fields=['name', 'group', 'description', 'total_columns', 'is_active', 'updated_at'])

    messages.success(request, f"Rack '{rack.name}' ({rack.group}) updated successfully.")
    return redirect(f"{reverse('company_profile_settings')}?tab=rack-management")


@login_required
@require_POST
def rack_delete(request, rack_id):
    """Delete a rack if it does not have active stored devices."""
    denied = _staff_access_required(request, "company_settings")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    rack_qs = DeviceRack.objects.all()
    if workspace:
        rack_qs = rack_qs.filter(workspace=workspace)
    rack = get_object_or_404(rack_qs, id=rack_id)

    active_count = rack.active_jobs_count
    if active_count > 0:
        messages.error(
            request,
            f"Cannot delete rack '{rack.name}' because {active_count} active device(s) are currently stored in it. "
            "Please move or close the tickets before deleting."
        )
        return redirect(f"{reverse('company_profile_settings')}?tab=rack-management")

    name = rack.name
    rack.delete()
    messages.success(request, f"Rack '{name}' deleted successfully.")
    return redirect(f"{reverse('company_profile_settings')}?tab=rack-management")


def _get_account_redirect_url(request):
    """Determine dynamic redirect target: accounts_dashboard or company_profile_settings tab."""
    next_url = (request.POST.get('next') or request.GET.get('next') or '').strip()
    if next_url:
        return next_url
    referer = request.META.get('HTTP_REFERER') or ''
    if 'company-profile' in referer:
        return f"{reverse('company_profile_settings')}?tab=bank-details"
    return reverse('accounts_dashboard')


@login_required
@require_POST
def account_create(request):
    """Create a new financial account for the workspace."""
    denied = _staff_access_required(request, "account_management")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    form = FinancialAccountForm(request.POST)
    if form.is_valid():
        account = form.save(commit=False)
        account.workspace = workspace
        account.save()
        messages.success(request, f"Account '{account.name}' created successfully.")
    else:
        for field, errs in form.errors.items():
            messages.error(request, f"{field}: {', '.join(errs)}")
    return redirect(_get_account_redirect_url(request))


@login_required
@require_POST
def account_edit(request, account_id):
    """Edit an existing financial account."""
    denied = _staff_access_required(request, "account_management")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    accounts_qs = FinancialAccount.objects.all()
    if workspace:
        accounts_qs = accounts_qs.filter(workspace=workspace)
    account = get_object_or_404(accounts_qs, id=account_id)

    desired_active = account.is_active
    if 'status_submitted' in request.POST or 'is_active' in request.POST:
        desired_active = ('is_active' in request.POST and request.POST.get('is_active') in ['true', 'True', 'on', '1'])
        if account.is_active and not desired_active:
            if account.is_default_cash or account.is_default_bank:
                role = "Default Cash" if account.is_default_cash else "Default Bank / Digital"
                messages.error(
                    request,
                    f"Cannot deactivate '{account.name}' because it is currently the active {role} account. "
                    f"Please set another account as the default first."
                )
                return redirect(_get_account_redirect_url(request))
            if account.current_balance != Decimal('0.00'):
                messages.error(
                    request,
                    f"Cannot deactivate '{account.name}' because it holds an active balance of ₹{account.current_balance:.2f}. "
                    f"Please use 'Transfer Money' to move the remaining balance out before deactivating."
                )
                return redirect(_get_account_redirect_url(request))

    form = FinancialAccountForm(request.POST, instance=account)
    if form.is_valid():
        acc = form.save(commit=False)
        acc.is_active = desired_active
        acc.save()
        messages.success(request, f"Account '{acc.name}' updated successfully.")
    else:
        for field, errs in form.errors.items():
            messages.error(request, f"{field}: {', '.join(errs)}")
    return redirect(_get_account_redirect_url(request))


@login_required
@require_POST
def account_set_default(request, account_id):
    """Set an account as default cash or default bank."""
    denied = _staff_access_required(request, "account_management")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    accounts_qs = FinancialAccount.objects.all()
    if workspace:
        accounts_qs = accounts_qs.filter(workspace=workspace)
    account = get_object_or_404(accounts_qs, id=account_id)
    default_type = (request.POST.get('default_type') or '').strip().lower()

    if default_type == 'cash':
        account.is_default_cash = True
        account.save()
        messages.success(request, f"'{account.name}' is now the Default Cash account.")
    elif default_type == 'bank':
        account.is_default_bank = True
        account.save()
        messages.success(request, f"'{account.name}' is now the Default Bank / Digital receiving account.")
    else:
        messages.error(request, "Invalid default type requested.")

    return redirect(_get_account_redirect_url(request))


@login_required
@require_POST
def account_deactivate(request, account_id):
    """Explicitly deactivate an account and move it to archived accounts."""
    denied = _staff_access_required(request, "account_management")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    accounts_qs = FinancialAccount.objects.all()
    if workspace:
        accounts_qs = accounts_qs.filter(workspace=workspace)
    account = get_object_or_404(accounts_qs, id=account_id)

    # 1. Block if it's currently a default account
    if account.is_default_cash or account.is_default_bank:
        role = "Default Cash" if account.is_default_cash else "Default Bank / Digital"
        messages.error(
            request,
            f"Cannot deactivate '{account.name}' because it is currently the active {role} account. "
            f"Please set another account as the default first."
        )
        return redirect(_get_account_redirect_url(request))

    # 2. Block if it holds an active non-zero balance
    if account.current_balance != Decimal('0.00'):
        messages.error(
            request,
            f"Cannot deactivate '{account.name}' because it holds an active balance of ₹{account.current_balance:.2f}. "
            f"Please use 'Transfer Money' to move the remaining balance out before deactivating."
        )
        return redirect(_get_account_redirect_url(request))

    account.is_active = False
    account.save(update_fields=['is_active'])
    messages.success(request, f"Account '{account.name}' has been deactivated and moved to archived accounts.")
    return redirect(_get_account_redirect_url(request))


@login_required
@require_POST
def account_delete(request, account_id):
    """Delete an account if it has no transactions and zero balance, or deactivate it."""
    denied = _staff_access_required(request, "account_management")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    accounts_qs = FinancialAccount.objects.all()
    if workspace:
        accounts_qs = accounts_qs.filter(workspace=workspace)
    account = get_object_or_404(accounts_qs, id=account_id)

    # 1. Block if it's currently a default account
    if account.is_default_cash or account.is_default_bank:
        role = "Default Cash" if account.is_default_cash else "Default Bank / Digital"
        messages.error(
            request,
            f"Cannot delete or deactivate '{account.name}' because it is currently the active {role} account. "
            f"Please set another account as the default first."
        )
        return redirect(_get_account_redirect_url(request))

    # 2. Block if it holds an active non-zero balance
    if account.current_balance != Decimal('0.00'):
        messages.error(
            request,
            f"Cannot delete or close '{account.name}' because it holds an active balance of ₹{account.current_balance:.2f}. "
            f"Please use 'Transfer Money' to move the remaining balance out before closing this account."
        )
        return redirect(_get_account_redirect_url(request))

    # 3. If it has transactions, deactivate it to preserve audit history
    if account.transactions.exists():
        account.is_active = False
        account.save(update_fields=['is_active'])
        messages.success(request, f"Account '{account.name}' has historical ledger records and has been safely archived.")
    else:
        name = account.name
        account.delete()
        messages.success(request, f"Account '{name}' deleted permanently.")

    return redirect(_get_account_redirect_url(request))


@login_required
@require_POST
def account_reactivate(request, account_id):
    """Reactivate an archived financial account."""
    denied = _staff_access_required(request, "account_management")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    accounts_qs = FinancialAccount.objects.all()
    if workspace:
        accounts_qs = accounts_qs.filter(workspace=workspace)
    account = get_object_or_404(accounts_qs, id=account_id)

    account.is_active = True
    account.save(update_fields=['is_active'])
    messages.success(request, f"Account '{account.name}' has been reactivated and restored to active accounts.")
    return redirect(_get_account_redirect_url(request))


@login_required
@require_POST
def account_transfer(request):
    """Execute a contra self-transfer between two accounts."""
    denied = _staff_access_required(request, "account_management")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    form = AccountTransferForm(request.POST, workspace=workspace)
    if form.is_valid():
        from_acc = form.cleaned_data['from_account']
        to_acc = form.cleaned_data['to_account']
        amount = form.cleaned_data['amount']
        txn_date = form.cleaned_data['transaction_date']
        ref = form.cleaned_data['reference_no']
        notes = form.cleaned_data['notes']

        try:
            FinancialAccount.transfer(
                from_account=from_acc,
                to_account=to_acc,
                amount=amount,
                reference_no=ref,
                notes=notes,
                transaction_date=txn_date,
                user=request.user,
            )
            messages.success(
                request,
                f"Successfully transferred ₹{amount:,.2f} from '{from_acc.name}' to '{to_acc.name}'."
            )
        except Exception as e:
            messages.error(request, f"Transfer failed: {str(e)}")
    else:
        for field, errs in form.errors.items():
            messages.error(request, f"{field}: {', '.join(errs)}")

    return redirect(_get_account_redirect_url(request))


# ==============================================================================
# INTAKE PRESETS & DEVICE CHECKLISTS MANAGEMENT
# ==============================================================================

def _build_presets_and_checklists_context(request, workspace):
    """Context builder for Intake Presets and Device Checklists."""
    presets_qs = JobFieldPreset.objects.all()
    if workspace:
        presets_qs = presets_qs.filter(Q(workspace=workspace) | Q(workspace__isnull=True))
    all_presets = list(presets_qs.order_by('field_name', 'sort_order', 'value'))

    presets_by_field = {
        'device_type': [p for p in all_presets if p.field_name == 'device_type'],
        'device_brand': [p for p in all_presets if p.field_name == 'device_brand'],
        'reported_issue': [p for p in all_presets if p.field_name == 'reported_issue'],
        'additional_items': [p for p in all_presets if p.field_name == 'additional_items'],
    }

    selected_preset_field = (request.GET.get('preset_field') or 'device_type').strip().lower()
    if selected_preset_field not in presets_by_field:
        selected_preset_field = 'device_type'

    templates_qs = DeviceChecklistTemplate.objects.all()
    if workspace:
        templates_qs = templates_qs.filter(Q(workspace=workspace) | Q(workspace__isnull=True))
    checklist_templates = list(
        templates_qs.prefetch_related('fields').order_by('device_type')
    )

    selected_template_id = (request.GET.get('checklist_template_id') or '').strip()
    selected_checklist_template = None
    if selected_template_id:
        selected_checklist_template = next(
            (t for t in checklist_templates if str(t.id) == selected_template_id), None
        )
    if not selected_checklist_template and checklist_templates:
        selected_checklist_template = checklist_templates[0]

    return {
        'presets_by_field': presets_by_field,
        'selected_preset_field': selected_preset_field,
        'all_presets_count': len(all_presets),
        'checklist_templates': checklist_templates,
        'selected_checklist_template': selected_checklist_template,
        'checklist_field_types': DeviceChecklistField.FIELD_TYPE_CHOICES,
    }


@login_required
@require_POST
def preset_create(request):
    """Create a new job field preset (device_type, device_brand, reported_issue, additional_items)."""
    from django.http import JsonResponse as _JsonResponse
    is_ajax = request.headers.get('X-Requested-With') == 'fetch'
    denied = _staff_access_required(request, "company_settings")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    field_name = (request.POST.get('field_name') or '').strip()
    value = (request.POST.get('value') or '').strip()
    sort_order_raw = (request.POST.get('sort_order') or '10').strip()

    if field_name not in ['device_type', 'device_brand', 'reported_issue', 'additional_items']:
        if is_ajax:
            return _JsonResponse({'ok': False, 'message': 'Invalid preset category.'})
        messages.error(request, "Invalid preset category.")
        return redirect(f"{reverse('company_profile_settings')}?tab=intake-presets")

    if not value:
        if is_ajax:
            return _JsonResponse({'ok': False, 'message': 'Preset value cannot be blank.'})
        messages.error(request, "Preset value cannot be blank.")
        return redirect(f"{reverse('company_profile_settings')}?tab=intake-presets&preset_field={field_name}")

    try:
        sort_order = int(sort_order_raw)
    except (ValueError, TypeError):
        sort_order = 10

    existing = JobFieldPreset.objects.filter(field_name=field_name, value__iexact=value)
    if workspace:
        existing = existing.filter(Q(workspace=workspace) | Q(workspace__isnull=True))
    if existing.exists():
        msg = f"Preset '{value}' already exists for this category."
        if is_ajax:
            return _JsonResponse({'ok': False, 'message': msg})
        messages.warning(request, msg)
        return redirect(f"{reverse('company_profile_settings')}?tab=intake-presets&preset_field={field_name}")

    JobFieldPreset.objects.create(
        workspace=workspace,
        field_name=field_name,
        value=value,
        sort_order=sort_order,
        is_active=True,
    )
    cache.delete('job_field_presets_v1')
    msg = f"Preset '{value}' added successfully."
    if is_ajax:
        return _JsonResponse({'ok': True, 'message': msg})
    messages.success(request, msg)
    return redirect(f"{reverse('company_profile_settings')}?tab=intake-presets&preset_field={field_name}")


@login_required
@require_POST
def preset_edit(request, preset_id):
    """Edit an existing job field preset."""
    denied = _staff_access_required(request, "company_settings")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    preset_qs = JobFieldPreset.objects.all()
    if workspace:
        preset_qs = preset_qs.filter(Q(workspace=workspace) | Q(workspace__isnull=True))
    preset = get_object_or_404(preset_qs, id=preset_id)

    value = (request.POST.get('value') or '').strip()
    sort_order_raw = (request.POST.get('sort_order') or '').strip()
    is_active = (request.POST.get('is_active') == 'on' or request.POST.get('is_active') == '1' or request.POST.get('is_active') == 'true')
    field_name = preset.field_name

    if not value:
        if request.headers.get('X-Requested-With') == 'fetch':
            from django.http import JsonResponse as _JsonResponse
            return _JsonResponse({'ok': False, 'message': 'Preset value cannot be blank.'})
        messages.error(request, "Preset value cannot be blank.")
        return redirect(f"{reverse('company_profile_settings')}?tab=intake-presets&preset_field={field_name}")

    try:
        sort_order = int(sort_order_raw) if sort_order_raw else preset.sort_order
    except (ValueError, TypeError):
        sort_order = preset.sort_order

    preset.value = value
    preset.sort_order = sort_order
    preset.is_active = is_active
    preset.save(update_fields=['value', 'sort_order', 'is_active', 'updated_at'])
    cache.delete('job_field_presets_v1')
    msg = f"Preset '{value}' updated."
    if request.headers.get('X-Requested-With') == 'fetch':
        from django.http import JsonResponse as _JsonResponse
        return _JsonResponse({'ok': True, 'message': msg})
    messages.success(request, msg)
    return redirect(f"{reverse('company_profile_settings')}?tab=intake-presets&preset_field={field_name}")


@login_required
@require_POST
def preset_delete(request, preset_id):
    """Delete a job field preset."""
    denied = _staff_access_required(request, "company_settings")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    preset_qs = JobFieldPreset.objects.all()
    if workspace:
        preset_qs = preset_qs.filter(Q(workspace=workspace) | Q(workspace__isnull=True))
    preset = get_object_or_404(preset_qs, id=preset_id)
    field_name = preset.field_name
    val = preset.value
    preset.delete()
    cache.delete('job_field_presets_v1')
    msg = f"Preset '{val}' deleted."
    if request.headers.get('X-Requested-With') == 'fetch':
        from django.http import JsonResponse as _JsonResponse
        return _JsonResponse({'ok': True, 'message': msg})
    messages.success(request, msg)
    return redirect(f"{reverse('company_profile_settings')}?tab=intake-presets&preset_field={field_name}")


@login_required
@require_POST
def checklist_template_create(request):
    """Create a new device checklist template."""
    denied = _staff_access_required(request, "company_settings")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    device_type = (request.POST.get('device_type') or '').strip()
    name = (request.POST.get('name') or '').strip()
    notes = (request.POST.get('notes') or '').strip()

    if not device_type:
        if request.headers.get('X-Requested-With') == 'fetch':
            from django.http import JsonResponse as _JsonResponse
            return _JsonResponse({'ok': False, 'message': 'Device type is required for checklist template.'})
        messages.error(request, "Device type is required for checklist template.")
        return redirect(f"{reverse('company_profile_settings')}?tab=intake-presets")

    if not name:
        name = f"{device_type} Inspection Checklist"

    existing = DeviceChecklistTemplate.objects.filter(device_type__iexact=device_type)
    if workspace:
        existing = existing.filter(Q(workspace=workspace) | Q(workspace__isnull=True))
    if existing.exists():
        template = existing.first()
        msg = f"Checklist for '{device_type}' already exists."
        if request.headers.get('X-Requested-With') == 'fetch':
            from django.http import JsonResponse as _JsonResponse
            return _JsonResponse({'ok': False, 'message': msg})
        messages.info(request, msg)
        return redirect(f"{reverse('company_profile_settings')}?tab=intake-presets&checklist_template_id={template.id}")

    template = DeviceChecklistTemplate.objects.create(
        workspace=workspace,
        device_type=device_type,
        name=name,
        notes=notes,
        is_active=True,
    )
    # Ensure device_type preset exists in JobFieldPreset
    if not JobFieldPreset.objects.filter(field_name='device_type', value__iexact=device_type).exists():
        JobFieldPreset.objects.create(workspace=workspace, field_name='device_type', value=device_type, sort_order=10)
        cache.delete('job_field_presets_v1')

    msg = f"Checklist template '{template.name}' created."
    if request.headers.get('X-Requested-With') == 'fetch':
        from django.http import JsonResponse as _JsonResponse
        return _JsonResponse({'ok': True, 'message': msg})
    messages.success(request, msg)
    return redirect(f"{reverse('company_profile_settings')}?tab=intake-presets&checklist_template_id={template.id}")


@login_required
@require_POST
def checklist_template_edit(request, template_id):
    """Edit checklist template metadata and active state."""
    denied = _staff_access_required(request, "company_settings")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    template_qs = DeviceChecklistTemplate.objects.all()
    if workspace:
        template_qs = template_qs.filter(Q(workspace=workspace) | Q(workspace__isnull=True))
    template = get_object_or_404(template_qs, id=template_id)

    name = (request.POST.get('name') or '').strip()
    notes = (request.POST.get('notes') or '').strip()
    is_active = (request.POST.get('is_active') == 'on' or request.POST.get('is_active') == '1' or request.POST.get('is_active') == 'true')

    if name:
        template.name = name
    template.notes = notes
    template.is_active = is_active
    template.save(update_fields=['name', 'notes', 'is_active', 'updated_at'])

    msg = f"Checklist template '{template.name}' updated."
    if request.headers.get('X-Requested-With') == 'fetch':
        from django.http import JsonResponse as _JsonResponse
        return _JsonResponse({'ok': True, 'message': msg})
    messages.success(request, msg)
    return redirect(f"{reverse('company_profile_settings')}?tab=intake-presets&checklist_template_id={template.id}")


@login_required
@require_POST
def checklist_template_delete(request, template_id):
    """Delete a checklist template and all its fields."""
    denied = _staff_access_required(request, "company_settings")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    template_qs = DeviceChecklistTemplate.objects.all()
    if workspace:
        template_qs = template_qs.filter(Q(workspace=workspace) | Q(workspace__isnull=True))
    template = get_object_or_404(template_qs, id=template_id)
    name = template.name
    template.delete()
    msg = f"Checklist template '{name}' deleted."
    if request.headers.get('X-Requested-With') == 'fetch':
        from django.http import JsonResponse as _JsonResponse
        return _JsonResponse({'ok': True, 'message': msg})
    messages.success(request, msg)
    return redirect(f"{reverse('company_profile_settings')}?tab=intake-presets")


@login_required
@require_POST
def checklist_field_create(request, template_id):
    """Add a new inspection field to a checklist template."""
    denied = _staff_access_required(request, "company_settings")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    template_qs = DeviceChecklistTemplate.objects.all()
    if workspace:
        template_qs = template_qs.filter(Q(workspace=workspace) | Q(workspace__isnull=True))
    template = get_object_or_404(template_qs, id=template_id)

    label = (request.POST.get('label') or '').strip()
    field_type = (request.POST.get('field_type') or 'checkbox').strip()
    is_required = (request.POST.get('is_required') == 'on' or request.POST.get('is_required') == '1')
    placeholder = (request.POST.get('placeholder') or '').strip()
    options = (request.POST.get('options') or '').strip()
    sort_order_raw = (request.POST.get('sort_order') or '10').strip()

    if not label:
        if request.headers.get('X-Requested-With') == 'fetch':
            from django.http import JsonResponse as _JsonResponse
            return _JsonResponse({'ok': False, 'message': 'Checklist item label is required.'})
        messages.error(request, "Checklist item label is required.")
        return redirect(f"{reverse('company_profile_settings')}?tab=intake-presets&checklist_template_id={template.id}")

    try:
        sort_order = int(sort_order_raw)
    except (ValueError, TypeError):
        sort_order = 10

    base_key = slugify(label).replace('-', '_')[:50] or 'item'
    field_key = base_key
    counter = 1
    while template.fields.filter(field_key=field_key).exists():
        field_key = f"{base_key}_{counter}"
        counter += 1

    DeviceChecklistField.objects.create(
        template=template,
        field_key=field_key,
        label=label,
        field_type=field_type,
        is_required=is_required,
        placeholder=placeholder,
        options=options,
        sort_order=sort_order,
        is_active=True,
    )
    msg = f"Checklist item '{label}' added to {template.name}."
    if request.headers.get('X-Requested-With') == 'fetch':
        from django.http import JsonResponse as _JsonResponse
        return _JsonResponse({'ok': True, 'message': msg})
    messages.success(request, msg)
    return redirect(f"{reverse('company_profile_settings')}?tab=intake-presets&checklist_template_id={template.id}")


@login_required
@require_POST
def checklist_field_edit(request, field_id):
    """Edit an inspection field in a checklist template."""
    denied = _staff_access_required(request, "company_settings")
    if denied:
        return denied

    field = get_object_or_404(DeviceChecklistField.objects.select_related('template'), id=field_id)
    template = field.template

    label = (request.POST.get('label') or '').strip()
    field_type = (request.POST.get('field_type') or field.field_type).strip()
    is_required = (request.POST.get('is_required') == 'on' or request.POST.get('is_required') == '1')
    placeholder = (request.POST.get('placeholder') or '').strip()
    options = (request.POST.get('options') or '').strip()
    sort_order_raw = (request.POST.get('sort_order') or '').strip()
    is_active = (request.POST.get('is_active') == 'on' or request.POST.get('is_active') == '1' or request.POST.get('is_active') == 'true')

    if not label:
        if request.headers.get('X-Requested-With') == 'fetch':
            from django.http import JsonResponse as _JsonResponse
            return _JsonResponse({'ok': False, 'message': 'Field label cannot be blank.'})
        messages.error(request, "Field label cannot be blank.")
        return redirect(f"{reverse('company_profile_settings')}?tab=intake-presets&checklist_template_id={template.id}")

    try:
        sort_order = int(sort_order_raw) if sort_order_raw else field.sort_order
    except (ValueError, TypeError):
        sort_order = field.sort_order

    field.label = label
    field.field_type = field_type
    field.is_required = is_required
    field.placeholder = placeholder
    field.options = options
    field.sort_order = sort_order
    field.is_active = is_active
    field.save(update_fields=['label', 'field_type', 'is_required', 'placeholder', 'options', 'sort_order', 'is_active'])

    msg = f"Checklist item '{label}' updated."
    if request.headers.get('X-Requested-With') == 'fetch':
        from django.http import JsonResponse as _JsonResponse
        return _JsonResponse({'ok': True, 'message': msg})
    messages.success(request, msg)
    return redirect(f"{reverse('company_profile_settings')}?tab=intake-presets&checklist_template_id={template.id}")


@login_required
@require_POST
def checklist_field_delete(request, field_id):
    """Delete an inspection field from a checklist template."""
    denied = _staff_access_required(request, "company_settings")
    if denied:
        return denied

    field = get_object_or_404(DeviceChecklistField.objects.select_related('template'), id=field_id)
    template_id = field.template_id
    label = field.label
    field.delete()

    msg = f"Checklist item '{label}' deleted."
    if request.headers.get('X-Requested-With') == 'fetch':
        from django.http import JsonResponse as _JsonResponse
        return _JsonResponse({'ok': True, 'message': msg})
    messages.success(request, msg)
    return redirect(f"{reverse('company_profile_settings')}?tab=intake-presets&checklist_template_id={template_id}")



