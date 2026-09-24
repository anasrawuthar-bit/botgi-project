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


class FeedbackCenterTests(TestCase):
    def setUp(self):
        self.workspace, self.user = _make_workspace_and_user(
            'feedback_staff',
            {'staff_dashboard', 'feedback_analytics'}
        )
        self.tech_user = User.objects.create_user('fb_tech', password='Password123!')
        tech_group, _ = Group.objects.get_or_create(name='Technicians')
        self.tech_user.groups.add(tech_group)
        CompanyUserMembership.objects.create(
            user=self.tech_user,
            workspace=self.workspace,
            role=CompanyUserMembership.ROLE_TECHNICIAN,
        )
        self.tech = TechnicianProfile.objects.create(
            user=self.tech_user,
            workspace=self.workspace,
            unique_id='FBT-01',
        )
        self.closed_job = JobTicket.objects.create(
            workspace=self.workspace,
            job_code='JOB-FB-001',
            customer_name='Sarah Connor',
            customer_phone='9876543210',
            device_type='Laptop',
            reported_issue='Keyboard fix',
            status='Closed',
            closed_at=timezone.now(),
            feedback_followup_enabled=True,
            feedback_due_at=timezone.now() - timezone.timedelta(hours=1),
            assigned_to=self.tech,
        )

    def test_feedback_analytics_dashboard_renders(self):
        self.client.force_login(self.user)
        res = self.client.get(reverse('feedback_analytics'))
        self.assertEqual(res.status_code, 200)
        # Verify 0 rating does not show Critical
        self.assertContains(res, "No Ratings Yet")
        self.assertNotContains(res, "Critical Attention")

    def test_feedback_queue_status_filtering(self):
        self.client.force_login(self.user)
        # Filter: need_call
        res = self.client.get(reverse('feedback_analytics') + '?queue_status=need_call')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, self.closed_job.job_code)

        # Filter: no_answer (job is not in no_answer yet, so should be empty)
        res_na = self.client.get(reverse('feedback_analytics') + '?queue_status=no_answer')
        self.assertEqual(res_na.status_code, 200)
        self.assertNotContains(res_na, self.closed_job.job_code)

    def test_update_feedback_followup_no_answer(self):
        self.client.force_login(self.user)
        res = self.client.post(reverse('update_feedback_followup', args=[self.closed_job.job_code]), {
            'feedback_action': 'no_answer',
            'feedback_note': 'Customer phone was busy',
        })
        self.assertEqual(res.status_code, 302)
        self.closed_job.refresh_from_db()
        self.assertEqual(self.closed_job.feedback_followup_status, JobTicket.FEEDBACK_NO_ANSWER)
        self.assertEqual(self.closed_job.feedback_call_attempts, 1)
        self.assertIn('Attempt 1/3: No answer. Rescheduled for tomorrow.', self.closed_job.feedback_followup_note)
        # Due at is pushed into future (tomorrow)
        self.assertGreater(self.closed_job.feedback_due_at, timezone.now())

    def test_update_feedback_followup_no_answer_reaches_unreachable_on_third_attempt(self):
        self.client.force_login(self.user)
        self.closed_job.feedback_call_attempts = 2
        self.closed_job.save(update_fields=['feedback_call_attempts'])

        res = self.client.post(reverse('update_feedback_followup', args=[self.closed_job.job_code]), {
            'feedback_action': 'no_answer',
        })
        self.assertEqual(res.status_code, 302)
        self.closed_job.refresh_from_db()
        self.assertEqual(self.closed_job.feedback_call_attempts, 3)
        self.assertEqual(self.closed_job.feedback_followup_status, JobTicket.FEEDBACK_UNREACHABLE)
        self.assertIn('Attempt 3/3: No answer. Max attempts reached; marked unreachable.', self.closed_job.feedback_followup_note)

    def test_update_feedback_followup_call_later_default_preset(self):
        self.client.force_login(self.user)
        res = self.client.post(reverse('update_feedback_followup', args=[self.closed_job.job_code]), {
            'feedback_action': 'call_later',
            'callback_preset': '2_days',
            'feedback_note': 'Call after 5 PM',
        })
        self.assertEqual(res.status_code, 302)
        self.closed_job.refresh_from_db()
        self.assertEqual(self.closed_job.feedback_followup_status, JobTicket.FEEDBACK_CALL_LATER)
        # Approx 2 days from now
        diff = self.closed_job.feedback_due_at - timezone.now()
        self.assertGreaterEqual(diff.total_seconds(), 86400 * 1.8)
        self.assertIn('Callback requested', self.closed_job.feedback_followup_note)
        self.assertIn('Call after 5 PM', self.closed_job.feedback_followup_note)

    def test_update_feedback_followup_call_later_custom_date(self):
        self.client.force_login(self.user)
        res = self.client.post(reverse('update_feedback_followup', args=[self.closed_job.job_code]), {
            'feedback_action': 'call_later',
            'callback_preset': 'custom',
            'callback_date': '2026-10-20',
            'feedback_note': 'Customer traveling until Oct 20',
        })
        self.assertEqual(res.status_code, 302)
        self.closed_job.refresh_from_db()
        self.assertEqual(self.closed_job.feedback_followup_status, JobTicket.FEEDBACK_CALL_LATER)
        self.assertEqual(timezone.localtime(self.closed_job.feedback_due_at).strftime('%Y-%m-%d'), '2026-10-20')
        self.assertIn('Customer traveling until Oct 20', self.closed_job.feedback_followup_note)

    def test_update_feedback_followup_mark_received(self):
        self.client.force_login(self.user)
        res = self.client.post(reverse('update_feedback_followup', args=[self.closed_job.job_code]), {
            'feedback_action': 'mark_received',
            'feedback_rating': '9',
            'feedback_note': 'Very happy with fast keyboard replacement',
        })
        self.assertEqual(res.status_code, 302)
        self.closed_job.refresh_from_db()
        self.assertEqual(self.closed_job.feedback_followup_status, JobTicket.FEEDBACK_RECEIVED)
        self.assertEqual(self.closed_job.feedback_rating, 9)
        self.assertIn('Very happy', self.closed_job.feedback_comment)


