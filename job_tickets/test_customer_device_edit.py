from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .access_control import apply_staff_access
from .models import (
    Client,
    CompanyUserMembership,
    CompanyWorkspace,
    JobTicket,
    JobTicketLog,
)


class CustomerDeviceEditTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            username='edit_staff_user',
            password='TestPassword123!',
            is_staff=True,
        )
        apply_staff_access(self.staff_user, {'staff_dashboard'})
        self.workspace = CompanyWorkspace.objects.create(name='Test WS', owner=self.staff_user)
        CompanyUserMembership.objects.create(
            workspace=self.workspace,
            user=self.staff_user,
            role=CompanyUserMembership.ROLE_STAFF,
        )

        self.client_obj = Client.objects.create(
            workspace=self.workspace,
            name='aasna',
            phone='9876543210',
        )

        self.job = JobTicket.objects.create(
            workspace=self.workspace,
            job_code='GI-260928-999',
            customer_name='aasna',
            customer_phone='9876543210',
            device_type='Laptop',
            device_brand='Dell',
            device_model='INSPIRON 3521',
            device_serial='serial123',
            device_password='1234',
            reported_issue='Display issue',
            additional_items='CHARGER',
        )

        self.client.login(username='edit_staff_user', password='TestPassword123!')

    def test_page_renders_edit_button_and_modal(self):
        """Job detail page must render the Edit Details button and editCustomerDeviceModal."""
        response = self.client.get(reverse('staff_job_detail', kwargs={'job_code': self.job.job_code}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit Details')
        self.assertContains(response, 'editCustomerDeviceModal')
        self.assertContains(response, 'edit_customer_device_details')
        self.assertContains(response, 'edit_device_password')

    def test_successful_edit_updates_job_and_creates_log(self):
        """Updating details updates job, syncs client, and writes an audit log."""
        post_data = {
            'action': 'edit_customer_device_details',
            'customer_name': 'Aasna Khan',
            'customer_phone': '9876543211',
            'device_type': 'Laptop',
            'device_brand': 'Dell',
            'device_model': 'Inspiron 15 3521',
            'device_serial': 'DL-3521-X',
            'device_password': '9876',
            'reported_issue': 'Display flickering and screen line',
            'additional_items': 'CHARGER, Power cable, Bag',
            'edit_reason': 'Customer updated phone and brought bag',
        }
        response = self.client.post(
            reverse('staff_job_detail', kwargs={'job_code': self.job.job_code}),
            data=post_data,
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        # Refresh job
        self.job.refresh_from_db()
        self.assertEqual(self.job.customer_name, 'Aasna Khan')
        self.assertEqual(self.job.customer_phone, '9876543211')
        self.assertEqual(self.job.device_model, 'Inspiron 15 3521')
        self.assertEqual(self.job.device_serial, 'DL-3521-X')
        self.assertEqual(self.job.device_password, '9876')
        self.assertEqual(self.job.reported_issue, 'Display flickering and screen line')
        self.assertEqual(self.job.additional_items, 'CHARGER, Power cable, Bag')

        # Check Client model sync
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.name, 'Aasna Khan')
        self.assertEqual(self.client_obj.phone, '9876543211')

        # Check JobTicketLog entry
        log = JobTicketLog.objects.filter(job_ticket=self.job, action='DETAILS').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.staff_user)
        self.assertIn("Customer Name: 'aasna' -> 'Aasna Khan'", log.details)
        self.assertIn("Customer Phone: '9876543210' -> '9876543211'", log.details)
        self.assertIn("Serial: 'serial123' -> 'DL-3521-X'", log.details)
        self.assertIn("Device Password: '1234' -> '9876'", log.details)
        self.assertIn("Reason: Customer updated phone and brought bag", log.details)

        # Ensure log renders in history
        self.assertContains(response, 'Customer &amp; Device Details Updated')
        from django.utils.html import escape
        self.assertContains(response, escape(log.details))

    def test_invalid_phone_number_rejected(self):
        """Invalid phone numbers must be rejected with an error message."""
        post_data = {
            'action': 'edit_customer_device_details',
            'customer_name': 'Aasna Khan',
            'customer_phone': '12345',  # invalid
            'device_type': 'Laptop',
            'device_brand': 'Dell',
            'device_model': 'INSPIRON 3521',
            'device_serial': 'serial123',
            'device_password': '1234',
            'reported_issue': 'Display issue',
            'additional_items': 'CHARGER',
        }
        response = self.client.post(
            reverse('staff_job_detail', kwargs={'job_code': self.job.job_code}),
            data=post_data,
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        # Should not change
        self.job.refresh_from_db()
        self.assertEqual(self.job.customer_phone, '9876543210')
        # No log created
        self.assertFalse(JobTicketLog.objects.filter(job_ticket=self.job, action='DETAILS').exists())

    def test_no_changes_detected_does_not_create_log(self):
        """Submitting with identical data produces an info message without creating a log."""
        post_data = {
            'action': 'edit_customer_device_details',
            'customer_name': self.job.customer_name,
            'customer_phone': self.job.customer_phone,
            'device_type': self.job.device_type,
            'device_brand': self.job.device_brand,
            'device_model': self.job.device_model,
            'device_serial': self.job.device_serial,
            'device_password': self.job.device_password,
            'reported_issue': self.job.reported_issue,
            'additional_items': self.job.additional_items,
        }
        response = self.client.post(
            reverse('staff_job_detail', kwargs={'job_code': self.job.job_code}),
            data=post_data,
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(JobTicketLog.objects.filter(job_ticket=self.job, action='DETAILS').exists())
