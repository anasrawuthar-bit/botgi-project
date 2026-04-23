from .helpers import *  # noqa: F401,F403


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

        # Auto-create or refresh the client directory.
        try:
            existing_client = Client.objects.filter(phone__in=phone_lookup_variants(customer_phone)).order_by('id').first()
            if existing_client:
                client_updated_fields = []
                if existing_client.name != customer_name:
                    existing_client.name = customer_name
                    client_updated_fields.append('name')
                if existing_client.phone != customer_phone:
                    existing_client.phone = customer_phone
                    client_updated_fields.append('phone')
                if client_updated_fields:
                    existing_client.save(update_fields=client_updated_fields)
            else:
                Client.objects.create(phone=customer_phone, name=customer_name)
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
                            content_type = (getattr(photo_file, 'content_type', '') or '').strip()
                            if not content_type:
                                guessed_type, _ = mimetypes.guess_type(getattr(photo_file, 'name', ''))
                                content_type = guessed_type or 'application/octet-stream'

                            JobTicketPhoto.objects.create(
                                job_ticket=new_job,
                                image_name=(getattr(photo_file, 'name', '') or 'device-photo').strip()[:255],
                                image_content_type=content_type[:100],
                                image_data=photo_file.read(),
                            )
                
                JobTicketLog.objects.create(job_ticket=new_job, user=request.user, action='CREATED', details=f"Job ticket created for device: {device_data['device_type']}.")
                
                created_job_codes.append(new_job.job_code)
                created_jobs_payload.append({
                    'job_code': new_job.job_code,
                    'customer_name': new_job.customer_name,
                    'customer_phone': new_job.customer_phone,
                    'device_type': new_job.device_type,
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
        assign_form = AssignJobForm(request.POST)
        if assign_form.is_valid():
            job_code = assign_form.cleaned_data['job_code']
            technician = assign_form.cleaned_data['technician']
            job_to_assign = get_object_or_404(JobTicket, job_code=job_code)
        
            old_status = job_to_assign.get_status_display()
            job_to_assign.assigned_to = technician
            job_to_assign.status = 'Under Inspection'
            # mark as new assignment so the technician sees a notification/badge
            job_to_assign.is_new_assignment = True
            job_to_assign.save(update_fields=['assigned_to', 'status', 'updated_at', 'is_new_assignment'])

            details = f"Assigned to technician '{technician.user.username}' and status changed from '{old_status}' to 'Under Inspection'."
            JobTicketLog.objects.create(job_ticket=job_to_assign, user=request.user, action='ASSIGNED', details=details)
            
            # Send WebSocket update for real-time job assignment notification
            send_job_update_message(job_to_assign.job_code, job_to_assign.status)
            
            messages.success(request, f"Job {job_to_assign.job_code} assigned to {technician.user.username}.")
            return redirect('staff_dashboard')
    else:
        assign_form = AssignJobForm()
    
    # START: NEW VENDOR ASSIGNMENT LOGIC (Logic retained)
    if request.method == 'POST' and 'assign_vendor_form_submit' in request.POST:
        assign_vendor_form = AssignVendorForm(request.POST)
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
    search_results = []
    if query:
        search_results = list(JobTicket.objects.filter(
            Q(job_code__icontains=query) |
            Q(customer_name__icontains=query) |
            Q(customer_phone__icontains=query)
        ).select_related(
            'assigned_to__user'
        ).prefetch_related(
            'service_logs'
        ).order_by('-created_at'))
        
        try:
            # Calculate totals for search results
            calculate_job_totals(search_results)
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
    
    pending_jobs = job_tickets.filter(status='Pending')
    returned_jobs = job_tickets.filter(status='Returned')
    ready_for_pickup_jobs = job_tickets.filter(status='Ready for Pickup')
    completed_jobs = job_tickets.filter(status='Completed')
    awaiting_assignment = SpecializedService.objects.filter(status='Awaiting Assignment').select_related('job_ticket')

    # Fetch and group in-progress jobs by technician (Logic retained)
    in_progress_jobs_qs = job_tickets.filter(
        Q(status='Under Inspection') | Q(status='Repairing')
    ).select_related('assigned_to__user')

    grouped_in_progress_jobs = {}
    for job in in_progress_jobs_qs:
        key = job.assigned_to.user.username if job.assigned_to and job.assigned_to.user else "Unassigned"
        if key not in grouped_in_progress_jobs:
            grouped_in_progress_jobs[key] = []
        grouped_in_progress_jobs[key].append(job)

    # Create a form instance for each of these jobs (Logic retained)
    for service in awaiting_assignment:
        service.form = AssignVendorForm(initial={'specialized_service_id': service.id})

    sent_to_vendor = SpecializedService.objects.filter(status='Sent to Vendor').select_related('job_ticket', 'vendor')

    # assignment lists for staff to review (Logic retained)
    pending_assignments = Assignment.objects.filter(
        status='pending'
    ).select_related('job', 'technician__user').order_by('-created_at')

    rejected_assignments = Assignment.objects.filter(
        status='rejected'
    ).select_related('job', 'technician__user').order_by('-responded_at')

    accepted_assignments = Assignment.objects.filter(
        status='accepted'
    ).select_related('job', 'technician__user').order_by('-responded_at')

    # FINAL CONTEXT
    context = {
        'form': JobTicketForm(), # Use an empty form here for any generic field access in the template
        'assign_form': assign_form,
        'job_field_presets': get_job_field_presets(),
        'show_create_job_modal': request.session.pop('show_create_job_modal', False),
        'pending_jobs': pending_jobs,
        'grouped_in_progress_jobs': grouped_in_progress_jobs,
        'in_progress_jobs_count': in_progress_jobs_qs.count(),
        'returned_jobs': returned_jobs,
        'ready_for_pickup_jobs': ready_for_pickup_jobs,
        'completed_jobs': completed_jobs,
        'username': request.user.username,
        'query': query,
        'search_results': search_results,
        'search_count': len(search_results) if query else 0,
        'pending_assignments': pending_assignments,
        'rejected_assignments': rejected_assignments,
        'accepted_assignments': accepted_assignments,
        'awaiting_assignment_jobs': awaiting_assignment,
        'sent_to_vendor_jobs': sent_to_vendor,
        'pending_count': pending_jobs.count(),
        'ready_count': ready_for_pickup_jobs.count(),
        'completed_count': completed_jobs.count(),
        'returned_count': returned_jobs.count(),
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

                        product = Product.objects.select_for_update().filter(pk=product_id).first()
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
    old_status = job.get_status_display()
    job.status = 'Closed'
    job.save()

    details = f"Status changed from '{old_status}' to 'Closed'."
    JobTicketLog.objects.create(job_ticket=job, user=request.user, action='CLOSED', details=details)

    send_job_update_message(job.job_code, job.status)
    
    next_url = (request.GET.get('next') or request.META.get('HTTP_REFERER') or '').strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect('staff_dashboard')

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
    checklist_schema, checklist_title, checklist_notes = _build_checklist_schema_for_job(job)

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
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

    job_tickets = [job]
    calculate_job_totals(job_tickets)
    
    history_logs = job.logs.all().select_related('user')
    specialized_service = SpecializedService.objects.filter(job_ticket=job).first()
    technician_list = get_assignable_technician_queryset()
    
    if job.customer_group_id:
        related_jobs = JobTicket.objects.filter(
            customer_group_id=job.customer_group_id
        ).exclude(job_code=job.job_code).order_by('-created_at')
    else:
        related_jobs = JobTicket.objects.none()
    
    all_jobs = JobTicket.objects.all().select_related(
        'assigned_to__user', 'created_by'
    ).prefetch_related('service_logs').order_by('-created_at')
    calculate_job_totals(all_jobs)
    
    subtotal = job.total
    grand_total = subtotal - job.discount_amount
    
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
        'specialized_service': specialized_service,
        'related_jobs': related_jobs,
        'all_jobs': all_jobs,
        'technician_list': technician_list,
        'ReassignTechnicianForm': ReassignTechnicianForm(),
        'qr_url': qr_url,
        'checklist_schema': checklist_schema,
        'checklist_title': checklist_title,
        'checklist_notes': checklist_notes,
    }
    return render(request, 'job_tickets/staff_job_detail.html', context)

@login_required
@require_POST
def staff_delete_job_photo(request, job_code, photo_id):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    job = get_object_or_404(JobTicket, job_code=job_code)
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
    photo = get_object_or_404(JobTicketPhoto, id=photo_id, job_ticket=job)

    if photo.image_data:
        response = HttpResponse(photo.image_data, content_type=photo.image_content_type or 'application/octet-stream')
        response['Content-Disposition'] = f'inline; filename="{photo.image_name or f"{job.job_code}-photo-{photo.id}.jpg"}"'
        return response

    if photo.image:
        return redirect(photo.image.url)

    return HttpResponse(status=404)

@login_required
@require_POST
def unlock_vendor_details(request, job_code):
    """Unlock vendor details section with password verification."""
    if not request.user.is_staff or not user_has_staff_access(request.user, "staff_dashboard"):
        return JsonResponse({'ok': False, 'error': 'Unauthorized'}, status=403)
    
    password = request.POST.get('vendor_password', '').strip()
    
    # Check against user's own password or default
    from django.contrib.auth import authenticate
    user_auth = authenticate(username=request.user.username, password=password)
    
    if user_auth is not None or password.lower() == 'vendor123':
        request.session['vendor_details_unlocked'] = True
        request.session.modified = True
        request.session.set_expiry(3600)
        
        # Get specialized service data for AJAX response
        job = get_object_or_404(JobTicket, job_code=job_code)
        specialized_service = SpecializedService.objects.filter(job_ticket=job).first()
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'ok': True, 
                'message': 'Vendor details unlocked.',
                'vendor_name': str(specialized_service.vendor) if specialized_service and specialized_service.vendor else 'N/A',
                'status': specialized_service.get_status_display() if specialized_service else 'N/A',
                'vendor_cost': float(specialized_service.vendor_cost) if specialized_service and specialized_service.vendor_cost else 0,
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
    
    request.session['vendor_details_unlocked'] = False
    request.session.modified = True  # Ensure session is saved
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'message': 'Vendor details locked.'})
    
    messages.info(request, 'Vendor details locked.')
    return redirect('staff_job_detail', job_code=job_code)

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
    active_jobs_qs = JobTicket.objects.filter(
        status__in=active_statuses
    ).select_related('assigned_to__user').order_by('assigned_to__user__username', 'job_code')

    # 2. Group the jobs by Technician for clear reporting
    grouped_jobs = {}
    
    for job in active_jobs_qs:
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
    
    form = ReassignTechnicianForm(request.POST)
    # Note: We must validate the job_code field that is passed implicitly here, but trust the primary key validation
    
    if form.is_valid():
        new_technician = form.cleaned_data['new_technician']
        
        # Get old values for logging
        old_technician_name = job.assigned_to.user.username if job.assigned_to else "Unassigned"
        new_technician_name = new_technician.user.username if new_technician else "Unassigned"
        
        # Prevent assigning to the same person
        if job.assigned_to == new_technician:
            messages.warning(request, f"Job {job_code} is already assigned to {old_technician_name}.")
            return redirect('staff_job_detail', job_code=job_code)
            
        # Update the job and mark as new assignment for the technician
        job.assigned_to = new_technician
        job.is_new_assignment = True
        job.save(update_fields=['assigned_to', 'is_new_assignment', 'updated_at'])
        
        # Log the action
        details = f"Reassigned from '{old_technician_name}' to '{new_technician_name}' by staff."
        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='ASSIGNED', details=details)
        
        # Send WebSocket update (job assignment change may affect status display)
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
    
    # --- Context Setup ---
    context = {
        'jobs': jobs_queryset,
        'current_start_date': start_date_str,
        'current_end_date': end_date_str,
        'today_date_str': timezone.localdate().strftime('%Y-%m-%d'),
        # Assuming you have a helper for company start date:
        'company_start_date': get_company_start_date().strftime('%Y-%m-%d'), 
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
        # Enhanced filtering for returned jobs using job logs to track history
        # Get all jobs that have been marked as 'Returned' at some point
        returned_job_ids = JobTicketLog.objects.filter(
            action='STATUS',
            details__icontains="'Returned'"
        ).values_list('job_ticket_id', flat=True).distinct()
        
        if status_filter == 'closed':
            # Jobs that were returned and are now closed
            q_status_filter = Q(id__in=returned_job_ids, status='Closed')
            report_title = "Returned Jobs - Closed"
        elif status_filter == 'returned':
            # Jobs that are currently in returned status
            q_status_filter = Q(status='Returned')
            report_title = "Returned Jobs - Still Returned"
        else:
            # Show all jobs that have been returned at some point
            q_status_filter = Q(id__in=returned_job_ids)
            report_title = "Jobs Returned (Non-Repairable/Rework)"
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
    jobs_list = list(jobs_queryset) 
    
    # Reuse the helper function to calculate individual job totals (part_total, service_total, total)
    calculate_job_totals(jobs_list) 
    
    # Calculate the grand total and grand discount from the list
    total_amount_sum = sum(job.total for job in jobs_list)
    total_discount_sum = sum(job.discount_amount for job in jobs_list)
    
    # Grand Total (Subtotal - Discount)
    grand_total_amount = total_amount_sum - total_discount_sum if total_amount_sum > total_discount_sum else Decimal('0.00')
    total_jobs_count = jobs_queryset.count()
    
    # Calculate counts for returned jobs filtering
    returned_count = 0
    closed_returned_count = 0
    if status_code == 'Returned':
        # Get all jobs that have been marked as 'Returned' at some point
        returned_job_ids = JobTicketLog.objects.filter(
            action='STATUS',
            details__icontains="'Returned'"
        ).values_list('job_ticket_id', flat=True).distinct()
        
        # Count jobs currently in Returned status
        returned_count = JobTicket.objects.filter(status='Returned').count()
        # Count jobs that were returned and are now closed
        closed_returned_count = JobTicket.objects.filter(
            id__in=returned_job_ids, 
            status='Closed'
        ).count()
    
    # --- Context Setup ---
    context = {
        'jobs': jobs_queryset,
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
