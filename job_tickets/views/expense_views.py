# job_tickets/views/expense_views.py
from decimal import Decimal
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import ExpenseForm
from ..models import Expense, JobTicket
from .helpers import _staff_access_required, scope_to_workspace


@login_required
def expense_dashboard(request):
    """Centralized dashboard for tracking direct job costs and general business overhead."""
    denied = _staff_access_required(request, "expense_management")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    qs = scope_to_workspace(Expense.objects.all(), workspace)

    # 1. Search Query
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) |
            Q(expense_number__icontains=q) |
            Q(notes__icontains=q) |
            Q(job_ticket__job_code__icontains=q) |
            Q(job_ticket__customer_name__icontains=q)
        )

    # 2. Type Filter (all, job, general)
    expense_type = (request.GET.get('type') or 'all').strip().lower()
    if expense_type == 'job':
        qs = qs.filter(job_ticket__isnull=False)
    elif expense_type == 'general':
        qs = qs.filter(job_ticket__isnull=True)

    # 3. Category Filter
    category = (request.GET.get('category') or '').strip()
    valid_categories = dict(Expense.CATEGORY_CHOICES)
    if category in valid_categories:
        qs = qs.filter(category=category)

    # 4. Payment Mode Filter
    payment_mode = (request.GET.get('payment_mode') or '').strip()
    valid_payment_modes = dict(Expense.PAYMENT_MODE_CHOICES)
    if payment_mode in valid_payment_modes:
        qs = qs.filter(payment_mode=payment_mode)

    # 5. Date Range Filter
    today = timezone.localdate()
    start_date_str = (request.GET.get('start_date') or '').strip()
    end_date_str = (request.GET.get('end_date') or '').strip()

    if start_date_str:
        try:
            start_date = timezone.datetime.strptime(start_date_str, '%Y-%m-%d').date()
            qs = qs.filter(expense_date__gte=start_date)
        except ValueError:
            start_date_str = ''

    if end_date_str:
        try:
            end_date = timezone.datetime.strptime(end_date_str, '%Y-%m-%d').date()
            qs = qs.filter(expense_date__lte=end_date)
        except ValueError:
            end_date_str = ''

    # Metrics on base workspace dataset for the current month
    month_start = today.replace(day=1)
    base_month_qs = scope_to_workspace(Expense.objects.all(), workspace).filter(
        expense_date__gte=month_start,
        expense_date__lte=today,
    )

    total_month_expenses = base_month_qs.aggregate(
        total=Coalesce(Sum('amount'), Decimal('0.00'))
    )['total']

    job_expenses_month = base_month_qs.filter(job_ticket__isnull=False).aggregate(
        total=Coalesce(Sum('amount'), Decimal('0.00'))
    )['total']

    general_expenses_month = base_month_qs.filter(job_ticket__isnull=True).aggregate(
        total=Coalesce(Sum('amount'), Decimal('0.00'))
    )['total']

    cash_expenses_month = base_month_qs.filter(
        payment_mode__in=[Expense.PAYMENT_MODE_CASH, Expense.PAYMENT_MODE_PETTY_CASH]
    ).aggregate(total=Coalesce(Sum('amount'), Decimal('0.00')))['total']

    digital_expenses_month = total_month_expenses - cash_expenses_month

    # Filtered Queryset Total
    filtered_total = qs.aggregate(
        total=Coalesce(Sum('amount'), Decimal('0.00'))
    )['total']

    # Pagination
    paginator = Paginator(qs.select_related('job_ticket', 'recorded_by'), 25)
    page_number = request.GET.get('page')
    expenses_page = paginator.get_page(page_number)

    # Empty form for modal
    create_form = ExpenseForm(workspace=workspace)

    context = {
        'expenses': expenses_page,
        'total_count': paginator.count,
        'filtered_total': filtered_total,
        'total_month_expenses': total_month_expenses,
        'job_expenses_month': job_expenses_month,
        'general_expenses_month': general_expenses_month,
        'cash_expenses_month': cash_expenses_month,
        'digital_expenses_month': digital_expenses_month,
        'category_choices': Expense.CATEGORY_CHOICES,
        'payment_mode_choices': Expense.PAYMENT_MODE_CHOICES,
        'selected_type': expense_type,
        'selected_category': category,
        'selected_payment_mode': payment_mode,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'search_query': q,
        'create_form': create_form,
    }
    return render(request, 'job_tickets/expense_dashboard.html', context)


@login_required
@require_POST
def expense_create(request):
    """Record a new direct job expense or shop overhead expense."""
    denied = _staff_access_required(request, "expense_management")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    form = ExpenseForm(request.POST, request.FILES, workspace=workspace)
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'expense_dashboard'

    if form.is_valid():
        expense = form.save(commit=False)
        expense.workspace = workspace
        expense.recorded_by = request.user
        expense.save()

        # If job linked, optionally log to JobTicketLog
        if expense.job_ticket:
            from ..models import JobTicketLog
            JobTicketLog.objects.create(
                job_ticket=expense.job_ticket,
                user=request.user,
                action='EXPENSE',
                details=f"Expense of ₹{expense.amount:.2f} ({expense.title}) recorded.",
            )

        messages.success(request, f"Expense '{expense.title}' (₹{expense.amount:.2f}) recorded successfully.")
        return redirect(next_url)

    for field, errs in form.errors.items():
        messages.error(request, f"{field}: {', '.join(errs)}")
    return redirect(next_url)


@login_required
@require_POST
def expense_delete(request, expense_id):
    """Delete an expense record."""
    denied = _staff_access_required(request, "expense_management")
    if denied:
        return denied

    workspace = getattr(request, 'current_workspace', None)
    qs = scope_to_workspace(Expense.objects.all(), workspace)
    expense = get_object_or_404(qs, id=expense_id)
    title = expense.title
    number = expense.expense_number or str(expense.id)
    expense.delete()

    messages.success(request, f"Expense {number} ('{title}') deleted successfully.")
    next_url = request.POST.get('next') or 'expense_dashboard'
    return redirect(next_url)
