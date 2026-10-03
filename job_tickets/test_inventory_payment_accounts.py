from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import Group, User
from django.urls import reverse
from django.utils import timezone
from job_tickets.models import (
    CompanyUserMembership,
    CompanyWorkspace,
    FinancialAccount,
    AccountTransaction,
    InventoryParty,
    Product,
    InventoryBill,
    InventoryEntry,
    InventoryCreditPayment,
    JobTicket,
)


class InventoryPaymentAccountsTestCase(TestCase):
    def setUp(self):
        self.staff_group, _ = Group.objects.get_or_create(name='Staff')
        self.user = User.objects.create_superuser(
            username='inventory_admin',
            email='admin@example.com',
            password='testpassword123'
        )
        self.user.groups.add(self.staff_group)

        self.workspace = CompanyWorkspace.objects.create(
            owner=self.user,
            name='Test Inventory Shop',
            slug='test-inv-shop'
        )
        CompanyUserMembership.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=CompanyUserMembership.ROLE_OWNER,
            is_active=True,
        )

        # Create financial accounts
        self.cash_account = FinancialAccount.objects.create(
            workspace=self.workspace,
            name='Main Shop Cash',
            account_type=FinancialAccount.ACCOUNT_TYPE_CASH,
            current_balance=Decimal('5000.00'),
            is_default_cash=True,
            is_active=True,
        )
        self.bank_account = FinancialAccount.objects.create(
            workspace=self.workspace,
            name='HDFC Current A/C',
            account_type=FinancialAccount.ACCOUNT_TYPE_BANK,
            current_balance=Decimal('25000.00'),
            is_default_bank=True,
            is_active=True,
        )
        self.upi_account = FinancialAccount.objects.create(
            workspace=self.workspace,
            name='GPay Shop Counter',
            account_type=FinancialAccount.ACCOUNT_TYPE_UPI,
            current_balance=Decimal('3000.00'),
            is_active=True,
        )

        # Create parties
        self.customer = InventoryParty.objects.create(
            workspace=self.workspace,
            name='Walk-in Retail Buyer',
            phone='9876543210',
            is_active=True,
        )
        self.supplier = InventoryParty.objects.create(
            workspace=self.workspace,
            name='Apex Spares Wholesale',
            phone='9876543211',
            is_active=True,
        )

        # Create products
        self.screen_prod = Product.objects.create(
            workspace=self.workspace,
            name='OLED Display Assembly',
            sku='OLED-001',
            unit_price=Decimal('3000.00'),
            cost_price=Decimal('1800.00'),
            stock_quantity=10,
            is_active=True,
        )

    def test_direct_sale_bill_paid_deposits_to_selected_account(self):
        """Creating a direct Sale marked as Paid deposits full amount into the selected financial account."""
        self.client.force_login(self.user)
        session = self.client.session
        session['active_workspace_id'] = self.workspace.id
        session.save()

        initial_upi_balance = self.upi_account.current_balance
        url = reverse('inventory_sales_dashboard')

        data = {
            'inventory_entry_submit': 'sale',
            'entry_date': timezone.localdate().isoformat(),
            'party': str(self.customer.id),
            'invoice_number': 'INV-SALE-101',
            'line_product_id[]': [str(self.screen_prod.id)],
            'line_quantity[]': ['2'],
            'line_unit_price[]': ['3000.00'],
            'line_gst_rate[]': ['0.00'],
            'bill_discount_amount': '500.00',  # 6000 - 500 = 5500
            'bill_payment_status': 'paid',
            'financial_account': str(self.upi_account.id),
            'bill_payment_reference': 'UPI-REF-9988',
        }

        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, 200)

        # Verify bill and entries
        bill = InventoryBill.objects.filter(party=self.customer, entry_type='sale').first()
        self.assertIsNotNone(bill)

        # Check InventoryCreditPayment
        credit_pmt = InventoryCreditPayment.objects.filter(bill=bill).first()
        self.assertIsNotNone(credit_pmt)
        self.assertEqual(credit_pmt.amount, Decimal('5500.00'))
        self.assertEqual(credit_pmt.direction, InventoryCreditPayment.DIRECTION_RECEIVABLE)
        self.assertEqual(credit_pmt.financial_account, self.upi_account)
        self.assertEqual(credit_pmt.payment_method, InventoryCreditPayment.METHOD_UPI)

        # Check financial account updated
        self.upi_account.refresh_from_db()
        self.assertEqual(self.upi_account.current_balance, initial_upi_balance + Decimal('5500.00'))

        # Check audit transaction
        txn = AccountTransaction.objects.filter(
            account=self.upi_account,
            inventory_credit_payment=credit_pmt,
            transaction_type=AccountTransaction.TYPE_INFLOW,
        ).first()
        self.assertIsNotNone(txn)
        self.assertEqual(txn.amount, Decimal('5500.00'))

    def test_direct_purchase_bill_part_paid_withdraws_from_selected_account(self):
        """Creating a direct Purchase marked as Partially Paid withdraws paid amount from selected account."""
        self.client.force_login(self.user)
        session = self.client.session
        session['active_workspace_id'] = self.workspace.id
        session.save()

        initial_bank_balance = self.bank_account.current_balance
        url = reverse('inventory_purchase_dashboard')

        data = {
            'inventory_entry_submit': 'purchase',
            'entry_date': timezone.localdate().isoformat(),
            'party': str(self.supplier.id),
            'invoice_number': 'PUR-INV-888',
            'invoice_date': timezone.localdate().isoformat(),
            'line_product_id[]': [str(self.screen_prod.id)],
            'line_quantity[]': ['5'],
            'line_unit_price[]': ['1500.00'],  # 7500 total
            'line_gst_rate[]': ['0.00'],
            'bill_discount_amount': '0.00',
            'bill_payment_status': 'part_paid',
            'bill_amount_paid': '4000.00',
            'financial_account': str(self.bank_account.id),
            'bill_payment_reference': 'NEFT-5544',
        }

        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, 200)

        bill = InventoryBill.objects.filter(invoice_number='PUR-INV-888').first()
        self.assertIsNotNone(bill)

        # Check InventoryCreditPayment
        credit_pmt = InventoryCreditPayment.objects.filter(bill=bill).first()
        self.assertIsNotNone(credit_pmt)
        self.assertEqual(credit_pmt.amount, Decimal('4000.00'))
        self.assertEqual(credit_pmt.direction, InventoryCreditPayment.DIRECTION_PAYABLE)
        self.assertEqual(credit_pmt.financial_account, self.bank_account)
        self.assertEqual(credit_pmt.payment_method, InventoryCreditPayment.METHOD_TRANSFER)

        # Check financial account updated
        self.bank_account.refresh_from_db()
        self.assertEqual(self.bank_account.current_balance, initial_bank_balance - Decimal('4000.00'))

        # Check audit transaction
        txn = AccountTransaction.objects.filter(
            account=self.bank_account,
            inventory_credit_payment=credit_pmt,
            transaction_type=AccountTransaction.TYPE_OUTFLOW,
        ).first()
        self.assertIsNotNone(txn)
        self.assertEqual(txn.amount, Decimal('4000.00'))

    def test_credit_bill_payment_modal_customer_receipt(self):
        """Recording credit payment on an unpaid Sales bill deposits to account and infers method."""
        self.client.force_login(self.user)
        session = self.client.session
        session['active_workspace_id'] = self.workspace.id
        session.save()

        # Create an unpaid sales bill
        bill = InventoryBill.objects.create(
            workspace=self.workspace,
            bill_number='SB-001',
            entry_type='sale',
            entry_date=timezone.localdate(),
            invoice_number='INV-CREDIT-01',
            party=self.customer,
            created_by=self.user,
        )
        InventoryEntry.objects.create(
            workspace=self.workspace,
            bill=bill,
            entry_number='SE-001',
            entry_type='sale',
            entry_date=timezone.localdate(),
            party=self.customer,
            product=self.screen_prod,
            quantity=1,
            unit_price=Decimal('3000.00'),
            taxable_amount=Decimal('3000.00'),
            gst_amount=Decimal('0.00'),
            total_amount=Decimal('3000.00'),
            created_by=self.user,
        )

        initial_cash_balance = self.cash_account.current_balance
        url = reverse('inventory_record_credit_payment')

        post_data = {
            'bill_id': str(bill.id),
            'amount': '1500.00',
            'payment_date': timezone.localdate().isoformat(),
            'financial_account': str(self.cash_account.id),
            'reference_no': 'CASH-RCPT-1',
            'notes': 'Partial cash receipt',
        }

        response = self.client.post(url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        pmt = InventoryCreditPayment.objects.filter(bill=bill).first()
        self.assertIsNotNone(pmt)
        self.assertEqual(pmt.amount, Decimal('1500.00'))
        self.assertEqual(pmt.financial_account, self.cash_account)
        self.assertEqual(pmt.payment_method, InventoryCreditPayment.METHOD_CASH)

        self.cash_account.refresh_from_db()
        self.assertEqual(self.cash_account.current_balance, initial_cash_balance + Decimal('1500.00'))

        txn = AccountTransaction.objects.filter(
            account=self.cash_account,
            inventory_credit_payment=pmt,
            transaction_type=AccountTransaction.TYPE_INFLOW,
        ).first()
        self.assertIsNotNone(txn)
        self.assertEqual(txn.amount, Decimal('1500.00'))

    def test_credit_bill_payment_modal_supplier_payment(self):
        """Recording credit payment on an unpaid Purchase bill withdraws from account and infers method."""
        self.client.force_login(self.user)
        session = self.client.session
        session['active_workspace_id'] = self.workspace.id
        session.save()

        # Create an unpaid purchase bill
        bill = InventoryBill.objects.create(
            workspace=self.workspace,
            bill_number='PB-001',
            entry_type='purchase',
            entry_date=timezone.localdate(),
            invoice_number='SUP-INV-55',
            party=self.supplier,
            created_by=self.user,
        )
        InventoryEntry.objects.create(
            workspace=self.workspace,
            bill=bill,
            entry_number='PE-001',
            entry_type='purchase',
            entry_date=timezone.localdate(),
            party=self.supplier,
            product=self.screen_prod,
            quantity=2,
            unit_price=Decimal('1800.00'),
            taxable_amount=Decimal('3600.00'),
            gst_amount=Decimal('0.00'),
            total_amount=Decimal('3600.00'),
            created_by=self.user,
        )

        initial_bank_balance = self.bank_account.current_balance
        url = reverse('inventory_record_credit_payment')

        post_data = {
            'bill_id': str(bill.id),
            'amount': '3600.00',
            'payment_date': timezone.localdate().isoformat(),
            'financial_account': str(self.bank_account.id),
            'reference_no': 'IMPS-SUP-99',
            'notes': 'Full settlement to supplier',
        }

        response = self.client.post(url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        pmt = InventoryCreditPayment.objects.filter(bill=bill).first()
        self.assertIsNotNone(pmt)
        self.assertEqual(pmt.amount, Decimal('3600.00'))
        self.assertEqual(pmt.financial_account, self.bank_account)
        self.assertEqual(pmt.payment_method, InventoryCreditPayment.METHOD_TRANSFER)

        self.bank_account.refresh_from_db()
        self.assertEqual(self.bank_account.current_balance, initial_bank_balance - Decimal('3600.00'))

        txn = AccountTransaction.objects.filter(
            account=self.bank_account,
            inventory_credit_payment=pmt,
            transaction_type=AccountTransaction.TYPE_OUTFLOW,
        ).first()
        self.assertIsNotNone(txn)
        self.assertEqual(txn.amount, Decimal('3600.00'))
