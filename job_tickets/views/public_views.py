from .helpers import *  # noqa: F401,F403


def job_creation_success(request, job_code):
    job_ticket = get_object_or_404(JobTicket, job_code=job_code)
    context = {
        'job_ticket': job_ticket
    }
    return render(request, 'job_tickets/job_creation_success.html', context)

# job_tickets/views.py (def get_report_period(request))

def client_login(request):
    if request.method == 'POST':
        job_code = (request.POST.get('job_code') or '').strip()
        customer_phone, customer_phone_error = normalize_indian_phone(
            request.POST.get('phone_number'),
            field_label='Phone Number',
        )

        if not job_code:
            return render(request, 'job_tickets/client_login.html', {
                'error': 'Job Ticket Number is required.',
            })
        if customer_phone_error:
            return render(request, 'job_tickets/client_login.html', {
                'error': customer_phone_error,
            })
        
        # Rate limiting for client login
        client_ip = request.META.get('REMOTE_ADDR')
        cache_key = f'client_login_attempts_{client_ip}'
        attempts = cache.get(cache_key, 0)
        
        if attempts >= 10:
            return render(request, 'job_tickets/client_login.html', {
                'error': 'Too many failed attempts. Please try again in 30 minutes.',
                'locked': True
            })
        
        try:
            job_ticket = JobTicket.objects.get(
                job_code=job_code,
                customer_phone__in=phone_lookup_variants(customer_phone),
            )
            cache.delete(cache_key)  # Clear attempts on success
            return redirect('client_status', job_code=job_code)
        except JobTicket.DoesNotExist:
            cache.set(cache_key, attempts + 1, 1800)  # 30 minutes
            return render(request, 'job_tickets/client_login.html', {
                'error': 'Invalid Job Ticket Number or Phone Number.',
                'attempts_left': 9 - attempts
            })
    return render(request, 'job_tickets/client_login.html')

def client_status(request, job_code):
    job_ticket = get_object_or_404(JobTicket, job_code=job_code)
    job_tickets = [job_ticket]
    calculate_job_totals(job_tickets)
    checklist_schema, checklist_title, checklist_notes = _build_checklist_schema_for_job(job_ticket)
    
    bill_available = job_ticket.status in ['Ready for Pickup', 'Closed']
    can_give_feedback = job_ticket.status == 'Closed' and not job_ticket.feedback_rating
    
    if request.method == 'POST' and can_give_feedback:
        feedback_form = FeedbackForm(request.POST)
        if feedback_form.is_valid():
            job_ticket.feedback_rating = int(feedback_form.cleaned_data['rating'])
            job_ticket.feedback_comment = feedback_form.cleaned_data['comment']
            job_ticket.feedback_date = timezone.now()
            job_ticket.save()
            
            JobTicketLog.objects.create(
                job_ticket=job_ticket,
                user=None,
                action='FEEDBACK',
                details=f"Customer feedback: {job_ticket.feedback_rating}/10"
            )
            
            messages.success(request, 'Thank you for your feedback!')
            return redirect('client_status', job_code=job_code)
    else:
        feedback_form = FeedbackForm()
    
    context = {
        'job_ticket': job_ticket,
        'service_logs': job_ticket.service_logs.all(),
        'total_parts_cost': job_ticket.part_total,
        'total_service_charges': job_ticket.service_total,
        'grand_total': job_ticket.total - job_ticket.discount_amount,
        'bill_available': bill_available,
        'can_give_feedback': can_give_feedback,
        'feedback_form': feedback_form,
        'checklist_schema': checklist_schema,
        'checklist_title': checklist_title,
        'checklist_notes': checklist_notes,
    }
    return render(request, 'job_tickets/client_status.html', context)

@login_required
def client_phone_lookup(request):
    if not request.user.is_staff or not user_has_staff_access(request.user, "staff_dashboard"):
        return JsonResponse({'ok': False, 'message': 'Unauthorized'}, status=403)

    phone = request.GET.get('phone')
    snapshot = get_phone_service_snapshot(phone)
    return JsonResponse({'ok': True, **snapshot})

def client_bill_view(request, job_code):
    job_ticket = get_object_or_404(JobTicket, job_code=job_code)
    
    # Only allow bill access if job is ready for pickup or closed
    if job_ticket.status not in ['Ready for Pickup', 'Closed']:
        return render(request, 'job_tickets/client_login.html', {
            'error': 'Bill is not yet available. Please check back when your device is ready for pickup.'
        })
    
    job_tickets = [job_ticket]
    calculate_job_totals(job_tickets)
    
    subtotal = job_ticket.total
    discount = job_ticket.discount_amount
    grand_total = subtotal - discount
    
    # Clean service logs to remove vendor names
    service_logs = job_ticket.service_logs.all()
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
        'job': job_ticket,
        'service_logs': cleaned_service_logs,
        'subtotal': subtotal,
        'discount': discount,
        'grand_total': grand_total,
        'technician_id': job_ticket.assigned_to.unique_id if job_ticket.assigned_to else 'N/A',
        'created_by_id': job_ticket.created_by.id if job_ticket.created_by else 'N/A',
    }
    return render(request, 'job_tickets/job_billing_print.html', context)


@never_cache
@require_GET
def app_release_meta(request):
    return JsonResponse(
        {
            'ok': True,
            'web_version': getattr(settings, 'WEB_RELEASE_VERSION', 'dev'),
            'poll_interval_seconds': max(getattr(settings, 'WEB_RELEASE_POLL_INTERVAL_SECONDS', 300), 60),
            'generated_at': timezone.now().isoformat(),
        }
    )


def get_job_status_data(request):
    if not request.user.is_staff or not user_has_staff_access(request.user, "staff_dashboard"):
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    pending_jobs = list(JobTicket.objects.filter(status='Pending').values('job_code', 'customer_name', 'device_type'))
    in_progress_jobs = list(JobTicket.objects.filter(Q(status='Under Inspection') | Q(status='Repairing')).values('job_code', 'customer_name', 'device_type', 'status', 'assigned_to__user__username'))
    ready_for_pickup_jobs = list(JobTicket.objects.filter(status='Ready for Pickup').values('job_code', 'customer_name', 'device_type', 'status'))
    completed_jobs = list(JobTicket.objects.filter(status='Completed').values('job_code', 'customer_name', 'device_type', 'status'))

    data = {
        'pending_jobs': pending_jobs,
        'in_progress_jobs': in_progress_jobs,
        'ready_for_pickup_jobs': ready_for_pickup_jobs,
        'completed_jobs': completed_jobs,
    }
    return JsonResponse(data)

@login_required
def job_creation_receipt_print_view(request, job_code):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    job_ticket = get_object_or_404(JobTicket, job_code=job_code)

    if job_ticket.customer_group_id:
        grouped_jobs = list(
            JobTicket.objects.filter(customer_group_id=job_ticket.customer_group_id).order_by('created_at')
        )
    else:
        grouped_jobs = [job_ticket]

    estimated_amount = job_ticket.estimated_amount if job_ticket.estimated_amount is not None else 0
    estimated_delivery = job_ticket.estimated_delivery or (job_ticket.created_at + timedelta(days=3))
    autoprint = _parse_autoprint_flag(request, default=True)

    context = {
        'job_ticket': job_ticket,
        'grouped_jobs': grouped_jobs,
        'estimated_amount': estimated_amount,
        'estimated_delivery': estimated_delivery,
        'autoprint': autoprint,
    }
    return render(request, 'job_tickets/job_creation_receipt_print.html', context)

def job_creation_receipt_public_view(request, job_code):
    job_ticket = get_object_or_404(JobTicket, job_code=job_code)
    token = (request.GET.get('token') or '').strip()
    if not verify_receipt_access_token(job_ticket, token):
        return HttpResponseForbidden("Invalid or expired receipt link.")

    if job_ticket.customer_group_id:
        grouped_jobs = list(
            JobTicket.objects.filter(customer_group_id=job_ticket.customer_group_id).order_by('created_at')
        )
    else:
        grouped_jobs = [job_ticket]

    estimated_amount = job_ticket.estimated_amount if job_ticket.estimated_amount is not None else 0
    estimated_delivery = job_ticket.estimated_delivery or (job_ticket.created_at + timedelta(days=3))
    autoprint = _parse_autoprint_flag(request, default=False)

    context = {
        'job_ticket': job_ticket,
        'grouped_jobs': grouped_jobs,
        'estimated_amount': estimated_amount,
        'estimated_delivery': estimated_delivery,
        'autoprint': autoprint,
    }
    return render(request, 'job_tickets/job_creation_receipt_print.html', context)

def qr_access(request, job_code):
    """Direct access to job status via QR code without login"""
    job_ticket = get_object_or_404(JobTicket, job_code=job_code)
    return redirect('client_status', job_code=job_code)

def custom_404(request, exception):
    """Custom 404 error page"""
    return render(request, '404.html', status=404)

def custom_500(request):
    """Custom 500 error page"""
    return render(request, '500.html', status=500)
