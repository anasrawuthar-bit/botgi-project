from .helpers import *  # noqa: F401,F403
from .helpers import (
    _money_or_zero,
    _net_amount_after_discount,
    _staff_access_required,
)
from django.db.models import Avg, Count, Prefetch, Q
from django.views.decorators.http import require_POST


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
        initial_tab = f"#{requested_tab}" if requested_tab else '#company-info'

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
    }
    return render(request, 'job_tickets/company_profile_settings.html', context)


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

