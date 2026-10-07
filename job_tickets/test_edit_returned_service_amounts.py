from decimal import Decimal
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from job_tickets.models import (
    CompanyUserMembership,
    CompanyWorkspace,
    JobTicket,
    JobTicketLog,
    ServiceLog,
    SpecializedService,
    Vendor,
)


class EditReturnedServiceAmountsTestCase(TestCase):
    def setUp(self):
        self.staff_group, _ = Group.objects.get_or_create(name='Staff')

        self.user = User.objects.create_user(
            username="staff_editor",
            password="password123",
            is_staff=True,
        )
        self.user.groups.add(self.staff_group)

        self.workspace = CompanyWorkspace.objects.create(
            name="Test Service Hub",
            slug="test-hub-edit",
            status=CompanyWorkspace.STATUS_ACTIVE,
            owner=self.user,
        )
        CompanyUserMembership.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=CompanyUserMembership.ROLE_STAFF,
            is_active=True,
        )

        self.vendor = Vendor.objects.create(
            workspace=self.workspace,
            company_name="Alpha Chipsets",
            name="John Alpha",
            phone="9876543210",
        )

        self.job = JobTicket.objects.create(
            job_code="BOT-20261007-001",
            customer_name="Ravi Kumar",
            customer_phone="9988776655",
            device_type="Laptop",
            device_brand="Lenovo",
            device_model="ThinkPad X1",
            status="Repairing",
            workspace=self.workspace,
            created_by=self.user,
        )

        self.service = SpecializedService.objects.create(
            job_ticket=self.job,
            vendor=self.vendor,
            status="Returned from Vendor",
            vendor_cost=Decimal('1000.00'),
            vendor_discount_amount=Decimal('0.00'),
            vendor_paid_amount=Decimal('0.00'),
            vendor_balance_amount=Decimal('1000.00'),
            client_charge=Decimal('1500.00'),
            vendor_bill_number="BILL-101",
            returned_date=timezone.now(),
        )

        self.service_log = ServiceLog.objects.create(
            job_ticket=self.job,
            description="Specialized Service - Alpha Chipsets",
            part_cost=Decimal('0.00'),
            service_charge=Decimal('1500.00'),
        )

        self.client.login(username="staff_editor", password="password123")

    def test_edit_returned_amounts_success(self):
        url = reverse('edit_returned_service_amounts', args=[self.service.id])
        response = self.client.post(url, {
            'vendor_cost': '1250.00',
            'client_charge': '1900.00',
            'vendor_bill_number': 'BILL-101-REVISED',
            'return_date': '2026-10-07',
        })
        self.assertEqual(response.status_code, 302)

        self.service.refresh_from_db()
        self.assertEqual(self.service.vendor_cost, Decimal('1250.00'))
        self.assertEqual(self.service.vendor_balance_amount, Decimal('1250.00'))
        self.assertEqual(self.service.client_charge, Decimal('1900.00'))
        self.assertEqual(self.service.vendor_bill_number, 'BILL-101-REVISED')

        self.service_log.refresh_from_db()
        self.assertEqual(self.service_log.service_charge, Decimal('1900.00'))

        log = JobTicketLog.objects.filter(job_ticket=self.job).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertIn("Vendor return details edited", log.details)
        self.assertIn("1250.00", log.details)

    def test_edit_amounts_blocked_when_job_closed(self):
        self.job.status = 'Closed'
        self.job.save(update_fields=['status'])

        url = reverse('edit_returned_service_amounts', args=[self.service.id])
        response = self.client.post(url, {
            'vendor_cost': '2000.00',
            'client_charge': '3000.00',
            'vendor_bill_number': 'BILL-CLOSED',
            'return_date': '2026-10-07',
        })
        self.assertEqual(response.status_code, 302)

        self.service.refresh_from_db()
        self.assertEqual(self.service.vendor_cost, Decimal('1000.00'))
        self.assertEqual(self.service.client_charge, Decimal('1500.00'))
        self.assertEqual(self.service.vendor_bill_number, 'BILL-101')

        self.service_log.refresh_from_db()
        self.assertEqual(self.service_log.service_charge, Decimal('1500.00'))

    def test_edit_amounts_cannot_go_below_paid_amount(self):
        self.service.vendor_paid_amount = Decimal('600.00')
        self.service.vendor_balance_amount = Decimal('400.00')
        self.service.save(update_fields=['vendor_paid_amount', 'vendor_balance_amount'])

        url = reverse('edit_returned_service_amounts', args=[self.service.id])
        response = self.client.post(url, {
            'vendor_cost': '500.00',  # Less than paid 600.00!
            'client_charge': '1500.00',
            'vendor_bill_number': 'BILL-101',
            'return_date': '2026-10-07',
        })
        self.assertEqual(response.status_code, 302)

        self.service.refresh_from_db()
        # Should remain unchanged
        self.assertEqual(self.service.vendor_cost, Decimal('1000.00'))
        self.assertEqual(self.service.vendor_balance_amount, Decimal('400.00'))
