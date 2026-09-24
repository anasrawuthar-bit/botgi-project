from decimal import Decimal
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .access_control import apply_staff_access
from .models import (
    CompanyUserMembership, CompanyWorkspace, Expense, JobTicket,
    ServiceLog, TechnicianProfile,
)
from .views.helpers import get_monthly_summary_context, report_date_bounds


def _make_workspace_and_user(username='exp_user', access_keys=None):
    user = User.objects.create_user(
        username=username,
        password='TestPassword123!',
        is_staff=True,
    )
    if access_keys is None:
        access_keys = {'staff_dashboard', 'expense_management'}
    apply_staff_access(user, access_keys)
    ws = CompanyWorkspace.objects.create(name=f'Workspace {username}', owner=user)
    CompanyUserMembership.objects.create(
        workspace=ws,
        user=user,
        role=CompanyUserMembership.ROLE_ADMIN,
    )
    return ws, user


class ExpenseSystemTests(TestCase):
    def setUp(self):
        self.workspace, self.user = _make_workspace_and_user('exp_staff', {'staff_dashboard', 'expense_management'})

        # Technician
        self.tech_user = User.objects.create_user(
            username='exp_tech',
            password='Password123!',
        )
        tech_group, _ = Group.objects.get_or_create(name='Technicians')
        self.tech_user.groups.add(tech_group)
        CompanyUserMembership.objects.create(
            user=self.tech_user,
            workspace=self.workspace,
            role=CompanyUserMembership.ROLE_TECHNICIAN,
        )
        self.tech_profile = TechnicianProfile.objects.create(
            user=self.tech_user,
            workspace=self.workspace,
            unique_id='EXP-T01',
        )

        # Job ticket
        self.job = JobTicket.objects.create(
            workspace=self.workspace,
            job_code='JOB-2026-EXP01',
            customer_name='Bob Williams',
            customer_phone='9876543210',
            device_type='Laptop',
            reported_issue='Display repair',
            status='In Progress',
            assigned_to=self.tech_profile,
        )

    def test_expense_sequence_number_and_isolation(self):
        ws2, user2 = _make_workspace_and_user('exp_user2')

        exp1 = Expense.objects.create(
            workspace=self.workspace,
            title='Office Electric Bill',
            amount=Decimal('1200.00'),
            category=Expense.CATEGORY_UTILITIES,
            payment_mode=Expense.PAYMENT_MODE_BANK,
            expense_date=timezone.localdate(),
            recorded_by=self.user,
        )
        self.assertTrue(exp1.expense_number.startswith('EXP-'))
        self.assertTrue(bool(exp1.expense_number))

        exp2 = Expense.objects.create(
            workspace=self.workspace,
            title='Display Courier',
            amount=Decimal('250.00'),
            category=Expense.CATEGORY_TRAVEL,
            payment_mode=Expense.PAYMENT_MODE_CASH,
            expense_date=timezone.localdate(),
            job_ticket=self.job,
            recorded_by=self.user,
        )
        self.assertTrue(exp2.expense_number.startswith('EXP-'))
        self.assertEqual(exp2.job_ticket, self.job)

        # Other workspace expense
        exp_other = Expense.objects.create(
            workspace=ws2,
            title='Other Shop Rent',
            amount=Decimal('8000.00'),
            category=Expense.CATEGORY_RENT,
            expense_date=timezone.localdate(),
        )
        self.assertEqual(Expense.objects.filter(workspace=self.workspace).count(), 2)
        self.assertEqual(Expense.objects.filter(workspace=ws2).count(), 1)

    def test_expense_access_control(self):
        # User without expense_management permission
        ws_no_access, user_no_access = _make_workspace_and_user('no_exp_user', {'staff_dashboard'})
        self.client.force_login(user_no_access)
        response = self.client.get(reverse('expense_dashboard'))
        # Should be redirected to unauthorized
        self.assertEqual(response.status_code, 302)

        # User with expense_management permission
        self.client.force_login(self.user)
        response = self.client.get(reverse('expense_dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_expense_create_overhead_and_job_linked(self):
        self.client.force_login(self.user)

        # 1. Create overhead expense
        res_overhead = self.client.post(reverse('expense_create'), {
            'title': 'Office Internet Bill',
            'amount': '899.00',
            'category': Expense.CATEGORY_SOFTWARE_INTERNET,
            'payment_mode': Expense.PAYMENT_MODE_UPI,
            'expense_date': str(timezone.localdate()),
            'job_ticket': '',
        })
        self.assertEqual(res_overhead.status_code, 302)
        overhead_exp = Expense.objects.filter(workspace=self.workspace, title='Office Internet Bill').first()
        self.assertIsNotNone(overhead_exp)
        self.assertEqual(overhead_exp.amount, Decimal('899.00'))
        self.assertIsNone(overhead_exp.job_ticket)

        # 2. Create job-linked direct expense
        res_job_exp = self.client.post(reverse('expense_create'), {
            'title': 'Urgent Courier Delivery',
            'amount': '150.00',
            'category': Expense.CATEGORY_TRAVEL,
            'payment_mode': Expense.PAYMENT_MODE_CASH,
            'expense_date': str(timezone.localdate()),
            'job_ticket': str(self.job.id),
        })
        self.assertEqual(res_job_exp.status_code, 302)
        job_exp = Expense.objects.filter(workspace=self.workspace, title='Urgent Courier Delivery').first()
        self.assertIsNotNone(job_exp)
        self.assertEqual(job_exp.job_ticket, self.job)

    def test_expense_delete(self):
        self.client.force_login(self.user)
        exp = Expense.objects.create(
            workspace=self.workspace,
            title='Delete Me',
            amount=Decimal('50.00'),
            category=Expense.CATEGORY_REFRESHMENTS,
            expense_date=timezone.localdate(),
        )
        del_resp = self.client.post(reverse('expense_delete', args=[exp.id]))
        self.assertEqual(del_resp.status_code, 302)
        self.assertFalse(Expense.objects.filter(id=exp.id).exists())

    def test_job_profitability_with_direct_expenses(self):
        # Service log: Parts = 1000, Labor = 1500 => Total Bill = 2500
        ServiceLog.objects.create(
            job_ticket=self.job,
            description='Screen Panel Replacement',
            part_cost=Decimal('1000.00'),
            service_charge=Decimal('1500.00'),
        )

        # Direct Job Expense: Travel = 150, Outsource = 350 => Total Direct Exp = 500
        Expense.objects.create(
            workspace=self.workspace,
            job_ticket=self.job,
            title='Screen Courier',
            amount=Decimal('150.00'),
            category=Expense.CATEGORY_TRAVEL,
            expense_date=timezone.localdate(),
        )
        Expense.objects.create(
            workspace=self.workspace,
            job_ticket=self.job,
            title='External Lab Diagnosis',
            amount=Decimal('350.00'),
            category=Expense.CATEGORY_JOB_PARTS_OUTSOURCE,
            expense_date=timezone.localdate(),
        )

        self.client.force_login(self.user)
        res = self.client.get(reverse('staff_job_detail', args=[self.job.job_code]))
        self.assertEqual(res.status_code, 200)

        # Verify job_expenses in context
        self.assertEqual(len(res.context['job_expenses']), 2)
        self.assertEqual(res.context['job_expenses_total'], Decimal('500.00'))
        # Net Profit: 2500 - 1000 (parts) - 500 (direct expenses) = 1000
        self.assertEqual(res.context['job_net_profit'], Decimal('1000.00'))

    def test_monthly_summary_report_overhead_and_net_profit(self):
        # Mark job as closed
        self.job.status = 'Closed'
        self.job.save()

        # Service log: Parts = 500, Labor = 1500 => Revenue = 2000, Parts Cost = 500 => Margin = 1500
        ServiceLog.objects.create(
            job_ticket=self.job,
            description='Keyboard Replacement',
            part_cost=Decimal('500.00'),
            service_charge=Decimal('1500.00'),
        )

        # Direct Job Expense = 200
        Expense.objects.create(
            workspace=self.workspace,
            job_ticket=self.job,
            title='Keyboard Delivery',
            amount=Decimal('200.00'),
            category=Expense.CATEGORY_TRAVEL,
            expense_date=timezone.localdate(),
        )

        # Shop Overhead Expense = 600
        Expense.objects.create(
            workspace=self.workspace,
            title='Shop Electricity',
            amount=Decimal('600.00'),
            category=Expense.CATEGORY_UTILITIES,
            expense_date=timezone.localdate(),
        )

        today = timezone.localdate()
        start, end = report_date_bounds(today, today)
        ctx = get_monthly_summary_context(
            start, end, str(today), str(today),
            workspace=self.workspace,
        )

        self.assertEqual(ctx.get('period_overhead_expenses'), Decimal('600.00'))
        # Revenue: 2000 (500 parts + 1500 labor), overall expense: 0, overall profit: 2000
        # True net profit after shop overhead (600) = 2000 - 600 = 1400
        self.assertEqual(ctx.get('period_net_profit'), Decimal('1400.00'))
