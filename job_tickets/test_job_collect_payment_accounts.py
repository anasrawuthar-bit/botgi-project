from decimal import Decimal
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from job_tickets.models import (
    AccountTransaction,
    CompanyUserMembership,
    CompanyWorkspace,
    FinancialAccount,
    InventoryCreditPayment,
    JobTicket,
    ServiceLog,
)


class JobCollectPaymentAccountsTestCase(TestCase):
    def setUp(self):
        self.staff_group, _ = Group.objects.get_or_create(name='Staff')

        self.user = User.objects.create_user(
            username="staff_cashier",
            password="password123",
            is_staff=True,
        )
        self.user.groups.add(self.staff_group)

        self.workspace = CompanyWorkspace.objects.create(
            name="City Repair Center",
            slug="city-repair",
            status=CompanyWorkspace.STATUS_ACTIVE,
            owner=self.user,
        )
        CompanyUserMembership.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=CompanyUserMembership.ROLE_STAFF,
            is_active=True,
        )

        # Seed default accounts
        FinancialAccount.ensure_default_accounts(self.workspace)
        self.cash_acc = FinancialAccount.get_default_cash_account(self.workspace)
        self.bank_acc = FinancialAccount.get_default_bank_account(self.workspace)

        self.cash_acc.current_balance = Decimal('500.00')
        self.cash_acc.save(update_fields=['current_balance'])

        self.bank_acc.current_balance = Decimal('10000.00')
        self.bank_acc.save(update_fields=['current_balance'])

        # Create a job ticket with a service log costing 1200
        self.job = JobTicket.objects.create(
            job_code="BOT-20260930-999",
            customer_name="John Doe",
            customer_phone="9876543210",
            device_type="Laptop",
            device_brand="Lenovo",
            device_model="ThinkPad",
            status="Completed",
            workspace=self.workspace,
            created_by=self.user,
            amount_paid=Decimal('200.00'),
            payment_status='part_paid',
        )
        ServiceLog.objects.create(
            job_ticket=self.job,
            description="Motherboard rework",
            part_cost=Decimal('400.00'),
            service_charge=Decimal('800.00'),
        )

        self.client.login(username="staff_cashier", password="password123")

    def test_collect_payment_deposits_into_selected_cash_account(self):
        """Collecting balance payment via cash drawer deposits into cash account and logs ledger inflow."""
        # Total = 1200. Paid so far = 200. Balance = 1000.
        # Pay 400 now into Cash Drawer
        response = self.client.post(
            reverse('staff_job_collect_payment', args=[self.job.job_code]),
            {
                'amount': '400.00',
                'financial_account': self.cash_acc.id,
                'payment_reference': 'RCPT-101',
                'notes': 'Partial cash installment',
            },
        )
        self.assertEqual(response.status_code, 302)

        # Refresh job
        self.job.refresh_from_db()
        self.assertEqual(self.job.amount_paid, Decimal('600.00'))
        self.assertEqual(self.job.payment_status, 'part_paid')
        self.assertEqual(self.job.financial_account, self.cash_acc)
        self.assertEqual(self.job.payment_method, 'Cash')

        # Check cash account balance
        self.cash_acc.refresh_from_db()
        self.assertEqual(self.cash_acc.current_balance, Decimal('900.00'))  # 500 + 400

        # Check AccountTransaction
        txn = AccountTransaction.objects.filter(job_ticket=self.job, account=self.cash_acc).first()
        self.assertIsNotNone(txn)
        self.assertEqual(txn.amount, Decimal('400.00'))
        self.assertEqual(txn.transaction_type, AccountTransaction.TYPE_INFLOW)
        self.assertEqual(txn.balance_after, Decimal('900.00'))

        # Check InventoryCreditPayment
        inv_payment = InventoryCreditPayment.objects.filter(bill__job_ticket=self.job).first()
        self.assertIsNotNone(inv_payment)
        self.assertEqual(inv_payment.amount, Decimal('400.00'))
        self.assertEqual(inv_payment.financial_account, self.cash_acc)
        self.assertEqual(inv_payment.payment_method, 'cash')

    def test_collect_payment_deposits_into_bank_and_marks_paid_in_full(self):
        """Collecting remaining balance into bank marks job paid in full and deposits into bank ledger."""
        # Balance = 1000. Pay full 1000 into Bank.
        response = self.client.post(
            reverse('staff_job_collect_payment', args=[self.job.job_code]),
            {
                'amount': '1000.00',
                'financial_account': self.bank_acc.id,
                'payment_reference': 'UPI-REF-888',
                'notes': 'Final settlement via UPI',
            },
        )
        self.assertEqual(response.status_code, 302)

        self.job.refresh_from_db()
        self.assertEqual(self.job.amount_paid, Decimal('1200.00'))
        self.assertEqual(self.job.payment_status, 'paid')
        self.assertEqual(self.job.financial_account, self.bank_acc)

        self.bank_acc.refresh_from_db()
        self.assertEqual(self.bank_acc.current_balance, Decimal('11000.00'))  # 10000 + 1000

        txn = AccountTransaction.objects.filter(job_ticket=self.job, account=self.bank_acc).first()
        self.assertIsNotNone(txn)
        self.assertEqual(txn.amount, Decimal('1000.00'))
        self.assertEqual(txn.balance_after, Decimal('11000.00'))

    def test_job_detail_renders_deposit_to_account_without_method_select(self):
        """Job detail page renders Deposit To Account and does not have redundant payment_method select."""
        response = self.client.get(reverse('staff_job_detail', args=[self.job.job_code]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('financial_accounts', response.context)

        content = response.content.decode('utf-8')
        self.assertIn('Deposit To Account', content)
        self.assertIn(self.cash_acc.name, content)
        self.assertIn('id="cp_financial_account"', content)
        # Should not have payment_method selector in the collect payment modal
        self.assertNotIn('name="payment_method"', content)
