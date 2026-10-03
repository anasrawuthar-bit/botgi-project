from decimal import Decimal
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from job_tickets.models import (
    CompanyWorkspace,
    CompanyProfile,
    FinancialAccount,
    JobTicket,
    ServiceLog,
    TechnicianProfile,
)
from job_tickets.views.helpers import build_job_billing_context
from job_tickets.forms import CompanyProfileForm
from django.template.loader import render_to_string


class BillPaymentDetailsToggleAndResolutionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="techuser", password="password123")
        self.workspace = CompanyWorkspace.objects.create(
            name="Test Billing Workspace",
            slug="test-billing-ws",
            owner=self.user,
        )
        self.profile = CompanyProfile.get_profile(self.workspace)
        self.profile.company_name = "Alpha Tech Services"
        self.profile.bank_name = "Profile Bank"
        self.profile.account_number = "9876543210"
        self.profile.ifsc_code = "PROF0001234"
        self.profile.branch = "Main City"
        self.profile.upi_id = "profile@upi"
        self.profile.include_bill_payment_details = True
        self.profile.save()

        self.tech = TechnicianProfile.objects.create(
            user=self.user,
            workspace=self.workspace,
            unique_id="1001",
        )
        self.job = JobTicket.objects.create(
            workspace=self.workspace,
            job_code="GI-9901",
            customer_name="John Doe",
            customer_phone="9876543210",
            device_type="Laptop",
            assigned_to=self.tech,
            created_by=self.user,
            amount_paid=Decimal("500.00"),
        )
        ServiceLog.objects.create(
            job_ticket=self.job,
            description="Screen Replacement",
            part_cost=Decimal("1000.00"),
            service_charge=Decimal("500.00"),
        )
        self.factory = RequestFactory()

    def test_context_resolves_fallback_company_profile_when_no_financial_account(self):
        # Ensure no FinancialAccount exists
        FinancialAccount.objects.filter(workspace=self.workspace).delete()

        request = self.factory.get("/print/")
        request.current_workspace = self.workspace
        context = build_job_billing_context(self.job, request=request)

        self.assertEqual(context['bank_name'], "Profile Bank")
        self.assertEqual(context['account_number'], "9876543210")
        self.assertEqual(context['ifsc_code'], "PROF0001234")
        self.assertEqual(context['branch'], "Main City")
        self.assertEqual(context['upi_id'], "profile@upi")
        self.assertIn("pa=profile@upi", context['upi_payment_url'])

    def test_context_resolves_default_financial_account_details(self):
        # Create FinancialAccount marked as is_default_bank
        acc = FinancialAccount.objects.create(
            workspace=self.workspace,
            name="Corporate HDFC Current",
            account_type=FinancialAccount.ACCOUNT_TYPE_BANK,
            bank_name="HDFC Bank",
            account_number="50200012345678",
            ifsc_code="HDFC0000001",
            branch="Downtown Branch",
            upi_id="hdfccorp@okhdfcbank",
            is_default_bank=True,
            is_active=True,
        )

        request = self.factory.get("/print/")
        request.current_workspace = self.workspace
        context = build_job_billing_context(self.job, request=request)

        self.assertEqual(context['bank_name'], "HDFC Bank")
        self.assertEqual(context['account_number'], "50200012345678")
        self.assertEqual(context['ifsc_code'], "HDFC0000001")
        self.assertEqual(context['branch'], "Downtown Branch")
        self.assertEqual(context['upi_id'], "hdfccorp@okhdfcbank")
        self.assertIn("pa=hdfccorp@okhdfcbank", context['upi_payment_url'])

    def test_bill_rendering_with_payment_details_enabled(self):
        self.profile.include_bill_payment_details = True
        self.profile.save()

        request = self.factory.get("/print/")
        request.current_workspace = self.workspace
        context = build_job_billing_context(self.job, request=request)
        html = render_to_string("job_tickets/job_billing_print.html", context)

        self.assertIn("Payment Settlement &amp; Bank Details", html)
        self.assertIn("Profile Bank", html)
        self.assertIn("9876543210", html)
        self.assertNotIn("settlement-grid single-col", html)
        self.assertNotIn("Repair Warranty Certificate", html)

    def test_bill_rendering_with_payment_details_disabled(self):
        self.profile.include_bill_payment_details = False
        self.profile.save()

        request = self.factory.get("/print/")
        request.current_workspace = self.workspace
        context = build_job_billing_context(self.job, request=request)
        html = render_to_string("job_tickets/job_billing_print.html", context)

        self.assertNotIn("Payment Settlement &amp; Bank Details", html)
        self.assertNotIn("Profile Bank", html)
        self.assertIn("settlement-grid single-col", html)
        self.assertNotIn("Repair Warranty Certificate", html)
