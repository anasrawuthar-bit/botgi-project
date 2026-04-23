from .helpers import *  # noqa: F401,F403


@login_required
def technician_dashboard(request):
    if not request.user.groups.filter(name='Technicians').exists():
        return redirect('unauthorized')

    technician = TechnicianProfile.objects.filter(user=request.user).first()
    if not technician:
        # ... (Handle missing profile) ...
        return render(request, 'job_tickets/technician_dashboard.html', {
            'active_jobs': [], 'history_jobs': [], 'username': request.user.username, 
            'warning': 'No technician profile found. Contact admin.'
        })
    
    # Handle search query
    query = request.GET.get('q', '').strip()
    search_results = []
    if query:
        search_results = list(JobTicket.objects.filter(
            Q(assigned_to=technician) &
            (Q(job_code__icontains=query) |
             Q(customer_name__icontains=query) |
             Q(customer_phone__icontains=query) |
             Q(device_type__icontains=query))
        ).prefetch_related('service_logs').order_by('-created_at'))
        calculate_job_totals(search_results, exclude_vendor_charges=True)

    # --- 1. GET DATE FILTERS (Year and Month) ---
    report_month_param = request.GET.get('report_month')
    preset = request.GET.get('preset') # NEW: Get preset parameter
    
    history_filter = Q(assigned_to=technician)  # Start with assigned technician filter
    current_year = None
    current_month = None

    # Get the current local date once
    today = timezone.localdate()

    # NEW: Handle presets first
    if preset == 'this_month':
        current_year = today.year
        current_month = today.month
        report_month_param = None # Clear report_month_param if preset is used
    elif preset == 'last_month':
        first_day_of_current_month = today.replace(day=1)
        last_month_date = first_day_of_current_month - timedelta(days=1)
        current_year = last_month_date.year
        current_month = last_month_date.month
        report_month_param = None # Clear report_month_param if preset is used
    
    if report_month_param:
        try:
            year_str, month_str = report_month_param.split('-')
            year = int(year_str)
            month = int(month_str)
            
            start_of_period = timezone.make_aware(datetime(year, month, 1, 0, 0, 0))
            
            if month == 12:
                end_of_period = start_of_period.replace(year=year + 1, month=1)
            else:
                end_of_period = start_of_period.replace(month=month + 1)
            
            # Apply time filter to history jobs
            history_filter &= Q(updated_at__gte=start_of_period, updated_at__lt=end_of_period)
            
            current_year = year
            current_month = month
            
        except (ValueError, TypeError):
            messages.error(request, "Invalid month or year provided for filtering history.")
            # If invalid, default to current month/year
            current_year = today.year
            current_month = today.month
            start_of_period = timezone.make_aware(datetime(current_year, current_month, 1, 0, 0, 0))
            if current_month == 12:
                end_of_period = start_of_period.replace(year=current_year + 1, month=1)
            else:
                end_of_period = start_of_period.replace(month=current_month + 1)
            history_filter &= Q(updated_at__gte=start_of_period, updated_at__lt=end_of_period)
    else:
        # Default to the current month and year if no filter is applied or if a preset was used
        if current_year is None or current_month is None: # Only if not set by preset
            current_year = today.year
            current_month = today.month
        
        start_of_period = timezone.make_aware(datetime(current_year, current_month, 1, 0, 0, 0))
        if current_month == 12:
            end_of_period = start_of_period.replace(year=current_year + 1, month=1)
        else:
            end_of_period = start_of_period.replace(month=current_month + 1)
            
        history_filter &= Q(updated_at__gte=start_of_period, updated_at__lt=end_of_period)


    # --- 2. DEFINE JOB LISTS ---
    # Treat these statuses as finished for the technician's "active" view so they don't appear
    # in the technician active jobs list. 'Ready for Pickup' is a customer-facing state and
    # should not be shown in the technician's active work queue.
    # Also exclude 'Returned' jobs as they are no longer with technician
    finished_statuses = ['Completed', 'Closed', 'Ready for Pickup', 'Returned']
    
    # Active Jobs (Unfiltered by date, exclude returned jobs)
    active_jobs_query = JobTicket.objects.filter(assigned_to=technician).prefetch_related('service_logs', 'specialized_service').exclude(status__in=finished_statuses).order_by('created_at')
    
    active_jobs = list(active_jobs_query)
    
    # Add vendor return indicator to each job
    for job in active_jobs:
        job.returned_from_vendor = False
        if hasattr(job, 'specialized_service') and job.specialized_service:
            job.returned_from_vendor = job.specialized_service.status == 'Returned from Vendor'
    
    # History Jobs (Filtered by date, status, and assigned technician)
    # Remove 'Returned' from history as these jobs are not completed by technician
    history_finished_statuses = ['Completed', 'Closed', 'Ready for Pickup']
    history_jobs = list(
        JobTicket.objects.filter(history_filter)
        .filter(status__in=history_finished_statuses)
        .prefetch_related('service_logs')
        .order_by('-updated_at')
    )

    # 3. Calculate totals excluding vendor charges for technician view
    calculate_job_totals(active_jobs, exclude_vendor_charges=True)
    calculate_job_totals(history_jobs, exclude_vendor_charges=True)

    # 4. Calculate history summary totals (Footer totals)
    history_parts_total = sum(j.part_total for j in history_jobs)
    history_service_total = sum(j.service_total for j in history_jobs)
    history_grand_total = history_parts_total + history_service_total
    
    # 5. Render context
    context = {
        'technician': technician,
        'active_jobs': active_jobs,
        'history_jobs': history_jobs,
        'username': request.user.username,
        'history_parts_total': history_parts_total,
        'history_service_total': history_service_total,
        'history_grand_total': history_grand_total,
        
        # Search functionality
        'query': query,
        'search_results': search_results,
        'search_count': len(search_results) if query else 0,
        
        # Dates for the filter inputs
        'current_year': current_year,
        'current_month': current_month,
        'current_month_filter': f"{current_year:04d}-{current_month:02d}", # YYYY-MM format for input value
        'technician_join_month': technician.user.date_joined.strftime('%Y-%m'), # YYYY-MM
        'current_month_year': today.strftime('%Y-%m'), # YYYY-MM
        'month_options': [(i, date(2000, i, 1).strftime('%B')) for i in range(1, 13)],
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        # Return both history table and active jobs table for AJAX updates
        history_html = render_to_string('job_tickets/_history_table.html', context, request=request)
        
        # Also render active jobs table rows
        active_jobs_html = render_to_string('job_tickets/_active_jobs_table.html', {
            'active_jobs': active_jobs,
            'request': request,
        }, request=request)
        
        return JsonResponse({
            'html': history_html,
            'active_jobs_html': active_jobs_html
        })

    return render(request, 'job_tickets/technician_dashboard.html', context)

@login_required
def job_detail_technician(request, job_code):
    # only technicians allowed
    if not request.user.groups.filter(name='Technicians').exists():
        return redirect('unauthorized')

    # safe lookup of TechnicianProfile (avoids AttributeError if profile missing)
    technician = TechnicianProfile.objects.filter(user=request.user).first()
    if not technician:
        messages.warning(request, "No technician profile found. Contact admin.")
        return redirect('unauthorized')

    # fetch job assigned to this technician
    job = get_object_or_404(JobTicket, job_code=job_code, assigned_to=technician)

    # ----------------------------------------------------
    # CORE CHANGE: Filter Status Choices for Technicians
    # ----------------------------------------------------
    EXCLUDED_STATUSES = ['Ready for Pickup', 'Closed', 'Specialized Service']
    
    # Create a filtered list from the model's choices
    technician_status_choices = [
        (value, label) for value, label in job.STATUS_CHOICES # Access choices from the JobTicket model
        if label not in EXCLUDED_STATUSES
    ]
    
    # Additional restriction: If job is in Specialized Service, check if it's returned from vendor
    can_change_status = True
    if job.status == 'Specialized Service':
        # Check if there's a specialized service record and if it's returned from vendor
        specialized_service = getattr(job, 'specialized_service', None)
        if specialized_service and specialized_service.status != 'Returned from Vendor':
            can_change_status = False
    checklist_schema, checklist_title, checklist_notes = _build_checklist_schema_for_job(job)
    checklist_required_for_completion = _checklist_requires_completion(checklist_schema)
    # ----------------------------------------------------

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_status':
            new_status = (request.POST.get('status') or '').strip()
            technician_notes = request.POST.get('technician_notes', '')
            posted_answers, missing_required_labels, invalid_option_labels = _extract_checklist_answers_from_post(
                request.POST,
                checklist_schema,
            )
            existing_answers = _get_job_checklist_answers(job)
            merged_answers = _merge_checklist_answers(existing_answers, posted_answers)

            # VALIDATION: Ensure the technician didn't somehow post an excluded status
            if new_status in EXCLUDED_STATUSES:
                 messages.error(request, 'Invalid status update attempt.')
                 return redirect('job_detail_technician', job_code=job_code)

            if invalid_option_labels:
                error_message = (
                    "Invalid checklist selection for: "
                    + ', '.join(invalid_option_labels[:6])
                    + ('...' if len(invalid_option_labels) > 6 else '')
                )
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse(
                        {
                            'ok': False,
                            'message': error_message,
                            'invalid_checklist_fields': invalid_option_labels,
                        },
                        status=400,
                    )
                messages.error(request, error_message)
                return redirect('job_detail_technician', job_code=job_code)

            if new_status == 'Completed' and missing_required_labels:
                error_message = _format_checklist_required_error(missing_required_labels)
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse(
                        {
                            'ok': False,
                            'message': error_message,
                            'missing_checklist_fields': missing_required_labels,
                        },
                        status=400,
                    )
                messages.error(request, error_message)
                return redirect('job_detail_technician', job_code=job_code)
            
            # VALIDATION: Check if job is in specialized service and not returned from vendor
            if job.status == 'Specialized Service':
                specialized_service = getattr(job, 'specialized_service', None)
                if specialized_service and specialized_service.status != 'Returned from Vendor':
                    error_message = 'Cannot change status while job is with vendor. Wait for vendor to return the device.'
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'ok': False, 'message': error_message}, status=403)
                    messages.error(request, error_message)
                    return redirect('job_detail_technician', job_code=job_code)

            # GET OLD VALUES BEFORE SAVING
            old_status = job.get_status_display()
            old_notes = job.technician_notes
            old_answers = _get_job_checklist_answers(job)

            job.status = new_status
            job.technician_notes = technician_notes
            job.technician_checklist = merged_answers
            job.save()

            if old_status != new_status:
                details = f"Status changed from '{old_status}' to '{job.get_status_display()}'."
                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='STATUS', details=details)
                # Send WebSocket update
                send_job_update_message(job.job_code, job.status)

            if old_notes != technician_notes:
                details = f"Technician notes updated: \"{technician_notes}\""
                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='NOTE', details=details)

            if old_answers != merged_answers:
                changed_labels = []
                for field in checklist_schema:
                    key = field['key']
                    old_value = _normalize_checklist_answer(old_answers.get(key, ''))
                    new_value = _normalize_checklist_answer(merged_answers.get(key, ''))
                    if old_value != new_value:
                        changed_labels.append(field['label'])
                if changed_labels:
                    summary = ', '.join(changed_labels[:8])
                    if len(changed_labels) > 8:
                        summary += '...'
                    details = f"Technician checklist updated: {summary}"
                else:
                    details = "Technician checklist updated."
                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='NOTE', details=details)

            # Return JSON response for AJAX requests (no page reload)
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'ok': True,
                    'message': 'Status and notes updated successfully.',
                    'status': job.status,
                    'status_display': job.get_status_display(),
                    'technician_notes': job.technician_notes,
                })
            
            messages.success(request, 'Status updated.')
            return redirect('job_detail_technician', job_code=job_code)

        elif action == 'add_service_log':
            # Check if job is in specialized service - prevent manual service charge entry
            if job.status == 'Specialized Service':
                error_message = 'Cannot add service logs while job is in Specialized Service. Service charges will be automatically added when returned from vendor.'
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({
                        'ok': False,
                        'message': error_message,
                    }, status=400)
                messages.error(request, error_message)
                return redirect('job_detail_technician', job_code=job_code)
            
            service_form = ServiceLogForm(request.POST)
            if service_form.is_valid():
                new_service = service_form.save(commit=False)
                new_service.job_ticket = job
                new_service.save()
                details = f"Added service: '{new_service.description}' (Part: {new_service.part_cost}, Service: {new_service.service_charge})"
                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='SERVICE', details=details)
                
                # Send WebSocket update
                send_job_update_message(job.job_code, job.status)
                
                # Return JSON response for AJAX requests (no page reload)
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    # Re-fetch service logs to include the new one
                    service_logs = job.service_logs.all()
                    html = render_to_string('job_tickets/_service_logs_table.html', {
                        'job': job,
                        'service_logs': service_logs,
                    }, request=request)
                    return JsonResponse({
                        'ok': True,
                        'message': 'Service log added successfully.',
                        'html': html,
                    })
                
                messages.success(request, 'Service log added.')
                return redirect('job_detail_technician', job_code=job_code)
            else:
                # Return JSON with errors for AJAX requests
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    errors = {field: [str(e) for e in service_form.errors[field]] for field in service_form.errors}
                    return JsonResponse({
                        'ok': False,
                        'message': 'Please correct the errors in the form.',
                        'errors': errors,
                    }, status=400)
                messages.error(request, 'Please correct the errors in the form.')

        elif action == 'update_service_logs':
            # Technician updated existing service log rows (description, part_cost, service_charge)
            # Prevent edits if job is finalized, billed, or in specialized service
            if job.status in ['Ready for Pickup', 'Completed', 'Closed', 'Specialized Service'] or job.vyapar_invoice_number:
                error_msg = 'Cannot edit logs after billing or completion.' if job.status in ['Ready for Pickup', 'Completed', 'Closed'] or job.vyapar_invoice_number else 'Cannot edit service logs while job is in Specialized Service.'
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'ok': False, 'error': 'editing_not_allowed', 'message': error_msg}, status=403)
                messages.error(request, error_msg)
                return redirect('job_detail_technician', job_code=job_code)
            updated_any = False
            for log in job.service_logs.all():
                try:
                    desc_key = f'description_{log.id}'
                    part_key = f'part_cost_{log.id}'
                    service_key = f'service_charge_{log.id}'

                    new_desc = request.POST.get(desc_key, '').strip()
                    new_part_raw = request.POST.get(part_key, '')
                    new_service_raw = request.POST.get(service_key, '')

                    # Parse decimals safely
                    try:
                        new_part = Decimal(new_part_raw) if new_part_raw not in (None, '') else None
                    except (InvalidOperation, ValueError, TypeError):
                        new_part = log.part_cost

                    try:
                        new_service = Decimal(new_service_raw) if new_service_raw not in (None, '') else log.service_charge
                    except (InvalidOperation, ValueError, TypeError):
                        new_service = log.service_charge

                    changed = False
                    details_parts = []
                    if new_desc and new_desc != log.description:
                        details_parts.append(f"description: '{log.description}' -> '{new_desc}'")
                        log.description = new_desc
                        changed = True

                    # Compare decimals as Decimal for accuracy
                    if new_part is not None and (log.part_cost != new_part):
                        details_parts.append(f"part_cost: ₹{log.part_cost or 0} -> ₹{new_part}")
                        log.part_cost = new_part
                        changed = True

                    if new_service is not None and (log.service_charge != new_service):
                        details_parts.append(f"service_charge: ₹{log.service_charge or 0} -> ₹{new_service}")
                        log.service_charge = new_service
                        changed = True

                    if changed:
                        log.save()
                        updated_any = True
                        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='SERVICE', details='; '.join(details_parts))

                except Exception as e:
                    # Log error but continue processing other rows
                    # (Don't expose internals to user)
                    continue

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                # Render updated table HTML and return as snapshot
                html = render_to_string('job_tickets/_service_logs_table.html', {
                    'job': job,
                    'service_logs': job.service_logs.all(),
                }, request=request)
                return JsonResponse({'ok': True, 'updated': updated_any, 'message': updated_any and 'Service logs updated.' or 'No changes detected.', 'html': html})

            if updated_any:
                messages.success(request, 'Service logs updated.')
            else:
                messages.info(request, 'No changes detected in service logs.')
            return redirect('job_detail_technician', job_code=job_code)


    # GET (or invalid POST) -> render page
    service_form = ServiceLogForm()
    service_logs = job.service_logs.all()
    calculate_job_totals([job])
    subtotal = job.total
    discount = job.discount_amount or Decimal('0.00')
    grand_total = subtotal - discount

    context = {
        'job': job,
        'service_logs': service_logs,
        'service_form': service_form,
        'total_parts_cost': job.part_total,
        'total_service_charges': job.service_total,
        'subtotal': subtotal,
        'discount': discount,
        'grand_total': grand_total,
        # Pass the filtered choices to the template
        'status_choices': technician_status_choices,
        'can_change_status': can_change_status,
        'checklist_schema': checklist_schema,
        'checklist_title': checklist_title,
        'checklist_notes': checklist_notes,
        'checklist_required_for_completion': checklist_required_for_completion,
    }
    return render(request, 'job_tickets/job_detail_technician.html', context)

@login_required
@require_POST
def assignment_respond(request, pk):
    """
    POST endpoint for technician to accept/reject an Assignment.
    Expects POST: action=accept|reject, note (optional).
    Returns JSON.
    """
    action = request.POST.get("action")
    note = request.POST.get("note", "").strip()

    if action not in ("accept", "reject"):
        return HttpResponseBadRequest("invalid action")

    try:
        with transaction.atomic():
            # Lock the assignment row to avoid race conditions
            assignment = (
                Assignment.objects.select_for_update()
                .select_related("technician__user", "job")
                .get(pk=pk)
            )

            # Only the assigned technician may respond
            if assignment.technician.user != request.user:
                return HttpResponseForbidden("You are not the assigned technician for this assignment.")

            # Prevent double response
            if assignment.status != "pending":
                return JsonResponse({"ok": False, "error": "already_responded", "status": assignment.status}, status=400)

            if action == "accept":
                assignment.accept(note=note)
            else:
                assignment.reject(note=note)
            
            # CHANNELS: Send update after assignment response changes job status (removed - Django Channels no longer used)

            return JsonResponse({"ok": True, "status": assignment.status})
    except Assignment.DoesNotExist:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)
    except ValueError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)

@login_required
@require_POST
def job_mark_started(request, job_code):
    """
    Mark a job as started (e.g., set to 'Repairing' or 'Under Inspection').
    Only the assigned technician (or staff) may perform this.
    """
    job = get_object_or_404(JobTicket, job_code=job_code)

    # Permission: allow assigned technician or staff
    is_assigned_tech = job.assigned_to and getattr(job.assigned_to, "user", None) == request.user
    is_staff_actor = bool(request.user.is_staff and user_has_staff_access(request.user, "staff_dashboard"))
    if not (is_assigned_tech or is_staff_actor):
        return HttpResponseForbidden("You are not permitted to mark this job as started.")

    # Decide the status you want when "started"
    old_status = job.get_status_display()
    new_status = "Repairing" if job.status != "Repairing" else job.status
    job.status = new_status
    job.save(update_fields=["status", "updated_at"])
    
    # Send WebSocket update
    if old_status != job.get_status_display():
        send_job_update_message(job.job_code, job.status)
        details = f"Status changed from '{old_status}' to '{job.get_status_display()}'."
        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='STATUS', details=details)
        
    messages.success(request, f"Job {job.job_code} marked as started ({new_status}).")
    return redirect("job_detail_technician", job_code=job.job_code)

@login_required
@require_POST
def job_mark_completed(request, job_code):
    """
    Mark a job as completed. Only the assigned technician or staff can do this.
    """
    job = get_object_or_404(JobTicket, job_code=job_code)

    is_assigned_tech = job.assigned_to and getattr(job.assigned_to, "user", None) == request.user
    is_staff_actor = bool(request.user.is_staff and user_has_staff_access(request.user, "staff_dashboard"))
    if not (is_assigned_tech or is_staff_actor):
        return HttpResponseForbidden("You are not permitted to mark this job as completed.")

    if not is_staff_actor:
        checklist_schema, _, _ = _build_checklist_schema_for_job(job)
        missing_required = _missing_required_checklist_labels(job, checklist_schema)
        if missing_required:
            messages.error(request, _format_checklist_required_error(missing_required))
            return redirect("job_detail_technician", job_code=job.job_code)

    old_status = job.get_status_display()
    job.status = "Completed"
    job.save(update_fields=["status", "updated_at"])
    
    # Send WebSocket update
    if old_status != job.get_status_display():
        send_job_update_message(job.job_code, job.status)
        details = f"Status changed from '{old_status}' to '{job.get_status_display()}'."
        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='STATUS', details=details)
        
    messages.success(request, f"Job {job.job_code} marked as Completed.")
    return redirect("job_detail_technician", job_code=job.job_code)

@login_required
@require_POST
def technician_delete_service_log(request, log_id):
    """Allow assigned technician to delete a service log row (with checks)."""
    # Find the service log and related job
    log = get_object_or_404(ServiceLog, id=log_id)
    job = log.job_ticket

    # Verify requester is the assigned technician
    tech = TechnicianProfile.objects.filter(user=request.user).first()
    if not tech or job.assigned_to != tech:
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    # Prevent deletion if job is billed/finalized
    if job.status in ['Ready for Pickup', 'Completed', 'Closed'] or job.vyapar_invoice_number:
        return JsonResponse({'ok': False, 'error': 'editing_not_allowed', 'message': 'Cannot delete logs after billing or completion.'}, status=403)

    # Delete and log
    details = f"Service log deleted: '{log.description}' (Part: {log.part_cost}, Service: {log.service_charge})"
    log.delete()
    JobTicketLog.objects.create(job_ticket=job, user=request.user, action='SERVICE', details=details)
    return JsonResponse({'ok': True, 'message': 'Service log deleted.'})

# job_tickets/views.py (Add this function)

@login_required
def technician_acknowledge_assignment(request, job_code):
    """Technician acknowledges a newly assigned job (clears is_new_assignment)."""
    # Ensure the user is a technician
    tech = TechnicianProfile.objects.filter(user=request.user).first()
    if not tech:
        return redirect('unauthorized')

    job = get_object_or_404(JobTicket, job_code=job_code)
    
    if request.method == 'POST':
        # Ensure the user is the assigned technician
        if job.assigned_to != tech:
            messages.error(request, "You are not assigned to this job.")
            return redirect('technician_dashboard') # Or return HttpResponseForbidden

        job.is_new_assignment = False
        job.save(update_fields=['is_new_assignment', 'updated_at'])

        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='ACKNOWLEDGED', details=f"Job {job.job_code} acknowledged by technician.")
        
        # Send WebSocket update
        send_job_update_message(job.job_code, job.status)

        # Re-fetch job with prefetched service_logs for rendering
        job = JobTicket.objects.filter(pk=job.pk).prefetch_related('service_logs').first()
        calculate_job_totals([job]) # Recalculate totals for the single job

        # Return JSON for AJAX requests, HTML for HTMX
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'ok': True,
                'message': 'Job acknowledged successfully.',
                'job_code': job.job_code,
            })
        
        # Render the updated job row HTML fragment for HTMX
        context = {'job': job, 'request': request} # Pass request to context for {% url %} and user checks
        updated_row_html = render_to_string('job_tickets/_job_row.html', context, request=request)
        return HttpResponse(updated_row_html)

    # For GET requests, or if not POST, redirect to dashboard
    return redirect('technician_dashboard')

@login_required
def technician_return_to_staff(request, job_code):
    """Technician returns the job to staff (unassigns and marks Pending)."""
    tech = TechnicianProfile.objects.filter(user=request.user).first()
    if not tech:
        return redirect('unauthorized')

    job = get_object_or_404(JobTicket, job_code=job_code)
    
    if request.method == 'POST': # Ensure this logic only runs for POST requests
        if job.assigned_to != tech:
            messages.error(request, "You are not assigned to this job.")
            return redirect('technician_dashboard') # Or return HttpResponseForbidden

        old_status = job.get_status_display()
        job.assigned_to = None
        job.status = 'Pending'
        job.is_new_assignment = False
        job.save(update_fields=['assigned_to', 'status', 'is_new_assignment', 'updated_at'])
        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='ASSIGNED', details=f"Technician returned job to staff. Previous status: {old_status}")
        
        # Send WebSocket update
        send_job_update_message(job.job_code, job.status)
        
        # messages.success(request, f"Job {job.job_code} returned to staff for reassignment.") # Messages won't show with htmx swap

        # Re-fetch job with prefetched service_logs for rendering
        job = JobTicket.objects.filter(pk=job.pk).prefetch_related('service_logs').first()
        calculate_job_totals([job]) # Recalculate totals for the single job

        # Return success response for AJAX
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'ok': True,
                'message': f'Job {job.job_code} returned to staff for reassignment.',
                'redirect': True
            })
        
        messages.success(request, f'Job {job.job_code} returned to staff for reassignment.')
        return redirect('technician_dashboard')

    # For GET requests, or if not POST, redirect to dashboard
    return redirect('technician_dashboard')
