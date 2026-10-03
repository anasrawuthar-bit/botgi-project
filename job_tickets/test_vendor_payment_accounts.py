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
    JobTicket,
    SpecializedService,
    Vendor,
    VendorPayment,
)


class VendorPaymentAccountsTestCase(TestCase):
    def setUp(self):
        # Create Staff group
        self.staff_group, _ = Group.objects.get_or_create(name='Staff')

        self.user = User.objects.create_user(
            username="staff_member",
            password="password123",
            is_staff=True,
        )
        self.user.groups.add(self.staff_group)

        self.workspace = CompanyWorkspace.objects.create(
            name="Test Service Hub",
            slug="test-hub",
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

        # Give accounts some initial balance
        self.cash_acc.current_balance = Decimal('1000.00')
        self.cash_acc.save(update_fields=['current_balance'])

        self.bank_acc.current_balance = Decimal('5000.00')
        self.bank_acc.save(update_fields=['current_balance'])

        # Create a vendor
        self.vendor = Vendor.objects.create(
            workspace=self.workspace,
            company_name="FoxPro Microchips",
            name="Fox Pro",
            phone="9876543210",
        )

        # Create a job ticket and returned specialized service
        self.job = JobTicket.objects.create(
            job_code="BOT-20260930-001",
            customer_name="Test Customer",
            customer_phone="9998887776",
            device_type="Laptop",
            device_brand="Dell",
            device_model="XPS 15",
            status="Specialized Service",
            workspace=self.workspace,
            created_by=self.user,
        )
        self.service = SpecializedService.objects.create(
            job_ticket=self.job,
            vendor=self.vendor,
            status="Returned from Vendor",
            vendor_cost=Decimal('500.00'),
            vendor_discount_amount=Decimal('50.00'),
            vendor_paid_amount=Decimal('0.00'),
            vendor_balance_amount=Decimal('450.00'),
            client_charge=Decimal('800.00'),
            returned_date=timezone.now(),
        )

        self.client.login(username="staff_member", password="password123")

    def test_record_vendor_payment_deducts_from_selected_cash_account(self):
        """Single job vendor payment without method option derives method from cash account and creates ledger."""
        response = self.client.post(
            reverse('record_vendor_payment', args=[self.vendor.id]),
            {
                'payment_scope': 'single',
                'specialized_service_id': self.service.id,
                'payment_amount': '200.00',
                'financial_account': self.cash_acc.id,
                'payment_date': timezone.localdate().strftime('%Y-%m-%d'),
                'reference_no': 'REF-CASH-001',
                'notes': 'Advance component payment',
            },
        )
        self.assertEqual(response.status_code, 302)

        # Refresh service
        self.service.refresh_from_db()
        self.assertEqual(self.service.vendor_paid_amount, Decimal('200.00'))
        self.assertEqual(self.service.vendor_balance_amount, Decimal('250.00'))

        # Check VendorPayment record - method automatically set to 'cash'
        payment = VendorPayment.objects.filter(vendor=self.vendor).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, Decimal('200.00'))
        self.assertEqual(payment.financial_account, self.cash_acc)
        self.assertEqual(payment.payment_method, VendorPayment.METHOD_CASH)

        # Refresh cash account balance
        self.cash_acc.refresh_from_db()
        self.assertEqual(self.cash_acc.current_balance, Decimal('800.00'))

        # Check AccountTransaction ledger entry
        txn = AccountTransaction.objects.filter(vendor_payment=payment).first()
        self.assertIsNotNone(txn)
        self.assertEqual(txn.account, self.cash_acc)
        self.assertEqual(txn.amount, Decimal('200.00'))
        self.assertEqual(txn.transaction_type, AccountTransaction.TYPE_OUTFLOW)
        self.assertEqual(txn.balance_after, Decimal('800.00'))
        self.assertIn("FoxPro Microchips", txn.description)

    def test_record_vendor_payment_auto_infers_transfer_from_bank_account(self):
        """Selecting bank account automatically sets payment_method to transfer."""
        response = self.client.post(
            reverse('record_vendor_payment', args=[self.vendor.id]),
            {
                'payment_scope': 'single',
                'specialized_service_id': self.service.id,
                'payment_amount': '300.00',
                'financial_account': self.bank_acc.id,
                'payment_date': timezone.localdate().strftime('%Y-%m-%d'),
                'reference_no': 'NEFT-999888',
                'notes': 'Online transfer',
            },
        )
        self.assertEqual(response.status_code, 302)

        # Check VendorPayment
        payment = VendorPayment.objects.filter(vendor=self.vendor).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.financial_account, self.bank_acc)
        self.assertEqual(payment.payment_method, VendorPayment.METHOD_TRANSFER)

        # Check bank balance deduction
        self.bank_acc.refresh_from_db()
        self.assertEqual(self.bank_acc.current_balance, Decimal('4700.00'))

        # Check ledger transaction
        txn = AccountTransaction.objects.filter(vendor_payment=payment).first()
        self.assertIsNotNone(txn)
        self.assertEqual(txn.account, self.bank_acc)
        self.assertEqual(txn.balance_after, Decimal('4700.00'))

    def test_vendor_bulk_payment_deducts_account_balance(self):
        """Bulk payment across services correctly deducts from financial account."""
        # Create second service for the vendor
        job2 = JobTicket.objects.create(
            job_code="BOT-20260930-002",
            customer_name="Customer 2",
            customer_phone="9998887775",
            device_type="Phone",
            device_brand="Samsung",
            device_model="S23",
            status="Specialized Service",
            workspace=self.workspace,
            created_by=self.user,
        )
        service2 = SpecializedService.objects.create(
            job_ticket=job2,
            vendor=self.vendor,
            status="Returned from Vendor",
            vendor_cost=Decimal('300.00'),
            vendor_discount_amount=Decimal('0.00'),
            vendor_paid_amount=Decimal('0.00'),
            vendor_balance_amount=Decimal('300.00'),
            client_charge=Decimal('500.00'),
            returned_date=timezone.now(),
        )

        # Service 1 balance = 450, Service 2 balance = 300. Total = 750.
        # Pay 500 in bulk via bank
        response = self.client.post(
            reverse('record_vendor_payment', args=[self.vendor.id]),
            {
                'payment_scope': 'bulk',
                'payment_amount': '500.00',
                'financial_account': self.bank_acc.id,
                'payment_date': timezone.localdate().strftime('%Y-%m-%d'),
                'reference_no': 'BULK-TXN-01',
            },
        )
        self.assertEqual(response.status_code, 302)

        # Bank balance should have been reduced by 500 (5000 - 500 = 4500)
        self.bank_acc.refresh_from_db()
        self.assertEqual(self.bank_acc.current_balance, Decimal('4500.00'))

        # Check total payments recorded
        payments = VendorPayment.objects.filter(vendor=self.vendor)
        self.assertEqual(payments.count(), 2)  # Allocated 450 to service 1, 50 to service 2
        total_paid = sum(p.amount for p in payments)
        self.assertEqual(total_paid, Decimal('500.00'))
        for p in payments:
            self.assertEqual(p.financial_account, self.bank_acc)
            self.assertEqual(p.payment_method, VendorPayment.METHOD_TRANSFER)

        # Check transactions
        txns = AccountTransaction.objects.filter(vendor_payment__in=payments)
        self.assertEqual(txns.count(), 2)
        total_txns = sum(t.amount for t in txns)
        self.assertEqual(total_txns, Decimal('500.00'))

    def test_vendor_dashboard_renders_financial_accounts_without_method_select(self):
        """Vendor dashboard renders Paid From Account and does NOT render redundant Method select."""
        response = self.client.get(reverse('vendor_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('financial_accounts', response.context)
        accounts = response.context['financial_accounts']
        account_names = [a.name for a in accounts]
        self.assertIn(self.cash_acc.name, account_names)
        self.assertIn(self.bank_acc.name, account_names)

        # Verify dropdown is rendered in HTML
        content = response.content.decode('utf-8')
        self.assertIn('Paid From Account', content)
        self.assertIn(self.cash_acc.name, content)
        self.assertIn('payment-account-select', content)

        # Method select dropdown should NOT be present in modal
        self.assertNotIn('name="payment_method"', content)
