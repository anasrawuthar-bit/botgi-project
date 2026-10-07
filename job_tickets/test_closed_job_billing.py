from decimal import Decimal
import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from job_tickets.models import (
    CompanyUserMembership,
    CompanyWorkspace,
    JobTicket,
    ServiceLog,
    ProductSale,
    Product,
    TechnicianProfile,
)
from job_tickets.views.helpers import mobile_can_manage_service_lines, issue_mobile_jwt

User = get_user_model()


class ClosedJobBillingLockTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_group, _ = Group.objects.get_or_create(name='Staff')
        self.tech_group, _ = Group.objects.get_or_create(name='Technicians')

        self.staff_user = User.objects.create_user(
            username='staff_billing_lock',
            email='staff@lock.test',
            password='password123',
            is_staff=True,
        )
        self.staff_user.groups.add(self.staff_group)

        self.tech_user = User.objects.create_user(
            username='tech_billing_lock',
            email='tech@lock.test',
            password='password123',
            is_staff=False,
        )
        self.tech_user.groups.add(self.tech_group)

        self.workspace = CompanyWorkspace.objects.create(
            name="Lock Test Hub",
            slug="lock-test-hub",
            status=CompanyWorkspace.STATUS_ACTIVE,
            owner=self.staff_user,
        )
        CompanyUserMembership.objects.create(
            workspace=self.workspace,
            user=self.staff_user,
            role=CompanyUserMembership.ROLE_STAFF,
            is_active=True,
        )

        self.technician = TechnicianProfile.objects.create(
            workspace=self.workspace,
            user=self.tech_user,
            unique_id='TL01',
        )

        self.job = JobTicket.objects.create(
            job_code='LOCK-202610-001',
            customer_name='Alice Smith',
            customer_phone='9876543210',
            device_type='Laptop',
            device_brand='Apple',
            device_model='MacBook Pro M2',
            reported_issue='Keyboard issue',
            status='Closed',
            workspace=self.workspace,
            created_by=self.staff_user,
            assigned_to=self.technician,
            discount_amount=Decimal('100.00'),
            vyapar_invoice_number='INV-ORIG-001',
        )

        self.service = ServiceLog.objects.create(
            job_ticket=self.job,
            description='Original Labor Service',
            part_cost=Decimal('500.00'),
            service_charge=Decimal('1500.00'),
        )

        self.product = Product.objects.create(
            workspace=self.workspace,
            name='Spare Keyboard',
            sku='KB-MBP-M2',
            stock_quantity=5,
            cost_price=Decimal('2000.00'),
            unit_price=Decimal('3500.00'),
        )

        self.client.login(username='staff_billing_lock', password='password123')

    def test_get_billing_page_on_closed_job_renders_locked_ui(self):
        url = reverse('job_billing_staff', kwargs={'job_code': self.job.job_code})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Master edit button and invoice edit button should NOT be rendered
        self.assertNotContains(response, 'id="edit-master-btn"')
        self.assertNotContains(response, 'id="edit-invoice-btn"')

        # Locked badge and warning banner should be rendered
        self.assertContains(response, 'Job Closed (Amounts Locked)')
        self.assertContains(response, 'Job Closed — Billing Locked')

    def test_get_job_detail_on_closed_job_renders_view_bill_instead_of_edit_bill(self):
        url = reverse('staff_job_detail', kwargs={'job_code': self.job.job_code})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # "View Bill" should be present, "Edit Bill" / "Manage Bill" should not
        self.assertContains(response, 'View Bill')
        self.assertNotContains(response, 'Edit Bill')
        self.assertNotContains(response, 'Manage Bill')

    def test_post_update_amounts_submit_blocked_on_closed_job(self):
        url = reverse('job_billing_staff', kwargs={'job_code': self.job.job_code})
        post_data = {
            'update_amounts_submit': '1',
            f'description_{self.service.id}': 'Hacked Description',
            f'part_cost_{self.service.id}': '9999.00',
            f'service_charge_{self.service.id}': '8888.00',
            'discount_amount': '500.00',
            'job_sales_invoice_number': 'INV-HACKED-999',
            'new_description[]': ['Unauthorized Service Line'],
            'new_part_cost[]': ['500.00'],
            'new_service_charge[]': ['500.00'],
            'product_id[]': [str(self.product.id)],
            'product_qty[]': ['1'],
            'product_unit_price[]': ['3500.00'],
        }

        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)

        # Verify nothing in database was altered
        self.service.refresh_from_db()
        self.assertEqual(self.service.description, 'Original Labor Service')
        self.assertEqual(self.service.part_cost, Decimal('500.00'))
        self.assertEqual(self.service.service_charge, Decimal('1500.00'))

        self.job.refresh_from_db()
        self.assertEqual(self.job.discount_amount, Decimal('100.00'))
        self.assertEqual(self.job.vyapar_invoice_number, 'INV-ORIG-001')

        # No new service lines created
        self.assertEqual(self.job.service_logs.count(), 1)

        # No product sale created and stock intact
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 5)
        self.assertEqual(ProductSale.objects.filter(job_ticket=self.job).count(), 0)

    def test_post_update_amounts_ajax_blocked_with_403(self):
        url = reverse('job_billing_staff', kwargs={'job_code': self.job.job_code})
        post_data = {
            'update_amounts_submit': '1',
            f'part_cost_{self.service.id}': '9999.00',
        }

        response = self.client.post(url, post_data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertFalse(data['ok'])
        self.assertIn('Cannot edit billing amounts for a closed job', data['error'])

    def test_post_delete_service_blocked_on_closed_job(self):
        url = reverse('job_billing_staff', kwargs={'job_code': self.job.job_code})
        post_data = {
            'update_amounts_submit': '1',
            'delete_service_ids[]': [str(self.service.id)],
        }

        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)

        # Service log must not be deleted
        self.assertTrue(ServiceLog.objects.filter(id=self.service.id).exists())

    def test_mobile_helper_disallows_service_lines_on_closed_job(self):
        # Even staff cannot manage lines on closed job
        self.assertFalse(mobile_can_manage_service_lines(self.staff_user, self.job))
        # Technician cannot manage lines on closed job
        self.assertFalse(mobile_can_manage_service_lines(self.tech_user, self.job))

    def test_mobile_api_service_line_create_rejected_on_closed_job(self):
        url = reverse('mobile_api_service_line_create', kwargs={'job_code': self.job.job_code})
        token = issue_mobile_jwt(self.staff_user)
        response = self.client.post(
            url,
            data=json.dumps({
                'description': 'Mobile Added Service',
                'part_cost': '200.00',
                'service_charge': '300.00',
            }),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.job.service_logs.count(), 1)
