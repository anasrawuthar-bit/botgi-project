from .helpers import *  # noqa: F401,F403


@login_required
def inventory_dashboard(request):
    denied = _staff_access_required(request, "inventory")
    if denied:
        return denied
    context = _build_inventory_dashboard_metrics()
    return render(request, 'job_tickets/inventory_dashboard.html', context)

@login_required
def inventory_party_dashboard(request):
    denied = _staff_access_required(request, "inventory")
    if denied:
        return denied

    query = (request.GET.get('q') or '').strip()
    start_date = None
    end_date = None
    start_date_raw = (request.GET.get('start_date') or '').strip()
    end_date_raw = (request.GET.get('end_date') or '').strip()
    active_tab = (request.GET.get('tab') or request.POST.get('tab') or 'all').strip().lower()
    if active_tab not in {'all', 'suppliers', 'customers'}:
        active_tab = 'all'

    if start_date_raw:
        try:
            start_date = datetime.strptime(start_date_raw, '%Y-%m-%d').date()
        except ValueError:
            start_date = None
    if end_date_raw:
        try:
            end_date = datetime.strptime(end_date_raw, '%Y-%m-%d').date()
        except ValueError:
            end_date = None
    if start_date and end_date and start_date > end_date:
        start_date, end_date = end_date, start_date

    posted_entry_type = (request.POST.get('inventory_entry_edit_submit') or '').strip()
    if request.method == 'POST' and posted_entry_type in INVENTORY_ENTRY_CONFIG:
        try:
            result = _process_inventory_grouped_bill_edit(request, entry_type=posted_entry_type)
            return _inventory_post_response(
                request,
                'inventory_party_dashboard',
                True,
                result['message'],
                extra_params={'tab': active_tab},
            )
        except ValueError as exc:
            return _inventory_post_response(
                request,
                'inventory_party_dashboard',
                False,
                str(exc),
                extra_params={'tab': active_tab},
            )

    if request.method == 'POST' and 'add_inventory_party_submit' in request.POST:
        party_form = InventoryPartyForm(request.POST)
        if party_form.is_valid():
            party = party_form.save()
            messages.success(request, f"Party '{party.name}' added successfully.")
            return redirect(f"{reverse('inventory_party_dashboard')}?tab={active_tab}")
        messages.error(request, 'Please fix the highlighted errors and try again.')
    else:
        party_form = InventoryPartyForm(
            initial={
                'opening_balance': Decimal('0.00'),
                'is_active': True,
            }
        )

    edit_party_modal_party_id = ''
    if request.method == 'POST' and 'edit_inventory_party_submit' in request.POST:
        edit_party_id = (request.POST.get('edit_party_id') or '').strip()
        party_to_edit = InventoryParty.objects.filter(pk=edit_party_id).first()
        if not party_to_edit:
            messages.error(request, 'Selected party was not found.')
            return redirect(f"{reverse('inventory_party_dashboard')}?tab={active_tab}")

        edit_party_form = InventoryPartyForm(request.POST, instance=party_to_edit, prefix='edit')
        if edit_party_form.is_valid():
            updated_party = edit_party_form.save()
            messages.success(request, f"Party '{updated_party.name}' updated successfully.")
            return redirect(f"{reverse('inventory_party_dashboard')}?tab={active_tab}")

        edit_party_modal_party_id = str(party_to_edit.id)
        messages.error(request, 'Please fix the highlighted party profile errors and try again.')
    else:
        edit_party_form = InventoryPartyForm(prefix='edit')

    directory_context = _build_inventory_party_directory(
        query=query,
        start_date=start_date,
        end_date=end_date,
    )
    parties = directory_context['parties']
    suppliers = directory_context['suppliers']
    customers = directory_context['customers']
    legacy_both_count = directory_context['legacy_both_count']

    try:
        default_gst_rate = CompanyProfile.get_profile().gst_rate
    except Exception:
        default_gst_rate = Decimal('18.00')

    shared_edit_options = InventoryParty.objects.filter(
        is_active=True,
    ).order_by('name')

    def serialize_party_options(option_qs):
        return [
            {
                'id': party.id,
                'label': f"{party.name} ({party.phone})" if party.phone else party.name,
            }
            for party in option_qs
        ]

    inventory_party_bill_payload = {}
    inventory_party_profile_payload = {}
    for party in parties:
        inventory_party_profile_payload[str(party.id)] = {
            'id': party.id,
            'name': party.name or '',
            'legal_name': party.legal_name or '',
            'contact_person': party.contact_person or '',
            'gst_registration_type': party.gst_registration_type or 'unregistered',
            'phone': party.phone or '',
            'gstin': party.gstin or '',
            'state_code': party.state_code or '',
            'default_place_of_supply_state': party.default_place_of_supply_state or '',
            'pan': party.pan or '',
            'email': party.email or '',
            'address': party.address or '',
            'shipping_address': party.shipping_address or '',
            'city': party.city or '',
            'state': party.state or '',
            'country': party.country or 'India',
            'pincode': party.pincode or '',
            'opening_balance': _money_text(party.opening_balance),
            'is_active': bool(party.is_active),
        }
        for bill in party.combined_history:
            payload_key = str(bill['bill_id'] or bill['bill_key'])
            if payload_key in inventory_party_bill_payload:
                continue

            lines = sorted(bill['lines'], key=lambda row: row.id)
            inventory_party_bill_payload[payload_key] = {
                'bill_id': bill['bill_id'] or '',
                'bill_key': bill['bill_key'],
                'entry_type': bill['entry_type'],
                'entry_type_label': bill['entry_type_label'],
                'bill_number': bill['bill_number'],
                'invoice_number': bill['invoice_number'],
                'entry_date': bill['entry_date'].isoformat() if bill['entry_date'] else '',
                'party_id': bill['party_id'],
                'party_name': bill['party'].name,
                'job_code': bill['job_code'] or '',
                'party_locked': bool(bill['job_ticket']),
                'bill_notes': bill['notes'] or '',
                'bill_discount_amount': _money_text(
                    sum((row.discount_amount or Decimal('0.00') for row in lines), Decimal('0.00'))
                ),
                'lines': [
                    {
                        'entry_id': row.id,
                        'entry_number': row.entry_number,
                        'product_id': row.product_id,
                        'quantity': int(row.quantity or 0),
                        'unit_price': _money_text(row.unit_price),
                        'gst_rate': _money_text(row.gst_rate),
                        'taxable_amount': _money_text(row.taxable_amount),
                        'gst_amount': _money_text(row.gst_amount),
                        'total_amount': _money_text(row.total_amount),
                    }
                    for row in lines
                ],
            }

    context = {
        'party_form': party_form,
        'edit_party_form': edit_party_form,
        'edit_party_modal_party_id': edit_party_modal_party_id,
        'parties': parties,
        'suppliers': suppliers,
        'customers': customers,
        'legacy_both_count': legacy_both_count,
        'query': query,
        'total_parties': directory_context['total_parties'],
        'supplier_count': directory_context['supplier_count'],
        'customer_count': directory_context['customer_count'],
        'active_tab': active_tab,
        'start_date': start_date.isoformat() if start_date else '',
        'end_date': end_date.isoformat() if end_date else '',
        'default_gst_rate': default_gst_rate,
        'line_products': Product.objects.filter(is_active=True).order_by('name'),
        'inventory_party_bill_payload': inventory_party_bill_payload,
        'inventory_party_profile_payload': inventory_party_profile_payload,
        'inventory_party_edit_options': {
            'purchase': serialize_party_options(shared_edit_options),
            'purchase_return': serialize_party_options(shared_edit_options),
            'sale': serialize_party_options(shared_edit_options),
            'sale_return': serialize_party_options(shared_edit_options),
        },
    }
    return render(request, 'job_tickets/inventory_party_dashboard.html', context)

@login_required
@require_POST
def inventory_quick_add_party(request):
    if not request.user.is_staff or not user_has_staff_access(request.user, "inventory"):
        return JsonResponse({'ok': False, 'error': 'Unauthorized'}, status=403)

    payload = request.POST.copy()
    payload['is_active'] = 'on'
    payload.setdefault('gst_registration_type', 'registered' if (payload.get('gstin') or '').strip() else 'unregistered')
    payload.setdefault('country', 'India')
    payload.setdefault('opening_balance', '0')

    party_form = InventoryPartyForm(payload)
    if not party_form.is_valid():
        return JsonResponse({'ok': False, 'errors': _inventory_form_errors(party_form)}, status=400)

    party = party_form.save(commit=False)
    party.party_type = 'both'
    party.is_active = True
    party.save()

    label = f"{party.name} ({party.phone})" if (party.phone or '').strip() else party.name
    return JsonResponse(
        {
            'ok': True,
            'party': {
                'id': party.id,
                'name': party.name,
                'phone': party.phone or '',
                'label': label,
            },
        }
    )

@login_required
@require_http_methods(["GET"])
def inventory_invoice_preview(request):
    if not request.user.is_staff or not user_has_staff_access(request.user, "inventory"):
        return JsonResponse({'ok': False, 'error': 'Unauthorized'}, status=403)

    entry_type = (request.GET.get('entry_type') or 'sale').strip().lower()
    if entry_type != 'sale':
        return JsonResponse({'ok': False, 'error': 'Unsupported entry type'}, status=400)

    raw_entry_date = (request.GET.get('entry_date') or '').strip()
    entry_date = timezone.localdate()
    if raw_entry_date:
        try:
            entry_date = datetime.strptime(raw_entry_date, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'ok': False, 'error': 'Invalid entry date'}, status=400)

    return JsonResponse(
        {
            'ok': True,
            'invoice_number': _generate_inventory_invoice_number(entry_type, entry_date),
        }
    )

@login_required
@require_POST
def inventory_quick_add_product(request):
    if not request.user.is_staff or not user_has_staff_access(request.user, "inventory"):
        return JsonResponse({'ok': False, 'error': 'Unauthorized'}, status=403)

    payload = request.POST.copy()
    payload.setdefault('stock_quantity', '0')
    payload.setdefault('reserved_stock', '0')
    payload.setdefault('description', '')
    payload.setdefault('item_type', 'goods')
    payload.setdefault('tax_category', 'taxable')
    payload.setdefault('uqc', 'NOS')
    payload.setdefault('cess_rate', '0.00')
    payload.setdefault('purchase_price_tax_mode', 'without_tax')
    payload.setdefault('sales_price_tax_mode', 'without_tax')
    payload.setdefault('is_tax_inclusive_default', '')

    try:
        payload.setdefault('gst_rate', str(CompanyProfile.get_profile().gst_rate or Decimal('18.00')))
    except Exception:
        payload.setdefault('gst_rate', '18.00')

    product_form = ProductForm(payload)
    if not product_form.is_valid():
        return JsonResponse({'ok': False, 'errors': _inventory_form_errors(product_form)}, status=400)

    product = product_form.save(commit=False)
    product.cost_price = _normalize_tax_mode_price(
        product_form.cleaned_data.get('cost_price'),
        product_form.cleaned_data.get('purchase_price_tax_mode'),
        effective_tax_rate(
            product_form.cleaned_data.get('gst_rate'),
            product_form.cleaned_data.get('tax_category'),
        ),
    )
    product.unit_price = _normalize_tax_mode_price(
        product_form.cleaned_data.get('unit_price'),
        product_form.cleaned_data.get('sales_price_tax_mode'),
        effective_tax_rate(
            product_form.cleaned_data.get('gst_rate'),
            product_form.cleaned_data.get('tax_category'),
        ),
    )
    product.stock_quantity = 0
    product.save()

    return JsonResponse(
        {
            'ok': True,
            'product': {
                'id': product.id,
                'name': product.name,
                'stock_quantity': int(product.stock_quantity or 0),
                'label': f"{product.name} (Stock: {int(product.stock_quantity or 0)})",
                'cost_price': format(product.cost_price, '.2f'),
                'unit_price': format(product.unit_price, '.2f'),
                'gst_rate': format(product.gst_rate, '.2f'),
                'tax_category': product.tax_category,
            },
        }
    )

@login_required
def inventory_purchase_dashboard(request):
    return _inventory_entry_dashboard(request, 'purchase')

@login_required
def inventory_purchase_return_dashboard(request):
    return _inventory_entry_dashboard(request, 'purchase_return')

@login_required
def inventory_sales_dashboard(request):
    return _inventory_entry_dashboard(request, 'sale')

@login_required
def inventory_sales_return_dashboard(request):
    return _inventory_entry_dashboard(request, 'sale_return')

@login_required
def inventory_sales_print_bill_view(request, bill_id):
    denied = _staff_access_required(request, "inventory")
    if denied:
        return denied

    sale_bill = (
        InventoryBill.objects.filter(pk=bill_id, entry_type='sale')
        .select_related('party', 'job_ticket')
        .first()
    )
    if not sale_bill:
        messages.error(request, 'Selected sales bill was not found.')
        return redirect('inventory_sales_dashboard')

    sale_entries = list(
        sale_bill.lines.select_related('bill', 'party', 'product', 'created_by', 'job_ticket')
        .order_by('id')
    )

    if not sale_entries:
        messages.error(request, f"Sales bill '{sale_bill.bill_number}' has no line items.")
        return redirect('inventory_sales_dashboard')

    context = _prepare_inventory_sale_bill_print_context(sale_bill, sale_entries)
    return render(request, 'job_tickets/inventory_sales_print.html', context)

@login_required
def inventory_sales_print_view(request, invoice_number):
    denied = _staff_access_required(request, "inventory")
    if denied:
        return denied

    normalized_invoice = (invoice_number or '').strip()
    sale_bill = (
        InventoryBill.objects.filter(
            entry_type='sale',
            invoice_number__iexact=normalized_invoice,
        )
        .select_related('party', 'job_ticket')
        .first()
    )
    if sale_bill:
        sale_entries = list(
            sale_bill.lines.select_related('bill', 'party', 'product', 'created_by', 'job_ticket')
            .order_by('id')
        )
        if sale_entries:
            context = _prepare_inventory_sale_bill_print_context(
                sale_bill,
                sale_entries,
                invoice_label=normalized_invoice,
            )
            return render(request, 'job_tickets/inventory_sales_print.html', context)

    messages.error(request, f"Sales invoice '{normalized_invoice}' was not found.")
    return redirect('inventory_sales_dashboard')

@login_required
def client_dashboard(request):
    denied = _staff_access_required(request, "staff_dashboard")
    if denied:
        return denied

    query = (request.GET.get('q') or '').strip()
    clients = Client.objects.all()

    if query:
        clients = clients.filter(
            Q(name__icontains=query) |
            Q(phone__icontains=query)
        )

    if request.method == 'POST' and 'add_client_submit' in request.POST:
        client_form = ClientForm(request.POST)
        if client_form.is_valid():
            client = client_form.save()
            messages.success(request, f"Client '{client.name}' added successfully.")
            return redirect('client_dashboard')
        messages.error(request, "Please fix the errors and try again.")
    else:
        client_form = ClientForm()

    phone_job_counts = {
        row['customer_phone']: row['total_jobs']
        for row in JobTicket.objects.values('customer_phone').annotate(total_jobs=Count('id'))
    }
    phone_device_rows = JobTicket.objects.values('customer_phone', 'device_type').annotate(total_jobs=Count('id')).order_by('customer_phone', '-total_jobs')
    device_map = {}
    for row in phone_device_rows:
        phone_key = row['customer_phone']
        device_label = (row['device_type'] or '').strip() or 'Unknown Device'
        device_map.setdefault(phone_key, []).append({
            'device_type': device_label,
            'count': row['total_jobs'],
        })

    client_rows = list(clients.order_by('-created_at'))
    client_phones = [client.phone for client in client_rows if client.phone]
    jobs_by_phone = {phone: [] for phone in client_phones}
    if client_phones:
        job_rows = (
            JobTicket.objects
            .filter(customer_phone__in=client_phones)
            .values('customer_phone', 'job_code', 'device_type', 'status', 'created_at')
            .order_by('-created_at')
        )
        for row in job_rows:
            phone_key = row['customer_phone']
            if phone_key in jobs_by_phone:
                jobs_by_phone[phone_key].append(row)
    for client in client_rows:
        client.total_jobs = phone_job_counts.get(client.phone, 0)
        client.device_breakdown = device_map.get(client.phone, [])
        client.jobs = jobs_by_phone.get(client.phone, [])

    context = {
        'clients': client_rows,
        'client_form': client_form,
        'query': query,
        'total_clients': Client.objects.count(),
    }
    return render(request, 'job_tickets/client_dashboard.html', context)

@login_required
def product_dashboard(request):
    denied = _staff_access_required(request, "inventory")
    if denied:
        return denied

    current_url_name = getattr(getattr(request, 'resolver_match', None), 'url_name', '')
    redirect_target = 'inventory_product_dashboard' if current_url_name == 'inventory_product_dashboard' else 'product_dashboard'

    query = (request.GET.get('q') or '').strip()
    products = Product.objects.all()

    if query:
        products = products.filter(
            Q(name__icontains=query) |
            Q(sku__icontains=query) |
            Q(category__icontains=query) |
            Q(brand__icontains=query) |
            Q(hsn_sac_code__icontains=query) |
            Q(uqc__icontains=query)
        )

    latest_purchase_entry = InventoryEntry.objects.filter(
        product=OuterRef('pk'),
        entry_type='purchase',
    ).order_by('-entry_date', '-id')
    products = products.annotate(
        latest_purchase_party=Subquery(latest_purchase_entry.values('party__name')[:1]),
        latest_purchase_invoice=Subquery(latest_purchase_entry.values('invoice_number')[:1]),
        latest_purchase_date=Subquery(latest_purchase_entry.values('entry_date')[:1]),
    )
    product_rows = list(products.order_by('name'))
    product_ids = [product.id for product in product_rows]
    opening_stock_map = {
        product.id: int(product.stock_quantity or 0)
        for product in product_rows
    }
    history_map = {
        product_id: {
            'purchase': [],
            'sale': [],
            'sale_return': [],
            'purchase_return': [],
            'combined': [],
        }
        for product_id in product_ids
    }
    max_history_per_type = 10
    max_combined_history = 20

    if product_ids:
        history_entries = (
            InventoryEntry.objects.filter(product_id__in=product_ids)
            .select_related('party')
            .order_by('-entry_date', '-id')
        )
        for entry in history_entries:
            product_history = history_map.get(entry.product_id, {})
            if entry.product_id in opening_stock_map:
                opening_stock_map[entry.product_id] -= entry.stock_effect
            bucket = product_history.get(entry.entry_type)
            if bucket is None:
                continue
            if len(bucket) < max_history_per_type:
                bucket.append(entry)
            combined = product_history.get('combined')
            if combined is not None and len(combined) < max_combined_history:
                combined.append(entry)

    def build_opening_history_entry(product, opening_quantity):
        if opening_quantity <= 0:
            return None

        opening_date = timezone.localtime(product.created_at).date() if product.created_at else None
        total_amount = (Decimal(opening_quantity) * (product.cost_price or Decimal('0.00'))).quantize(Decimal('0.01'))
        return SimpleNamespace(
            entry_type='opening_stock',
            entry_date=opening_date,
            invoice_number='Opening Stock',
            party=SimpleNamespace(name='-'),
            quantity=opening_quantity,
            total_amount=total_amount,
            created_at=product.created_at,
            sort_id=-1,
        )

    def history_sort_key(item):
        entry_date = getattr(item, 'entry_date', None) or date.min
        created_at = getattr(item, 'created_at', None)
        created_at_sort = created_at.timestamp() if created_at else 0
        sort_id = getattr(item, 'id', None)
        if sort_id is None:
            sort_id = getattr(item, 'sort_id', 0)
        return (entry_date, created_at_sort, sort_id)

    for product in product_rows:
        history = history_map.get(product.id, {})
        product.purchase_history = history.get('purchase', [])
        product.sale_history = history.get('sale', [])
        product.sale_return_history = history.get('sale_return', [])
        product.purchase_return_history = history.get('purchase_return', [])
        combined_history = list(history.get('combined', []))
        opening_entry = build_opening_history_entry(product, opening_stock_map.get(product.id, 0))
        if opening_entry:
            combined_history.append(opening_entry)
        combined_history.sort(key=history_sort_key, reverse=True)
        if len(combined_history) > max_combined_history:
            if opening_entry and opening_entry in combined_history[max_combined_history:]:
                combined_history = combined_history[:max_combined_history - 1] + [opening_entry]
            else:
                combined_history = combined_history[:max_combined_history]
        product.combined_history = combined_history
        product.has_transaction_history = bool(product.combined_history)

    if request.method == 'POST':
        if 'update_reserved_stock_submit' in request.POST:
            is_async_request = request.headers.get('X-Botgi-Async') == '1'
            reload_url = request.get_full_path()
            product = Product.objects.filter(pk=request.POST.get('product_id')).first()
            if not product:
                if is_async_request:
                    return JsonResponse({'ok': False, 'message': 'Selected product was not found.'}, status=404)
                messages.error(request, 'Selected product was not found.')
                return redirect(redirect_target)

            try:
                reserved_stock = int((request.POST.get('reserved_stock') or '0').strip() or '0')
            except (TypeError, ValueError):
                if is_async_request:
                    return JsonResponse({'ok': False, 'message': 'Reserved stock must be a whole number.'}, status=400)
                messages.error(request, 'Reserved stock must be a whole number.')
                return redirect(redirect_target)

            if reserved_stock < 0:
                if is_async_request:
                    return JsonResponse({'ok': False, 'message': 'Reserved stock cannot be negative.'}, status=400)
                messages.error(request, 'Reserved stock cannot be negative.')
                return redirect(redirect_target)

            if product.reserved_stock != reserved_stock:
                product.reserved_stock = reserved_stock
                product.save(update_fields=['reserved_stock', 'updated_at'])
                if is_async_request:
                    return JsonResponse(
                        {
                            'ok': True,
                            'message': f"Reserved stock updated for '{product.name}'.",
                            'reload_url': reload_url,
                        }
                    )
                messages.success(request, f"Reserved stock updated for '{product.name}'.")
            else:
                if is_async_request:
                    return JsonResponse(
                        {
                            'ok': True,
                            'message': f"No reserved stock change for '{product.name}'.",
                            'reload_url': reload_url,
                        }
                    )
                messages.info(request, f"No reserved stock change for '{product.name}'.")
            return redirect(redirect_target)

        if 'add_product_submit' in request.POST:
            product_form = ProductForm(request.POST)
            if product_form.is_valid():
                def _normalize_tax_mode_price(raw_price, price_mode):
                    price = raw_price or Decimal('0.00')
                    gst_rate = effective_tax_rate(
                        product_form.cleaned_data.get('gst_rate'),
                        product_form.cleaned_data.get('tax_category'),
                    )
                    if price_mode == 'with_tax' and gst_rate > 0:
                        divisor = Decimal('100.00') + gst_rate
                        if divisor > 0:
                            price = (price * Decimal('100.00')) / divisor
                    return price.quantize(Decimal('0.01'))

                product = product_form.save(commit=False)
                product.cost_price = _normalize_tax_mode_price(
                    product_form.cleaned_data.get('cost_price'),
                    product_form.cleaned_data.get('purchase_price_tax_mode'),
                )
                product.unit_price = _normalize_tax_mode_price(
                    product_form.cleaned_data.get('unit_price'),
                    product_form.cleaned_data.get('sales_price_tax_mode'),
                )
                product.save()
                messages.success(request, f"Product '{product.name}' added successfully.")
                return redirect(redirect_target)
            messages.error(request, "Please fix the errors and try again.")
        else:
            product_form = ProductForm()
    else:
        product_form = ProductForm()

    out_of_stock_count = Product.objects.filter(stock_quantity__lte=0).count()
    reserved_alert_count = Product.objects.filter(
        reserved_stock__gt=0,
        stock_quantity__lte=F('reserved_stock'),
    ).count()
    context = {
        'products': product_rows,
        'product_form': product_form,
        'query': query,
        'total_products': Product.objects.count(),
        'reserved_alert_count': reserved_alert_count,
        'out_of_stock_count': out_of_stock_count,
        'from_inventory': current_url_name == 'inventory_product_dashboard',
    }
    return render(request, 'job_tickets/product_dashboard.html', context)
