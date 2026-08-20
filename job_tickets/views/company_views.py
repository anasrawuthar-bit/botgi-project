from .helpers import *  # noqa: F401,F403
from django.db.models import Avg, Count, Q


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

    start_date = (request.GET.get('start_date') or '').strip()
    end_date = (request.GET.get('end_date') or '').strip()
    selected_rating_raw = (request.GET.get('rating') or '').strip()
    selected_technician_raw = (request.GET.get('technician') or '').strip()

    jobs_with_feedback = JobTicket.objects.filter(
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
    ]

    # Base queryset for followup stats — reused to avoid repeating filters
    followup_base = JobTicket.objects.filter(
        status='Closed',
        feedback_followup_enabled=True,
        feedback_due_at__lte=timezone.now(),
        feedback_rating__isnull=True,
    ).exclude(feedback_followup_status__in=feedback_done_statuses)

    # Single aggregated query for all followup counts instead of 6 separate queries
    followup_counts = followup_base.aggregate(
        total=Count('id'),
        message_sent=Count('id', filter=Q(feedback_message_sent_at__isnull=False)),
        call_later=Count('id', filter=Q(feedback_followup_status=JobTicket.FEEDBACK_CALL_LATER)),
        no_answer=Count('id', filter=Q(feedback_followup_status=JobTicket.FEEDBACK_NO_ANSWER)),
    )
    feedback_followup_count = followup_counts['total'] or 0
    feedback_message_sent_count = followup_counts['message_sent'] or 0
    feedback_call_later_count = followup_counts['call_later'] or 0
    feedback_no_answer_count = followup_counts['no_answer'] or 0

    # These two don't share the same base filter — keep separate but they're simple counts
    feedback_issue_count = JobTicket.objects.filter(
        status='Closed',
        feedback_followup_status=JobTicket.FEEDBACK_CALLED_ISSUE,
    ).count()
    feedback_received_count = JobTicket.objects.filter(
        status='Closed',
        feedback_followup_status=JobTicket.FEEDBACK_RECEIVED,
    ).count()

    feedback_followup_jobs = list(
        followup_base
        .select_related('assigned_to__user', 'feedback_followup_marked_by')
        .prefetch_related('service_logs')
        .order_by('feedback_due_at', 'id')[:100]
    )

    feedback_followup_history = list(
        JobTicket.objects.filter(status='Closed')
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
        'feedback_followup_jobs': feedback_followup_jobs,
        'feedback_followup_count': feedback_followup_count,
        'feedback_message_sent_count': feedback_message_sent_count,
        'feedback_call_later_count': feedback_call_later_count,
        'feedback_no_answer_count': feedback_no_answer_count,
        'feedback_issue_count': feedback_issue_count,
        'feedback_received_count': feedback_received_count,
        'feedback_followup_history': feedback_followup_history,
    }
    return render(request, 'job_tickets/feedback_analytics.html', context)

@login_required
def company_profile_settings(request):
    """Manage client company profile settings."""
    denied = _staff_access_required(request, "company_settings")
    if denied:
        return denied
    
    profile = CompanyProfile.get_profile()
    whatsapp_settings = WhatsAppIntegrationSettings.get_settings()
    
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
    
    requested_tab = (request.GET.get('tab') or '').strip()
    initial_tab = f"#{requested_tab}" if requested_tab else '#company-info'

    context = {
        'form': form,
        'profile': profile,
        'whatsapp_form': whatsapp_form,
        'initial_tab': initial_tab,
        'wa_recommended_public_site_url': request.build_absolute_uri('/').rstrip('/'),
        'whatsapp_webhook_url': request.build_absolute_uri(reverse('whatsapp_cloud_webhook_api')),
    }
    return render(request, 'job_tickets/company_profile_settings.html', context)
