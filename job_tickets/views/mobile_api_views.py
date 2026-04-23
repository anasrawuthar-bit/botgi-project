from .helpers import *  # noqa: F401,F403


@csrf_exempt
@require_POST
def mobile_api_login(request):
    """JWT login endpoint for the Flutter mobile app."""
    payload = {}
    if 'application/json' in (request.content_type or ''):
        try:
            payload = json.loads((request.body or b'{}').decode('utf-8'))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)
    else:
        payload = request.POST

    username = (payload.get('username') or '').strip()
    password = (payload.get('password') or '').strip()
    if not username or not password:
        return JsonResponse(
            {'error': 'missing_credentials', 'message': 'Username and password are required.'},
            status=400,
        )

    user = authenticate(request, username=username, password=password)
    if not user or not user.is_active:
        return JsonResponse({'error': 'invalid_credentials', 'message': 'Invalid username or password.'}, status=401)

    access_token = issue_mobile_jwt(user)
    role = 'staff' if user.is_staff else 'technician'
    tech_id = ''
    if hasattr(user, 'technician_profile'):
        tech_id = user.technician_profile.unique_id or ''

    return JsonResponse(
        {
            'access_token': access_token,
            'token_type': 'Bearer',
            'expires_in': MOBILE_JWT_EXP_SECONDS,
            'user': {
                'id': user.id,
                'username': user.username,
                'is_staff': user.is_staff,
                'role': role,
                'technician_id': tech_id,
            },
        }
    )

def mobile_api_me(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    role = 'staff' if user.is_staff else 'technician'
    tech_id = ''
    if hasattr(user, 'technician_profile'):
        tech_id = user.technician_profile.unique_id or ''

    return JsonResponse(
        {
            'user': {
                'id': user.id,
                'username': user.username,
                'is_staff': user.is_staff,
                'role': role,
                'technician_id': tech_id,
            }
        }
    )

def mobile_api_jobs(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    if user.is_staff:
        if not user_has_staff_access(user, "staff_dashboard"):
            return JsonResponse({'error': 'forbidden', 'message': 'Staff dashboard access required.'}, status=403)
        jobs_qs = JobTicket.objects.all()
    elif hasattr(user, 'technician_profile'):
        jobs_qs = JobTicket.objects.filter(assigned_to=user.technician_profile)
    else:
        jobs_qs = JobTicket.objects.none()

    jobs = list(
        jobs_qs.select_related('assigned_to__user').prefetch_related('service_logs').order_by('-updated_at')[:30]
    )
    calculate_job_totals(jobs, exclude_vendor_charges=True)

    jobs_data = []
    for job in jobs:
        jobs_data.append(
            {
                'job_code': job.job_code,
                'customer_name': job.customer_name,
                'customer_phone': job.customer_phone,
                'device': f"{job.device_type} {job.device_brand or ''} {job.device_model or ''}".strip(),
                'status': job.status,
                'updated_at': timezone.localtime(job.updated_at).strftime('%Y-%m-%d %H:%M'),
                'total': str(job.total or Decimal('0.00')),
                'part_total': str(job.part_total or Decimal('0.00')),
                'service_total': str(job.service_total or Decimal('0.00')),
                'discount_amount': str(job.discount_amount or Decimal('0.00')),
                'assigned_to': (
                    job.assigned_to.user.username
                    if job.assigned_to and getattr(job.assigned_to, 'user', None)
                    else ''
                ),
            }
        )

    return JsonResponse({'count': len(jobs_data), 'jobs': jobs_data})

def mobile_api_job_detail(request, job_code):
    if request.method != 'GET':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    job = get_object_or_404(
        JobTicket.objects.select_related('assigned_to__user', 'created_by').prefetch_related(
            'service_logs__product_sale__product',
            'logs__user',
        ),
        job_code=job_code,
    )

    permissions = get_mobile_job_permissions(user, job)
    if not permissions['can_access']:
        return JsonResponse(
            {'error': 'forbidden', 'message': 'You are not allowed to access this job.'},
            status=403,
        )

    calculate_job_totals([job], exclude_vendor_charges=True)
    grand_total = (job.total or Decimal('0.00')) - (job.discount_amount or Decimal('0.00'))

    service_logs_data = []
    for service_log in job.service_logs.all().order_by('created_at'):
        product_sale = getattr(service_log, 'product_sale', None)
        service_logs_data.append(
            {
                'id': service_log.id,
                'description': service_log.description,
                'part_cost': str(service_log.part_cost or Decimal('0.00')),
                'service_charge': str(service_log.service_charge or Decimal('0.00')),
                'sales_invoice_number': service_log.sales_invoice_number or '',
                'created_at': timezone.localtime(service_log.created_at).strftime('%Y-%m-%d %H:%M'),
                'is_product_sale': bool(product_sale),
                'product_name': product_sale.product.name if product_sale and product_sale.product else '',
                'product_quantity': int(product_sale.quantity) if product_sale else 0,
                'product_unit_price': str(product_sale.unit_price or Decimal('0.00')) if product_sale else '0.00',
                'product_line_total': str(product_sale.line_total or Decimal('0.00')) if product_sale else '0.00',
            }
        )

    action_labels = {
        'CREATED': 'Job Created',
        'ASSIGNED': 'Technician Assigned',
        'STATUS': 'Status Updated',
        'NOTE': 'Note Updated',
        'SERVICE': 'Service Updated',
        'BILLING': 'Billing Updated',
        'CLOSED': 'Job Closed',
    }
    timeline_queryset = job.logs.select_related('user').order_by('-timestamp')[:60]
    timeline = []
    for entry in reversed(list(timeline_queryset)):
        timeline.append(
            {
                'action': entry.action,
                'label': action_labels.get(entry.action, entry.action.title()),
                'details': entry.details,
                'timestamp': timezone.localtime(entry.timestamp).strftime('%Y-%m-%d %H:%M'),
                'user': entry.user.username if entry.user else 'System',
            }
        )

    if not timeline:
        timeline.append(
            {
                'action': 'CREATED',
                'label': 'Job Created',
                'details': f"Job {job.job_code} created.",
                'timestamp': timezone.localtime(job.created_at).strftime('%Y-%m-%d %H:%M'),
                'user': job.created_by.username if job.created_by else 'System',
            }
        )

    checklist_schema, checklist_title, checklist_notes = _build_checklist_schema_for_job(job)

    return JsonResponse(
        {
            'job': {
                'job_code': job.job_code,
                'status': job.status,
                'status_display': job.get_status_display(),
                'customer_name': job.customer_name,
                'customer_phone': job.customer_phone,
                'device_type': job.device_type or '',
                'device_brand': job.device_brand or '',
                'device_model': job.device_model or '',
                'device_serial': job.device_serial or '',
                'reported_issue': job.reported_issue or '',
                'additional_items': job.additional_items or '',
                'technician_notes': job.technician_notes or '',
                'is_under_warranty': bool(job.is_under_warranty),
                'estimated_amount': str(job.estimated_amount or Decimal('0.00')) if job.estimated_amount else '',
                'estimated_delivery': job.estimated_delivery.strftime('%Y-%m-%d') if job.estimated_delivery else '',
                'vyapar_invoice_number': job.vyapar_invoice_number or '',
                'feedback_rating': int(job.feedback_rating) if job.feedback_rating else 0,
                'feedback_comment': job.feedback_comment or '',
                'feedback_date': timezone.localtime(job.feedback_date).strftime('%Y-%m-%d %H:%M')
                if job.feedback_date
                else '',
                'created_by': job.created_by.username if job.created_by else '',
                'assigned_to': (
                    job.assigned_to.user.username
                    if job.assigned_to and getattr(job.assigned_to, 'user', None)
                    else ''
                ),
                'updated_at': timezone.localtime(job.updated_at).strftime('%Y-%m-%d %H:%M'),
                'created_at': timezone.localtime(job.created_at).strftime('%Y-%m-%d %H:%M'),
                'technician_checklist': _get_job_checklist_answers(job),
            },
            'financials': {
                'part_total': str(job.part_total or Decimal('0.00')),
                'service_total': str(job.service_total or Decimal('0.00')),
                'subtotal': str(job.total or Decimal('0.00')),
                'discount_amount': str(job.discount_amount or Decimal('0.00')),
                'grand_total': str(grand_total),
            },
            'service_logs': service_logs_data,
            'timeline': timeline,
            'available_actions': get_mobile_job_available_actions(user, job),
            'permissions': {
                'can_edit_notes': mobile_can_edit_notes(user, job),
                'can_manage_service_logs': mobile_can_manage_service_lines(user, job),
            },
            'technician_checklist_schema': checklist_schema,
            'technician_checklist_title': checklist_title,
            'technician_checklist_notes': checklist_notes,
        }
    )

@csrf_exempt
@require_POST
def mobile_api_job_action(request, job_code):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    action_key = (payload.get('action') or '').strip()
    if not action_key:
        return JsonResponse({'error': 'missing_action', 'message': 'Action is required.'}, status=400)

    with transaction.atomic():
        job = get_object_or_404(
            JobTicket.objects.select_for_update().select_related('assigned_to__user'),
            job_code=job_code,
        )

        permissions = get_mobile_job_permissions(user, job)
        if not permissions['can_access']:
            return JsonResponse(
                {'error': 'forbidden', 'message': 'You are not allowed to update this job.'},
                status=403,
            )

        old_status_display = job.get_status_display()
        target_status = None
        log_action = 'STATUS'

        if action_key == 'start':
            if job.status not in ['Pending', 'Under Inspection']:
                return JsonResponse(
                    {'error': 'invalid_transition', 'message': 'Job cannot be marked started from current status.'},
                    status=400,
                )
            target_status = 'Repairing'
        elif action_key == 'complete':
            if job.status not in ['Under Inspection', 'Repairing', 'Specialized Service']:
                return JsonResponse(
                    {'error': 'invalid_transition', 'message': 'Job cannot be completed from current status.'},
                    status=400,
                )
            if not permissions['is_staff']:
                checklist_schema, _, _ = _build_checklist_schema_for_job(job)
                missing_required = _missing_required_checklist_labels(job, checklist_schema)
                if missing_required:
                    return JsonResponse(
                        {
                            'error': 'checklist_incomplete',
                            'message': _format_checklist_required_error(missing_required),
                            'missing_checklist_fields': missing_required,
                        },
                        status=400,
                    )
            target_status = 'Completed'
        elif action_key == 'ready_for_pickup':
            if not permissions['is_staff']:
                return JsonResponse({'error': 'forbidden', 'message': 'Only staff can perform this action.'}, status=403)
            if job.status != 'Completed':
                return JsonResponse(
                    {'error': 'invalid_transition', 'message': 'Only completed jobs can be marked ready for pickup.'},
                    status=400,
                )
            target_status = 'Ready for Pickup'
        elif action_key == 'close':
            if not permissions['is_staff']:
                return JsonResponse({'error': 'forbidden', 'message': 'Only staff can perform this action.'}, status=403)
            if job.status not in ['Completed', 'Ready for Pickup']:
                return JsonResponse(
                    {'error': 'invalid_transition', 'message': 'Job cannot be closed from current status.'},
                    status=400,
                )
            target_status = 'Closed'
            log_action = 'CLOSED'
        else:
            return JsonResponse({'error': 'invalid_action', 'message': 'Unsupported action.'}, status=400)

        job.status = target_status
        job.save(update_fields=['status', 'updated_at'])

        send_job_update_message(job.job_code, job.status)
        details = f"Status changed from '{old_status_display}' to '{job.get_status_display()}'."
        JobTicketLog.objects.create(job_ticket=job, user=user, action=log_action, details=details)

    return JsonResponse(
        {
            'ok': True,
            'message': f"Job {job.job_code} updated to {job.get_status_display()}.",
            'status': job.status,
            'status_display': job.get_status_display(),
            'available_actions': get_mobile_job_available_actions(user, job),
        }
    )

@csrf_exempt
@require_POST
def mobile_api_job_notes(request, job_code):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    new_notes = (payload.get('technician_notes') or '').strip()

    with transaction.atomic():
        job = get_object_or_404(JobTicket.objects.select_for_update(), job_code=job_code)

        permissions = get_mobile_job_permissions(user, job)
        if not permissions['can_access']:
            return JsonResponse(
                {'error': 'forbidden', 'message': 'You are not allowed to update this job.'},
                status=403,
            )

        old_notes = (job.technician_notes or '').strip()
        if old_notes == new_notes:
            return JsonResponse(
                {
                    'ok': True,
                    'message': 'No changes detected.',
                    'technician_notes': job.technician_notes or '',
                }
            )

        job.technician_notes = new_notes
        job.save(update_fields=['technician_notes', 'updated_at'])

        if new_notes:
            details = f'Technician notes updated: "{new_notes}"'
        else:
            details = 'Technician notes cleared.'
        JobTicketLog.objects.create(job_ticket=job, user=user, action='NOTE', details=details)

    send_job_update_message(job.job_code, job.status)
    return JsonResponse(
        {
            'ok': True,
            'message': 'Notes saved successfully.',
            'technician_notes': job.technician_notes or '',
        }
    )

@csrf_exempt
@require_POST
def mobile_api_service_line_create(request, job_code):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    description = (payload.get('description') or '').strip()
    if not description:
        return JsonResponse({'error': 'missing_description', 'message': 'Description is required.'}, status=400)

    part_cost, part_error = _mobile_parse_decimal(payload.get('part_cost'), 'part cost')
    if part_error:
        return JsonResponse({'error': 'invalid_part_cost', 'message': part_error}, status=400)

    service_charge, service_error = _mobile_parse_decimal(payload.get('service_charge'), 'service charge')
    if service_error:
        return JsonResponse({'error': 'invalid_service_charge', 'message': service_error}, status=400)

    sales_invoice_number = (payload.get('sales_invoice_number') or '').strip()

    with transaction.atomic():
        job = get_object_or_404(JobTicket.objects.select_for_update(), job_code=job_code)

        if not mobile_can_manage_service_lines(user, job):
            return JsonResponse(
                {'error': 'forbidden', 'message': 'You are not allowed to manage service lines for this job.'},
                status=403,
            )

        created_line = ServiceLog.objects.create(
            job_ticket=job,
            description=description,
            part_cost=part_cost,
            service_charge=service_charge,
            sales_invoice_number=sales_invoice_number or None,
        )
        details = f"Added service: '{created_line.description}' (Part: Rs {part_cost}, Service: Rs {service_charge})"
        JobTicketLog.objects.create(job_ticket=job, user=user, action='SERVICE', details=details)

    send_job_update_message(job.job_code, job.status)
    return JsonResponse(
        {
            'ok': True,
            'message': 'Service line added successfully.',
            'service_line_id': created_line.id,
        }
    )

@csrf_exempt
@require_POST
def mobile_api_service_line_update(request, job_code, line_id):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    with transaction.atomic():
        job = get_object_or_404(JobTicket.objects.select_for_update(), job_code=job_code)
        if not mobile_can_manage_service_lines(user, job):
            return JsonResponse(
                {'error': 'forbidden', 'message': 'You are not allowed to manage service lines for this job.'},
                status=403,
            )

        service_log = get_object_or_404(ServiceLog.objects.select_for_update(), id=line_id, job_ticket=job)

        if hasattr(service_log, 'product_sale'):
            return JsonResponse(
                {
                    'error': 'product_sale_locked',
                    'message': 'Product sale lines cannot be edited directly. Delete and re-add with the correct quantity.',
                },
                status=400,
            )

        new_description = (payload.get('description') or '').strip()
        if not new_description:
            return JsonResponse({'error': 'missing_description', 'message': 'Description is required.'}, status=400)

        new_part_cost, part_error = _mobile_parse_decimal(payload.get('part_cost'), 'part cost')
        if part_error:
            return JsonResponse({'error': 'invalid_part_cost', 'message': part_error}, status=400)

        new_service_charge, service_error = _mobile_parse_decimal(payload.get('service_charge'), 'service charge')
        if service_error:
            return JsonResponse({'error': 'invalid_service_charge', 'message': service_error}, status=400)

        new_invoice_number = (payload.get('sales_invoice_number') or '').strip()

        change_parts = []
        if service_log.description != new_description:
            change_parts.append(f"description: '{service_log.description}' -> '{new_description}'")
            service_log.description = new_description
        old_part_cost = service_log.part_cost or Decimal('0.00')
        if old_part_cost != new_part_cost:
            change_parts.append(f"part_cost: Rs {old_part_cost} -> Rs {new_part_cost}")
            service_log.part_cost = new_part_cost
        old_service_charge = service_log.service_charge or Decimal('0.00')
        if old_service_charge != new_service_charge:
            change_parts.append(f"service_charge: Rs {old_service_charge} -> Rs {new_service_charge}")
            service_log.service_charge = new_service_charge
        old_invoice_number = service_log.sales_invoice_number or ''
        if old_invoice_number != new_invoice_number:
            change_parts.append(f"sales_invoice_number: '{old_invoice_number}' -> '{new_invoice_number}'")
            service_log.sales_invoice_number = new_invoice_number or None

        if not change_parts:
            return JsonResponse({'ok': True, 'message': 'No changes detected.'})

        service_log.save(update_fields=['description', 'part_cost', 'service_charge', 'sales_invoice_number'])
        JobTicketLog.objects.create(job_ticket=job, user=user, action='SERVICE', details='; '.join(change_parts))

    send_job_update_message(job.job_code, job.status)
    return JsonResponse({'ok': True, 'message': 'Service line updated successfully.'})

@csrf_exempt
@require_http_methods(['POST', 'DELETE'])
def mobile_api_service_line_delete(request, job_code, line_id):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    with transaction.atomic():
        job = get_object_or_404(JobTicket.objects.select_for_update(), job_code=job_code)
        if not mobile_can_manage_service_lines(user, job):
            return JsonResponse(
                {'error': 'forbidden', 'message': 'You are not allowed to manage service lines for this job.'},
                status=403,
            )

        service_log = get_object_or_404(ServiceLog.objects.select_for_update(), id=line_id, job_ticket=job)
        line_description = service_log.description
        line_part_cost = service_log.part_cost or Decimal('0.00')
        line_service_charge = service_log.service_charge or Decimal('0.00')

        product_sale_entry = ProductSale.objects.filter(service_log=service_log).select_related('product').first()
        parsed_product_sale = parse_product_sale_log(service_log.description) if not product_sale_entry else None

        if product_sale_entry:
            product = Product.objects.select_for_update().filter(id=product_sale_entry.product_id).first()
            if product:
                product.stock_quantity += product_sale_entry.quantity
                product.save(update_fields=['stock_quantity', 'updated_at'])
                JobTicketLog.objects.create(
                    job_ticket=job,
                    user=user,
                    action='SERVICE',
                    details=(
                        f"Restocked {product.name} by {product_sale_entry.quantity} "
                        'after deleting product sale line.'
                    ),
                )
        elif parsed_product_sale:
            product = Product.objects.select_for_update().filter(id=parsed_product_sale['product_id']).first()
            if product:
                product.stock_quantity += parsed_product_sale['quantity']
                product.save(update_fields=['stock_quantity', 'updated_at'])
                JobTicketLog.objects.create(
                    job_ticket=job,
                    user=user,
                    action='SERVICE',
                    details=(
                        f"Restocked {product.name} by {parsed_product_sale['quantity']} "
                        'after deleting legacy product sale line.'
                    ),
                )

        service_log.delete()
        JobTicketLog.objects.create(
            job_ticket=job,
            user=user,
            action='SERVICE',
            details=(
                f"Deleted service: '{line_description}' "
                f"(Part: Rs {line_part_cost}, Service: Rs {line_service_charge})"
            ),
        )

    send_job_update_message(job.job_code, job.status)
    return JsonResponse({'ok': True, 'message': 'Service line deleted successfully.'})

@csrf_exempt
@require_http_methods(['GET', 'POST'])
def mobile_api_inventory_summary(request):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response
    if not user.is_staff or not user_has_staff_access(user, "inventory"):
        return JsonResponse({'error': 'forbidden', 'message': 'Inventory access required.'}, status=403)

    metrics = _build_inventory_dashboard_metrics()
    return JsonResponse(
        {
            'summary': {
                'party_count': int(metrics['party_count']),
                'product_count': int(metrics['product_count']),
                'low_stock_count': int(metrics['low_stock_count']),
                'reserved_alert_count': int(metrics['reserved_alert_count']),
                'inventory_value': _money_text(metrics['inventory_value']),
                'monthly_purchase_total': _money_text(metrics['monthly_purchase_total']),
                'monthly_purchase_return_total': _money_text(metrics['monthly_purchase_return_total']),
                'monthly_sales_total': _money_text(metrics['monthly_sales_total']),
                'monthly_sales_return_total': _money_text(metrics['monthly_sales_return_total']),
                'monthly_purchase_qty': int(metrics['monthly_purchase_qty']),
                'monthly_purchase_return_qty': int(metrics['monthly_purchase_return_qty']),
                'monthly_sales_qty': int(metrics['monthly_sales_qty']),
                'monthly_sales_return_qty': int(metrics['monthly_sales_return_qty']),
                'monthly_stock_in_qty': int(metrics['monthly_stock_in_qty']),
                'monthly_stock_out_qty': int(metrics['monthly_stock_out_qty']),
                'monthly_net_stock_qty': int(metrics['monthly_net_stock_qty']),
                'monthly_stock_in_amount': _money_text(metrics['monthly_stock_in_amount']),
                'monthly_stock_out_amount': _money_text(metrics['monthly_stock_out_amount']),
                'monthly_net_amount': _money_text(metrics['monthly_net_amount']),
            },
            'reserved_stock_products': [
                {
                    'id': product.id,
                    'name': product.name,
                    'category': product.category or '',
                    'stock_quantity': int(product.stock_quantity or 0),
                    'reserved_stock': int(product.reserved_stock or 0),
                }
                for product in metrics['reserved_stock_products']
            ],
            'recent_entries': [
                {
                    'id': entry.id,
                    'entry_number': entry.entry_number,
                    'entry_type': entry.entry_type,
                    'entry_type_label': entry.get_entry_type_display(),
                    'entry_date': entry.entry_date.isoformat() if entry.entry_date else '',
                    'invoice_number': entry.invoice_number or '',
                    'party_name': entry.party.name if entry.party_id else '',
                    'product_name': entry.product.name if entry.product_id else '',
                    'quantity': int(entry.quantity or 0),
                    'total_amount': _money_text(entry.total_amount),
                    'stock_before': int(entry.stock_before or 0),
                    'stock_after': int(entry.stock_after or 0),
                }
                for entry in metrics['recent_entries']
            ],
        }
    )

@csrf_exempt
@require_http_methods(['GET', 'POST'])
def mobile_api_inventory_parties(request):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response
    if not user.is_staff or not user_has_staff_access(user, "inventory"):
        return JsonResponse({'error': 'forbidden', 'message': 'Inventory access required.'}, status=403)

    if request.method == 'GET':
        query = (request.GET.get('q') or '').strip()
        start_date = None
        end_date = None
        start_date_raw = (request.GET.get('start_date') or '').strip()
        end_date_raw = (request.GET.get('end_date') or '').strip()

        if start_date_raw:
            try:
                start_date = datetime.strptime(start_date_raw, '%Y-%m-%d').date()
            except ValueError:
                return JsonResponse({'error': 'invalid_start_date', 'message': 'Start date must be YYYY-MM-DD.'}, status=400)
        if end_date_raw:
            try:
                end_date = datetime.strptime(end_date_raw, '%Y-%m-%d').date()
            except ValueError:
                return JsonResponse({'error': 'invalid_end_date', 'message': 'End date must be YYYY-MM-DD.'}, status=400)
        if start_date and end_date and start_date > end_date:
            start_date, end_date = end_date, start_date

        directory = _build_inventory_party_directory(
            query=query,
            start_date=start_date,
            end_date=end_date,
        )
        return JsonResponse(
            {
                'summary': {
                    'total_parties': int(directory['total_parties']),
                    'supplier_count': int(directory['supplier_count']),
                    'customer_count': int(directory['customer_count']),
                    'legacy_both_count': int(directory['legacy_both_count']),
                },
                'query': query,
                'start_date': start_date.isoformat() if start_date else '',
                'end_date': end_date.isoformat() if end_date else '',
                'parties': [_serialize_inventory_party_for_api(party) for party in directory['parties']],
                'suppliers': [_serialize_inventory_party_for_api(party) for party in directory['suppliers']],
                'customers': [_serialize_inventory_party_for_api(party) for party in directory['customers']],
                'can_edit': bool(user.is_staff and user_has_staff_access(user, "inventory")),
            }
        )

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    form_payload = _inventory_party_form_payload_from_api(payload)

    party_form = InventoryPartyForm(form_payload)
    if not party_form.is_valid():
        return JsonResponse(
            {'error': 'invalid_payload', 'message': 'Party data is invalid.', 'errors': _inventory_form_errors(party_form)},
            status=400,
        )

    party = party_form.save()
    return JsonResponse(
        {
            'ok': True,
            'message': f"Party '{party.name}' created successfully.",
            'party': _serialize_inventory_party_for_api(party),
        }
    )

@csrf_exempt
@require_http_methods(['POST', 'PATCH'])
def mobile_api_inventory_party_update(request, party_id):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response
    if not user.is_staff or not user_has_staff_access(user, "inventory"):
        return JsonResponse({'error': 'forbidden', 'message': 'Inventory access required.'}, status=403)

    party = get_object_or_404(InventoryParty, id=party_id)

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    form_payload = _inventory_party_form_payload_from_api(payload)
    party_form = InventoryPartyForm(form_payload, instance=party)
    if not party_form.is_valid():
        return JsonResponse(
            {'error': 'invalid_payload', 'message': 'Party data is invalid.', 'errors': _inventory_form_errors(party_form)},
            status=400,
        )

    updated_party = party_form.save()

    return JsonResponse(
        {
            'ok': True,
            'message': f"Party '{updated_party.name}' updated successfully.",
            'party': _serialize_inventory_party_for_api(updated_party),
        }
    )

@csrf_exempt
@require_GET
def mobile_api_inventory_register(request, entry_type):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response
    if not user.is_staff or not user_has_staff_access(user, "inventory"):
        return JsonResponse({'error': 'forbidden', 'message': 'Inventory access required.'}, status=403)
    if entry_type not in INVENTORY_ENTRY_CONFIG:
        return JsonResponse({'error': 'invalid_entry_type', 'message': 'Unsupported inventory register.'}, status=404)

    query = (request.GET.get('q') or '').strip()
    source_bill_id = None
    source_party_id = None
    source_bill_id_raw = (request.GET.get('source_bill_id') or '').strip()
    source_party_id_raw = (request.GET.get('source_party_id') or '').strip()
    if source_bill_id_raw.isdigit():
        source_bill_id = int(source_bill_id_raw)
    if source_party_id_raw.isdigit():
        source_party_id = int(source_party_id_raw)

    snapshot = _build_inventory_register_snapshot(
        entry_type,
        query=query,
        source_bill_id=source_bill_id,
        source_invoice=(request.GET.get('source_invoice') or '').strip(),
        source_party_id=source_party_id,
    )
    config = snapshot['config']

    return JsonResponse(
        {
            'config': {
                'entry_type': entry_type,
                'title': config['title'],
                'description': config['description'],
                'icon': config['icon'],
                'submit_label': config['submit_label'],
                'party_label': config['party_label'],
                'legacy_url': reverse(config['url_name']),
            },
            'summary': {
                'entry_count': int(snapshot['entry_count']),
                'total_quantity': int(snapshot['total_quantity'] or 0),
                'total_amount': _money_text(snapshot['total_amount']),
            },
            'query': query,
            'show_add_entry_button': bool(snapshot['show_add_entry_button']),
            'register_rows': [
                _serialize_inventory_register_bill_for_api(bill)
                for bill in snapshot['register_rows']
            ],
            'source_bill': snapshot['source_bill'] or None,
            'source_bill_lines': [
                {
                    'product_id': int(line['product_id']),
                    'product_name': line['product_name'],
                    'product_stock': int(line['product_stock']),
                    'max_quantity': int(line['max_quantity']),
                    'unit_price': _money_text(line['unit_price']),
                    'gst_rate': _money_text(line['gst_rate']),
                }
                for line in snapshot['source_bill_lines']
            ],
        }
    )

@csrf_exempt
@require_http_methods(['GET', 'POST'])
def mobile_api_products(request):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response
    if user.is_staff and not user_has_staff_access(user, "inventory"):
        return JsonResponse({'error': 'forbidden', 'message': 'Inventory access required.'}, status=403)

    if request.method == 'GET':
        query = (request.GET.get('q') or '').strip()
        catalog = _build_inventory_product_catalog(query=query)
        products_data = [
            _serialize_inventory_product_for_api(product)
            for product in catalog['products'][:200]
        ]

        return JsonResponse(
            {
                'count': len(products_data),
                'filtered_count': int(catalog['filtered_count']),
                'summary': {
                    'total_products': int(catalog['total_products']),
                    'out_of_stock_count': int(catalog['out_of_stock_count']),
                    'reserved_alert_count': int(catalog['reserved_alert_count']),
                },
                'products': products_data,
                'can_edit': bool(user.is_staff and user_has_staff_access(user, "inventory")),
            }
        )

    if not user.is_staff or not user_has_staff_access(user, "inventory"):
        return JsonResponse({'error': 'forbidden', 'message': 'Only staff can create products.'}, status=403)

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    sku = (payload.get('sku') or '').strip()
    if sku and Product.objects.filter(sku__iexact=sku).exists():
        return JsonResponse({'error': 'duplicate_sku', 'message': 'SKU already exists.'}, status=400)

    try:
        default_gst_rate = CompanyProfile.get_profile().gst_rate or Decimal('18.00')
    except Exception:
        default_gst_rate = Decimal('18.00')

    form_payload = {
        'name': (payload.get('name') or '').strip(),
        'category': (payload.get('category') or '').strip(),
        'brand': (payload.get('brand') or '').strip(),
        'item_type': (payload.get('item_type') or 'goods').strip() or 'goods',
        'hsn_sac_code': (payload.get('hsn_sac_code') or '').strip(),
        'uqc': (payload.get('uqc') or 'NOS').strip() or 'NOS',
        'tax_category': (payload.get('tax_category') or 'taxable').strip() or 'taxable',
        'gst_rate': str(payload.get('gst_rate') or default_gst_rate),
        'cess_rate': str(payload.get('cess_rate') or '0.00'),
        'is_tax_inclusive_default': 'on' if _mobile_parse_bool(payload.get('is_tax_inclusive_default')) else '',
        'cost_price': str(payload.get('cost_price') or '0.00'),
        'unit_price': str(payload.get('unit_price') or '0.00'),
        'stock_quantity': str(payload.get('stock_quantity') or '0'),
        'reserved_stock': str(payload.get('reserved_stock') or '0'),
        'description': (payload.get('description') or '').strip(),
        'purchase_price_tax_mode': (payload.get('purchase_price_tax_mode') or 'without_tax').strip() or 'without_tax',
        'sales_price_tax_mode': (payload.get('sales_price_tax_mode') or 'without_tax').strip() or 'without_tax',
    }
    product_form = ProductForm(form_payload)
    if not product_form.is_valid():
        return JsonResponse(
            {
                'error': 'invalid_product',
                'message': 'Please fix the product fields and try again.',
                'errors': _inventory_form_errors(product_form),
            },
            status=400,
        )

    product = product_form.save(commit=False)
    product.sku = sku or None
    product.is_active = _mobile_parse_bool(payload.get('is_active', True))
    effective_rate = effective_tax_rate(
        product_form.cleaned_data.get('gst_rate'),
        product_form.cleaned_data.get('tax_category'),
    )
    product.cost_price = _normalize_tax_mode_price(
        product_form.cleaned_data.get('cost_price'),
        product_form.cleaned_data.get('purchase_price_tax_mode'),
        effective_rate,
    )
    product.unit_price = _normalize_tax_mode_price(
        product_form.cleaned_data.get('unit_price'),
        product_form.cleaned_data.get('sales_price_tax_mode'),
        effective_rate,
    )
    product.save()
    return JsonResponse(
        {
            'ok': True,
            'message': f"Product '{product.name}' created successfully.",
            'product_id': product.id,
            'product': _serialize_inventory_product_for_api(product),
        }
    )

@csrf_exempt
@require_POST
def mobile_api_product_update(request, product_id):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response
    if not user.is_staff or not user_has_staff_access(user, "inventory"):
        return JsonResponse({'error': 'forbidden', 'message': 'Only staff can update products.'}, status=403)

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    product = get_object_or_404(Product, pk=product_id)
    sku = (payload.get('sku') or product.sku or '').strip()
    if sku and Product.objects.exclude(pk=product.pk).filter(sku__iexact=sku).exists():
        return JsonResponse({'error': 'duplicate_sku', 'message': 'SKU already exists.'}, status=400)

    form_payload = {
        'name': (payload.get('name') or product.name or '').strip(),
        'category': (payload.get('category') or product.category or '').strip(),
        'brand': (payload.get('brand') or product.brand or '').strip(),
        'item_type': (payload.get('item_type') or product.item_type or 'goods').strip() or 'goods',
        'hsn_sac_code': (payload.get('hsn_sac_code') or product.hsn_sac_code or '').strip(),
        'uqc': (payload.get('uqc') or product.uqc or 'NOS').strip() or 'NOS',
        'tax_category': (payload.get('tax_category') or product.tax_category or 'taxable').strip() or 'taxable',
        'gst_rate': str(payload.get('gst_rate') if 'gst_rate' in payload else product.gst_rate),
        'cess_rate': str(payload.get('cess_rate') if 'cess_rate' in payload else product.cess_rate),
        'is_tax_inclusive_default': (
            'on'
            if _mobile_parse_bool(
                payload.get('is_tax_inclusive_default', product.is_tax_inclusive_default)
            )
            else ''
        ),
        'cost_price': str(payload.get('cost_price') if 'cost_price' in payload else product.cost_price),
        'unit_price': str(payload.get('unit_price') if 'unit_price' in payload else product.unit_price),
        'stock_quantity': str(payload.get('stock_quantity') if 'stock_quantity' in payload else product.stock_quantity),
        'reserved_stock': str(payload.get('reserved_stock') if 'reserved_stock' in payload else product.reserved_stock),
        'description': (payload.get('description') or product.description or '').strip(),
        'purchase_price_tax_mode': (payload.get('purchase_price_tax_mode') or 'without_tax').strip() or 'without_tax',
        'sales_price_tax_mode': (payload.get('sales_price_tax_mode') or 'without_tax').strip() or 'without_tax',
    }
    original_values = {
        'name': product.name,
        'sku': product.sku,
        'category': product.category,
        'brand': product.brand,
        'item_type': product.item_type,
        'hsn_sac_code': product.hsn_sac_code,
        'uqc': product.uqc,
        'tax_category': product.tax_category,
        'gst_rate': product.gst_rate,
        'cess_rate': product.cess_rate,
        'is_tax_inclusive_default': bool(product.is_tax_inclusive_default),
        'cost_price': product.cost_price,
        'unit_price': product.unit_price,
        'stock_quantity': int(product.stock_quantity or 0),
        'reserved_stock': int(product.reserved_stock or 0),
        'description': product.description,
        'is_active': bool(product.is_active),
    }
    product_form = ProductForm(form_payload, instance=product)
    if not product_form.is_valid():
        return JsonResponse(
            {
                'error': 'invalid_product',
                'message': 'Please fix the product fields and try again.',
                'errors': _inventory_form_errors(product_form),
            },
            status=400,
        )

    updated_product = product_form.save(commit=False)
    effective_rate = effective_tax_rate(
        product_form.cleaned_data.get('gst_rate'),
        product_form.cleaned_data.get('tax_category'),
    )
    updated_values = {
        'name': updated_product.name,
        'sku': sku or None,
        'category': updated_product.category,
        'brand': updated_product.brand,
        'item_type': updated_product.item_type,
        'hsn_sac_code': updated_product.hsn_sac_code,
        'uqc': updated_product.uqc,
        'tax_category': updated_product.tax_category,
        'gst_rate': updated_product.gst_rate,
        'cess_rate': updated_product.cess_rate,
        'is_tax_inclusive_default': bool(updated_product.is_tax_inclusive_default),
        'cost_price': _normalize_tax_mode_price(
            product_form.cleaned_data.get('cost_price'),
            product_form.cleaned_data.get('purchase_price_tax_mode'),
            effective_rate,
        ),
        'unit_price': _normalize_tax_mode_price(
            product_form.cleaned_data.get('unit_price'),
            product_form.cleaned_data.get('sales_price_tax_mode'),
            effective_rate,
        ),
        'stock_quantity': int(updated_product.stock_quantity or 0),
        'reserved_stock': int(updated_product.reserved_stock or 0),
        'description': updated_product.description,
        'is_active': _mobile_parse_bool(payload.get('is_active', product.is_active)),
    }

    update_fields = []
    for field_name, new_value in updated_values.items():
        if original_values[field_name] != new_value:
            setattr(product, field_name, new_value)
            update_fields.append(field_name)

    if not update_fields:
        return JsonResponse({'ok': True, 'message': 'No changes detected.'})

    update_fields.append('updated_at')
    product.save(update_fields=update_fields)
    return JsonResponse(
        {
            'ok': True,
            'message': f"Product '{product.name}' updated successfully.",
            'product': _serialize_inventory_product_for_api(product),
        }
    )

@csrf_exempt
@require_http_methods(['GET', 'POST'])
def mobile_api_clients(request):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response
    if user.is_staff and not user_has_staff_access(user, "staff_dashboard"):
        return JsonResponse({'error': 'forbidden', 'message': 'Staff dashboard access required.'}, status=403)

    if request.method == 'GET':
        query = (request.GET.get('q') or '').strip()
        clients_qs = Client.objects.all().order_by('name')
        if query:
            clients_qs = clients_qs.filter(
                Q(name__icontains=query)
                | Q(phone__icontains=query)
                | Q(email__icontains=query)
                | Q(company_name__icontains=query)
            )

        clients_data = []
        for client in clients_qs[:200]:
            clients_data.append(
                {
                    'id': client.id,
                    'name': client.name,
                    'phone': client.phone,
                    'email': client.email or '',
                    'company_name': client.company_name or '',
                    'address': client.address or '',
                    'notes': client.notes or '',
                    'is_active': bool(client.is_active),
                    'updated_at': timezone.localtime(client.updated_at).strftime('%Y-%m-%d %H:%M'),
                }
            )

        return JsonResponse(
            {
                'count': len(clients_data),
                'clients': clients_data,
                'can_edit': bool(user.is_staff and user_has_staff_access(user, "staff_dashboard")),
            }
        )

    if not user.is_staff or not user_has_staff_access(user, "staff_dashboard"):
        return JsonResponse({'error': 'forbidden', 'message': 'Only staff can create clients.'}, status=403)

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    name = (payload.get('name') or '').strip()
    phone, phone_error = normalize_indian_phone(payload.get('phone'), field_label='Phone number')
    if not name:
        return JsonResponse({'error': 'missing_name', 'message': 'Client name is required.'}, status=400)
    if phone_error:
        return JsonResponse({'error': 'invalid_phone', 'message': phone_error}, status=400)
    if Client.objects.filter(phone__in=phone_lookup_variants(phone)).exists():
        return JsonResponse({'error': 'duplicate_phone', 'message': 'A client with this phone already exists.'}, status=400)

    client = Client.objects.create(
        name=name,
        phone=phone,
        email=(payload.get('email') or '').strip(),
        company_name=(payload.get('company_name') or '').strip(),
        address=(payload.get('address') or '').strip(),
        notes=(payload.get('notes') or '').strip(),
        is_active=_mobile_parse_bool(payload.get('is_active', True)),
    )
    return JsonResponse(
        {
            'ok': True,
            'message': f"Client '{client.name}' created successfully.",
            'client_id': client.id,
        }
    )

@csrf_exempt
@require_POST
def mobile_api_client_update(request, client_id):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response
    if not user.is_staff or not user_has_staff_access(user, "staff_dashboard"):
        return JsonResponse({'error': 'forbidden', 'message': 'Only staff can update clients.'}, status=403)

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    client = get_object_or_404(Client, pk=client_id)
    update_fields = []

    if 'name' in payload:
        name = (payload.get('name') or '').strip()
        if not name:
            return JsonResponse({'error': 'missing_name', 'message': 'Client name is required.'}, status=400)
        if client.name != name:
            client.name = name
            update_fields.append('name')

    if 'phone' in payload:
        phone, phone_error = normalize_indian_phone(payload.get('phone'), field_label='Phone number')
        if phone_error:
            return JsonResponse({'error': 'invalid_phone', 'message': phone_error}, status=400)
        if Client.objects.filter(phone__in=phone_lookup_variants(phone)).exclude(id=client.id).exists():
            return JsonResponse({'error': 'duplicate_phone', 'message': 'A client with this phone already exists.'}, status=400)
        if client.phone != phone:
            client.phone = phone
            update_fields.append('phone')

    for text_field in ('email', 'company_name', 'address', 'notes'):
        if text_field in payload:
            new_value = (payload.get(text_field) or '').strip()
            if getattr(client, text_field) != new_value:
                setattr(client, text_field, new_value)
                update_fields.append(text_field)

    if 'is_active' in payload:
        is_active = _mobile_parse_bool(payload.get('is_active'))
        if client.is_active != is_active:
            client.is_active = is_active
            update_fields.append('is_active')

    if not update_fields:
        return JsonResponse({'ok': True, 'message': 'No changes detected.'})

    update_fields.append('updated_at')
    client.save(update_fields=update_fields)
    return JsonResponse({'ok': True, 'message': f"Client '{client.name}' updated successfully."})

@require_http_methods(['GET'])
def mobile_api_pending_approvals(request):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response
    if user.is_staff and not user_has_staff_access(user, "staff_dashboard"):
        return JsonResponse({'error': 'forbidden', 'message': 'Staff dashboard access required.'}, status=403)

    is_technician = hasattr(user, 'technician_profile')
    can_act = bool(is_technician and not user.is_staff)

    if user.is_staff:
        approvals_qs = Assignment.objects.filter(status='pending').select_related('job', 'technician__user').order_by('-created_at')
    elif is_technician:
        approvals_qs = Assignment.objects.filter(
            status='pending',
            technician=user.technician_profile,
        ).select_related('job', 'technician__user').order_by('-created_at')
    else:
        approvals_qs = Assignment.objects.none()

    approvals_data = []
    for assignment in approvals_qs[:200]:
        job = assignment.job
        approvals_data.append(
            {
                'id': assignment.id,
                'job_code': job.job_code,
                'job_status': job.status,
                'customer_name': job.customer_name,
                'customer_phone': job.customer_phone,
                'device': f"{job.device_type} {job.device_brand or ''} {job.device_model or ''}".strip(),
                'technician': assignment.technician.user.username if assignment.technician and assignment.technician.user else '',
                'created_at': timezone.localtime(assignment.created_at).strftime('%Y-%m-%d %H:%M'),
            }
        )

    return JsonResponse({'count': len(approvals_data), 'can_act': can_act, 'approvals': approvals_data})

@csrf_exempt
@require_POST
def mobile_api_pending_approval_action(request, assignment_id):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response

    if not hasattr(user, 'technician_profile'):
        return JsonResponse({'error': 'forbidden', 'message': 'Only technicians can respond to approvals.'}, status=403)

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_payload', 'message': 'Invalid JSON body.'}, status=400)

    action_key = (payload.get('action') or '').strip().lower()
    note = (payload.get('note') or '').strip()
    if action_key not in {'accept', 'reject'}:
        return JsonResponse({'error': 'invalid_action', 'message': 'Action must be accept or reject.'}, status=400)

    with transaction.atomic():
        assignment = get_object_or_404(
            Assignment.objects.select_for_update().select_related('job', 'technician__user'),
            pk=assignment_id,
        )

        if assignment.technician_id != user.technician_profile.id:
            return JsonResponse({'error': 'forbidden', 'message': 'You are not assigned to this approval.'}, status=403)
        if assignment.status != 'pending':
            return JsonResponse({'error': 'already_responded', 'message': 'Approval already responded.'}, status=400)

        if action_key == 'accept':
            assignment.accept(note=note)
            details = f"Assignment accepted by technician '{user.username}'."
            message = 'Approval accepted.'
        else:
            assignment.reject(note=note)
            details = f"Assignment rejected by technician '{user.username}'."
            message = 'Approval rejected.'

        if note:
            details = f'{details} Note: {note}'

        JobTicketLog.objects.create(job_ticket=assignment.job, user=user, action='ASSIGNED', details=details)
        assignment.job.refresh_from_db(fields=['status', 'updated_at'])

    send_job_update_message(assignment.job.job_code, assignment.job.status)
    return JsonResponse(
        {
            'ok': True,
            'message': message,
            'job_code': assignment.job.job_code,
            'job_status': assignment.job.status,
            'job_status_display': assignment.job.get_status_display(),
        }
    )

@require_http_methods(['GET'])
def mobile_api_reports_summary(request):
    user, error_response = authenticate_mobile_request(request)
    if error_response:
        return error_response
    if not user.is_staff or not user_has_staff_access(user, "reports_financial"):
        return JsonResponse({'error': 'forbidden', 'message': 'Only staff can access reports.'}, status=403)

    period = resolve_monthly_summary_period(request)
    report_context = get_monthly_summary_context(
        period['start_of_period'],
        period['end_of_period'],
        period['start_date_str'],
        period['end_date_str'],
        preset=period['preset'],
        show_jobs='',
    )

    top_products = []
    for row in report_context['stock_products_breakdown'][:8]:
        top_products.append(
            {
                'product_id': row['product_id'],
                'name': row['name'],
                'sku': row['sku'],
                'units_sold': row['units_sold'],
                'sale_lines': row['sale_lines'],
                'average_unit_price': str(row['average_unit_price']),
                'revenue': str(row['revenue']),
                'cogs': str(row['cogs']),
                'profit': str(row['profit']),
            }
        )

    return JsonResponse(
        {
            'period': {
                'start_date': period['start_date_str'],
                'end_date': period['end_date_str'],
                'preset': period['preset'],
            },
            'summary': {
                'jobs_created': report_context['jobs_created_count'],
                'jobs_finished': report_context['jobs_finished_count'],
                'jobs_returned': report_context['jobs_returned_count'],
                'vendor_jobs': report_context['vendor_jobs_count'],
                'overall_revenue': str(report_context['overall_revenue']),
                'overall_expense': str(report_context['overall_expense']),
                'overall_profit': str(report_context['overall_profit']),
                'overall_margin': str(report_context['overall_margin']),
                'service_revenue': str(report_context['service_revenue']),
                'service_profit': str(report_context['service_profit']),
                'stock_sales_income': str(report_context['stock_sales_income']),
                'stock_sales_cogs': str(report_context['stock_sales_cogs']),
                'stock_sales_profit': str(report_context['stock_sales_profit']),
                'stock_sales_units': report_context['stock_sales_units'],
                'stock_products_count': report_context['stock_products_count'],
                'vendor_revenue': str(report_context['vendor_revenue']),
                'vendor_expense': str(report_context['vendor_expense']),
                'vendor_profit': str(report_context['vendor_profit']),
            },
            'top_products': top_products,
        }
    )
