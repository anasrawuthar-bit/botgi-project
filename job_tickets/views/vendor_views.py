from .helpers import *  # noqa: F401,F403


@login_required
@require_POST
def request_specialized_service(request, job_code):
    if not request.user.groups.filter(name='Technicians').exists():
        return redirect('unauthorized')
        
    job = get_object_or_404(JobTicket, job_code=job_code)
    
    with transaction.atomic():
        # Check if a SpecializedService already exists
        if hasattr(job, 'specialized_service'):
            service = job.specialized_service
            
            # If status is 'Returned from Vendor', reset it to allow re-assignment
            if service.status == 'Returned from Vendor':
                old_status = job.get_status_display()
                job.status = 'Specialized Service'
                job.save()
                
                # Send WebSocket update
                send_job_update_message(job.job_code, job.status)
                
                # Reset the specialized service record to await new vendor assignment
                service.status = 'Awaiting Assignment'
                service.vendor = None
                service.vendor_cost = None
                service.client_charge = None
                service.sent_date = None
                service.returned_date = None
                service.save()
                
                details = f"Status changed from '{old_status}' to 'Specialized Service'. Re-requested specialized service. Service charges will be automatically handled when returned from vendor."
                JobTicketLog.objects.create(job_ticket=job, user=request.user, action='STATUS', details=details)
                
                messages.success(request, f"Job {job.job_code} has been re-sent to staff for specialized service assignment. Service charges will be automatically added when returned.")
                return redirect('technician_dashboard')
            else:
                # Already awaiting assignment or sent to vendor - prevent duplicate
                messages.warning(request, 'This job has already been marked for specialized service.')
                return redirect('job_detail_technician', job_code=job.job_code)

        # No existing SpecializedService - create a new one
        old_status = job.get_status_display()
        job.status = 'Specialized Service'
        job.save()

        # Create the tracking record for the specialized service
        SpecializedService.objects.create(job_ticket=job)

        # Log this important action
        details = f"Status changed from '{old_status}' to 'Specialized Service'. Awaiting vendor assignment by staff. Service charges will be automatically handled when returned from vendor."
        JobTicketLog.objects.create(job_ticket=job, user=request.user, action='STATUS', details=details)
        
        # Send WebSocket update
        send_job_update_message(job.job_code, job.status)

    messages.success(request, f"Job {job.job_code} has been sent to staff for specialized service assignment. Service charges will be automatically added when the job returns from the vendor.")
    return redirect('technician_dashboard')

@login_required
def mark_service_returned(request, service_id):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    service = get_object_or_404(SpecializedService, id=service_id)
    job = service.job_ticket

    # Handle POST request with cost data
    if request.method == 'POST':
        vendor_cost = request.POST.get('vendor_cost')
        client_charge = request.POST.get('client_charge')
        
        # Validate that costs are provided
        if not vendor_cost or not client_charge:
            messages.error(request, "Both Vendor Cost and Client Charge are required.")
            return redirect('vendor_dashboard')
        
        try:
            vendor_cost = Decimal(vendor_cost)
            client_charge = Decimal(client_charge)
        except (ValueError, TypeError):
            messages.error(request, "Invalid cost values. Please enter valid numbers.")
            return redirect('vendor_dashboard')
        
        with transaction.atomic():
            # Step 1: Update the SpecializedService record with costs
            service.status = 'Returned from Vendor'
            service.returned_date = timezone.now()
            service.vendor_cost = vendor_cost
            service.client_charge = client_charge
            service.save()

            # Step 2: Automatically create ServiceLog with the client charge
            # This eliminates the need for technicians to manually add service charges
            ServiceLog.objects.update_or_create(
                job_ticket=service.job_ticket,
                description=f"Specialized Service - {service.vendor.company_name}",
                defaults={
                    'part_cost': Decimal('0.00'),
                    'service_charge': client_charge
                }
            )

            # Step 3: Update the main JobTicket status to put it back in the technician's queue
            old_status = job.get_status_display()
            job.status = 'Repairing' 
            job.save()

            # Step 4: Log this important event
            details = f"Device returned from vendor '{service.vendor.company_name}'. Costs: Vendor ₹{vendor_cost}, Client ₹{client_charge}. Service charge automatically added. Status changed from '{old_status}' to 'Repairing'."
            JobTicketLog.objects.create(job_ticket=job, user=request.user, action='STATUS', details=details)
            
            # Send WebSocket update
            send_job_update_message(job.job_code, job.status)

        messages.success(request, f"Job {job.job_code} marked as returned with costs recorded and service charge automatically added. Job is now back in the technician's queue.")
        return redirect('vendor_dashboard')
    
    # GET request should not happen, redirect to vendor dashboard
    return redirect('vendor_dashboard')


INVENTORY_ENTRY_CONFIG = {
    'purchase': {
        'title': 'Purchase',
        'icon': 'fa-cart-arrow-down',
        'description': 'Add purchase entries to increase stock.',
        'url_name': 'inventory_purchase_dashboard',
        'submit_label': 'Record Purchase',
        'success_label': 'Purchase',
        'party_label': 'Parties',
        'party_label_singular': 'Party',
    },
    'purchase_return': {
        'title': 'Purchase Return',
        'icon': 'fa-rotate-left',
        'description': 'Review purchase return bills created from the purchase register.',
        'url_name': 'inventory_purchase_return_dashboard',
        'submit_label': 'Record Purchase Return',
        'success_label': 'Purchase return',
        'party_label': 'Parties',
        'party_label_singular': 'Party',
    },
    'sale': {
        'title': 'Sales',
        'icon': 'fa-cart-shopping',
        'description': 'Create sales entries that reduce stock.',
        'url_name': 'inventory_sales_dashboard',
        'submit_label': 'Record Sale',
        'success_label': 'Sale',
        'party_label': 'Parties',
        'party_label_singular': 'Party',
    },
    'sale_return': {
        'title': 'Sales Return',
        'icon': 'fa-rotate-right',
        'description': 'Review sales return bills created from the sales register.',
        'url_name': 'inventory_sales_return_dashboard',
        'submit_label': 'Record Sales Return',
        'success_label': 'Sales return',
        'party_label': 'Parties',
        'party_label_singular': 'Party',
    },
}

@login_required
def vendor_dashboard(request):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    
    if request.method == 'POST' and 'add_vendor_submit' in request.POST:
        vendor_form = VendorForm(request.POST)
        if vendor_form.is_valid():
            vendor_form.save()
            messages.success(request, f"Vendor '{vendor_form.cleaned_data['company_name']}' added successfully.")
            return redirect('vendor_dashboard')
        else:
            messages.error(request, "Error adding vendor. Please check inputs.")
            # Fall through to GET context to display the form with errors

    else:
        vendor_form = VendorForm() # For GET request or error display

    # Get all vendors and annotate them with the count of jobs currently with them
    vendors = Vendor.objects.annotate(
        active_jobs_count=Count('services', filter=Q(services__status='Sent to Vendor'))
    ).order_by('company_name')

    # Get all jobs that are currently with any vendor, ordered for easy grouping in the template
    active_services = SpecializedService.objects.filter(status='Sent to Vendor').select_related('job_ticket', 'vendor').order_by('vendor__company_name', 'sent_date')

    context = {
        'vendors': vendors,
        'vendor_form': vendor_form,
        'active_services_by_vendor': active_services,
    }
    return render(request, 'job_tickets/vendor_dashboard.html', context)

@login_required
@require_POST
def edit_vendor(request, vendor_id):
    """Edit an existing vendor."""
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    
    vendor = get_object_or_404(Vendor, id=vendor_id)
    
    # Update vendor fields
    vendor.company_name = request.POST.get('company_name', vendor.company_name)
    vendor.name = request.POST.get('name', vendor.name)
    vendor.phone = request.POST.get('phone', vendor.phone)
    vendor.email = request.POST.get('email', vendor.email)
    vendor.address = request.POST.get('address', vendor.address)
    vendor.specialties = request.POST.get('specialties', vendor.specialties)
    
    try:
        vendor.save()
        messages.success(request, f"Vendor '{vendor.company_name}' updated successfully.")
    except Exception as e:
        messages.error(request, f"Error updating vendor: {str(e)}")
    
    return redirect('vendor_dashboard')

@login_required
@require_POST
def delete_vendor(request, vendor_id):
    """Delete a vendor (only if no active services)."""
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied
    
    vendor = get_object_or_404(Vendor, id=vendor_id)
    
    # Check if vendor has any active services
    active_services = SpecializedService.objects.filter(vendor=vendor, status='Sent to Vendor').count()
    
    if active_services > 0:
        messages.error(request, f"Cannot delete vendor '{vendor.company_name}' because they have {active_services} active job(s). Please mark those jobs as returned first.")
        return redirect('vendor_dashboard')
    
    vendor_name = vendor.company_name
    vendor.delete()
    messages.success(request, f"Vendor '{vendor_name}' deleted successfully.")
    
    return redirect('vendor_dashboard')

@login_required
def vendor_report_detail(request, vendor_id):
    denied = _staff_access_required(request, "reports_vendor")
    if denied:
        return denied
    if not user_can_view_financial_reports(request.user):
        return redirect('unauthorized')

    vendor = get_object_or_404(Vendor, id=vendor_id)
    
    # Get date filters from URL parameters
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    # Start with all services for this vendor
    services = SpecializedService.objects.filter(vendor=vendor).select_related('job_ticket')
    
    # Apply date filtering using vendor concept
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            start_of_period = timezone.make_aware(datetime(start_date.year, start_date.month, start_date.day))
            end_of_period = timezone.make_aware(datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59))
            
            # Filter using vendor concept: only jobs returned in the period
            services = services.filter(
                returned_date__gte=start_of_period,
                returned_date__lte=end_of_period
            )
        except ValueError:
            # If date parsing fails, show all services
            pass
    
    services = services.order_by('-sent_date')

    # Calculate financial totals
    totals = services.aggregate(
        total_cost=Coalesce(Sum('vendor_cost', output_field=DecimalField()), Decimal('0')),
        total_charge=Coalesce(Sum('client_charge', output_field=DecimalField()), Decimal('0'))
    )
    
    profit = totals['total_charge'] - totals['total_cost']

    context = {
        'vendor': vendor,
        'services': services,
        'total_jobs': services.count(),
        'total_vendor_cost': totals['total_cost'],
        'total_client_charge': totals['total_charge'],
        'total_profit': profit,
        'start_date': start_date_str,
        'end_date': end_date_str,
    }
    return render(request, 'job_tickets/vendor_report_detail.html', context)
