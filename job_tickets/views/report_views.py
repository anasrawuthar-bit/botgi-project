from .helpers import *  # noqa: F401,F403


@login_required
@never_cache
def reports_dashboard(request):
    denied = _staff_access_required(request, "reports_dashboard")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')

    period = get_report_period(request)
    start_of_period = period['start']
    end_of_period = period['end']
    status_filter = request.GET.get('status_filter')

    # --- 1. ALL-TIME STATUS COUNTS (single aggregate query) ---
    status_counts = JobTicket.objects.aggregate(
        all_jobs_count=Count('id'),
        pending_count=Count('id', filter=Q(status='Pending')),
        in_progress_count=Count('id', filter=Q(status__in=['Under Inspection', 'Repairing', 'Specialized Service'])),
        completed_count=Count('id', filter=Q(status='Completed')),
        ready_for_pickup_count=Count('id', filter=Q(status='Ready for Pickup')),
        returned_only_count=Count('id', filter=Q(status='Returned')),
        closed_count=Count('id', filter=Q(status='Closed')),
    )
    returned_to_closed_count = get_returned_to_closed_job_ids().count()
    returned_count = status_counts['returned_only_count'] + returned_to_closed_count

    company_start_date = get_company_start_date()
    today = timezone.localdate()
    today_date_str = today.strftime('%Y-%m-%d')

    # --- 2. TODAY'S STATS ---
    start_of_day = timezone.make_aware(datetime.combine(today, datetime.min.time()))
    end_of_day = timezone.make_aware(datetime.combine(today, datetime.max.time()))

    todays_jobs_in = JobTicket.objects.filter(created_at__range=(start_of_day, end_of_day)).count()

    # Count only jobs with an audited transition to Closed today. The closure
    # timestamp can be backfilled when an older already-closed job is edited, which must
    # not make that job appear in today's operational statistics.
    closed_today_ids = (
        JobTicketLog.objects
        .filter(
            action__in=['STATUS', 'CLOSED'],
            details__icontains="to 'Closed'",
            timestamp__range=(start_of_day, end_of_day),
        )
        .values_list('job_ticket_id', flat=True)
        .distinct()
    )
    todays_jobs_out_qs = JobTicket.objects.filter(
        id__in=closed_today_ids,
        status='Closed',
        created_at__range=(start_of_day, end_of_day),
    )
    todays_jobs_out = todays_jobs_out_qs.count()

    # Use JobTicketLog to find jobs that actually transitioned to 'Completed' today.
    # Using updated_at is wrong — it counts old Completed jobs whose updated_at
    # changed today for unrelated reasons (e.g. notes added, service logs updated).
    completed_today_ids = list(
        JobTicketLog.objects
        .filter(
            details__icontains="to 'Completed'",
            timestamp__range=(start_of_day, end_of_day),
        )
        .values_list('job_ticket_id', flat=True)
        .distinct()
    )
    todays_completed_jobs_qs = JobTicket.objects.filter(
        id__in=completed_today_ids,
        status='Completed',
    )
    todays_jobs_completed = todays_completed_jobs_qs.count()

    def today_service_totals(jobs_queryset):
        agg = ServiceLog.objects.filter(job_ticket__in=jobs_queryset).aggregate(
            parts=Coalesce(Sum('part_cost', output_field=DecimalField()), Decimal('0.00')),
            service=Coalesce(Sum('service_charge', output_field=DecimalField()), Decimal('0.00')),
        )
        spare_total = agg['parts']
        service_total = agg['service']
        return spare_total, service_total, spare_total + service_total

    todays_completed_spare, todays_completed_service, todays_completed_total = today_service_totals(todays_completed_jobs_qs)
    todays_closed_spare, todays_closed_service, todays_closed_total = today_service_totals(todays_jobs_out_qs)
    todays_total_spare = todays_completed_spare + todays_closed_spare
    todays_total_service = todays_completed_service + todays_closed_service

    # --- 3. PERIOD-BASED STATS (for tech/vendor performance tables) ---
    def parse_section_dates(start_str, end_str):
        if start_str and end_str:
            try:
                sd = datetime.strptime(start_str, '%Y-%m-%d').date()
                ed = datetime.strptime(end_str, '%Y-%m-%d').date()
                sd_aware = timezone.make_aware(datetime(sd.year, sd.month, sd.day))
                ed_aware = timezone.make_aware(datetime(ed.year, ed.month, ed.day, 23, 59, 59))
                return sd_aware, ed_aware, start_str, end_str
            except Exception:
                pass
        return start_of_period, end_of_period, period['start_date_str'], period['end_date_str']

    tech_start_str = request.GET.get('tech_start_date') or request.GET.get('perf_start_date')
    tech_end_str = request.GET.get('tech_end_date') or request.GET.get('perf_end_date')
    tech_start, tech_end, tech_start_date_str, tech_end_date_str = parse_section_dates(tech_start_str, tech_end_str)

    vendor_start_str = request.GET.get('vendor_start_date')
    vendor_end_str = request.GET.get('vendor_end_date')
    vendor_start, vendor_end, vendor_start_date_str, vendor_end_date_str = parse_section_dates(vendor_start_str, vendor_end_str)

    # Monthly period jobs (for summary counts/financials)
    monthly_finished_jobs_list = get_jobs_for_report_period(start_of_period, end_of_period, status_filter)
    monthly_finished_ids = [job.id for job in monthly_finished_jobs_list]
    monthly_finished_jobs = JobTicket.objects.filter(id__in=monthly_finished_ids)

    jobs_in_period = JobTicket.objects.filter(
        created_at__gte=start_of_period,
        created_at__lt=end_of_period,
    ).count()
    jobs_out_period = len(monthly_finished_ids)

    logs_in_period = ServiceLog.objects.filter(job_ticket__in=monthly_finished_ids)
    income_agg = logs_in_period.aggregate(
        parts=Coalesce(Sum('part_cost', output_field=DecimalField()), Decimal('0.00')),
        service=Coalesce(Sum('service_charge', output_field=DecimalField()), Decimal('0.00')),
    )
    monthly_income_parts = income_agg['parts']
    monthly_income_service = income_agg['service']
    monthly_vendor_expense = sum_vendor_net_cost(
        SpecializedService.objects.filter(job_ticket__in=monthly_finished_ids)
    )
    monthly_total_discounts = _sum_job_discounts(monthly_finished_jobs)
    monthly_total_income = _net_amount_after_discount(
        monthly_income_parts + monthly_income_service, monthly_total_discounts
    )
    monthly_net_profit = monthly_total_income - monthly_vendor_expense

    # Technician performance
    tech_finished_ids = [job.id for job in get_jobs_for_report_period(tech_start, tech_end)]
    tech_log_agg = (
        ServiceLog.objects.filter(job_ticket__in=tech_finished_ids)
        .exclude(description__icontains='Specialized Service')
        .values('job_ticket__assigned_to')
        .annotate(
            parts=Coalesce(Sum('part_cost', output_field=DecimalField()), Decimal('0.00')),
            service=Coalesce(Sum('service_charge', output_field=DecimalField()), Decimal('0.00')),
        )
    )
    tech_log_map = {row['job_ticket__assigned_to']: row for row in tech_log_agg}
    tech_count_map = {
        row['assigned_to']: row['cnt']
        for row in (
            JobTicket.objects.filter(id__in=tech_finished_ids, assigned_to__isnull=False)
            .values('assigned_to')
            .annotate(cnt=Count('id'))
        )
    }
    tech_profiles = list(
        TechnicianProfile.objects.filter(
            user__groups__name='Technicians',
            user__is_active=True,
        ).select_related('user')
    )
    for tp in tech_profiles:
        agg = tech_log_map.get(tp.id, {})
        tp.jobs_done = tech_count_map.get(tp.id, 0)
        tp.monthly_parts_sales = agg.get('parts', Decimal('0.00'))
        tp.monthly_service_sales = agg.get('service', Decimal('0.00'))
    monthly_tech_performance = sorted(tech_profiles, key=lambda x: x.jobs_done, reverse=True)

    # Vendor performance
    vendor_finished_ids = [
        job.id for job in get_jobs_for_report_period(vendor_start, vendor_end)
    ]
    vendor_finished_jobs = JobTicket.objects.filter(
        id__in=vendor_finished_ids, specialized_service__isnull=False
    )
    vendor_performance = Vendor.objects.annotate(
        total_jobs_given=Count('services', filter=Q(services__job_ticket__in=vendor_finished_jobs)),
        total_vendor_cost=Coalesce(
            Sum(vendor_net_cost_expression('services__'),
                filter=Q(services__job_ticket__in=vendor_finished_jobs),
                output_field=DecimalField()),
            Decimal('0.00'),
        ),
        total_client_charge=Coalesce(
            Sum('services__client_charge',
                filter=Q(services__job_ticket__in=vendor_finished_jobs),
                output_field=DecimalField()),
            Decimal('0.00'),
        ),
    ).annotate(
        profit=F('total_client_charge') - F('total_vendor_cost')
    ).order_by('-total_jobs_given')

    context = {
        # Today's Stats
        'todays_jobs_in': todays_jobs_in,
        'todays_jobs_out': todays_jobs_out,
        'todays_jobs_completed': todays_jobs_completed,
        'todays_total_spare': todays_total_spare,
        'todays_total_service': todays_total_service,
        'todays_completed_spare': todays_completed_spare,
        'todays_completed_service': todays_completed_service,
        'todays_completed_total': todays_completed_total,
        'todays_closed_spare': todays_closed_spare,
        'todays_closed_service': todays_closed_service,
        'todays_closed_total': todays_closed_total,
        # Date/period metadata
        'company_start_date': company_start_date.strftime('%Y-%m-%d'),
        'today_date_str': today_date_str,
        'current_report_start': period['start_date_str'],
        'current_report_end': period['end_date_str'],
        'tech_start_date': tech_start_date_str,
        'tech_end_date': tech_end_date_str,
        'vendor_start_date': vendor_start_date_str,
        'vendor_end_date': vendor_end_date_str,
        'status_filter': status_filter or 'ALL',
        'current_report_date': start_of_period,
        # Period financials
        'jobs_created_in_period': jobs_in_period,
        'jobs_finished_in_period': jobs_out_period,
        'monthly_total_income': monthly_total_income,
        'monthly_income_parts': monthly_income_parts,
        'monthly_income_service': monthly_income_service,
        'monthly_vendor_expense': monthly_vendor_expense,
        'monthly_net_profit': monthly_net_profit,
        'monthly_total_discounts': monthly_total_discounts,
        'monthly_completed_jobs_count': jobs_out_period,
        # All-Time Stats
        'all_jobs_count': status_counts['all_jobs_count'],
        'completed_count': status_counts['completed_count'],
        'pending_count': status_counts['pending_count'],
        'in_progress_count': status_counts['in_progress_count'],
        'ready_for_pickup_count': status_counts['ready_for_pickup_count'],
        'returned_count': returned_count,
        'closed_count': status_counts['closed_count'],
        # The legacy archive markup is hidden; do not render every closed job (N+1 queries).
        'closed_jobs': (),
        # Performance
        'monthly_tech_performance': monthly_tech_performance,
        'vendor_performance': vendor_performance,
    }
    return render(request, 'job_tickets/reports_dashboard.html', context)

@login_required
def reports_chart_data(request):
    """Return JSON aggregates (monthly + yearly) for the Reports Dashboard charts.

    Accepts the same query params as `reports_dashboard` (start_date, end_date, status_filter, preset).
    Uses `get_report_period()` so it shares the same defaults and timezone handling.
    """
    access = get_staff_access(request.user)
    if not request.user.is_staff or not access.get("reports_overview"):
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    period = get_report_period(request)
    start_of_period = period['start']
    end_of_period = period['end']
    status_filter = request.GET.get('status_filter')

    finished_statuses = ['Completed', 'Closed']

    # Helper to apply status filter onto a base Q
    def apply_status_filter(q):
        if status_filter == 'ALL_FINISHED':
            q &= Q(status__in=finished_statuses)
        elif status_filter == 'ACTIVE_WORKLOAD':
            q &= Q(status__in=['Under Inspection', 'Repairing', 'Specialized Service'])
        elif status_filter and status_filter != 'ALL':
            q &= Q(status=status_filter)
        return q

    # Iterate month-by-month from start_of_period (inclusive) to end_of_period (exclusive)
    monthly = []
    current = start_of_period
    while current < end_of_period:
        # month start is current
        month_start = current
        # compute next month start
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1, day=1)

        # Get jobs for this month using vendor concept
        monthly_jobs_list = get_jobs_for_report_period(month_start, next_month, status_filter)
        jobs_qs = JobTicket.objects.filter(id__in=[job.id for job in monthly_jobs_list])
        jobs_count = len(monthly_jobs_list)

        logs_qs = ServiceLog.objects.filter(job_ticket__in=jobs_qs)
        parts_total = logs_qs.aggregate(total=Coalesce(Sum('part_cost', output_field=DecimalField()), Decimal('0.00')))['total']
        service_total = logs_qs.aggregate(total=Coalesce(Sum('service_charge', output_field=DecimalField()), Decimal('0.00')))['total']
        discount_total = _sum_job_discounts(jobs_qs)
        total_income = _net_amount_after_discount(parts_total + service_total, discount_total)

        vendor_qs = SpecializedService.objects.filter(job_ticket__in=jobs_qs)
        vendor_expense = sum_vendor_net_cost(vendor_qs)

        monthly.append({
            'label': month_start.strftime('%Y-%m'),
            'jobs_finished': int(jobs_count),
            'parts_income': float(parts_total),
            'service_income': float(service_total),
            'discount_total': float(discount_total),
            'total_income': float(total_income),
            'vendor_expense': float(vendor_expense),
            'net_profit': float(total_income - vendor_expense),
        })

        current = next_month

    # Yearly aggregates: compute year by year in the same range
    yearly = []
    start_year = start_of_period.year
    end_year = (end_of_period - timedelta(seconds=1)).year
    for yr in range(start_year, end_year + 1):
        y_start = timezone.make_aware(datetime(yr, 1, 1))
        y_end = timezone.make_aware(datetime(yr + 1, 1, 1))
        
        # Get jobs for this year using vendor concept
        yearly_jobs_list = get_jobs_for_report_period(y_start, y_end, status_filter)
        jobs_qs = JobTicket.objects.filter(id__in=[job.id for job in yearly_jobs_list])
        jobs_count = len(yearly_jobs_list)

        logs_qs = ServiceLog.objects.filter(job_ticket__in=jobs_qs)
        parts_total = logs_qs.aggregate(total=Coalesce(Sum('part_cost', output_field=DecimalField()), Decimal('0.00')))['total']
        service_total = logs_qs.aggregate(total=Coalesce(Sum('service_charge', output_field=DecimalField()), Decimal('0.00')))['total']
        discount_total = _sum_job_discounts(jobs_qs)
        total_income = _net_amount_after_discount(parts_total + service_total, discount_total)

        vendor_qs = SpecializedService.objects.filter(job_ticket__in=jobs_qs)
        vendor_expense = sum_vendor_net_cost(vendor_qs)

        yearly.append({
            'year': yr,
            'jobs_finished': int(jobs_count),
            'discount_total': float(discount_total),
            'total_income': float(total_income),
            'vendor_expense': float(vendor_expense),
            'net_profit': float(total_income - vendor_expense),
        })

    return JsonResponse({'monthly': monthly, 'yearly': yearly})

# job_tickets/views.py

# job_tickets/views.py

def _build_technician_report_context(request, tech_id):
    finished_statuses = ['Completed', 'Closed']
    technician = get_object_or_404(TechnicianProfile, id=tech_id)

    # 1. GET DATE FILTERS from URL (These are passed from the Reports Dashboard)
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    # Start with base filters: assigned technician and finished statuses
    jobs_filter = Q(assigned_to=technician, status__in=finished_statuses)

    # 2. APPLY DATE FILTERING
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            if end_date < start_date:
                start_date, end_date = end_date, start_date
                start_date_str = start_date.isoformat()
                end_date_str = end_date.isoformat()

            # Create Timezone-Aware Boundaries
            start_of_period = timezone.make_aware(datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0))
            end_of_period = timezone.make_aware(datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59))

            # Filter jobs by the date they were last updated (completion/closure date)
            jobs_filter &= Q(updated_at__gte=start_of_period, updated_at__lte=end_of_period)

        except ValueError:
            messages.error(request, "Invalid date format provided for report filtering.")
            # If dates are bad, the report defaults to All Time (jobs_filter remains simple)
            start_date_str = None
            end_date_str = None
    else:
        # If no dates provided, ensure variables are None to display 'All Time' header
        start_date_str = None
        end_date_str = None

    # 3. Fetch Jobs
    jobs = list(
        JobTicket.objects.filter(jobs_filter)
        .prefetch_related('service_logs')
        .order_by('-updated_at', '-id')
    )

    # 4. Calculate Totals excluding vendor service charges
    calculate_job_totals(jobs, exclude_vendor_charges=True)

    total_parts_all = sum(job.part_total for job in jobs)
    total_services_all = sum(job.service_total for job in jobs)
    total_discounts_all = Decimal('0.00')
    total_income = Decimal('0.00')
    for job in jobs:
        job.discount_total = _money_or_zero(job.discount_amount)
        job.net_total = _net_amount_after_discount(job.total, job.discount_total)
        job.device_label = ' '.join(
            part for part in [job.device_type, job.device_brand, job.device_model]
            if part
        )
        job.report_date = job.updated_at
        total_discounts_all += job.discount_total
        total_income += job.net_total

    jobs_count = len(jobs)
    completed_count = sum(1 for job in jobs if job.status == 'Completed')
    closed_count = sum(1 for job in jobs if job.status == 'Closed')
    average_income = total_income / jobs_count if jobs_count else Decimal('0.00')
    technician_name = technician.user.get_full_name() or technician.user.username
    period_query = ''
    if start_date_str and end_date_str:
        period_query = urlencode({'start_date': start_date_str, 'end_date': end_date_str})

    return {
        'company': CompanyProfile.get_profile(getattr(request, 'current_workspace', None)),
        'technician': technician,
        'technician_name': technician_name,
        'jobs': jobs,
        'jobs_count': jobs_count,
        'completed_count': completed_count,
        'closed_count': closed_count,
        'total_parts': total_parts_all,
        'total_services': total_services_all,
        'total_discounts': total_discounts_all,
        'total_income': total_income,
        'average_income': average_income,
        # Pass dates for display in the report header
        'report_start_date': start_date_str,
        'report_end_date': end_date_str,
        'period_query': period_query,
        'generated_at': timezone.now(),
    }


@login_required
def technician_report_print(request, tech_id):
    denied = _staff_access_required(request, "reports_technician")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')

    context = _build_technician_report_context(request, tech_id)
    return render(request, 'job_tickets/technician_report_print.html', context)


@login_required
def technician_report_export_csv(request, tech_id):
    denied = _staff_access_required(request, "reports_technician")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')

    context = _build_technician_report_context(request, tech_id)
    safe_name = re.sub(r'[^A-Za-z0-9_-]+', '-', context['technician_name']).strip('-') or 'technician'
    if context['report_start_date'] and context['report_end_date']:
        period_text = f"{context['report_start_date']}_to_{context['report_end_date']}"
    else:
        period_text = 'all_time'
    filename = f"technician_report_{safe_name}_{period_text}.csv"

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    def money(value):
        return f"{(_money_or_zero(value)):.2f}"

    writer = csv.writer(response)
    writer.writerow(['Technician Report'])
    writer.writerow(['Technician', context['technician_name']])
    writer.writerow([
        'Period',
        f"{context['report_start_date']} to {context['report_end_date']}"
        if context['report_start_date'] and context['report_end_date']
        else 'All Time Completed/Closed Jobs',
    ])
    writer.writerow(['Generated At', timezone.localtime(context['generated_at']).strftime('%Y-%m-%d %H:%M')])
    writer.writerow([])
    writer.writerow(['Summary'])
    writer.writerow(['Jobs Counted', context['jobs_count']])
    writer.writerow(['Completed Jobs', context['completed_count']])
    writer.writerow(['Closed Jobs', context['closed_count']])
    writer.writerow(['Total Parts Sales', money(context['total_parts'])])
    writer.writerow(['Total Service Sales', money(context['total_services'])])
    writer.writerow(['Total Discounts', money(context['total_discounts'])])
    writer.writerow(['Net Income', money(context['total_income'])])
    writer.writerow(['Average Net Per Job', money(context['average_income'])])
    writer.writerow([])
    writer.writerow([
        'Job Code',
        'Customer',
        'Phone',
        'Device',
        'Status',
        'Report Date',
        'Part Cost',
        'Service Charge',
        'Discount',
        'Net Total',
        'Job URL',
    ])
    for job in context['jobs']:
        writer.writerow([
            job.job_code,
            job.customer_name,
            job.customer_phone,
            job.device_label,
            job.status,
            timezone.localtime(job.report_date).strftime('%Y-%m-%d %H:%M') if job.report_date else '',
            money(job.part_total),
            money(job.service_total),
            money(job.discount_total),
            money(job.net_total),
            request.build_absolute_uri(reverse('staff_job_detail', args=[job.job_code])),
        ])

    return response

@login_required
def print_pending_jobs_report(request):
    access = get_staff_access(request.user)
    if not request.user.is_staff or not access.get("reports_overview"):
        return redirect('unauthorized')
    
    pending_jobs = list(JobTicket.objects.filter(status='Pending').prefetch_related('service_logs').order_by('created_at'))
    calculate_job_totals(pending_jobs)
    for job in pending_jobs:
        job.discount_total = _money_or_zero(job.discount_amount)
        job.net_total = _net_amount_after_discount(job.total, job.discount_total)
    company = CompanyProfile.get_profile()
    
    context = {
        'pending_jobs': pending_jobs,
        'report_date': datetime.now(),
        'company': company,
    }
    return render(request, 'job_tickets/print_pending_jobs_report.html', context)

@login_required
def print_monthly_summary_report(request):
    denied = _staff_access_required(request, "reports_financial")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')

    period = resolve_monthly_summary_period(request)
    context = get_monthly_summary_context(
        period['start_of_period'],
        period['end_of_period'],
        period['start_date_str'],
        period['end_date_str'],
        preset=period['preset'],
        show_jobs=period['show_jobs'],
    )
    return render(request, 'job_tickets/print_monthly_summary_report.html', context)

@login_required
def export_monthly_summary_csv(request):
    denied = _staff_access_required(request, "reports_financial")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')

    period = resolve_monthly_summary_period(request)
    context = get_monthly_summary_context(
        period['start_of_period'],
        period['end_of_period'],
        period['start_date_str'],
        period['end_date_str'],
        preset=period['preset'],
        show_jobs='',
    )

    def money(value):
        return f"{(value or Decimal('0.00')):.2f}"

    filename = f"financial_summary_{period['start_date_str']}_to_{period['end_date_str']}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow(['Financial Summary Report'])
    writer.writerow(['Period', f"{period['start_date_str']} to {period['end_date_str']}"])
    writer.writerow(['Basis', 'Closed jobs only for financial totals'])
    writer.writerow(['Unclaimed / Ready Basis', 'All-time jobs with Completed or Ready for Pickup status'])
    writer.writerow([])
    writer.writerow(['Job Statistics'])
    writer.writerow(['Jobs Created', context['jobs_created_count']])
    writer.writerow(['Jobs Closed', context['jobs_closed_count']])
    writer.writerow(['Current Month In Jobs Closed', context['current_month_in_closed_count']])
    writer.writerow(['Previous Month In Jobs Closed', context['previous_month_in_closed_count']])
    writer.writerow(['All-time Unclaimed / Ready Jobs', context['pending_completed_count']])
    writer.writerow(['All-time Unclaimed / Ready Value', money(context['pending_completed_value'])])
    writer.writerow(['All-time Ready for Pickup Jobs', context['ready_for_pickup_count']])
    writer.writerow(['All-time Ready for Pickup Value', money(context['ready_for_pickup_value'])])
    writer.writerow(['Returned -> Closed Jobs', context['jobs_returned_count']])
    writer.writerow(['Closed Vendor Jobs', context['vendor_jobs_count']])
    writer.writerow([])

    writer.writerow(['Closed Job Source Split'])
    writer.writerow(['Source', 'Revenue', 'Expense', 'Profit'])
    writer.writerow([
        'Current Month In Jobs Closed',
        money(context['current_month_in_closed_revenue']),
        money(context['current_month_in_closed_expense']),
        money(context['current_month_in_closed_profit']),
    ])
    writer.writerow([
        'Previous Month In Jobs Closed',
        money(context['previous_month_in_closed_revenue']),
        money(context['previous_month_in_closed_expense']),
        money(context['previous_month_in_closed_profit']),
    ])
    writer.writerow([])

    writer.writerow(['Closed Job Financial Summary'])
    writer.writerow(['Closed Revenue', money(context['overall_revenue'])])
    writer.writerow(['Closed Expense', money(context['overall_expense'])])
    writer.writerow(['Closed Profit', money(context['overall_profit'])])
    writer.writerow(['Overall Margin %', f"{(context['overall_margin'] or Decimal('0.00')):.2f}"])
    writer.writerow(['Gross Revenue Before Discount', money(context['closed_gross_revenue'])])
    writer.writerow(['Total Discount Applied Once', money(context['total_discounts'])])
    writer.writerow([])

    writer.writerow(['Closed Job Financial Blocks'])
    writer.writerow(['Block', 'Basis', 'Revenue', 'Expense', 'Profit'])
    for block in context['closed_financial_blocks']:
        writer.writerow([
            block['label'],
            block['note'],
            money(block['revenue']),
            money(block['expense']),
            money(block['profit']),
        ])
    writer.writerow([])

    writer.writerow(['Stock Sales Summary'])
    writer.writerow(['Units Sold', context['stock_sales_units']])
    writer.writerow(['Sale Lines', context['stock_sale_lines_count']])
    writer.writerow(['Unique Products', context['stock_products_count']])
    writer.writerow(['Average Sale Value', money(context['stock_avg_sale_value'])])
    writer.writerow([])

    writer.writerow(['Product-wise Stock Sales'])
    writer.writerow(['Product', 'SKU', 'Category', 'Units Sold', 'Sale Lines', 'Avg Unit Price', 'Revenue', 'COGS', 'Profit'])
    for product_row in context['stock_products_breakdown']:
        writer.writerow([
            product_row['name'],
            product_row['sku'],
            product_row['category'],
            product_row['units_sold'],
            product_row['sale_lines'],
            money(product_row['average_unit_price']),
            money(product_row['revenue']),
            money(product_row['cogs']),
            money(product_row['profit']),
        ])

    return response

@login_required
def print_monthly_summary_pdf(request):
    denied = _staff_access_required(request, "reports_financial")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')

    period = resolve_monthly_summary_period(request)
    context = get_monthly_summary_context(
        period['start_of_period'],
        period['end_of_period'],
        period['start_date_str'],
        period['end_date_str'],
        preset=period['preset'],
        show_jobs='',
    )
    context['pdf_layout'] = True
    return render(request, 'job_tickets/print_monthly_summary_pdf.html', context)

# in job_tickets/views.py

@login_required
def staff_technician_reports(request):
    # only staff allowed
    denied = _staff_access_required(request, "reports_technician")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')

    # get all technicians — active only
    techs = TechnicianProfile.objects.filter(
        user__is_active=True,
    ).select_related('user').all()

    # Use aggregated DB queries instead of N+1 Python loops
    from django.db.models import Count, Sum, DecimalField
    from django.db.models.functions import Coalesce

    tech_stats = TechnicianProfile.objects.filter(
        id__in=[t.id for t in techs]
    ).annotate(
        completed_count=Count(
            'jobticket',
            filter=Q(jobticket__status='Completed'),
            distinct=True,
        ),
        parts_total=Coalesce(
            Sum(
                'jobticket__service_logs__part_cost',
                filter=Q(
                    jobticket__status='Completed',
                ) & ~Q(jobticket__service_logs__description__icontains='Specialized Service'),
                output_field=DecimalField(),
            ),
            Decimal('0.00'),
        ),
        service_total=Coalesce(
            Sum(
                'jobticket__service_logs__service_charge',
                filter=Q(
                    jobticket__status='Completed',
                ) & ~Q(jobticket__service_logs__description__icontains='Specialized Service'),
                output_field=DecimalField(),
            ),
            Decimal('0.00'),
        ),
    )
    stats_map = {s.id: s for s in tech_stats}
    tech_rows = []
    for tech in techs:
        s = stats_map.get(tech.id, tech)
        tech_rows.append({
            'tech': tech,
            'completed_count': getattr(s, 'completed_count', 0) or 0,
            'parts_total': getattr(s, 'parts_total', Decimal('0.00')) or Decimal('0.00'),
            'service_total': getattr(s, 'service_total', Decimal('0.00')) or Decimal('0.00'),
        })

    return render(request, 'job_tickets/staff_technician_reports.html', {'tech_rows': tech_rows})

@login_required
def daily_jobs_report(request, date_str, filter_type):
    access = get_staff_access(request.user)
    if not request.user.is_staff or not access.get("reports_overview"):
        return redirect('unauthorized')

    try:
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        messages.error(request, "Invalid date format provided.")
        return redirect('reports_dashboard')

    start_of_day = timezone.make_aware(datetime.combine(report_date, datetime.min.time()))
    end_of_day = timezone.make_aware(datetime.combine(report_date, datetime.max.time()))

    jobs_queryset = JobTicket.objects.all().order_by('-created_at')
    report_title = f"Jobs Report for {report_date.strftime('%B %d, %Y')}"

    if filter_type == 'in':
        jobs_queryset = jobs_queryset.filter(created_at__range=(start_of_day, end_of_day))
        report_title = f"Jobs Created On {date_str}"
    elif filter_type == 'out':
        closed_job_ids = (
            JobTicketLog.objects
            .filter(
                action__in=['STATUS', 'CLOSED'],
                details__icontains="to 'Closed'",
                timestamp__range=(start_of_day, end_of_day),
            )
            .values_list('job_ticket_id', flat=True)
            .distinct()
        )
        jobs_queryset = jobs_queryset.filter(
            id__in=closed_job_ids,
            status='Closed',
            created_at__range=(start_of_day, end_of_day),
        )
        report_title = f"Jobs Closed On {date_str}"
    elif filter_type == 'completed':
        jobs_queryset = jobs_queryset.filter(
            status='Completed',
            updated_at__range=(start_of_day, end_of_day)
        )
        report_title = f"Jobs Completed On {date_str}"
    else:
        messages.error(request, "Invalid filter type provided.")
        return redirect('reports_dashboard')

    jobs = list(jobs_queryset.prefetch_related('service_logs'))
    calculate_job_totals(jobs)
    for job in jobs:
        job.discount_total = _money_or_zero(job.discount_amount)
        job.net_total = _net_amount_after_discount(job.total, job.discount_total)

    context = {
        'jobs': jobs,
        'report_title': report_title,
    }
    return render(request, 'job_tickets/daily_jobs_report.html', context)


# ---------------------------------------------------------------------------
# 1. SERVICE JOB REPORT
# ---------------------------------------------------------------------------

def _build_service_job_report_context(request):
    """Build context for the Service Job Report (all jobs with service/financial fields)."""
    period = get_report_period(request)
    start_of_period = period['start']
    end_of_period = period['end']
    status_filter = request.GET.get('status_filter', '').strip()

    # Base queryset — all statuses unless filtered
    jobs_qs = (
        JobTicket.objects
        .select_related('assigned_to__user', 'created_by', 'specialized_service__vendor')
        .prefetch_related('service_logs', 'logs')
        .order_by('created_at')
    )

    # Date filter: created_at in period
    jobs_qs = jobs_qs.filter(created_at__gte=start_of_period, created_at__lt=end_of_period)

    # Optional status filter
    status_choices = [c[0] for c in JobTicket.STATUS_CHOICES]
    if status_filter and status_filter in status_choices:
        jobs_qs = jobs_qs.filter(status=status_filter)

    jobs = list(jobs_qs)
    calculate_job_totals(jobs)

    def _find_log_date(job, action_keyword):
        """Return the earliest log timestamp matching a keyword in details."""
        for log in sorted(job.logs.all(), key=lambda l: l.timestamp):
            if action_keyword in (log.details or ''):
                return log.timestamp
        return None

    for job in jobs:
        job.discount_total = _money_or_zero(job.discount_amount)
        job.net_amount = _net_amount_after_discount(job.total, job.discount_total)
        job.technician_id = job.assigned_to.unique_id if job.assigned_to else ''
        job.technician_name = (
            job.assigned_to.user.get_full_name() or job.assigned_to.user.username
            if job.assigned_to else ''
        )
        # Derive key event timestamps from the audit log
        job.completed_date = _find_log_date(job, "to 'Completed'")
        job.ready_date = _find_log_date(job, "to 'Ready for Pickup'")
        job.closed_date = job.closed_at or _find_log_date(job, "to 'Closed'")
        # Service type / problem description summary
        job.service_summary = '; '.join(
            log.description for log in job.service_logs.all()
        ) or job.reported_issue[:80]

    total_jobs = len(jobs)
    total_service_charge = sum(j.service_total for j in jobs)
    total_parts_cost = sum(j.part_total for j in jobs)
    total_discounts = sum(j.discount_total for j in jobs)
    total_net = sum(j.net_amount for j in jobs)

    return {
        'jobs': jobs,
        'total_jobs': total_jobs,
        'total_service_charge': total_service_charge,
        'total_parts_cost': total_parts_cost,
        'total_discounts': total_discounts,
        'total_net': total_net,
        'report_start_date': period['start_date_str'],
        'report_end_date': period['end_date_str'],
        'status_filter': status_filter,
        'status_choices': status_choices,
        'generated_at': timezone.now(),
        'company': CompanyProfile.get_profile(getattr(request, 'current_workspace', None)),
    }


@login_required
def service_job_report(request):
    denied = _staff_access_required(request, "reports_overview")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')
    context = _build_service_job_report_context(request)
    return render(request, 'job_tickets/service_job_report.html', context)


@login_required
def service_job_report_export_csv(request):
    denied = _staff_access_required(request, "reports_overview")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')

    context = _build_service_job_report_context(request)
    filename = f"service_job_report_{context['report_start_date']}_to_{context['report_end_date']}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    def money(v):
        return f"{_money_or_zero(v):.2f}"

    def fmt_dt(dt):
        if not dt:
            return ''
        return timezone.localtime(dt).strftime('%Y-%m-%d %H:%M')

    writer = csv.writer(response)
    writer.writerow(['Service Job Report'])
    writer.writerow(['Period', f"{context['report_start_date']} to {context['report_end_date']}"])
    writer.writerow(['Status Filter', context['status_filter'] or 'All'])
    writer.writerow(['Generated At', timezone.localtime(context['generated_at']).strftime('%Y-%m-%d %H:%M')])
    writer.writerow([])
    writer.writerow(['Summary'])
    writer.writerow(['Total Jobs', context['total_jobs']])
    writer.writerow(['Total Service Charge', money(context['total_service_charge'])])
    writer.writerow(['Total Parts Cost', money(context['total_parts_cost'])])
    writer.writerow(['Total Discounts', money(context['total_discounts'])])
    writer.writerow(['Total Net Amount', money(context['total_net'])])
    writer.writerow([])
    writer.writerow([
        'Job ID', 'Created Date/Time', 'Customer', 'Phone',
        'Device Type', 'Device Brand', 'Device Model', 'Device Serial',
        'Service Type / Problem', 'Technician ID', 'Technician Name',
        'Branch', 'Current Status', 'Is Warranty',
        'Completed Date/Time', 'Ready-for-Pickup Date/Time', 'Closed Date/Time',
        'Service Charge', 'Parts Cost', 'Discount', 'Net Amount',
    ])
    for job in context['jobs']:
        writer.writerow([
            job.job_code,
            fmt_dt(job.created_at),
            job.customer_name,
            job.customer_phone,
            job.device_type,
            job.device_brand,
            job.device_model,
            job.device_serial,
            job.service_summary,
            job.technician_id,
            job.technician_name,
            getattr(job, 'branch', ''),
            job.status,
            'Yes' if job.is_under_warranty else 'No',
            fmt_dt(job.completed_date),
            fmt_dt(job.ready_date),
            fmt_dt(job.closed_date),
            money(job.service_total),
            money(job.part_total),
            money(job.discount_total),
            money(job.net_amount),
        ])
    return response


# ---------------------------------------------------------------------------
# 2. JOB STATUS HISTORY REPORT
# ---------------------------------------------------------------------------

def _build_job_status_history_context(request):
    """Build context for the Job Status History Report."""
    period = get_report_period(request)
    start_of_period = period['start']
    end_of_period = period['end']
    job_code_filter = request.GET.get('job_code', '').strip()

    logs_qs = (
        JobTicketLog.objects
        .select_related('job_ticket', 'user')
        .filter(action='STATUS', timestamp__gte=start_of_period, timestamp__lt=end_of_period)
        .order_by('job_ticket__job_code', 'timestamp')
    )

    if job_code_filter:
        logs_qs = logs_qs.filter(job_ticket__job_code__icontains=job_code_filter)

    # Parse "Status changed from 'X' to 'Y'" out of the details field
    import re as _re
    STATUS_CHANGE_PATTERN = _re.compile(
        r"[Ss]tatus changed from ['\"]?(?P<old>[^'\"]+)['\"]? to ['\"]?(?P<new>[^'\"]+)['\"]?"
    )

    history_rows = []
    for log in logs_qs:
        old_status = ''
        new_status = ''
        m = STATUS_CHANGE_PATTERN.search(log.details or '')
        if m:
            old_status = m.group('old').strip(" '\"")
            new_status = m.group('new').strip(" '\"")
        history_rows.append({
            'job_id': log.job_ticket.job_code,
            'old_status': old_status or '—',
            'new_status': new_status or log.details[:60],
            'changed_at': log.timestamp,
            'changed_by': log.user.get_full_name() or log.user.username if log.user else 'System',
        })

    return {
        'history_rows': history_rows,
        'total_rows': len(history_rows),
        'report_start_date': period['start_date_str'],
        'report_end_date': period['end_date_str'],
        'job_code_filter': job_code_filter,
        'generated_at': timezone.now(),
        'company': CompanyProfile.get_profile(getattr(request, 'current_workspace', None)),
    }


@login_required
def job_status_history_report(request):
    denied = _staff_access_required(request, "reports_overview")
    if denied:
        return denied
    context = _build_job_status_history_context(request)
    return render(request, 'job_tickets/job_status_history_report.html', context)


@login_required
def job_status_history_report_export_csv(request):
    denied = _staff_access_required(request, "reports_overview")
    if denied:
        return denied

    context = _build_job_status_history_context(request)
    filename = f"job_status_history_{context['report_start_date']}_to_{context['report_end_date']}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    def fmt_dt(dt):
        if not dt:
            return ''
        return timezone.localtime(dt).strftime('%Y-%m-%d %H:%M')

    writer = csv.writer(response)
    writer.writerow(['Job Status History Report'])
    writer.writerow(['Period', f"{context['report_start_date']} to {context['report_end_date']}"])
    if context['job_code_filter']:
        writer.writerow(['Job Code Filter', context['job_code_filter']])
    writer.writerow(['Total Rows', context['total_rows']])
    writer.writerow(['Generated At', timezone.localtime(context['generated_at']).strftime('%Y-%m-%d %H:%M')])
    writer.writerow([])
    writer.writerow(['Job ID', 'Old Status', 'New Status', 'Status Changed Date/Time', 'Changed By'])
    for row in context['history_rows']:
        writer.writerow([
            row['job_id'],
            row['old_status'],
            row['new_status'],
            fmt_dt(row['changed_at']),
            row['changed_by'],
        ])
    return response


# ---------------------------------------------------------------------------
# 3. JOB PARTS / SPARE PARTS REPORT
# ---------------------------------------------------------------------------

def _build_job_parts_report_context(request):
    """Build context for the Job Parts / Spare Parts Report."""
    period = get_report_period(request)
    start_of_period = period['start']
    end_of_period = period['end']
    technician_id = request.GET.get('technician_id', '').strip()

    # Start from ProductSale (preferred — has part code, qty, unit price, cost)
    ps_qs = (
        ProductSale.objects
        .select_related('job_ticket__assigned_to__user', 'product', 'service_log')
        .filter(job_ticket__created_at__gte=start_of_period, job_ticket__created_at__lt=end_of_period)
        .order_by('job_ticket__job_code', 'sold_at')
    )

    if technician_id:
        ps_qs = ps_qs.filter(job_ticket__assigned_to__id=technician_id)

    part_rows = []
    for ps in ps_qs:
        job = ps.job_ticket
        tp = job.assigned_to
        part_rows.append({
            'job_id': job.job_code,
            'part_code': ps.product.sku or '—',
            'part_name': ps.product.name,
            'quantity': ps.quantity,
            'unit_price': ps.unit_price,
            'cost': ps.line_cost,
            'selling_amount': ps.line_total,
            'technician': (tp.user.get_full_name() or tp.user.username) if tp else '—',
        })

    # Also capture manual service-log lines that are NOT linked to ProductSale
    # (legacy parts logged as plain ServiceLog entries with part_cost > 0)
    all_product_sale_log_ids = set(
        ProductSale.objects.filter(
            service_log__isnull=False,
            job_ticket__created_at__gte=start_of_period,
            job_ticket__created_at__lt=end_of_period,
        ).values_list('service_log_id', flat=True)
    )
    manual_logs_qs = (
        ServiceLog.objects
        .select_related('job_ticket__assigned_to__user')
        .filter(
            job_ticket__created_at__gte=start_of_period,
            job_ticket__created_at__lt=end_of_period,
            part_cost__isnull=False,
        )
        .exclude(id__in=all_product_sale_log_ids)
        .order_by('job_ticket__job_code', 'created_at')
    )
    if technician_id:
        manual_logs_qs = manual_logs_qs.filter(job_ticket__assigned_to__id=technician_id)

    for log in manual_logs_qs:
        job = log.job_ticket
        tp = job.assigned_to
        part_rows.append({
            'job_id': job.job_code,
            'part_code': '—',
            'part_name': log.description,
            'quantity': 1,
            'unit_price': _money_or_zero(log.part_cost),
            'cost': Decimal('0.00'),
            'selling_amount': _money_or_zero(log.part_cost),
            'technician': (tp.user.get_full_name() or tp.user.username) if tp else '—',
        })

    total_qty = sum(r['quantity'] for r in part_rows)
    total_cost = sum(r['cost'] for r in part_rows)
    total_selling = sum(r['selling_amount'] for r in part_rows)

    technicians = list(
        TechnicianProfile.objects.filter(
            user__is_active=True,
        ).select_related('user').order_by('user__username')
    )

    return {
        'part_rows': part_rows,
        'total_rows': len(part_rows),
        'total_qty': total_qty,
        'total_cost': total_cost,
        'total_selling': total_selling,
        'report_start_date': period['start_date_str'],
        'report_end_date': period['end_date_str'],
        'technician_id': technician_id,
        'technicians': technicians,
        'generated_at': timezone.now(),
        'company': CompanyProfile.get_profile(getattr(request, 'current_workspace', None)),
    }


@login_required
def job_parts_report(request):
    denied = _staff_access_required(request, "reports_overview")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')
    context = _build_job_parts_report_context(request)
    return render(request, 'job_tickets/job_parts_report.html', context)


@login_required
def job_parts_report_export_csv(request):
    denied = _staff_access_required(request, "reports_overview")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')

    context = _build_job_parts_report_context(request)
    filename = f"job_parts_report_{context['report_start_date']}_to_{context['report_end_date']}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    def money(v):
        return f"{_money_or_zero(v):.2f}"

    writer = csv.writer(response)
    writer.writerow(['Job Parts / Spare Parts Report'])
    writer.writerow(['Period', f"{context['report_start_date']} to {context['report_end_date']}"])
    writer.writerow(['Total Rows', context['total_rows']])
    writer.writerow(['Total Qty', context['total_qty']])
    writer.writerow(['Total Cost (COGS)', money(context['total_cost'])])
    writer.writerow(['Total Selling Amount', money(context['total_selling'])])
    writer.writerow(['Generated At', timezone.localtime(context['generated_at']).strftime('%Y-%m-%d %H:%M')])
    writer.writerow([])
    writer.writerow(['Job ID', 'Part Code', 'Part Name', 'Quantity', 'Unit Price', 'Cost (COGS)', 'Selling Amount', 'Technician'])
    for row in context['part_rows']:
        writer.writerow([
            row['job_id'],
            row['part_code'],
            row['part_name'],
            row['quantity'],
            money(row['unit_price']),
            money(row['cost']),
            money(row['selling_amount']),
            row['technician'],
        ])
    return response


# ---------------------------------------------------------------------------
# 4. TECHNICIAN MASTER REPORT
# ---------------------------------------------------------------------------

def _build_technician_master_context(request):
    """Build context for the Technician Master listing."""
    search_q = request.GET.get('q', '').strip()

    technicians_qs = (
        TechnicianProfile.objects
        .select_related('user', 'workspace')
        .order_by('unique_id')
    )

    if search_q:
        technicians_qs = technicians_qs.filter(
            Q(user__username__icontains=search_q) |
            Q(user__first_name__icontains=search_q) |
            Q(user__last_name__icontains=search_q) |
            Q(unique_id__icontains=search_q)
        )

    # Annotate with aggregate job counts
    technicians_qs = technicians_qs.annotate(
        total_jobs=Count('assignments', filter=Q(assignments__status='accepted'), distinct=True),
        active_jobs=Count(
            'jobticket',
            filter=Q(jobticket__status__in=['Under Inspection', 'Repairing', 'Specialized Service']),
            distinct=True,
        ),
        completed_jobs=Count(
            'jobticket',
            filter=Q(jobticket__status__in=['Completed', 'Closed']),
            distinct=True,
        ),
    )

    rows = []
    for tp in technicians_qs:
        user = tp.user
        rows.append({
            'technician_id': tp.unique_id,
            'name': user.get_full_name() or user.username,
            'username': user.username,
            'email': user.email,
            'branch': getattr(tp, 'branch', ''),
            'department': getattr(tp, 'department', ''),
            'joining_date': user.date_joined,
            'is_active': user.is_active,
            'total_jobs': tp.total_jobs,
            'active_jobs': tp.active_jobs,
            'completed_jobs': tp.completed_jobs,
            'tp_id': tp.id,
        })

    return {
        'rows': rows,
        'total_technicians': len(rows),
        'active_count': sum(1 for r in rows if r['is_active']),
        'inactive_count': sum(1 for r in rows if not r['is_active']),
        'search_q': search_q,
        'generated_at': timezone.now(),
        'company': CompanyProfile.get_profile(getattr(request, 'current_workspace', None)),
    }


@login_required
def technician_master_report(request):
    denied = _staff_access_required(request, "reports_technician")
    if denied:
        return denied
    context = _build_technician_master_context(request)
    return render(request, 'job_tickets/technician_master_report.html', context)


@login_required
def technician_master_report_export_csv(request):
    denied = _staff_access_required(request, "reports_technician")
    if denied:
        return denied

    context = _build_technician_master_context(request)
    filename = f"technician_master_{timezone.localdate().isoformat()}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    def fmt_dt(dt):
        if not dt:
            return ''
        return timezone.localtime(dt).strftime('%Y-%m-%d %H:%M')

    writer = csv.writer(response)
    writer.writerow(['Technician Master Report'])
    writer.writerow(['Total Technicians', context['total_technicians']])
    writer.writerow(['Active', context['active_count']])
    writer.writerow(['Inactive', context['inactive_count']])
    writer.writerow(['Generated At', timezone.localtime(context['generated_at']).strftime('%Y-%m-%d %H:%M')])
    writer.writerow([])
    writer.writerow([
        'Technician ID', 'Name', 'Username', 'Email',
        'Branch', 'Department', 'Joining Date', 'Active/Inactive',
        'Total Assigned Jobs', 'Active Jobs', 'Completed/Closed Jobs',
    ])
    for row in context['rows']:
        writer.writerow([
            row['technician_id'],
            row['name'],
            row['username'],
            row['email'],
            row['branch'],
            row['department'],
            fmt_dt(row['joining_date']),
            'Active' if row['is_active'] else 'Inactive',
            row['total_jobs'],
            row['active_jobs'],
            row['completed_jobs'],
        ])
    return response
