import json
from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from job_tickets.access_control import apply_staff_access
from job_tickets.models import CompanyWorkspace, CompanyUserMembership, JobTicket


class JobIntakeWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='reception_staff',
            password='StaffPassword123!',
            is_staff=True,
        )
        apply_staff_access(self.user, {'staff_dashboard'})
        self.workspace = CompanyWorkspace.objects.create(name='Main Workshop', owner=self.user)
        CompanyUserMembership.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=CompanyUserMembership.ROLE_ADMIN,
        )
        self.client = Client()
        self.client.login(username='reception_staff', password='StaffPassword123!')

    def test_ajax_job_creation_returns_proper_payload(self):
        """Verify that AJAX job creation returns the required payload for receipt opening and dashboard refresh."""
        url = reverse('staff_dashboard')
        data = {
            'job_ticket_form_submit': 'true',
            'customer_name': 'Ramesh Kumar',
            'customer_phone': '9876543210',
            'device_forms[0].device_type': 'Laptop',
            'device_forms[0].device_brand': 'Dell',
            'device_forms[0].device_model': 'Inspiron 15',
            'device_forms[0].reported_issue': 'Screen flickering on boot',
            'estimated_amount': '1500.00',
        }
        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)

        json_data = response.json()
        self.assertTrue(json_data.get('success'))
        self.assertEqual(len(json_data.get('job_codes', [])), 1)
        self.assertEqual(len(json_data.get('jobs', [])), 1)

        job_info = json_data['jobs'][0]
        job_code = job_info['job_code']
        self.assertTrue(bool(job_code))
        self.assertEqual(job_info['customer_name'], 'Ramesh Kumar')
        self.assertEqual(job_info['customer_phone'], '9876543210')
        self.assertEqual(job_info['device_type'], 'Laptop')
        self.assertTrue('receipt_url' in job_info)
        self.assertTrue('detail_url' in job_info)

        # Verify receipt URL works and is accessible
        receipt_res = self.client.get(job_info['receipt_url'])
        self.assertEqual(receipt_res.status_code, 200)
        self.assertContains(receipt_res, job_code)
        self.assertContains(receipt_res, 'Ramesh Kumar')

        # Verify dashboard now has the job in pending queue
        dash_res = self.client.get(url)
        self.assertEqual(dash_res.status_code, 200)
        self.assertContains(dash_res, job_code)
        self.assertContains(dash_res, 'Ramesh Kumar')
        self.assertContains(dash_res, '1 pending intake')

    def test_ajax_multi_device_job_creation(self):
        """Verify multiple devices submitted at once all return proper receipt and job code info."""
        url = reverse('staff_dashboard')
        data = {
            'job_ticket_form_submit': 'true',
            'customer_name': 'Priya Sharma',
            'customer_phone': '9123456780',
            'device_forms[0].device_type': 'Laptop',
            'device_forms[0].device_brand': 'HP',
            'device_forms[0].device_model': 'Pavilion',
            'device_forms[0].reported_issue': 'Fan noise',
            'device_forms[1].device_type': 'Mobile',
            'device_forms[1].device_brand': 'Samsung',
            'device_forms[1].device_model': 'Galaxy S21',
            'device_forms[1].reported_issue': 'Battery draining fast',
            'estimated_amount': '2500.00',
        }
        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)

        json_data = response.json()
        self.assertTrue(json_data.get('success'))
        self.assertEqual(len(json_data.get('job_codes', [])), 2)
        self.assertEqual(len(json_data.get('jobs', [])), 2)

        # Both jobs should share the same customer group ID
        jobs = JobTicket.objects.filter(job_code__in=json_data['job_codes'])
        self.assertEqual(jobs.count(), 2)
        self.assertEqual(jobs[0].customer_group_id, jobs[1].customer_group_id)
