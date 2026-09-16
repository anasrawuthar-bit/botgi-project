from .helpers import *  # noqa: F401,F403
from .helpers import (
    _build_checklist_schema_for_job,
    _extract_checklist_answers_from_post,
    _format_checklist_required_error,
    _generate_inventory_bill_number,
    _generate_inventory_entry_number,
    _get_job_checklist_answers,
    _get_or_create_inventory_customer_party_for_job,
    _merge_checklist_answers,
    _money_or_zero,
    _net_amount_after_discount,
    _normalize_checkbox_answer,
    _normalize_checklist_answer,
    _staff_access_required,
)
from ..whatsapp_service import queue_job_whatsapp_message, send_job_whatsapp_notification


REMINDER_PROMPT_COOLDOWN_MINUTES = 10
REMINDER_WORK_START = datetime.strptime('09:00', '%H:%M').time()
REMINDER_WORK_END = datetime.strptime('22:00', '%H:%M').time()
REMINDER_DEFAULT_TIME = '09:00'
FEEDBACK_FOLLOWUP_DAYS = 7
FEEDBACK_AUTO_SEND_LIMIT = 25


def _parse_html_time(raw_time):
    for fmt in ('%H:%M', '%H:%M:%S'):
        try:
            return datetime.strptime(raw_time, fmt).time()
        except (TypeError, ValueError):
            continue
    return None


def _parse_reminder_due_at(post_data, *, date_field='reminder_date', time_field='reminder_time', require_value=False):
    raw_date = (post_data.get(date_field) or '').strip()
    raw_time = (post_data.get(time_field) or '').strip()

    if not raw_date and not raw_time:
        if require_value:
            return None, 'Choose reminder date.'
        return None, ''
    if not raw_date:
        return None, 'Choose reminder date.'

    try:
        reminder_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None, 'Reminder date must be valid.'

    reminder_time = _parse_html_time(raw_time or REMINDER_DEFAULT_TIME)
    if reminder_time is None:
        return None, 'Reminder time must be valid.'

    if reminder_time < REMINDER_WORK_START or reminder_time > REMINDER_WORK_END:
        return None, 'Reminder time must be between 9:00 AM and 10:00 PM.'

    due_at = timezone.make_aware(
        datetime.combine(reminder_date, reminder_time),
        timezone.get_current_timezone(),
    )
    if due_at <= timezone.now():
        return None, 'Reminder date and time must be in the future.'

    return due_at, ''


def _default_reminder_schedule(active_reminder=None):
    now = timezone.localtime()

    if active_reminder:
        local_due_at = timezone.localtime(active_reminder.due_at)
        return {
            'date': local_due_at.date().isoformat(),
            'time': local_due_at.strftime('%H:%M'),
            'min_date': now.date().isoformat(),
            'default_time': REMINDER_DEFAULT_TIME,
        }

    reminder_date = now.date()
    if now.time() >= REMINDER_WORK_START:
        reminder_date += timedelta(days=1)

    return {
        'date': reminder_date.isoformat(),
        'time': REMINDER_DEFAULT_TIME,
        'min_date': now.date().isoformat(),
        'default_time': REMINDER_DEFAULT_TIME,
    }


def _parse_reminder_offset(post_data, *, hour_field='reminder_hours', minute_field='reminder_minutes', require_value=False):
    raw_hours = (post_data.get(hour_field) or '').strip()
    raw_minutes = (post_data.get(minute_field) or '').strip()

    if not raw_hours and not raw_minutes:
        if require_value:
            return None, 'Enter reminder hour or minute.'
        return None, ''

    try:
        hours = int(raw_hours or 0)
        minutes = int(raw_minutes or 0)
    except (TypeError, ValueError):
        return None, 'Reminder hour and minute must be valid numbers.'

    if hours < 0 or hours > 24:
        return None, 'Reminder hour must be between 0 and 24.'
    if minutes < 0 or minutes > 60:
        return None, 'Reminder minute must be between 0 and 60.'
    if hours == 0 and minutes == 0:
        if require_value:
            return None, 'Enter reminder hour or minute.'
        return None, ''

    return timedelta(hours=hours, minutes=minutes), ''


def _parse_estimated_amount(raw_amount):
    raw_amount = (raw_amount or '').strip()
    if not raw_amount:
        return None, ''
    try:
        amount = Decimal(raw_amount)
    except InvalidOperation:
        return None, 'Invalid estimate amount.'
    if amount < 0:
        return None, 'Estimate amount cannot be negative.'
    return amount.quantize(Decimal('0.01')), ''


def _save_job_estimation_from_post(request, job):
    estimated_amount, amount_error = _parse_estimated_amount(request.POST.get('estimated_amount'))
    if amount_error:
        return amount_error

    estimation_note = (request.POST.get('estimation_note') or '').strip()
    old_amount = job.estimated_amount
    old_note = job.estimation_note or ''

    if old_amount == estimated_amount and old_note == estimation_note:
        return ''

    job.estimated_amount = estimated_amount
    job.estimation_note = estimation_note
    job.save(update_fields=['estimated_amount', 'estimation_note', 'updated_at'])

    changes = []
    if old_amount != estimated_amount:
        changes.append(f"estimate amount changed from Rs {old_amount or '0.00'} to Rs {estimated_amount or '0.00'}")
    if old_note != estimation_note:
        changes.append('estimate note updated')

    JobTicketLog.objects.create(
        job_ticket=job,
        user=request.user,
        action='NOTE',
        details='Staff updated ' + ', '.join(changes) + '.',
    )
    return ''


def _active_job_reminder(job):
    return job.reminders.filter(status=JobReminder.STATUS_PENDING).order_by('due_at', 'id').first()


def _feedback_due_at_from_closed_at(closed_at):
    return closed_at + timedelta(days=FEEDBACK_FOLLOWUP_DAYS)


def _schedule_feedback_followup(job, *, save=True):
    if job.status != 'Closed':
        return []

    now = timezone.now()
    changed_fields = []
    if not job.closed_at:
        job.closed_at = now
        changed_fields.append('closed_at')
    if not job.feedback_due_at:
        job.feedback_due_at = _feedback_due_at_from_closed_at(job.closed_at)
        changed_fields.append('feedback_due_at')
    if not job.feedback_followup_enabled:
        job.feedback_followup_enabled = True
        changed_fields.append('feedback_followup_enabled')
    if job.feedback_rating and job.feedback_followup_status != JobTicket.FEEDBACK_RECEIVED:
        job.feedback_followup_status = JobTicket.FEEDBACK_RECEIVED
        changed_fields.append('feedback_followup_status')

    if save and changed_fields:
        job.save(update_fields=[*changed_fields, 'updated_at'])
    return changed_fields


def _prepare_feedback_followups():
    JobTicket.objects.filter(
        feedback_rating__isnull=False,
    ).exclude(
        feedback_followup_status=JobTicket.FEEDBACK_RECEIVED,
    ).update(
        feedback_followup_status=JobTicket.FEEDBACK_RECEIVED,
    )


def _queue_feedback_followup_message(job, *, user=None, manual=False):
    result = (
        queue_job_whatsapp_message(job, MessageQueue.EVENT_FEEDBACK)
        if manual
        else send_job_whatsapp_notification(job, MessageQueue.EVENT_FEEDBACK)
    )
    if not result.get('ok'):
        return result

    now = timezone.now()
    update_fields = ['feedback_message_sent_at', 'feedback_followup_status', 'updated_at']
    job.feedback_message_sent_at = now
    if job.feedback_followup_status == JobTicket.FEEDBACK_PENDING:
        job.feedback_followup_status = JobTicket.FEEDBACK_MESSAGE_SENT
    job.save(update_fields=update_fields)

    JobTicketLog.objects.create(
        job_ticket=job,
        user=user,
        action='FEEDBACK',
        details='Feedback WhatsApp follow-up queued.',
    )
    return result


def _auto_send_due_feedback_messages():
    _prepare_feedback_followups()
    due_jobs = JobTicket.objects.filter(
        status='Closed',
        feedback_followup_enabled=True,
        feedback_rating__isnull=True,
        feedback_due_at__lte=timezone.now(),
        feedback_message_sent_at__isnull=True,
    ).exclude(
        feedback_followup_status__in=[
            JobTicket.FEEDBACK_RECEIVED,
            JobTicket.FEEDBACK_CALLED_HAPPY,
        ]
    ).order_by('feedback_due_at', 'id')[:FEEDBACK_AUTO_SEND_LIMIT]

    sent_count = 0
    for job in due_jobs:
        result = _queue_feedback_followup_message(job)
        if result.get('ok'):
            sent_count += 1
    return sent_count


def _append_feedback_note(existing_note, new_note):
    new_note = (new_note or '').strip()
    if not new_note:
        return existing_note or ''
    timestamp = timezone.localtime(timezone.now()).strftime('%d-%m-%Y %I:%M %p')
    entry = f"{timestamp}: {new_note}"
    return f"{existing_note}\n{entry}".strip() if existing_note else entry


def _safe_next_redirect(request, fallback='staff_dashboard', **fallback_kwargs):
    next_url = (request.POST.get('next') or request.GET.get('next') or request.META.get('HTTP_REFERER') or '').strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect(fallback, **fallback_kwargs)


@login_required
def staff_dashboard(request):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    
    # Ensure Decimal is imported
    from decimal import Decimal, InvalidOperation
    period = get_report_period(request)
    start_of_period = period['start']
    end_of_period = period['end']
    
    # --- START: REWRITTEN JOB CREATION POST HANDLER FOR MULTI-DEVICE ---
    if request.method == 'POST' and 'job_ticket_form_submit' in request.POST:

        is_ajax_request = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        # CRITICAL STEP: Generate one group ID for this entire customer submission batch
        submission_group_id = str(uuid4())

        # 1. Extract static customer data from the form.
        customer_name = (request.POST.get('customer_name') or '').strip()
        customer_phone, customer_phone_error = normalize_indian_phone(
            request.POST.get('customer_phone'),
            field_label='Customer Phone',
        )

        estimated_amount_raw = (request.POST.get('estimated_amount') or '').strip()
        estimated_delivery_raw = request.POST.get('estimated_delivery')
        
        # Basic Validation
        basic_errors = []
        field_errors = {}
        if not customer_name:
            field_errors['customer_name'] = "Customer Name is required."
            basic_errors.append(field_errors['customer_name'])
        if customer_phone_error:
            field_errors['customer_phone'] = customer_phone_error
            basic_errors.append(customer_phone_error)

        if basic_errors:
            if is_ajax_request:
                return JsonResponse(
                    {'success': False, 'message': " ".join(basic_errors), 'field_errors': field_errors},
                    status=400,
                )
            request.session['show_create_job_modal'] = True
            for error in basic_errors:
                messages.error(request, error)
            return redirect('staff_dashboard')

        current_workspace = getattr(request, 'current_workspace', None)

        # Auto-create or refresh the client directory.
        try:
            client_qs = Client.objects.filter(phone__in=phone_lookup_variants(customer_phone))
            if current_workspace:
                client_qs = client_qs.filter(workspace=current_workspace)
            existing_client = client_qs.order_by('id').first()
            if existing_client:
                client_updated_fields = []
                if current_workspace and existing_client.workspace_id != current_workspace.id:
                    existing_client.workspace = current_workspace
                    client_updated_fields.append('workspace')
                if existing_client.name != customer_name:
                    existing_client.name = customer_name
                    client_updated_fields.append('name')
                if existing_client.phone != customer_phone:
                    existing_client.phone = customer_phone
                    client_updated_fields.append('phone')
                if client_updated_fields:
                    existing_client.save(update_fields=client_updated_fields)
            else:
                Client.objects.create(workspace=current_workspace, phone=customer_phone, name=customer_name)
        except Exception:
            # Client directory sync should not block ticket creation.
            pass

        try:
            estimated_amount = Decimal(estimated_amount_raw) if estimated_amount_raw else None
        except InvalidOperation:
            error_message = "Invalid input for Estimated Amount. Please enter a valid number."
            if is_ajax_request:
                return JsonResponse({'success': False, 'message': error_message}, status=400)
            request.session['show_create_job_modal'] = True
            messages.error(request, error_message)
            return redirect('staff_dashboard')

        estimated_delivery = None
        
        if estimated_delivery_raw:
            try:
                # The browser sends date input as YYYY-MM-DD
                estimated_delivery = datetime.strptime(estimated_delivery_raw, '%Y-%m-%d').date()
            except ValueError:
                error_message = "Invalid Estimated Delivery date format."
                if is_ajax_request:
                    return JsonResponse({'success': False, 'message': error_message}, status=400)
                request.session['show_create_job_modal'] = True
                messages.error(request, error_message)
                return redirect('staff_dashboard')

        reminder_delta, reminder_error = _parse_reminder_offset(request.POST)
        if reminder_error:
            if is_ajax_request:
                return JsonResponse({'success': False, 'message': reminder_error}, status=400)
            request.session['show_create_job_modal'] = True
            messages.error(request, reminder_error)
            return redirect('staff_dashboard')

        reminder_due_at = timezone.now() + reminder_delta if reminder_delta else None
        
        # 2. Identify and collect all device submissions using JavaScript's array naming
        device_submissions = []
        device_photo_payloads = []
        validation_errors = []
        i = 0
        # This loop correctly parses the dynamic fields sent by the frontend
        while request.POST.get(f'device_forms[{i}].device_type'):
            
            device_type = (request.POST.get(f'device_forms[{i}].device_type') or '').strip()
            device_brand = (request.POST.get(f'device_forms[{i}].device_brand') or '').strip()
            device_model = (request.POST.get(f'device_forms[{i}].device_model') or '').strip()
            device_serial = (request.POST.get(f'device_forms[{i}].device_serial') or '').strip()
            reported_issue = (request.POST.get(f'device_forms[{i}].reported_issue') or '').strip()
            additional_items = (request.POST.get(f'device_forms[{i}].additional_items') or '').strip()
            photo_files = request.FILES.getlist(f'device_forms[{i}].device_photos')

            required_fields = [
                ('device_type', device_type, 'Device type'),
                ('device_brand', device_brand, 'Device brand'),
                ('device_model', device_model, 'Device model'),
                ('reported_issue', reported_issue, 'Reported issue'),
            ]

            missing_fields = [label for _, value, label in required_fields if not value]
            if missing_fields:
                for field_name, value, label in required_fields:
                    if not value:
                        validation_errors.append({
                            'device_index': i,
                            'field': field_name,
                            'message': f'{label} is required.'
                        })
            else:
                # Checkbox sends 'on' if checked, otherwise it's absent
                is_under_warranty_val = request.POST.get(f'device_forms[{i}].is_under_warranty')
                is_under_warranty = True if is_under_warranty_val == 'on' else False
                requires_laptop_inspection_checklist = (
                    request.POST.get(f'device_forms[{i}].requires_laptop_inspection_checklist') == 'on'
                )

                device_submissions.append({
                    'device_type': device_type,
                    'device_brand': device_brand,
                    'device_model': device_model,
                    'device_serial': device_serial,
                    'reported_issue': reported_issue,
                    'additional_items': additional_items,
                    'is_under_warranty': is_under_warranty,
                    'requires_laptop_inspection_checklist': requires_laptop_inspection_checklist,
                })
                device_photo_payloads.append(photo_files)
            i += 1

        if validation_errors:
            if is_ajax_request:
                return JsonResponse({'success': False, 'errors': validation_errors}, status=400)
            request.session['show_create_job_modal'] = True
            for error in validation_errors:
                messages.error(request, f"Device #{error['device_index'] + 1}: {error['message']}")
            return redirect('staff_dashboard')

        for device_index, photo_files in enumerate(device_photo_payloads):
            for photo_file in photo_files:
                if not photo_file:
                    continue
                _, upload_error = validate_job_photo_upload(photo_file)
                if upload_error:
                    validation_errors.append({
                        'device_index': device_index,
                        'field': 'device_photos',
                        'message': upload_error,
                    })

        if validation_errors:
            if is_ajax_request:
                return JsonResponse({'success': False, 'errors': validation_errors}, status=400)
            request.session['show_create_job_modal'] = True
            for error in validation_errors:
                messages.error(request, f"Device #{error['device_index'] + 1}: {error['message']}")
            return redirect('staff_dashboard')

        if not device_submissions:
            error_message = "Please add at least one device to create a job ticket."
            if is_ajax_request:
                return JsonResponse({'success': False, 'message': error_message}, status=400)
            request.session['show_create_job_modal'] = True
            messages.error(request, error_message)
            return redirect('staff_dashboard')

        # 3. Create Jobs in a Transaction
        with transaction.atomic():
            created_job_codes = []
            created_jobs_payload = []
            
            for idx, device_data in enumerate(device_submissions):
                photo_files = device_photo_payloads[idx] if idx < len(device_photo_payloads) else []
                # CRITICAL: Call the helper function to get a unique, simple job code
                new_job_code = get_next_job_code() 
                
                new_job = JobTicket.objects.create(
                    workspace=current_workspace,
                    job_code=new_job_code,
                    customer_name=customer_name,
                    customer_phone=customer_phone,
                    created_by=request.user,
                    estimated_amount=estimated_amount,
                    estimated_delivery=estimated_delivery,
                    customer_group_id=submission_group_id, 
                    **device_data 
                )

                if photo_files:
                    for photo_file in photo_files:
                        if photo_file:
                            content_type, _ = validate_job_photo_upload(photo_file)

                            JobTicketPhoto.objects.create(
                                job_ticket=new_job,
                                image_name=(getattr(photo_file, 'name', '') or 'device-photo').strip()[:255],
                                image_content_type=content_type[:100],
                                image_data=photo_file.read(),
                            )
                
                JobTicketLog.objects.create(job_ticket=new_job, user=request.user, action='CREATED', details=f"Job ticket created for device: {device_data['device_type']}.")

                if reminder_due_at:
                    reminder = JobReminder.objects.create(
                        job_ticket=new_job,
                        due_at=reminder_due_at,
                        created_by=request.user,
                    )
                    local_due_at = timezone.localtime(reminder.due_at).strftime('%d-%m-%Y %I:%M %p')
                    JobTicketLog.objects.create(
                        job_ticket=new_job,
                        user=request.user,
                        action='NOTE',
                        details=f"Callback reminder scheduled for {local_due_at}.",
                    )
                
                created_job_codes.append(new_job.job_code)
                created_jobs_payload.append({
                    'job_code': new_job.job_code,
                    'customer_name': new_job.customer_name,
                    'customer_phone': new_job.customer_phone,
                    'device_type': new_job.device_type,
                    'net_total': '0.00',
                    'detail_url': reverse('staff_job_detail', args=[new_job.job_code]),
                    'receipt_url': reverse('job_creation_receipt_print', args=[new_job.job_code]),
                })

        success_message = (
            f"Successfully created {len(created_job_codes)} new job ticket(s) for {customer_name}."
            if len(created_job_codes) > 1
            else f"Job {created_job_codes[0]} created successfully."
        )

        # Keep preset lists useful by learning values from created tickets.
        try:
            sync_job_field_presets(device_submissions)
        except Exception:
            pass

        if is_ajax_request:
            response_data = {
                'success': True,
                'message': success_message,
                'job_codes': created_job_codes,
                'jobs': created_jobs_payload,
            }
            if len(created_job_codes) == 1:
                response_data['redirect_url'] = reverse('job_creation_success', args=[created_job_codes[0]])
            return JsonResponse(response_data)

        # 4. Success Redirection (non-AJAX)
        if len(created_job_codes) == 1:
            return redirect('job_creation_success', job_code=created_job_codes[0])
        else:
            messages.success(request, success_message)
            return redirect('staff_dashboard')
    # --- END: REWRITTEN JOB CREATION POST HANDLER ---

    # --- START: NON-CREATION POST HANDLERS & GET LOGIC (Code is kept identical to yours below) ---

    # Handle Job Assignment Form (Logic retained)
    else: # This 'else' catches the GET request for the dashboard initially
        form = JobTicketForm()
        
    if request.method == 'POST' and 'assign_job_form_submit' in request.POST:
        assign_form = AssignJobForm(request.POST, workspace=getattr(request, 'current_workspace', None))
        if assign_form.is_valid():
            job_code = assign_form.cleaned_data['job_code']
            technician = assign_form.cleaned_data['technician']
            job_to_assign = get_object_or_404(JobTicket, job_code=job_code)

            with transaction.atomic():
                old_status = job_to_assign.get_status_display()
                job_to_assign.assigned_to = technician
                job_to_assign.status = 'Under Inspection'
                job_to_assign.is_new_assignment = True
                job_to_assign.save(update_fields=['assigned_to', 'status', 'updated_at', 'is_new_assignment'])

                details = f"Assigned to technician '{technician.user.username}' and status changed from '{old_status}' to 'Under Inspection'."
                JobTicketLog.objects.create(job_ticket=job_to_assign, user=request.user, action='ASSIGNED', details=details)

            # Send WebSocket update for real-time job assignment notification
            send_job_update_message(job_to_assign.job_code, job_to_assign.status)

            messages.success(request, f"Job {job_to_assign.job_code} assigned to {technician.user.username}.")
            return redirect('staff_dashboard')
    else:
        assign_form = AssignJobForm(workspace=getattr(request, 'current_workspace', None))

    
    # START: NEW VENDOR ASSIGNMENT LOGIC (Logic retained)
    if request.method == 'POST' and 'assign_vendor_form_submit' in request.POST:
        assign_vendor_form = AssignVendorForm(request.POST, workspace=getattr(request, 'current_workspace', None))
        if assign_vendor_form.is_valid():
            data = assign_vendor_form.cleaned_data
            service = get_object_or_404(SpecializedService, id=data['specialized_service_id'])
            
            with transaction.atomic():
                service.vendor = data['vendor']
                # Costs will be entered when device returns from vendor
                service.status = 'Sent to Vendor'
                service.sent_date = timezone.now()
                service.save()
                
                details = f"Assigned to vendor '{service.vendor.company_name}' and sent for service."
                JobTicketLog.objects.create(job_ticket=service.job_ticket, user=request.user, action='STATUS', details=details)

            messages.success(request, f"Job {service.job_ticket.job_code} assigned to {service.vendor.company_name}.")
            
            # CHANNELS: Send update (removed - Django Channels no longer used)
            
            return redirect('staff_dashboard')

    # GET QUERY AND LIST FETCHING (Logic retained)
    query = request.GET.get('q')
    current_workspace = getattr(request, 'current_workspace', None)
    search_results = []
    if query:
        search_qs = JobTicket.objects.filter(
            Q(job_code__icontains=query) |
            Q(customer_name__icontains=query) |
            Q(customer_phone__icontains=query)
        )
        if current_workspace:
            search_qs = search_qs.filter(workspace=current_workspace)
        search_results = list(search_qs.select_related(
            'assigned_to__user'
        ).prefetch_related(
            'service_logs'
        ).order_by('-created_at'))
        
        try:
            # Calculate totals for search results
            calculate_job_totals(search_results)
            for job in search_results:
                job.discount_total = _money_or_zero(job.discount_amount)
                job.net_total = _net_amount_after_discount(job.total, job.discount_total)
        except InvalidOperation:
            messages.error(request, "Error calculating job totals. Some values may be incorrect.")
        
        # Use search results for all status filters
        job_tickets = JobTicket.objects.filter(
            Q(job_code__icontains=query) |
            Q(customer_name__icontains=query) |
            Q(customer_phone__icontains=query)
        ).order_by('-created_at')
    else:
        job_tickets = JobTicket.objects.all().order_by('-created_at')
    if current_workspace:
        job_tickets = job_tickets.filter(workspace=current_workspace)
    # Defer large text fields not needed for dashboard listing
    job_tickets = job_tickets.defer('technician_notes', 'technician_checklist', 'feedback_followup_note')
    
    def prepare_dashboard_jobs(queryset):
        jobs = list(queryset.select_related('assigned_to__user').prefetch_related('service_logs'))
        calculate_job_totals(jobs)
        for job in jobs:
            job.discount_total = _money_or_zero(job.discount_amount)
            job.net_total = _net_amount_after_discount(job.total, job.discount_total)
        return jobs

    pending_jobs = prepare_dashboard_jobs(job_tickets.filter(status='Pending'))
    returned_jobs = prepare_dashboard_jobs(job_tickets.filter(status='Returned'))
    ready_for_pickup_jobs = prepare_dashboard_jobs(job_tickets.filter(status='Ready for Pickup'))
    completed_jobs = prepare_dashboard_jobs(job_tickets.filter(status='Completed'))
    awaiting_assignment = list(
        SpecializedService.objects.filter(status='Awaiting Assignment')
        .select_related('job_ticket')
        .prefetch_related('job_ticket__service_logs')
    )

    # Fetch and group in-progress jobs by technician (Logic retained)
    in_progress_jobs_qs = job_tickets.filter(
        Q(status='Under Inspection') | Q(status='Repairing')
    )
    in_progress_jobs = prepare_dashboard_jobs(in_progress_jobs_qs)

    grouped_in_progress_jobs = {}
    for job in in_progress_jobs:
        key = job.assigned_to.user.username if job.assigned_to and job.assigned_to.user else "Unassigned"
        if key not in grouped_in_progress_jobs:
            grouped_in_progress_jobs[key] = []
        grouped_in_progress_jobs[key].append(job)

    # Create a form instance for each of these jobs (Logic retained)
    for service in awaiting_assignment:
        calculate_job_totals([service.job_ticket])
        service.job_ticket.discount_total = _money_or_zero(service.job_ticket.discount_amount)
        service.job_ticket.net_total = _net_amount_after_discount(service.job_ticket.total, service.job_ticket.discount_total)
        service.form = AssignVendorForm(
            initial={'specialized_service_id': service.id},
            workspace=getattr(request, 'current_workspace', None) or service.job_ticket.workspace,
        )

    sent_to_vendor = SpecializedService.objects.filter(status='Sent to Vendor').select_related('job_ticket', 'vendor')

    reminder_alerts = list(
        JobReminder.objects.filter(status=JobReminder.STATUS_PENDING)
        .select_related('job_ticket', 'created_by')
        .order_by('due_at', 'id')[:75]
    )
    reminder_alert_count = JobReminder.objects.filter(status=JobReminder.STATUS_PENDING).count()
    due_reminder_count = JobReminder.objects.filter(
        status=JobReminder.STATUS_PENDING,
        due_at__lte=timezone.now(),
    ).count()

    # FINAL CONTEXT
    context = {
        'form': JobTicketForm(), # Use an empty form here for any generic field access in the template
        'assign_form': assign_form,
        'job_field_presets': get_job_field_presets(),
        'show_create_job_modal': request.session.pop('show_create_job_modal', False),
        'pending_jobs': pending_jobs,
        'grouped_in_progress_jobs': grouped_in_progress_jobs,
        'in_progress_jobs_count': len(in_progress_jobs),
        'returned_jobs': returned_jobs,
        'ready_for_pickup_jobs': ready_for_pickup_jobs,
        'completed_jobs': completed_jobs,
        'username': request.user.username,
        'query': query,
        'search_results': search_results,
        'search_count': len(search_results) if query else 0,
        'awaiting_assignment_jobs': awaiting_assignment,
        'sent_to_vendor_jobs': sent_to_vendor,
        'pending_count': len(pending_jobs),
        'ready_count': len(ready_for_pickup_jobs),
        'completed_count': len(completed_jobs),
        'returned_count': len(returned_jobs),
        'reminder_alerts': reminder_alerts,
        'reminder_alert_count': reminder_alert_count,
        'due_reminder_count': due_reminder_count,
    }
    return render(request, 'job_tickets/staff_dashboard.html', context)

# job_tickets/views.py

# job_tickets/views.py

@login_required
def job_billing_staff(request, job_code):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    
    job = get_object_or_404(JobTicket, job_code=job_code)
    
    if request.method == 'POST':
        # --- Handle Billing/Invoice Submission (Includes Job and Log Updates) ---
        if 'update_amounts_submit' in request.POST:
            try:
                with transaction.atomic():
                    raw_delete_service_ids = request.POST.getlist('delete_service_ids[]')
                    delete_service_ids = []
                    seen_delete_ids = set()
                    for raw_service_id in raw_delete_service_ids:
                        try:
                            service_id_int = int(raw_service_id)
                        except (TypeError, ValueError):
                            continue
                        if service_id_int in seen_delete_ids:
                            continue
                        seen_delete_ids.add(service_id_int)
                        delete_service_ids.append(service_id_int)
                    delete_service_ids_set = set(delete_service_ids)

                    # 1. HANDLE JOB-LEVEL INVOICE NUMBER (shared across service + inventory sales)
                    submitted_invoice = (request.POST.get('job_sales_invoice_number') or '').strip()
                    old_vyapar_invoice = job.vyapar_invoice_number or ""
                    sale_entry_date = timezone.localdate()

                    if submitted_invoice:
                        validate_sales_invoice_number_uniqueness(
                            submitted_invoice,
                            exclude_job_id=job.id,
                            allow_inventory_job_id=job.id,
                        )
                        new_vyapar_invoice = submitted_invoice
                    elif old_vyapar_invoice:
                        new_vyapar_invoice = old_vyapar_invoice
                    else:
                        # No invoice submitted and none previously saved - leave blank.
                        new_vyapar_invoice = ''

                    if old_vyapar_invoice != new_vyapar_invoice:
                        details = f"Sales Invoice No. updated from '{old_vyapar_invoice}' to '{new_vyapar_invoice}'."
                        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='BILLING', details=details)
                        job.vyapar_invoice_number = new_vyapar_invoice or None

                    # Keep existing linked inventory sales entries and bill header on the same shared invoice.
                    updated_invoice_rows = (
                        InventoryEntry.objects.filter(entry_type='sale', job_ticket=job)
                        .exclude(invoice_number=new_vyapar_invoice)
                        .update(invoice_number=new_vyapar_invoice)
                    )
                    InventoryBill.objects.filter(entry_type='sale', job_ticket=job).exclude(
                        invoice_number=new_vyapar_invoice
                    ).update(invoice_number=new_vyapar_invoice)
                    if updated_invoice_rows:
                        JobTicketLog.objects.create(
                            job_ticket=job,
                            user=request.user,
                            action='BILLING',
                            details=(
                                f"Updated {updated_invoice_rows} linked inventory sale line(s) "
                                f"to invoice '{new_vyapar_invoice}'."
                            ),
                        )
                    
                    # 2. UPDATE EXISTING SERVICE LOGS (skip lines queued for deletion)
                    product_sales_by_log_id = {
                        sale.service_log_id: sale
                        for sale in ProductSale.objects.select_related('product', 'inventory_entry').filter(
                            job_ticket=job,
                            service_log__isnull=False,
                        )
                    }
                    for log in job.service_logs.all():
                        log_id = log.id
                        if log_id in delete_service_ids_set:
                            continue

                        is_updated = False
                        product_sale_entry = product_sales_by_log_id.get(log_id)
                        try:
                            new_part_cost = Decimal(request.POST.get(f'part_cost_{log_id}', 0) or 0)
                            new_service_charge = Decimal(request.POST.get(f'service_charge_{log_id}', 0) or 0)
                        except InvalidOperation:
                            raise ValueError(f"Invalid amount entered for '{log.description}'.")

                        old_part_cost = log.part_cost or Decimal('0')
                        old_service_charge = log.service_charge or Decimal('0')
                        description_field = f'description_{log_id}'
                        if description_field in request.POST:
                            old_description = log.description or ''
                            new_description = (request.POST.get(description_field) or '').strip()
                            if not new_description:
                                raise ValueError("Service description cannot be empty.")
                            if len(new_description) > 255:
                                raise ValueError("Service description cannot exceed 255 characters.")
                            if old_description != new_description:
                                log.description = new_description
                                is_updated = True
                                details = f"Updated service description from '{old_description}' to '{new_description}'."
                                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='BILLING', details=details)

                        if product_sale_entry:
                            if new_part_cost < 0:
                                raise ValueError(
                                    f"Product amount cannot be negative for '{product_sale_entry.product.name}'."
                                )

                            if old_part_cost != new_part_cost:
                                quantity = product_sale_entry.quantity or 0
                                if quantity <= 0:
                                    raise ValueError(
                                        f"Product sale quantity is invalid for '{product_sale_entry.product.name}'."
                                    )

                                quantized_part_cost = new_part_cost.quantize(Decimal('0.01'))
                                new_unit_price = (
                                    quantized_part_cost / Decimal(quantity)
                                ).quantize(Decimal('0.01'))
                                line_cost = (
                                    (product_sale_entry.cost_price or Decimal('0.00')) * Decimal(quantity)
                                ).quantize(Decimal('0.01'))
                                line_profit = (quantized_part_cost - line_cost).quantize(Decimal('0.01'))

                                log.part_cost = quantized_part_cost
                                product_sale_entry.unit_price = new_unit_price
                                product_sale_entry.line_total = quantized_part_cost
                                product_sale_entry.line_profit = line_profit

                                if product_sale_entry.inventory_entry_id:
                                    inv_entry = product_sale_entry.inventory_entry
                                    inv_entry.unit_price = new_unit_price
                                    inv_entry.taxable_amount = quantized_part_cost
                                    inv_gst_rate = inv_entry.gst_rate or Decimal('0.00')
                                    inv_gst_amount = (quantized_part_cost * inv_gst_rate / Decimal('100')).quantize(Decimal('0.01'))
                                    inv_entry.gst_amount = inv_gst_amount
                                    inv_entry.total_amount = (quantized_part_cost + inv_gst_amount).quantize(Decimal('0.01'))
                                    inv_entry.save(update_fields=['unit_price', 'taxable_amount', 'gst_amount', 'total_amount'])
                                is_updated = True

                                details = (
                                    f"Updated product sale '{product_sale_entry.product.name}' amount "
                                    f"from Rs {old_part_cost} to Rs {quantized_part_cost}."
                                )
                                JobTicketLog.objects.create(
                                    job_ticket=job,
                                    user=request.user,
                                    action='BILLING',
                                    details=details,
                                )
                            if old_service_charge != new_service_charge:
                                log.service_charge = new_service_charge
                                is_updated = True
                                JobTicketLog.objects.create(
                                    job_ticket=job,
                                    user=request.user,
                                    action='BILLING',
                                    details=(
                                        f"Updated product sale '{product_sale_entry.product.name}' service charge "
                                        f"from Rs {old_service_charge} to Rs {new_service_charge}."
                                    ),
                                )
                        else:
                            if old_part_cost != new_part_cost:
                                log.part_cost = new_part_cost
                                is_updated = True
                                details = f"Updated '{log.description}' part cost from Rs {old_part_cost} to Rs {new_part_cost}."
                                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='BILLING', details=details)

                            if old_service_charge != new_service_charge:
                                log.service_charge = new_service_charge
                                is_updated = True
                                details = f"Updated '{log.description}' service charge from Rs {old_service_charge} to Rs {new_service_charge}."
                                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='BILLING', details=details)
                        
                        log_invoice_field = f'sales_invoice_number_{log_id}'
                        if log_invoice_field in request.POST:
                            old_log_invoice = log.sales_invoice_number or ""
                            new_log_invoice = request.POST.get(log_invoice_field, '').strip()
                            if old_log_invoice != new_log_invoice:
                                log.sales_invoice_number = new_log_invoice
                                is_updated = True
                                details = f"Log Invoice updated for '{log.description}' from '{old_log_invoice}' to '{new_log_invoice}'."
                                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='BILLING', details=details)
                            
                        if is_updated:
                            if product_sale_entry:
                                product_sale_entry.save(update_fields=['unit_price', 'line_total', 'line_profit'])
                            log.save()
                    
                    # 3. HANDLE NEW MANUAL SERVICE LINES
                    new_descriptions = request.POST.getlist('new_description[]')
                    new_part_costs = request.POST.getlist('new_part_cost[]')
                    new_service_charges = request.POST.getlist('new_service_charge[]')

                    for i in range(len(new_descriptions)):
                        description = (new_descriptions[i] or '').strip()
                        if not description:
                            continue
                        try:
                            part_cost = Decimal((new_part_costs[i] if i < len(new_part_costs) else 0) or 0)
                            service_charge = Decimal((new_service_charges[i] if i < len(new_service_charges) else 0) or 0)
                        except InvalidOperation:
                            raise ValueError(f"Invalid amount for new service line '{description}'.")

                        ServiceLog.objects.create(
                            job_ticket=job,
                            description=description,
                            part_cost=part_cost,
                            service_charge=service_charge
                        )
                        details = f"Added new service: '{description}' (Part: Rs {part_cost}, Service: Rs {service_charge})."
                        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='SERVICE', details=details)

                    # 4. HANDLE DELETIONS (restock product if product-line deleted)
                    for service_id in delete_service_ids:
                        try:
                            service_log = ServiceLog.objects.select_for_update().get(id=service_id, job_ticket=job)
                        except ServiceLog.DoesNotExist:
                            continue

                        product_sale_entry = ProductSale.objects.filter(service_log=service_log).select_related('product').first()
                        parsed_product_sale = parse_product_sale_log(service_log.description) if not product_sale_entry else None

                        if product_sale_entry:
                            product = Product.objects.select_for_update().filter(id=product_sale_entry.product_id).first()
                            if product:
                                product.stock_quantity += product_sale_entry.quantity
                                product.save(update_fields=['stock_quantity', 'updated_at'])
                                JobTicketLog.objects.create(
                                    job_ticket=job,
                                    user=request.user,
                                    action='SERVICE',
                                    details=f"Restocked {product.name} by {product_sale_entry.quantity} after deleting product sale line.",
                                )
                            if product_sale_entry.inventory_entry_id:
                                product_sale_entry.inventory_entry.delete()
                        elif parsed_product_sale:
                            product = Product.objects.select_for_update().filter(id=parsed_product_sale['product_id']).first()
                            if product:
                                product.stock_quantity += parsed_product_sale['quantity']
                                product.save(update_fields=['stock_quantity', 'updated_at'])
                                JobTicketLog.objects.create(
                                    job_ticket=job,
                                    user=request.user,
                                    action='SERVICE',
                                    details=f"Restocked {product.name} by {parsed_product_sale['quantity']} after deleting legacy product sale line.",
                                )

                        details = f"Deleted service: '{service_log.description}' (Part: Rs {service_log.part_cost}, Service: Rs {service_log.service_charge})"
                        service_log.delete()
                        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='SERVICE', details=details)

                    # 5. HANDLE PRODUCT SALES (service + product in one bill)
                    # Keep this after deletions so stock released by deleted lines is immediately reusable.
                    product_ids = request.POST.getlist('product_id[]')
                    product_quantities = request.POST.getlist('product_qty[]')
                    product_service_charges = request.POST.getlist('product_service_charge[]')
                    customer_party = _get_or_create_inventory_customer_party_for_job(job)
                    inventory_sale_bill = (
                        InventoryBill.objects.select_for_update()
                        .filter(entry_type='sale', job_ticket=job)
                        .first()
                    )
                    if inventory_sale_bill:
                        inventory_bill_updates = []
                        if inventory_sale_bill.entry_date != sale_entry_date:
                            inventory_sale_bill.entry_date = sale_entry_date
                            inventory_bill_updates.append('entry_date')
                        if (inventory_sale_bill.invoice_number or '') != new_vyapar_invoice:
                            inventory_sale_bill.invoice_number = new_vyapar_invoice
                            inventory_bill_updates.append('invoice_number')
                        if inventory_sale_bill.party_id != customer_party.id:
                            inventory_sale_bill.party = customer_party
                            inventory_bill_updates.append('party')
                        expected_bill_note = f"Auto product sale entries from job {job.job_code}."
                        if inventory_sale_bill.notes != expected_bill_note:
                            inventory_sale_bill.notes = expected_bill_note
                            inventory_bill_updates.append('notes')
                        if inventory_sale_bill.created_by_id is None:
                            inventory_sale_bill.created_by = request.user
                            inventory_bill_updates.append('created_by')
                        if inventory_bill_updates:
                            inventory_sale_bill.save(update_fields=inventory_bill_updates + ['updated_at'])
                    else:
                        inventory_sale_bill = InventoryBill.objects.create(
                            workspace=job.workspace or getattr(request, 'current_workspace', None),
                            bill_number=_generate_inventory_bill_number('sale', sale_entry_date),
                            entry_type='sale',
                            entry_date=sale_entry_date,
                            invoice_number=new_vyapar_invoice,
                            job_ticket=job,
                            party=customer_party,
                            notes=f"Auto product sale entries from job {job.job_code}.",
                            created_by=request.user,
                        )

                    for index, raw_product_id in enumerate(product_ids):
                        product_id = (raw_product_id or '').strip()
                        raw_qty = (product_quantities[index] if index < len(product_quantities) else '').strip()
                        raw_service_charge = (
                            product_service_charges[index] if index < len(product_service_charges) else ''
                        ).strip()

                        if not product_id:
                            continue

                        try:
                            quantity = int(raw_qty)
                        except (TypeError, ValueError):
                            raise ValueError("Product quantity must be a valid whole number.")

                        try:
                            product_service_charge = Decimal(raw_service_charge or 0)
                        except InvalidOperation:
                            raise ValueError("Product service charge must be a valid amount.")

                        if quantity <= 0:
                            raise ValueError("Product quantity must be greater than zero.")
                        if product_service_charge < 0:
                            raise ValueError("Product service charge cannot be negative.")

                        product_qs = Product.objects.select_for_update().filter(pk=product_id)
                        if job.workspace_id:
                            product_qs = product_qs.filter(workspace=job.workspace)
                        product = product_qs.first()
                        if not product:
                            raise ValueError("Selected product no longer exists.")
                        stock_before = product.stock_quantity
                        stock_after = stock_before - quantity

                        line_total = (product.unit_price or Decimal('0')) * Decimal(quantity)
                        line_description = f"Product Sale - {product.name} (Qty: {quantity})"

                        created_sale_log = ServiceLog.objects.create(
                            job_ticket=job,
                            description=line_description,
                            part_cost=line_total,
                            service_charge=product_service_charge.quantize(Decimal('0.01')),
                        )

                        line_cost = (product.cost_price or Decimal('0')) * Decimal(quantity)
                        line_profit = line_total - line_cost
                        inventory_sale_entry = InventoryEntry.objects.create(
                            workspace=job.workspace or getattr(request, 'current_workspace', None),
                            bill=inventory_sale_bill,
                            entry_number=_generate_inventory_entry_number('sale', sale_entry_date),
                            entry_type='sale',
                            entry_date=sale_entry_date,
                            invoice_number=new_vyapar_invoice,
                            job_ticket=job,
                            party=customer_party,
                            product=product,
                            quantity=quantity,
                            unit_price=product.unit_price or Decimal('0.00'),
                            discount_amount=Decimal('0.00'),
                            gst_rate=Decimal('0.00'),
                            taxable_amount=line_total.quantize(Decimal('0.01')),
                            gst_amount=Decimal('0.00'),
                            total_amount=line_total.quantize(Decimal('0.01')),
                            stock_before=stock_before,
                            stock_after=stock_after,
                            notes=f"Auto product sale entry from job {job.job_code}.",
                            created_by=request.user,
                        )

                        ProductSale.objects.create(
                            workspace=job.workspace or getattr(request, 'current_workspace', None),
                            job_ticket=job,
                            product=product,
                            service_log=created_sale_log,
                            inventory_entry=inventory_sale_entry,
                            quantity=quantity,
                            unit_price=product.unit_price or Decimal('0.00'),
                            cost_price=product.cost_price or Decimal('0.00'),
                            line_total=line_total,
                            line_cost=line_cost,
                            line_profit=line_profit,
                            sold_by=request.user,
                        )

                        product.stock_quantity = stock_after
                        product.save(update_fields=['stock_quantity', 'updated_at'])

                        JobTicketLog.objects.create(
                            job_ticket=job,
                            user=request.user,
                            action='SERVICE',
                            details=(
                                f"Added product sale: {product.name} x{quantity} at Rs {product.unit_price} each "
                                f"(Revenue: Rs {line_total}, Service Charge: Rs {product_service_charge}, "
                                f"Cost: Rs {line_cost}, Profit: Rs {line_profit}, "
                                f"Sale Invoice: {new_vyapar_invoice})."
                            ),
                        )

                    InventoryBill.objects.filter(
                        entry_type='sale',
                        job_ticket=job,
                        lines__isnull=True,
                    ).delete()

                    # 6. HANDLE DISCOUNT + FINAL SAVE
                    old_discount = job.discount_amount
                    try:
                        new_discount = Decimal(request.POST.get('discount_amount', 0) or 0)
                    except InvalidOperation:
                        raise ValueError("Invalid discount amount.")

                    if old_discount != new_discount:
                        job.discount_amount = new_discount
                        details = f"Discount updated from Rs {old_discount} to Rs {new_discount}."
                        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='BILLING', details=details)

                    job.save(update_fields=['vyapar_invoice_number', 'discount_amount', 'updated_at'])
                
                messages.success(request, f"Billing and Invoice details for Job {job_code} updated successfully.")
            except ValueError as exc:
                messages.error(request, str(exc))
            except InvalidOperation:
                messages.error(request, "Invalid amount format found in billing form.")
            except Exception:
                messages.error(request, "Unable to update billing details right now. Please try again.")

            return redirect('job_billing_staff', job_code=job_code)
        
        # --- Handle Rework Form Submission ---
        if 'rework_form_submit' in request.POST:
            rework_form = ReworkForm(request.POST)
            if rework_form.is_valid():
                rework_reason = rework_form.cleaned_data['rework_reason']
                new_job_code = get_next_job_code()
                
                new_job = JobTicket.objects.create(
                    workspace=getattr(request, 'current_workspace', None) or job.workspace,
                    job_code=new_job_code,
                    customer_name=job.customer_name,
                    customer_phone=job.customer_phone,
                    device_type=job.device_type,
                    device_brand=job.device_brand,
                    device_model=job.device_model,
                    device_serial=job.device_serial,
                    reported_issue=f"Rework from original ticket {job.job_code}: {rework_reason}",
                    original_job_ticket=job,
                    status='Pending',
                    created_by=request.user
                )
                
                return redirect('job_creation_success', job_code=new_job.job_code)

    # --- GET / RENDERING PATH ---
    job_tickets = [job]
    calculate_job_totals(job_tickets)
    
    subtotal = job.total
    discount = job.discount_amount
    grand_total = subtotal - discount
    
    rework_form = ReworkForm()
    discount_form = DiscountForm(initial={'discount_amount': job.discount_amount})
    technician_id = job.assigned_to.unique_id if job.assigned_to else 'N/A'
    product_sale_log_ids = list(
        ProductSale.objects.filter(job_ticket=job, service_log__isnull=False).values_list('service_log_id', flat=True)
    )
    
    context = {
        'job': job,
        'service_logs': job.service_logs.all(),
        'total_parts_cost': job.part_total,
        'total_service_charges': job.service_total,
        'subtotal': subtotal,
        'discount': discount,
        'grand_total': grand_total,
        'rework_form': rework_form,
        'discount_form': discount_form,
        'technician_id': technician_id,
        'product_sale_log_ids': product_sale_log_ids,
        'products_for_sale': Product.objects.all().order_by('name'),
        'payment_methods': InventoryCreditPayment.METHOD_CHOICES,
    }
    return render(request, 'job_tickets/job_billing_staff.html', context)

@login_required
def mark_ready_for_pickup(request, job_code):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    
    job = get_object_or_404(JobTicket, job_code=job_code)
    old_status = job.get_status_display()
    job.status = 'Ready for Pickup'
    job.save()
    
    # Send WebSocket update
    send_job_update_message(job.job_code, job.status)
    details = f"Status changed from '{old_status}' to '{job.get_status_display()}'."
    JobTicketLog.objects.create(job_ticket=job, user=request.user, action='STATUS', details=details)
    
    return redirect('staff_dashboard')

@login_required
def close_job(request, job_code):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    job = get_object_or_404(JobTicket, job_code=job_code)
    if request.method != 'POST':
        messages.error(request, 'Use the close confirmation window to close a job.')
        return redirect('job_billing_staff', job_code=job.job_code)

    calculate_job_totals([job])
    grand_total = max(Decimal('0.00'), (job.total or Decimal('0.00')) - (job.discount_amount or Decimal('0.00')))

    payment_status = (request.POST.get('payment_status') or 'paid').strip().lower()
    if payment_status not in {'paid', 'part_paid', 'unpaid'}:
        payment_status = 'paid'

    payment_method = (request.POST.get('payment_method') or InventoryCreditPayment.METHOD_CASH).strip()
    valid_methods = {choice[0] for choice in InventoryCreditPayment.METHOD_CHOICES}
    if payment_method not in valid_methods:
        payment_method = InventoryCreditPayment.METHOD_CASH

    payment_reference = (request.POST.get('payment_reference') or '').strip()

    if payment_status == 'paid':
        amount_paid = grand_total
        payment_date = timezone.now()
    elif payment_status == 'part_paid':
        try:
            amount_paid = Decimal((request.POST.get('amount_paid') or '0').strip()).quantize(Decimal('0.01'))
        except (InvalidOperation, ValueError, TypeError):
            messages.error(request, 'Invalid partial payment amount entered.')
            return redirect('job_billing_staff', job_code=job.job_code)
        if amount_paid <= Decimal('0.00'):
            messages.error(request, 'Partial payment amount must be greater than zero.')
            return redirect('job_billing_staff', job_code=job.job_code)
        if amount_paid >= grand_total:
            amount_paid = grand_total
            payment_status = 'paid'
        payment_date = timezone.now()
    else:  # unpaid (credit)
        amount_paid = Decimal('0.00')
        payment_method = ''
        payment_date = None

    old_status = job.get_status_display()
    job.status = 'Closed'
    job.closed_at = timezone.now()
    job.feedback_due_at = _feedback_due_at_from_closed_at(job.closed_at)
    job.feedback_followup_enabled = True
    job.feedback_followup_status = (
        JobTicket.FEEDBACK_RECEIVED if job.feedback_rating else JobTicket.FEEDBACK_PENDING
    )
    job.payment_status = payment_status
    job.payment_method = payment_method or None
    job.amount_paid = amount_paid
    job.payment_reference = payment_reference
    job.payment_date = payment_date
    job.save(update_fields=[
        'status',
        'closed_at',
        'feedback_due_at',
        'feedback_followup_enabled',
        'feedback_followup_status',
        'payment_status',
        'payment_method',
        'amount_paid',
        'payment_reference',
        'payment_date',
        'updated_at',
    ])

    # Record inventory credit/payment ledger if applicable
    party = _get_or_create_inventory_customer_party_for_job(job)
    bill = InventoryBill.objects.filter(entry_type='sale', job_ticket=job).first()
    if not bill and (grand_total > Decimal('0.00') or amount_paid > Decimal('0.00')):
        bill = InventoryBill.objects.create(
            workspace=job.workspace,
            bill_number=_generate_inventory_bill_number('sale', timezone.localdate(), job.workspace),
            entry_type='sale',
            entry_date=timezone.localdate(),
            invoice_number=job.vyapar_invoice_number or '',
            job_ticket=job,
            party=party,
            notes=f"Repair Job {job.job_code} settlement",
            created_by=request.user,
        )
        InventoryEntry.objects.create(
            workspace=job.workspace,
            bill=bill,
            party=party,
            entry_type='sale',
            entry_date=timezone.localdate(),
            quantity=1,
            unit_price=grand_total,
            total_amount=grand_total,
            notes=f"Repair Service Charges - Job {job.job_code}",
            job_ticket=job,
            created_by=request.user,
        )

    if bill and amount_paid > Decimal('0.00'):
        balance_after = max(Decimal('0.00'), grand_total - amount_paid)
        InventoryCreditPayment.objects.create(
            workspace=job.workspace,
            party=party,
            bill=bill,
            direction=InventoryCreditPayment.DIRECTION_RECEIVABLE,
            payment_date=timezone.localdate(),
            payment_method=payment_method or InventoryCreditPayment.METHOD_CASH,
            amount=amount_paid,
            balance_before=grand_total,
            balance_after=balance_after,
            reference_no=payment_reference,
            notes=f"Settlement for Job {job.job_code} ({payment_status})",
            created_by=request.user,
        )

    method_display = dict(InventoryCreditPayment.METHOD_CHOICES).get(payment_method, payment_method) or 'N/A'
    balance_due = max(Decimal('0.00'), grand_total - amount_paid)
    details = (
        f"Status changed from '{old_status}' to 'Closed'. "
        f"Payment: {payment_status.replace('_', ' ').title()} "
        f"(Paid: Rs {amount_paid}, Balance Due: Rs {balance_due} via {method_display})."
    )
    JobTicketLog.objects.create(job_ticket=job, user=request.user, action='CLOSED', details=details)

    send_job_update_message(job.job_code, job.status)
    messages.success(request, f"Job {job.job_code} closed successfully. Payment recorded: {payment_status.replace('_', ' ').title()}.")
    return _safe_next_redirect(request)


@login_required
@require_POST
def update_feedback_followup(request, job_code):
    if not request.user.is_staff or not (
        user_has_staff_access(request.user, "staff_dashboard")
        or user_has_staff_access(request.user, "feedback_analytics")
    ):
        return redirect('unauthorized')

    job = get_object_or_404(JobTicket, job_code=job_code)
    if job.status != 'Closed':
        messages.error(request, 'Feedback follow-up is available only after the job is closed.')
        return _safe_next_redirect(request, 'staff_job_detail', job_code=job.job_code)
    if not job.feedback_followup_enabled or not job.feedback_due_at:
        messages.error(request, 'Feedback follow-up is enabled only for newly closed jobs.')
        return _safe_next_redirect(request, 'staff_job_detail', job_code=job.job_code)

    action = (request.POST.get('feedback_action') or '').strip()
    note = (request.POST.get('feedback_note') or '').strip()
    rating_raw = (request.POST.get('feedback_rating') or '').strip()
    status_map = {
        'called_happy': JobTicket.FEEDBACK_CALLED_HAPPY,
        'called_issue': JobTicket.FEEDBACK_CALLED_ISSUE,
        'no_answer': JobTicket.FEEDBACK_NO_ANSWER,
        'call_later': JobTicket.FEEDBACK_CALL_LATER,
    }

    if action == 'send_now':
        result = _queue_feedback_followup_message(job, user=request.user, manual=True)
        if result.get('ok'):
            messages.success(request, f'Feedback WhatsApp queued for {job.customer_name}.')
        else:
            messages.error(request, result.get('reason') or result.get('error') or 'Could not queue feedback WhatsApp.')
        return _safe_next_redirect(request, 'staff_job_detail', job_code=job.job_code)

    update_fields = ['feedback_followup_status', 'feedback_followup_note', 'feedback_followup_marked_by', 'updated_at']
    old_status = job.get_feedback_followup_status_display()
    job.feedback_followup_marked_by = request.user
    if note:
        job.feedback_followup_note = _append_feedback_note(job.feedback_followup_note, note)

    if action == 'mark_received':
        if not rating_raw or not note:
            messages.error(request, 'Rating and feedback note are required to mark feedback as received.')
            return _safe_next_redirect(request, 'staff_job_detail', job_code=job.job_code)

        try:
            rating = int(rating_raw)
        except (TypeError, ValueError):
            messages.error(request, 'Feedback rating must be between 1 and 10.')
            return _safe_next_redirect(request, 'staff_job_detail', job_code=job.job_code)
        if rating < 1 or rating > 10:
            messages.error(request, 'Feedback rating must be between 1 and 10.')
            return _safe_next_redirect(request, 'staff_job_detail', job_code=job.job_code)

        job.feedback_followup_status = JobTicket.FEEDBACK_RECEIVED
        job.feedback_rating = rating
        job.feedback_comment = note
        job.feedback_date = timezone.now()
        update_fields.extend(['feedback_rating', 'feedback_comment', 'feedback_date'])
        success_message = 'Feedback marked as received.'
    elif action in status_map:
        job.feedback_followup_status = status_map[action]
        job.feedback_followup_called_at = timezone.now()
        update_fields.append('feedback_followup_called_at')
        success_message = f'Feedback follow-up marked as {dict(JobTicket.FEEDBACK_FOLLOWUP_CHOICES)[job.feedback_followup_status]}.'
    else:
        messages.error(request, 'Invalid feedback follow-up action.')
        return _safe_next_redirect(request, 'staff_job_detail', job_code=job.job_code)

    job.save(update_fields=list(dict.fromkeys(update_fields)))
    JobTicketLog.objects.create(
        job_ticket=job,
        user=request.user,
        action='FEEDBACK',
        details=(
            f"Feedback follow-up changed from '{old_status}' to "
            f"'{job.get_feedback_followup_status_display()}'."
        ),
    )
    messages.success(request, success_message)
    return _safe_next_redirect(request, 'staff_job_detail', job_code=job.job_code)


@login_required
def job_billing_print_view(request, job_code):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    
    job = get_object_or_404(JobTicket, job_code=job_code)
    job_tickets = [job]
    calculate_job_totals(job_tickets)
    
    subtotal = job.total
    discount = job.discount_amount
    grand_total = subtotal - discount
    
    technician_id = job.assigned_to.unique_id if job.assigned_to else 'N/A'
    
    # Corrected: Use a fallback value if created_by is None
    created_by_id = job.created_by.id if job.created_by else 'N/A'
    
    # Clean service logs to remove vendor names
    service_logs = job.service_logs.all()
    cleaned_service_logs = []
    for log in service_logs:
        # Replace specialized service descriptions with generic terms
        if 'Specialized Service' in log.description:
            description = 'Specialized Service'
        else:
            description = log.description
            
        cleaned_log = {
            'description': description,
            'part_cost': log.part_cost,
            'service_charge': log.service_charge,
        }
        cleaned_service_logs.append(cleaned_log)
    
    context = {
        'job': job,
        'service_logs': cleaned_service_logs,
        'subtotal': subtotal,
        'discount': discount,
        'grand_total': grand_total,
        'technician_id': technician_id,
        'created_by_id': created_by_id,
        'company': CompanyProfile.get_profile(),
    }
    return render(request, 'job_tickets/job_billing_print.html', context)

@login_required
def staff_job_detail(request, job_code):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    job = get_object_or_404(JobTicket.objects.prefetch_related('photos'), job_code=job_code)
    if not user_has_workspace_access(request.user, job.workspace):
        return redirect('unauthorized')
    session = getattr(request, 'session', None)
    if session is not None:
        session['vendor_details_unlocked'] = (
            session.get('vendor_details_unlocked_job_code') == job.job_code
        )
    checklist_schema, checklist_title, checklist_notes = _build_checklist_schema_for_job(job)

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        if action == 'update_status':
            new_status = (request.POST.get('status') or '').strip()
            valid_statuses = {value for value, _label in JobTicket.STATUS_CHOICES}

            if new_status not in valid_statuses:
                messages.error(request, 'Invalid job status selected.')
                return redirect('staff_job_detail', job_code=job_code)

            if new_status == job.status:
                messages.info(request, 'Status is already up to date.')
                return redirect('staff_job_detail', job_code=job_code)

            old_status = job.get_status_display()
            with transaction.atomic():
                job.status = new_status
                update_fields = ['status', 'updated_at']
                if new_status == 'Closed' and not job.closed_at:
                    job.closed_at = timezone.now()
                    update_fields.append('closed_at')
                if new_status == 'Closed' and not job.feedback_due_at:
                    job.feedback_due_at = _feedback_due_at_from_closed_at(job.closed_at or timezone.now())
                    update_fields.append('feedback_due_at')
                if new_status == 'Closed':
                    job.feedback_followup_enabled = True
                    job.feedback_followup_status = (
                        JobTicket.FEEDBACK_RECEIVED if job.feedback_rating else JobTicket.FEEDBACK_PENDING
                    )
                    update_fields.append('feedback_followup_enabled')
                    update_fields.append('feedback_followup_status')
                elif new_status != 'Closed' and job.closed_at:
                    job.closed_at = None
                    job.feedback_due_at = None
                    job.feedback_followup_enabled = False
                    job.feedback_message_sent_at = None
                    job.feedback_followup_status = JobTicket.FEEDBACK_PENDING
                    job.feedback_followup_called_at = None
                    job.feedback_followup_marked_by = None
                    update_fields.append('closed_at')
                    update_fields.extend([
                        'feedback_due_at',
                        'feedback_followup_enabled',
                        'feedback_message_sent_at',
                        'feedback_followup_status',
                        'feedback_followup_called_at',
                        'feedback_followup_marked_by',
                    ])
                update_fields = list(dict.fromkeys(update_fields))
                job.save(update_fields=update_fields)
                if new_status == 'Specialized Service':
                    service, _created = SpecializedService.objects.get_or_create(job_ticket=job)
                    if service.status == 'Returned from Vendor':
                        service.status = 'Awaiting Assignment'
                        service.vendor = None
                        service.vendor_cost = None
                        service.vendor_discount_amount = Decimal('0.00')
                        service.vendor_paid_amount = Decimal('0.00')
                        service.vendor_balance_amount = Decimal('0.00')
                        service.client_charge = None
                        service.sent_date = None
                        service.returned_date = None
                        service.save()
                details = f"Staff changed status from '{old_status}' to '{job.get_status_display()}'."
                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='STATUS', details=details)

            send_job_update_message(job.job_code, job.status)
            messages.success(request, f"Status updated to {job.get_status_display()}.")
            return redirect('staff_job_detail', job_code=job_code)

        if action == 'update_checklist':
            posted_answers, missing_required_labels, invalid_option_labels = _extract_checklist_answers_from_post(
                request.POST,
                checklist_schema,
            )

            if invalid_option_labels:
                messages.error(
                    request,
                    "Invalid checklist selection for: "
                    + ', '.join(invalid_option_labels[:6])
                    + ('...' if len(invalid_option_labels) > 6 else ''),
                )
                return redirect('staff_job_detail', job_code=job_code)

            if missing_required_labels:
                messages.error(request, _format_checklist_required_error(missing_required_labels))
                return redirect('staff_job_detail', job_code=job_code)

            old_answers = _get_job_checklist_answers(job)
            merged_answers = _merge_checklist_answers(old_answers, posted_answers)

            if merged_answers == old_answers:
                messages.info(request, 'No checklist changes detected.')
                return redirect('staff_job_detail', job_code=job_code)

            job.technician_checklist = merged_answers
            job.save(update_fields=['technician_checklist', 'updated_at'])

            change_details = []
            for field in checklist_schema:
                key = field['key']
                field_type = field.get('type')
                if field_type == 'checkbox':
                    old_value = _normalize_checkbox_answer(old_answers.get(key, ''))
                    new_value = _normalize_checkbox_answer(merged_answers.get(key, ''))
                    old_text = 'Verified' if old_value == '1' else 'Not Verified'
                    new_text = 'Verified' if new_value == '1' else 'Not Verified'
                else:
                    old_value = _normalize_checklist_answer(old_answers.get(key, ''))
                    new_value = _normalize_checklist_answer(merged_answers.get(key, ''))
                    old_text = old_value or 'blank'
                    new_text = new_value or 'blank'

                if old_value != new_value:
                    change_details.append(f"{field['label']}: '{old_text}' -> '{new_text}'")

            if change_details:
                details = "Staff updated inspection checklist: " + "; ".join(change_details[:10])
                if len(change_details) > 10:
                    details += "..."
            else:
                details = "Staff updated inspection checklist."

            JobTicketLog.objects.create(
                job_ticket=job,
                user=request.user,
                action='NOTE',
                details=details,
            )
            messages.success(request, 'Inspection checklist updated.')
            return redirect('staff_job_detail', job_code=job_code)

        if action in {'save_estimation', 'send_estimation_whatsapp'}:
            estimation_error = _save_job_estimation_from_post(request, job)
            if estimation_error:
                messages.error(request, estimation_error)
                return redirect('staff_job_detail', job_code=job_code)

            if action == 'save_estimation':
                messages.success(request, 'Estimate note saved.')
                return redirect('staff_job_detail', job_code=job_code)

            if job.estimated_amount is None:
                messages.error(request, 'Enter estimate amount before sending WhatsApp.')
                return redirect('staff_job_detail', job_code=job_code)

            result = queue_job_whatsapp_message(job, MessageQueue.EVENT_ESTIMATE)
            if result.get('ok'):
                queue_id = (result.get('data') or {}).get('message_queue_id')
                queue = MessageQueue.objects.filter(id=queue_id).first() if queue_id else None
                if queue and queue.status == MessageQueue.STATUS_FAILED:
                    messages.error(request, queue.error_message or 'Estimate WhatsApp failed.')
                else:
                    active_reminder = _active_job_reminder(job)
                    if active_reminder:
                        now = timezone.now()
                        active_reminder.status = JobReminder.STATUS_DONE
                        active_reminder.completed_at = now
                        active_reminder.save(update_fields=['status', 'completed_at', 'updated_at'])
                        JobTicketLog.objects.create(
                            job_ticket=job,
                            user=request.user,
                            action='NOTE',
                            details='Callback reminder completed after estimate WhatsApp was queued.',
                        )
                    messages.success(request, 'Estimate WhatsApp queued.')
            else:
                messages.error(request, result.get('error') or 'Unable to queue estimate WhatsApp.')
            return redirect('staff_job_detail', job_code=job_code)

        if action in {'schedule_reminder', 'reschedule_reminder'}:
            due_at, reminder_error = _parse_reminder_due_at(request.POST, require_value=False)
            if due_at is None and not reminder_error:
                reminder_delta, reminder_error = _parse_reminder_offset(request.POST, require_value=True)
                due_at = timezone.now() + reminder_delta if reminder_delta else None
            if reminder_error:
                messages.error(request, reminder_error)
                return redirect('staff_job_detail', job_code=job_code)

            reminder_id = (request.POST.get('reminder_id') or '').strip()
            reminder = None
            if reminder_id:
                reminder = get_object_or_404(JobReminder, id=reminder_id, job_ticket=job)
            if reminder is None:
                reminder = _active_job_reminder(job)

            local_due_at = timezone.localtime(due_at).strftime('%d-%m-%Y %I:%M %p')
            if reminder:
                old_due_at = timezone.localtime(reminder.due_at).strftime('%d-%m-%Y %I:%M %p')
                reminder.due_at = due_at
                reminder.status = JobReminder.STATUS_PENDING
                reminder.completed_at = None
                reminder.last_prompted_at = None
                reminder.save(update_fields=['due_at', 'status', 'completed_at', 'last_prompted_at', 'updated_at'])
                details = f"Callback reminder rescheduled from {old_due_at} to {local_due_at}."
            else:
                JobReminder.objects.create(
                    job_ticket=job,
                    due_at=due_at,
                    created_by=request.user,
                )
                details = f"Callback reminder scheduled for {local_due_at}."

            JobTicketLog.objects.create(job_ticket=job, user=request.user, action='NOTE', details=details)
            messages.success(request, 'Reminder scheduled.')
            return redirect('staff_job_detail', job_code=job_code)

        if action == 'complete_reminder':
            reminder_id = (request.POST.get('reminder_id') or '').strip()
            reminder = get_object_or_404(JobReminder, id=reminder_id, job_ticket=job)
            if reminder.status != JobReminder.STATUS_DONE:
                reminder.status = JobReminder.STATUS_DONE
                reminder.completed_at = timezone.now()
                reminder.save(update_fields=['status', 'completed_at', 'updated_at'])
                JobTicketLog.objects.create(
                    job_ticket=job,
                    user=request.user,
                    action='NOTE',
                    details='Callback reminder marked done.',
                )
                messages.success(request, 'Reminder marked done.')
            else:
                messages.info(request, 'Reminder is already done.')
            return redirect('staff_job_detail', job_code=job_code)

    job_tickets = [job]
    calculate_job_totals(job_tickets)
    
    history_logs = job.logs.all().select_related('user')
    specialized_service = SpecializedService.objects.filter(job_ticket=job).first()
    technician_list = get_assignable_technician_queryset(getattr(request, 'current_workspace', None) or job.workspace)
    job_reminders = job.reminders.select_related('created_by').order_by('-due_at', '-id')
    active_reminder = _active_job_reminder(job)
    reminder_schedule = _default_reminder_schedule(active_reminder)
    
    if job.customer_group_id:
        related_jobs = JobTicket.objects.filter(
            customer_group_id=job.customer_group_id
        ).exclude(job_code=job.job_code).order_by('-created_at')
    else:
        related_jobs = JobTicket.objects.none()
    
    subtotal = job.total
    grand_total = subtotal - job.discount_amount
    amount_paid = job.amount_paid or Decimal('0.00')
    balance_due = max(Decimal('0.00'), grand_total - amount_paid)
    job_payments = (
        InventoryCreditPayment.objects.filter(bill__job_ticket=job)
        .select_related('created_by')
        .order_by('-payment_date', '-id')
    )
    
    # Generate QR code URL
    qr_url = request.build_absolute_uri(f'/qr/{job.job_code}/')

    context = {
        'job': job,
        'service_logs': job.service_logs.all(),
        'history_logs': history_logs,
        'total_parts_cost': job.part_total,
        'total_service_charges': job.service_total,
        'subtotal': subtotal,
        'discount_amount': job.discount_amount,
        'grand_total': grand_total,
        'amount_paid': amount_paid,
        'balance_due': balance_due,
        'job_payments': job_payments,
        'payment_methods': InventoryCreditPayment.METHOD_CHOICES,
        'specialized_service': specialized_service,
        'related_jobs': related_jobs,
        'technician_list': technician_list,
        'ReassignTechnicianForm': ReassignTechnicianForm(workspace=getattr(request, 'current_workspace', None) or job.workspace),
        'qr_url': qr_url,
        'checklist_schema': checklist_schema,
        'checklist_title': checklist_title,
        'checklist_notes': checklist_notes,
        'staff_status_choices': JobTicket.STATUS_CHOICES,
        'today': timezone.localdate().isoformat(),
        'job_reminders': job_reminders,
        'active_reminder': active_reminder,
        'reminder_schedule': reminder_schedule,
    }
    return render(request, 'job_tickets/staff_job_detail.html', context)


@login_required
@require_POST
def staff_job_collect_payment(request, job_code):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    job = get_object_or_404(JobTicket, job_code=job_code)
    if not user_has_workspace_access(request.user, job.workspace):
        return redirect('unauthorized')

    calculate_job_totals([job])
    grand_total = max(Decimal('0.00'), (job.total or Decimal('0.00')) - (job.discount_amount or Decimal('0.00')))
    current_paid = job.amount_paid or Decimal('0.00')
    balance_due = max(Decimal('0.00'), grand_total - current_paid)

    if balance_due <= Decimal('0.00'):
        messages.info(request, f"Job {job.job_code} is already fully settled.")
        return redirect('staff_job_detail', job_code=job_code)

    amount_raw = (request.POST.get('amount') or '').strip()
    try:
        amount = Decimal(amount_raw).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError, TypeError):
        messages.error(request, "Please enter a valid payment amount.")
        return redirect('staff_job_detail', job_code=job_code)

    if amount <= Decimal('0.00'):
        messages.error(request, "Payment amount must be greater than zero.")
        return redirect('staff_job_detail', job_code=job_code)

    if amount > balance_due:
        messages.error(request, f"Payment amount (Rs.{amount}) cannot exceed current balance due of Rs.{balance_due}.")
        return redirect('staff_job_detail', job_code=job_code)

    method_key = (request.POST.get('payment_method') or InventoryCreditPayment.METHOD_CASH).strip()
    custom_method = (request.POST.get('custom_payment_method') or '').strip()
    if method_key in {'custom', 'other'} and custom_method:
        payment_method_display = custom_method
        inv_method = InventoryCreditPayment.METHOD_CASH
    else:
        valid_methods = {choice[0] for choice in InventoryCreditPayment.METHOD_CHOICES}
        inv_method = method_key if method_key in valid_methods else InventoryCreditPayment.METHOD_CASH
        payment_method_display = dict(InventoryCreditPayment.METHOD_CHOICES).get(inv_method, inv_method)

    payment_reference = (request.POST.get('payment_reference') or '').strip()
    notes = (request.POST.get('notes') or '').strip()

    # Dynamic Custom Payment Fields
    custom_field_names = request.POST.getlist('custom_field_name[]')
    custom_field_values = request.POST.getlist('custom_field_value[]')
    custom_pairs = []
    for name, val in zip(custom_field_names, custom_field_values):
        k = (name or '').strip()
        v = (val or '').strip()
        if k and v:
            custom_pairs.append(f"{k}: {v}")

    custom_fields_str = f" [{', '.join(custom_pairs)}]" if custom_pairs else ""

    payment_date_raw = (request.POST.get('payment_date') or '').strip()
    if payment_date_raw:
        try:
            payment_date = datetime.strptime(payment_date_raw, '%Y-%m-%d').date()
        except ValueError:
            payment_date = timezone.localdate()
    else:
        payment_date = timezone.localdate()

    with transaction.atomic():
        new_paid = (current_paid + amount).quantize(Decimal('0.01'))
        new_balance = max(Decimal('0.00'), grand_total - new_paid)
        job.amount_paid = new_paid
        job.payment_status = 'paid' if new_balance <= Decimal('0.00') else 'part_paid'
        job.payment_method = payment_method_display
        if payment_reference:
            job.payment_reference = payment_reference
        job.payment_date = timezone.now()
        job.save(update_fields=['amount_paid', 'payment_status', 'payment_method', 'payment_reference', 'payment_date', 'updated_at'])

        # Sync with Inventory Party & Bill
        party = _get_or_create_inventory_customer_party_for_job(job)
        bill = InventoryBill.objects.filter(entry_type='sale', job_ticket=job).first()
        if not bill:
            bill = InventoryBill.objects.create(
                workspace=job.workspace,
                bill_number=_generate_inventory_bill_number('sale', payment_date, job.workspace),
                entry_type='sale',
                entry_date=payment_date,
                invoice_number=job.vyapar_invoice_number or '',
                job_ticket=job,
                party=party,
                notes=f"Repair Job {job.job_code} settlement",
                created_by=request.user,
            )
        if not bill.entries.exists():
            InventoryEntry.objects.create(
                workspace=job.workspace,
                bill=bill,
                party=party,
                entry_type='sale',
                entry_date=payment_date,
                quantity=1,
                unit_price=grand_total,
                total_amount=grand_total,
                notes=f"Repair Service Charges - Job {job.job_code}",
                job_ticket=job,
                created_by=request.user,
            )

        pay_note = f"Collected for Job {job.job_code} via {payment_method_display}.{custom_fields_str} {notes}".strip()
        InventoryCreditPayment.objects.create(
            workspace=job.workspace,
            party=party,
            bill=bill,
            direction=InventoryCreditPayment.DIRECTION_RECEIVABLE,
            payment_date=payment_date,
            payment_method=inv_method,
            amount=amount,
            balance_before=balance_due,
            balance_after=new_balance,
            reference_no=payment_reference,
            notes=pay_note,
            created_by=request.user,
        )

        log_details = f"Collected installment payment of Rs.{amount} via {payment_method_display}."
        if payment_reference:
            log_details += f" Ref: {payment_reference}."
        if custom_pairs:
            log_details += f" Custom Fields: {', '.join(custom_pairs)}."
        log_details += f" Remaining Balance: Rs.{new_balance} ({job.get_payment_status_display()})."
        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='PAYMENT', details=log_details)

    send_job_update_message(job.job_code, job.status)
    messages.success(request, f"Payment of Rs.{amount} collected successfully via {payment_method_display}. Remaining balance: Rs.{new_balance}.")
    return redirect('staff_job_detail', job_code=job_code)

@login_required
@require_POST
def staff_delete_job_photo(request, job_code, photo_id):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    job = get_object_or_404(JobTicket, job_code=job_code)
    if not user_has_workspace_access(request.user, job.workspace):
        return redirect('unauthorized')
    photo = get_object_or_404(JobTicketPhoto, id=photo_id, job_ticket=job)

    try:
        if photo.image:
            photo.image.delete(save=False)
    except Exception:
        pass

    photo.delete()
    messages.success(request, 'Photo deleted successfully.')
    return redirect('staff_job_detail', job_code=job_code)

@login_required
def staff_job_photo_file(request, job_code, photo_id):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    job = get_object_or_404(JobTicket, job_code=job_code)
    if not user_has_workspace_access(request.user, job.workspace):
        return redirect('unauthorized')
    photo = get_object_or_404(JobTicketPhoto, id=photo_id, job_ticket=job)

    if photo.image_data:
        response = HttpResponse(photo.image_data, content_type=photo.image_content_type or 'application/octet-stream')
        response['Content-Disposition'] = f'inline; filename="{photo.image_name or f"{job.job_code}-photo-{photo.id}.jpg"}"'
        return response

    if photo.image:
        with photo.image.open('rb') as image_file:
            image_bytes = image_file.read()
        response = HttpResponse(
            image_bytes,
            content_type=photo.image_content_type or mimetypes.guess_type(photo.image.name)[0] or 'application/octet-stream',
        )
        response['Content-Disposition'] = f'inline; filename="{photo.image_name or f"{job.job_code}-photo-{photo.id}.jpg"}"'
        return response

    return HttpResponse(status=404)

@login_required
@require_POST
def unlock_vendor_details(request, job_code):
    """Unlock vendor details section with password verification."""
    if not request.user.is_staff or not user_has_staff_access(request.user, "staff_dashboard"):
        return JsonResponse({'ok': False, 'error': 'Unauthorized'}, status=403)
    
    password = request.POST.get('vendor_password', '').strip()
    
    # Check against the authenticated user's password.
    from django.contrib.auth import authenticate
    user_auth = authenticate(username=request.user.username, password=password)
    
    if user_auth is not None:
        job = get_object_or_404(JobTicket, job_code=job_code)
        if not user_has_workspace_access(request.user, job.workspace):
            return JsonResponse({'ok': False, 'error': 'Unauthorized'}, status=403)
        request.session['vendor_details_unlocked_job_code'] = job_code
        request.session['vendor_details_unlocked'] = True
        request.session.modified = True
        request.session.set_expiry(3600)

        # Get specialized service data for AJAX response
        specialized_service = SpecializedService.objects.filter(job_ticket=job).first()
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'ok': True, 
                'message': 'Vendor details unlocked.',
                'vendor_name': str(specialized_service.vendor) if specialized_service and specialized_service.vendor else 'N/A',
                'status': specialized_service.get_status_display() if specialized_service else 'N/A',
                'vendor_cost': float(specialized_service.vendor_cost) if specialized_service and specialized_service.vendor_cost else 0,
                'vendor_discount_amount': float(specialized_service.vendor_discount_amount) if specialized_service else 0,
                'vendor_paid_amount': float(specialized_service.vendor_paid_amount) if specialized_service else 0,
                'vendor_balance_amount': float(specialized_service.vendor_balance_amount) if specialized_service else 0,
                'vendor_net_payable': float(specialized_service.vendor_net_payable) if specialized_service else 0,
                'vendor_payment_status': specialized_service.vendor_payment_status if specialized_service else 'N/A',
                'client_charge': float(specialized_service.client_charge) if specialized_service and specialized_service.client_charge else 0,
                'sent_date': specialized_service.sent_date.strftime('%Y-%m-%d') if specialized_service and specialized_service.sent_date else None,
                'returned_date': specialized_service.returned_date.strftime('%Y-%m-%d') if specialized_service and specialized_service.returned_date else None
            })
        messages.success(request, 'Vendor details unlocked.')
    else:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': 'Incorrect password.'}, status=400)
        messages.error(request, 'Incorrect password.')
    
    return redirect('staff_job_detail', job_code=job_code)

@login_required
@require_POST
def lock_vendor_details(request, job_code):
    """Lock vendor details section."""
    if not request.user.is_staff or not user_has_staff_access(request.user, "staff_dashboard"):
        return JsonResponse({'ok': False, 'error': 'Unauthorized'}, status=403)
    
    request.session.pop('vendor_details_unlocked_job_code', None)
    request.session['vendor_details_unlocked'] = False
    request.session.modified = True  # Ensure session is saved
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'message': 'Vendor details locked.'})
    
    messages.info(request, 'Vendor details locked.')
    return redirect('staff_job_detail', job_code=job_code)


@login_required
@require_GET
def due_job_reminders_api(request):
    if not request.user.is_staff or not user_has_staff_access(request.user, "staff_dashboard"):
        return JsonResponse({'ok': False, 'error': 'Unauthorized'}, status=403)

    now = timezone.now()
    prompt_cutoff = now - timedelta(minutes=REMINDER_PROMPT_COOLDOWN_MINUTES)
    reminders = list(
        JobReminder.objects.filter(
            status=JobReminder.STATUS_PENDING,
            due_at__lte=now,
        )
        .filter(Q(last_prompted_at__isnull=True) | Q(last_prompted_at__lte=prompt_cutoff))
        .select_related('job_ticket')
        .order_by('due_at', 'id')[:5]
    )

    reminder_ids = [reminder.id for reminder in reminders]
    if reminder_ids:
        JobReminder.objects.filter(id__in=reminder_ids).update(last_prompted_at=now)

    payload = []
    for reminder in reminders:
        job = reminder.job_ticket
        payload.append({
            'id': reminder.id,
            'job_code': job.job_code,
            'customer_name': job.customer_name,
            'customer_phone': job.customer_phone,
            'device': ' '.join(part for part in [job.device_type, job.device_brand, job.device_model] if part).strip(),
            'due_at': timezone.localtime(reminder.due_at).strftime('%d-%m-%Y %I:%M %p'),
            'url': reverse('staff_job_detail', args=[job.job_code]),
        })

    return JsonResponse({
        'ok': True,
        'count': len(payload),
        'cooldown_minutes': REMINDER_PROMPT_COOLDOWN_MINUTES,
        'reminders': payload,
    })


@login_required
def api_all_jobs(request):
    """API endpoint to fetch all jobs as JSON for real-time updates"""
    if not request.user.is_staff or not user_has_staff_access(request.user, "staff_dashboard"):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    jobs = JobTicket.objects.all().select_related(
        'assigned_to__user', 'created_by'
    ).prefetch_related('service_logs').order_by('-created_at')
    
    calculate_job_totals(jobs)
    
    jobs_data = []
    for job in jobs:
        jobs_data.append({
            'job_code': job.job_code,
            'customer_name': job.customer_name,
            'customer_phone': job.customer_phone,
            'device_type': job.device_type,
            'device_brand': job.device_brand or '',
            'device_model': job.device_model or '',
            'status': job.status,
            'status_display': job.get_status_display(),
            'assigned_to': job.assigned_to.user.username if job.assigned_to and job.assigned_to.user else None,
            'created_at': job.created_at.strftime('%Y-%m-%d %H:%M'),
            'updated_at': job.updated_at.strftime('%Y-%m-%d %H:%M'),
            'total': str(job.total) if job.total else '0.00',
            'part_total': str(job.part_total) if job.part_total else '0.00',
            'service_total': str(job.service_total) if job.service_total else '0.00',
            'discount_amount': str(job.discount_amount) if job.discount_amount else '0.00',
            'technician_notes': job.technician_notes or '',
            'url': f'/staff/job/{job.job_code}/',
        })
    
    return JsonResponse({'jobs': jobs_data})

@login_required
def print_active_workload_report(request):
    access = get_staff_access(request.user)
    if not request.user.is_staff or not access.get("reports_overview"):
        return redirect('unauthorized')
    
    # Define statuses that represent active work (In-Progress)
    active_statuses = ['Under Inspection', 'Repairing', 'Specialized Service', 'Returned']
    
    # 1. Fetch active jobs, excluding those that are ready for pickup or closed
    active_jobs = list(JobTicket.objects.filter(
        status__in=active_statuses
    ).select_related('assigned_to__user').prefetch_related('service_logs').order_by('assigned_to__user__username', 'job_code'))
    calculate_job_totals(active_jobs)
    for job in active_jobs:
        job.discount_total = _money_or_zero(job.discount_amount)
        job.net_total = _net_amount_after_discount(job.total, job.discount_total)

    # 2. Group the jobs by Technician for clear reporting
    grouped_jobs = {}
    
    for job in active_jobs:
        technician_name = job.assigned_to.user.username if job.assigned_to and job.assigned_to.user else "UNASSIGNED"
        
        if technician_name not in grouped_jobs:
            grouped_jobs[technician_name] = []
            
        grouped_jobs[technician_name].append(job)

    # 3. Prepare the final context
    company = CompanyProfile.get_profile()
    context = {
        'grouped_jobs': grouped_jobs,
        'report_date': datetime.now(),
        'company': company,
    }
    return render(request, 'job_tickets/print_active_workload_report.html', context)

@login_required
@require_POST
def job_reassign_staff(request, job_code):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    
    job = get_object_or_404(JobTicket, job_code=job_code)
    
    form = ReassignTechnicianForm(request.POST, workspace=getattr(request, 'current_workspace', None) or job.workspace)

    if form.is_valid():
        new_technician = form.cleaned_data['new_technician']

        # Get old values for logging
        old_technician_name = job.assigned_to.user.username if job.assigned_to else "Unassigned"
        new_technician_name = new_technician.user.username if new_technician else "Unassigned"

        # Prevent assigning to the same person
        if job.assigned_to == new_technician and new_technician is not None:
            messages.warning(request, f"Job {job_code} is already assigned to {old_technician_name}.")
            return redirect('staff_job_detail', job_code=job_code)

        with transaction.atomic():
            job.assigned_to = new_technician
            job.is_new_assignment = True if new_technician else False
            job.save(update_fields=['assigned_to', 'is_new_assignment', 'updated_at'])

            details = f"Reassigned from '{old_technician_name}' to '{new_technician_name}' by staff."
            JobTicketLog.objects.create(job_ticket=job, user=request.user, action='ASSIGNED', details=details)

            send_job_update_message(job.job_code, job.status)

        messages.success(request, f"Job {job_code} successfully reassigned to {new_technician_name}.")
        return redirect('staff_job_detail', job_code=job_code)

    messages.error(request, "Invalid reassignment attempt.")
    return redirect('staff_job_detail', job_code=job_code)


@login_required
def staff_job_archive_view(request):
    access = get_staff_access(request.user)
    if not request.user.is_staff or not access.get("reports_overview"):
        return redirect('unauthorized')

    # Get URL parameters for filtering
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    # Start with a queryset of ALL jobs, ordered by latest first
    jobs_queryset = JobTicket.objects.all().order_by('-created_at')

    # --- Date Filtering Logic ---
    start_date = None
    end_date = None
    
    if start_date_str and end_date_str:
        try:
            # 1. Parse Dates
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            # 2. Create Timezone-Aware Boundaries for Query
            start_of_period = timezone.make_aware(datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0))
            end_of_period = timezone.make_aware(datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59))
            
            # 3. Apply Filter to Queryset (Filtering by Created Date)
            jobs_queryset = jobs_queryset.filter(
                created_at__gte=start_of_period,
                created_at__lte=end_of_period
            )
            
        except ValueError:
            messages.error(request, "Invalid date format provided for filtering.")
            # Keep jobs_queryset unfiltered on error
    
    jobs_list = list(jobs_queryset.prefetch_related('service_logs'))
    calculate_job_totals(jobs_list)
    for job in jobs_list:
        job.discount_total = _money_or_zero(job.discount_amount)
        job.net_total = _net_amount_after_discount(job.total, job.discount_total)

    total_amount_sum = sum((job.total for job in jobs_list), Decimal('0.00'))
    total_discount_sum = sum((job.discount_total for job in jobs_list), Decimal('0.00'))
    grand_total_amount = _net_amount_after_discount(total_amount_sum, total_discount_sum)

    # --- Context Setup ---
    context = {
        'jobs': jobs_list,
        'current_start_date': start_date_str,
        'current_end_date': end_date_str,
        'today_date_str': timezone.localdate().strftime('%Y-%m-%d'),
        # Assuming you have a helper for company start date:
        'company_start_date': get_company_start_date().strftime('%Y-%m-%d'), 
        'total_jobs_count': len(jobs_list),
        'total_jobs_amount': grand_total_amount,
    }
    return render(request, 'job_tickets/staff_job_archive.html', context)

def staff_job_filtered_archive_view(request, status_code):
    access = get_staff_access(request.user)
    if not request.user.is_staff or not access.get("reports_overview"):
        return redirect('unauthorized')

    # Get optional date filters
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    status_filter = request.GET.get('status_filter')  # New: sub-status filter for returned jobs
    
    # Start with a queryset of ALL jobs, ordered by latest first
    jobs_queryset = JobTicket.objects.all().order_by('-created_at')
    
    # --- Status Filtering Logic ---
    report_title = "Filtered Job Archive"

    # Define Q object for filtering
    q_status_filter = Q()
    
    # Standard statuses for display clarity
    if status_code == 'Pending':
        q_status_filter = Q(status='Pending')
        report_title = "Pending Jobs Archive"
    elif status_code == 'Active':
        q_status_filter = Q(status__in=['Under Inspection', 'Repairing', 'Specialized Service'])
        report_title = "Active Workload Archive"
    elif status_code == 'CompletedReady':
        q_status_filter = Q(status__in=['Completed', 'Ready for Pickup'])
        report_title = "Completed/Ready Jobs Archive"
    elif status_code == 'Returned':
        closed_returned_job_ids = get_returned_to_closed_job_ids()
        
        if status_filter == 'closed':
            # Jobs that were closed directly from Returned status
            q_status_filter = Q(id__in=closed_returned_job_ids, status='Closed')
            report_title = "Returned -> Closed Jobs"
        elif status_filter == 'returned':
            # Jobs that are currently in returned status
            q_status_filter = Q(status='Returned')
            report_title = "Returned Jobs - Still Returned"
        else:
            # Show current Returned jobs and jobs closed directly from Returned status
            q_status_filter = Q(status='Returned') | Q(id__in=closed_returned_job_ids, status='Closed')
            report_title = "Returned -> Closed Jobs"
    elif status_code == 'Closed':
        q_status_filter = Q(status='Closed')
        report_title = "Closed Jobs Archive"
    
    jobs_queryset = jobs_queryset.filter(q_status_filter)

    # --- Date Filtering Logic (Copied from staff_job_archive_view) ---
    start_date = None
    end_date = None
    
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            start_of_period = timezone.make_aware(datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0))
            end_of_period = timezone.make_aware(datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59))
            
            # Apply Filter by Created Date
            jobs_queryset = jobs_queryset.filter(
                created_at__gte=start_of_period,
                created_at__lte=end_of_period
            )
            
        except ValueError:
            messages.error(request, "Invalid date format provided for filtering.")

        # Fetch job objects (including prefetched service_logs) to calculate totals per job
    jobs_list = list(jobs_queryset.prefetch_related('service_logs'))
    
    # Reuse the helper function to calculate individual job totals (part_total, service_total, total)
    calculate_job_totals(jobs_list) 
    
    # Calculate the grand total and grand discount from the list
    for job in jobs_list:
        job.discount_total = _money_or_zero(job.discount_amount)
        job.net_total = _net_amount_after_discount(job.total, job.discount_total)

    total_amount_sum = sum((job.total for job in jobs_list), Decimal('0.00'))
    total_discount_sum = sum((job.discount_total for job in jobs_list), Decimal('0.00'))
    
    # Grand Total (Subtotal - Discount)
    grand_total_amount = _net_amount_after_discount(total_amount_sum, total_discount_sum)
    total_jobs_count = len(jobs_list)
    
    # Calculate counts for returned jobs filtering
    returned_count = 0
    closed_returned_count = 0
    if status_code == 'Returned':
        # Count jobs currently in Returned status
        returned_count = JobTicket.objects.filter(status='Returned').count()
        # Count jobs closed directly from Returned status
        closed_returned_count = get_returned_to_closed_jobs().count()
    
    # --- Context Setup ---
    context = {
        'jobs': jobs_list,
        'report_title': report_title,
        'current_start_date': start_date_str,
        'current_end_date': end_date_str,
        'today_date_str': timezone.localdate().strftime('%Y-%m-%d'),
        'company_start_date': get_company_start_date().strftime('%Y-%m-%d'), 
        'status_code': status_code, # Pass code back for form actions
        'status_filter': status_filter,  # Pass current sub-status filter
        'total_jobs_count': total_jobs_count,
        'total_jobs_amount': grand_total_amount,
        'returned_count': returned_count,
        'closed_returned_count': closed_returned_count,
    }
    return render(request, 'job_tickets/closed_job_archive.html', context)


# ---------------------------------------------------------------------------
# Standalone Task Management Views (Staff)
# ---------------------------------------------------------------------------

@login_required
def task_dashboard(request):
    """Priority-ordered dashboard of standalone tasks with search and filtering."""
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    qs = Task.objects.all()
    if workspace:
        qs = qs.filter(workspace=workspace)

    # Search query
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) |
            Q(description__icontains=q) |
            Q(assigned_to__user__username__icontains=q) |
            Q(job_reference__job_code__icontains=q)
        )

    # Priority filter
    priority = (request.GET.get('priority') or '').strip().lower()
    if priority in dict(Task.PRIORITY_CHOICES):
        qs = qs.filter(priority=priority)

    # Status filter
    status = (request.GET.get('status') or '').strip().lower()
    if status in dict(Task.STATUS_CHOICES):
        qs = qs.filter(status=status)
    elif status == 'all':
        pass
    else:
        status = 'active'
        qs = qs.filter(status__in=[Task.STATUS_OPEN, Task.STATUS_IN_PROGRESS])

    # Technician filter
    tech_id = request.GET.get('tech')
    if tech_id:
        qs = qs.filter(assigned_to_id=tech_id)

    tasks = list(qs.select_related('assigned_to__user', 'created_by', 'job_reference').prefetch_related('attachments', 'messages'))

    # Metrics on total tasks
    base_qs = Task.objects.all()
    if workspace:
        base_qs = base_qs.filter(workspace=workspace)
    urgent_count = base_qs.filter(priority=Task.PRIORITY_URGENT, status__in=[Task.STATUS_OPEN, Task.STATUS_IN_PROGRESS]).count()
    open_count = base_qs.filter(status=Task.STATUS_OPEN).count()
    in_progress_count = base_qs.filter(status=Task.STATUS_IN_PROGRESS).count()
    done_count = base_qs.filter(status=Task.STATUS_DONE).count()

    create_form = TaskCreateForm(workspace=workspace)
    technicians = get_assignable_technician_queryset(workspace)

    context = {
        'tasks': tasks,
        'urgent_count': urgent_count,
        'open_count': open_count,
        'in_progress_count': in_progress_count,
        'done_count': done_count,
        'status_filter': status,
        'priority_filter': priority,
        'tech_filter': tech_id,
        'search_query': q,
        'create_form': create_form,
        'technicians': technicians,
    }
    return render(request, 'job_tickets/task_dashboard.html', context)


@login_required
@require_POST
def task_create(request):
    """Create a new standalone task."""
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    form = TaskCreateForm(request.POST, workspace=workspace)
    if form.is_valid():
        task = Task.objects.create(
            workspace=workspace,
            title=form.cleaned_data['title'],
            description=form.cleaned_data.get('description') or '',
            priority=form.cleaned_data['priority'],
            due_date=form.cleaned_data.get('due_date'),
            assigned_to=form.cleaned_data.get('assigned_to'),
            job_reference=form.cleaned_data.get('job_reference'),
            created_by=request.user,
        )
        files = request.FILES.getlist('attachments')
        for f in files:
            TaskAttachment.objects.create(
                task=task,
                file=f,
                file_name=f.name,
                file_size=f.size,
                uploaded_by=request.user,
            )
        initial_message = (request.POST.get('initial_message') or '').strip()
        if initial_message:
            init_msg = TaskMessage.objects.create(
                task=task,
                sender=request.user,
                body=initial_message,
            )
            broadcast_task_message(task, init_msg)
        broadcast_task_created(task)
        messages.success(request, f"Task '{task.title}' created successfully.")
        return redirect('task_detail', task_id=task.id)

    for field, errs in form.errors.items():
        messages.error(request, f"{field}: {', '.join(errs)}")
    return redirect('task_dashboard')


@login_required
def task_detail(request, task_id):
    """View task detail with message thread, attachments, and status controls."""
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    qs = Task.objects.select_related('assigned_to__user', 'created_by', 'job_reference', 'workspace')
    if workspace:
        qs = qs.filter(workspace=workspace)
    task = get_object_or_404(qs, id=task_id)

    attachments = task.attachments.all()
    messages_list = task.messages.select_related('sender').all()
    message_form = TaskMessageForm()
    technicians = get_assignable_technician_queryset(workspace)

    context = {
        'task': task,
        'attachments': attachments,
        'messages_list': messages_list,
        'message_form': message_form,
        'technicians': technicians,
    }
    return render(request, 'job_tickets/task_detail.html', context)


@login_required
@require_POST
def task_message_send(request, task_id):
    """Send a message and optional attachments on a task thread."""
    workspace = getattr(request, 'current_workspace', None)
    qs = Task.objects.all()
    if workspace:
        qs = qs.filter(workspace=workspace)
    task = get_object_or_404(qs, id=task_id)

    is_tech = hasattr(request.user, 'technician_profile') and task.assigned_to == request.user.technician_profile
    if not request.user.is_staff and not is_tech:
        return HttpResponseForbidden("Access denied.")

    form = TaskMessageForm(request.POST)
    if form.is_valid():
        msg = TaskMessage.objects.create(
            task=task,
            sender=request.user,
            body=form.cleaned_data['body'],
        )
        files = request.FILES.getlist('attachments')
        for f in files:
            TaskAttachment.objects.create(
                task=task,
                file=f,
                file_name=f.name,
                file_size=f.size,
                uploaded_by=request.user,
            )
        broadcast_task_message(task, msg)
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'ok': True,
                'id': msg.id,
                'sender': msg.sender.username,
                'body': msg.body,
                'sent_at': timezone.localtime(msg.sent_at).strftime('%d %b %Y, %H:%M'),
            })

    if is_tech and not request.user.is_staff:
        return redirect('technician_task_detail', task_id=task.id)
    return redirect('task_detail', task_id=task.id)


@login_required
@require_POST
def task_update_status(request, task_id):
    """Update task status, priority, or assignee."""
    workspace = getattr(request, 'current_workspace', None)
    qs = Task.objects.all()
    if workspace:
        qs = qs.filter(workspace=workspace)
    task = get_object_or_404(qs, id=task_id)

    is_tech = hasattr(request.user, 'technician_profile') and task.assigned_to == request.user.technician_profile
    if not request.user.is_staff and not is_tech:
        return HttpResponseForbidden("Access denied.")

    old_status = task.status
    new_status = (request.POST.get('status') or '').strip().lower()
    if new_status in dict(Task.STATUS_CHOICES):
        if new_status == Task.STATUS_IN_PROGRESS:
            task.mark_in_progress()
        elif new_status == Task.STATUS_DONE:
            task.mark_done()
        elif new_status == Task.STATUS_CANCELLED:
            task.mark_cancelled()
        elif new_status == Task.STATUS_OPEN:
            task.status = Task.STATUS_OPEN
            task.completed_at = None
            task.save(update_fields=['status', 'completed_at', 'updated_at'])
        if new_status != old_status:
            broadcast_task_status(task, old_status, new_status, request.user)
        messages.success(request, f"Task status updated to {task.get_status_display()}.")

    if request.user.is_staff:
        if 'priority' in request.POST and request.POST['priority'] in dict(Task.PRIORITY_CHOICES):
            task.priority = request.POST['priority']
            task.save(update_fields=['priority', 'updated_at'])
            broadcast_task_status(task, task.status, task.status, request.user)
        if 'assigned_to' in request.POST:
            tech_id = request.POST.get('assigned_to')
            task.assigned_to_id = tech_id if tech_id else None
            task.save(update_fields=['assigned_to', 'updated_at'])
            broadcast_task_status(task, task.status, task.status, request.user)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'ok': True,
            'status': task.status,
            'status_display': task.get_status_display(),
            'priority': task.priority,
            'priority_display': task.get_priority_display(),
        })

    if is_tech and not request.user.is_staff:
        return redirect('technician_task_detail', task_id=task.id)
    return redirect('task_detail', task_id=task.id)


@login_required
@require_POST
def task_delete(request, task_id):
    """Delete a task (staff only)."""
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    qs = Task.objects.all()
    if workspace:
        qs = qs.filter(workspace=workspace)
    task = get_object_or_404(qs, id=task_id)
    workspace_id = task.workspace_id
    title = task.title
    task.delete()
    broadcast_task_deleted(workspace_id, task_id, title)
    messages.success(request, f"Task '{title}' deleted.")
    return redirect('task_dashboard')
