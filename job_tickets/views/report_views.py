from .helpers import *  # noqa: F401,F403


@login_required
def reports_dashboard(request):
    denied = _staff_access_required(request, "reports_dashboard")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')
    
    # 1. UNIFIED PERIOD DETERMINATION (The ONLY call needed)
    period = get_report_period(request)
    start_of_period = period['start']
    end_of_period = period['end']
    status_filter = request.GET.get('status_filter')
    all_jobs = JobTicket.objects.all()
    all_jobs_count = all_jobs.count()
    pending_count = all_jobs.filter(status='Pending').count()

    in_progress_count = all_jobs.filter(
        Q(status='Under Inspection') | Q(status='Repairing') | Q(status='Specialized Service')
    ).count()

    completed_awaiting_billing_count = all_jobs.filter(
        Q(status='Completed') | Q(status='Ready for Pickup')
    ).count()

    # Returned means either currently Returned, or closed directly from Returned status.
    closed_returned_jobs_all_time = get_returned_to_closed_jobs(all_jobs)
    returned_count = all_jobs.filter(status='Returned').count() + closed_returned_jobs_all_time.count()
    closed_count = all_jobs.filter(status='Closed').count()
    
    # Static data for HTML limits
    company_start_date = get_company_start_date()
    today_date_str = timezone.localdate().strftime('%Y-%m-%d')


    # --- 2. QUERIES setup ---
    finished_statuses = ['Completed', 'Closed']
    
    # Base filter for time window
    q_filter = Q(updated_at__gte=start_of_period, updated_at__lt=end_of_period)

    # Apply Status Filter if selected by the user
    if status_filter == 'ALL_FINISHED':
        q_filter &= Q(status__in=finished_statuses)
    elif status_filter == 'ACTIVE_WORKLOAD':
        q_filter &= Q(status__in=['Under Inspection', 'Repairing', 'Specialized Service'])
    elif status_filter and status_filter != 'ALL':
        # Filter for a specific status (e.g., 'Completed', 'Returned')
        q_filter &= Q(status=status_filter)

    # 2a. Monthly/Period Finished Jobs (Using vendor concept)
    monthly_finished_jobs_list = get_jobs_for_report_period(start_of_period, end_of_period, status_filter)
    monthly_finished_jobs = JobTicket.objects.filter(
        id__in=[job.id for job in monthly_finished_jobs_list]
    )
    
    # 2b. Jobs Created (IN) - Filtered ONLY by date, NOT status
    jobs_in_period = JobTicket.objects.filter(
        created_at__gte=start_of_period,
        created_at__lt=end_of_period
    ).count()

    jobs_out_period = monthly_finished_jobs.count() # Count reflects the status filter

    # Query logs related to jobs finished in the selected period
    logs_in_period = ServiceLog.objects.filter(job_ticket__in=monthly_finished_jobs)
    
    # 2c. Income Calculations
    monthly_income_parts = logs_in_period.aggregate(
        total=Coalesce(Sum('part_cost', output_field=DecimalField()), Decimal('0.00'))
    )['total']
    
    monthly_income_service = logs_in_period.aggregate(
        total=Coalesce(Sum('service_charge', output_field=DecimalField()), Decimal('0.00'))
    )['total']
    
    monthly_total_income = monthly_income_parts + monthly_income_service

    # 2d. Expense Calculations
    vendor_services_in_period = SpecializedService.objects.filter(job_ticket__in=monthly_finished_jobs)
    monthly_vendor_expense = sum_vendor_net_cost(vendor_services_in_period)

    # Subtract job-level discounts from total income
    monthly_total_discounts = _sum_job_discounts(monthly_finished_jobs)
    monthly_total_income = _net_amount_after_discount(monthly_total_income, monthly_total_discounts)

    monthly_net_profit = monthly_total_income - monthly_vendor_expense

    # --- 2e. Per-section custom date ranges (Technician / Vendor) ---
    # Accept GET params: tech_start_date, tech_end_date, vendor_start_date, vendor_end_date
    def parse_section_dates(start_str, end_str):
        if start_str and end_str:
            try:
                sd = datetime.strptime(start_str, '%Y-%m-%d').date()
                ed = datetime.strptime(end_str, '%Y-%m-%d').date()
                sd_aware = timezone.make_aware(datetime(sd.year, sd.month, sd.day))
                # inclusive end -> set to 23:59:59
                ed_aware = timezone.make_aware(datetime(ed.year, ed.month, ed.day, 23, 59, 59))
                return sd_aware, ed_aware, start_str, end_str
            except Exception:
                # fallback to global period
                return start_of_period, end_of_period, period['start_date_str'], period['end_date_str']
        return start_of_period, end_of_period, period['start_date_str'], period['end_date_str']

    tech_start_str = request.GET.get('tech_start_date') or request.GET.get('perf_start_date')
    tech_end_str = request.GET.get('tech_end_date') or request.GET.get('perf_end_date')
    tech_start, tech_end, tech_start_date_str, tech_end_date_str = parse_section_dates(tech_start_str, tech_end_str)

    vendor_start_str = request.GET.get('vendor_start_date')
    vendor_end_str = request.GET.get('vendor_end_date')
    vendor_start, vendor_end, vendor_start_date_str, vendor_end_date_str = parse_section_dates(vendor_start_str, vendor_end_str)


    # --- 3. ALL-TIME STATS (Remain unfiltered by date/status) ---

    all_jobs = JobTicket.objects.all()
    completed_jobs_all_time = all_jobs.filter(status='Completed')
    pending_jobs_all_time = all_jobs.filter(status='Pending')
    in_progress_jobs_all_time = all_jobs.filter(Q(status='Under Inspection') | Q(status='Repairing'))
    ready_for_pickup_jobs_all_time = all_jobs.filter(status='Ready for Pickup')
    returned_jobs_all_time = all_jobs.filter(status='Returned')
    closed_jobs = all_jobs.filter(status='Closed').order_by('-updated_at')

    # Technician-level performance (Filtered by per-section period)
    # Build the set of finished jobs for the technician filter period using vendor concept
    tech_finished_jobs_list = get_jobs_for_report_period(tech_start, tech_end)
    tech_finished_jobs = JobTicket.objects.filter(
        id__in=[job.id for job in tech_finished_jobs_list]
    )

    tech_job_count_subquery = JobTicket.objects.filter(
        assigned_to=OuterRef('pk'),
        id__in=tech_finished_jobs.values('id')
    ).values('assigned_to').annotate(
        count=Count('id', distinct=True)
    ).values('count')

    monthly_tech_performance = TechnicianProfile.objects.filter(
        user__groups__name='Technicians'
    ).annotate(
        jobs_done=Coalesce(
            Subquery(tech_job_count_subquery),
            0,
            output_field=IntegerField()
        ),
        monthly_parts_sales=Coalesce(
            Sum('jobticket__service_logs__part_cost',
                filter=Q(jobticket__in=tech_finished_jobs.values('id')) & ~Q(jobticket__service_logs__description__icontains='Specialized Service'),
                output_field=DecimalField()
            ), Decimal('0.00'), output_field=DecimalField()
        ),
        monthly_service_sales=Coalesce(
            Sum('jobticket__service_logs__service_charge',
                filter=Q(jobticket__in=tech_finished_jobs.values('id')) & ~Q(jobticket__service_logs__description__icontains='Specialized Service'),
                output_field=DecimalField()
            ), Decimal('0.00'), output_field=DecimalField()
        )
    ).order_by('-jobs_done')

    # VENDOR PERFORMANCE QUERY (Using vendor concept)
    # Get vendor jobs that were returned in the specified period
    vendor_jobs_list = get_jobs_for_report_period(vendor_start, vendor_end)
    vendor_finished_jobs = JobTicket.objects.filter(
        id__in=[job.id for job in vendor_jobs_list],
        specialized_service__isnull=False
    )
    
    vendor_performance = Vendor.objects.annotate(
        total_jobs_given=Count('services', filter=Q(
            services__job_ticket__in=vendor_finished_jobs
        )),
        total_vendor_cost=Coalesce(Sum(vendor_net_cost_expression('services__'), filter=Q(
            services__job_ticket__in=vendor_finished_jobs
        ), output_field=DecimalField()), Decimal('0.00')),
        total_client_charge=Coalesce(Sum('services__client_charge', filter=Q(
            services__job_ticket__in=vendor_finished_jobs
        ), output_field=DecimalField()), Decimal('0.00'))
    ).annotate(
        profit=F('total_client_charge') - F('total_vendor_cost')
    ).order_by('-total_jobs_given')

    # --- 3.5 TODAY'S STATS ---
    today = timezone.localdate()
    start_of_day = timezone.make_aware(datetime.combine(today, datetime.min.time()))
    end_of_day = timezone.make_aware(datetime.combine(today, datetime.max.time()))

    todays_jobs_in = JobTicket.objects.filter(created_at__range=(start_of_day, end_of_day)).count()
    
    todays_jobs_out_qs = JobTicket.objects.filter(
        status='Closed',
        updated_at__range=(start_of_day, end_of_day)
    )
    todays_jobs_out = todays_jobs_out_qs.count()

    todays_completed_jobs_qs = JobTicket.objects.filter(
        status='Completed',
        updated_at__range=(start_of_day, end_of_day)
    )
    todays_jobs_completed = todays_completed_jobs_qs.count()

    def today_service_totals(jobs_queryset):
        logs = ServiceLog.objects.filter(job_ticket__in=jobs_queryset)
        spare_total = logs.aggregate(
            total=Coalesce(Sum('part_cost', output_field=DecimalField()), Decimal('0.00'))
        )['total']
        service_total = logs.aggregate(
            total=Coalesce(Sum('service_charge', output_field=DecimalField()), Decimal('0.00'))
        )['total']
        return spare_total, service_total, spare_total + service_total

    todays_completed_spare, todays_completed_service, todays_completed_total = today_service_totals(todays_completed_jobs_qs)
    todays_closed_spare, todays_closed_service, todays_closed_total = today_service_totals(todays_jobs_out_qs)
    todays_total_spare = todays_completed_spare + todays_closed_spare
    todays_total_service = todays_completed_service + todays_closed_service


    # --- 4. CONTEXT BUILDING ---
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

        'company_start_date': company_start_date.strftime('%Y-%m-%d'),
        'today_date_str': today_date_str,
        'current_report_start': period['start_date_str'],
        'current_report_end': period['end_date_str'],
        'tech_start_date': tech_start_date_str,
        'tech_end_date': tech_end_date_str,
        'vendor_start_date': vendor_start_date_str,
        'vendor_end_date': vendor_end_date_str,
        'status_filter': status_filter or 'ALL',
        'jobs_created_in_period': jobs_in_period,
        'jobs_finished_in_period': jobs_out_period,
        'current_report_date': start_of_period,
        'monthly_total_income': monthly_total_income,
        'monthly_income_parts': monthly_income_parts,
        'monthly_income_service': monthly_income_service,
        'monthly_vendor_expense': monthly_vendor_expense,
        'monthly_net_profit': monthly_net_profit,
        'monthly_total_discounts': monthly_total_discounts,
        'monthly_completed_jobs_count': monthly_finished_jobs.count(),

        # All-Time Stats
        'all_jobs_count': all_jobs.count(),
        'completed_count': completed_jobs_all_time.count(),
        'pending_count': pending_jobs_all_time.count(),
        'in_progress_count': in_progress_jobs_all_time.count(),
        'ready_for_pickup_count': ready_for_pickup_jobs_all_time.count(),
        'returned_count': returned_jobs_all_time.count(),
        'closed_jobs': closed_jobs,
        
        # Performance
        'monthly_tech_performance': monthly_tech_performance,
        'vendor_performance': vendor_performance,
        'all_jobs_count': all_jobs_count,
        'pending_count': pending_count,
        'in_progress_count': in_progress_count,
        'completed_awaiting_billing_count': completed_awaiting_billing_count,
        'returned_count': returned_count,
        'closed_count': closed_count,

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

    # get all technicians
    techs = TechnicianProfile.objects.select_related('user').all()

    # optionally: annotate some simple counts/totals for display
    tech_rows = []
    for tech in techs:
        jobs = JobTicket.objects.filter(assigned_to=tech).prefetch_related('service_logs')
        
        completed_jobs = [j for j in jobs if j.status == 'Completed']
        
        completed_count = len(completed_jobs)
        
        # Exclude vendor service charges from technician totals
        total_parts = Decimal('0.00')
        total_services = Decimal('0.00')
        
        for job in completed_jobs:
            for log in job.service_logs.all():
                if 'Specialized Service' not in log.description:
                    total_parts += log.part_cost or Decimal('0.00')
                    total_services += log.service_charge or Decimal('0.00')
        
        tech_rows.append({
            'tech': tech,
            'completed_count': completed_count,
            'parts_total': total_parts,
            'service_total': total_services,
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
        jobs_queryset = jobs_queryset.filter(
            status='Closed',
            updated_at__range=(start_of_day, end_of_day)
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
