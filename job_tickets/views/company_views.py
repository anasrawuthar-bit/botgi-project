from .helpers import *  # noqa: F401,F403


@login_required
def feedback_analytics(request):
    """Feedback analytics dashboard for staff"""
    denied = _staff_access_required(request, "feedback_analytics")
    if denied:
        return denied

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

    total_feedback = jobs_with_feedback.count()
    if total_feedback > 0:
        avg_rating = sum(j.feedback_rating for j in jobs_with_feedback) / total_feedback
        rating_distribution = []
        for i in range(1, 11):
            count = jobs_with_feedback.filter(feedback_rating=i).count()
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
    else:
        avg_rating = 0
        rating_distribution = []
        for i in range(1, 11):
            query_params = {}
            if start_date:
                query_params['start_date'] = start_date
            if end_date:
                query_params['end_date'] = end_date
            query_params['rating'] = i
            rating_distribution.append({
                'rating': i,
                'count': 0,
                'percentage': 0,
                'is_active': selected_rating == i,
                'filter_url': f"{reverse('feedback_analytics')}?{urlencode(query_params)}",
            })

    tech_feedback = {}
    for tech in TechnicianProfile.objects.all().select_related('user'):
        tech_jobs = jobs_with_feedback.filter(assigned_to=tech)
        if tech_jobs.exists():
            tech_avg = sum(j.feedback_rating for j in tech_jobs) / tech_jobs.count()
            tech_query_params = {}
            if start_date:
                tech_query_params['start_date'] = start_date
            if end_date:
                tech_query_params['end_date'] = end_date
            if selected_rating is not None:
                tech_query_params['rating'] = selected_rating
            tech_query_params['technician'] = tech.pk
            tech_feedback[tech] = {
                'count': tech_jobs.count(),
                'avg_rating': round(tech_avg, 2),
                'percentage': round(tech_avg * 10, 1),  # Convert 10-point to 100%
                'jobs': list(tech_jobs[:5]),
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

    context = {
        'total_feedback': total_feedback,
        'avg_rating': round(avg_rating, 2),
        'rating_distribution': rating_distribution,
        'tech_feedback': tech_feedback,
        'recent_feedback': list(filtered_feedback),
        'filtered_feedback_count': filtered_feedback.count(),
        'selected_rating': selected_rating,
        'selected_technician': selected_technician,
        'start_date': start_date,
        'end_date': end_date,
        'clear_rating_url': clear_rating_url,
        'clear_technician_url': clear_technician_url,
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
            whatsapp_form = WhatsAppIntegrationSettingsForm(request.POST, instance=whatsapp_settings)
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
        'whatsapp_webhook_url': request.build_absolute_uri(reverse('whatsapp_cloud_webhook_api')),
    }
    return render(request, 'job_tickets/company_profile_settings.html', context)
