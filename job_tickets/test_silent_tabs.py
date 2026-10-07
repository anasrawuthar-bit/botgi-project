from decimal import Decimal
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from job_tickets.access_control import apply_staff_access
from job_tickets.models import JobTicket, TechnicianProfile, SpecializedService
from job_tickets.views.helpers import send_job_update_message


class SilentTabReloadTests(TestCase):
    def setUp(self):
        # Create test users
        self.staff_user = User.objects.create_user(
            username='staff_tester',
            password='password123',
            is_staff=True,
        )
        apply_staff_access(self.staff_user, {'staff_dashboard'})

        self.tech_user = User.objects.create_user(
            username='tech_tester',
            password='password123',
        )
        self.technician = TechnicianProfile.objects.create(
            user=self.tech_user,
            unique_id='TECH-01',
        )

        # Create sample job tickets across different statuses
        self.pending_job = JobTicket.objects.create(
            job_code='GI-TEST-001',
            customer_name='Alice Smith',
            customer_phone='9876543210',
            device_type='Mobile',
            device_brand='Apple',
            reported_issue='Broken screen',
            status='Pending',
        )

        self.in_progress_job = JobTicket.objects.create(
            job_code='GI-TEST-002',
            customer_name='Bob Jones',
            customer_phone='9876543211',
            device_type='Laptop',
            device_brand='Dell',
            reported_issue='Keyboard not working',
            status='Under Inspection',
            assigned_to=self.technician,
        )

        self.ready_job = JobTicket.objects.create(
            job_code='GI-TEST-003',
            customer_name='Charlie Brown',
            customer_phone='9876543212',
            device_type='Tablet',
            device_brand='Samsung',
            reported_issue='Battery replacement',
            status='Ready for Pickup',
            assigned_to=self.technician,
        )

        self.completed_job = JobTicket.objects.create(
            job_code='GI-TEST-004',
            customer_name='Diana Prince',
            customer_phone='9876543213',
            device_type='Mobile',
            device_brand='Google',
            reported_issue='Camera glitch',
            status='Completed',
            assigned_to=self.technician,
        )

        self.returned_job = JobTicket.objects.create(
            job_code='GI-TEST-005',
            customer_name='Evan Wright',
            customer_phone='9876543214',
            device_type='Laptop',
            device_brand='HP',
            reported_issue='Motherboard dead',
            status='Returned',
        )

    def test_unauthenticated_user_redirected(self):
        url = reverse('staff_dashboard_tab_partial')
        response = self.client.get(url, {'tab': 'pending'})
        self.assertEqual(response.status_code, 302)

    def test_unauthorized_user_denied(self):
        non_staff = User.objects.create_user(username='regular_user', password='password123')
        self.client.login(username='regular_user', password='password123')
        url = reverse('staff_dashboard_tab_partial')
        response = self.client.get(url, {'tab': 'pending'})
        self.assertIn(response.status_code, [302, 403])

    def test_fetch_single_tab_partial(self):
        self.client.login(username='staff_tester', password='password123')
        url = reverse('staff_dashboard_tab_partial')

        response = self.client.get(url, {'tab': 'ready'})
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertTrue(data.get('ok'))
        self.assertIn('counts', data)
        self.assertEqual(data['counts']['ready'], 1)
        self.assertEqual(data['counts']['pending'], 1)
        self.assertEqual(data['counts']['in-progress'], 1)
        self.assertEqual(data['counts']['completed'], 1)
        self.assertEqual(data['counts']['returned'], 1)

        self.assertIn('tabs', data)
        self.assertIn('ready', data['tabs'])
        self.assertIn(self.ready_job.job_code, data['tabs']['ready']['html'])
        self.assertIn('Charlie Brown', data['tabs']['ready']['html'])

        # Since only 'ready' was requested, 'pending' should not be in tabs payload
        self.assertNotIn('pending', data['tabs'])

    def test_fetch_multiple_tabs_partial(self):
        self.client.login(username='staff_tester', password='password123')
        url = reverse('staff_dashboard_tab_partial')

        response = self.client.get(url, {'tab': 'pending,in-progress'})
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertTrue(data.get('ok'))
        self.assertIn('pending', data['tabs'])
        self.assertIn('in-progress', data['tabs'])
        self.assertIn(self.pending_job.job_code, data['tabs']['pending']['html'])
        self.assertIn(self.in_progress_job.job_code, data['tabs']['in-progress']['html'])

    def test_fetch_all_tabs_partial(self):
        self.client.login(username='staff_tester', password='password123')
        url = reverse('staff_dashboard_tab_partial')

        response = self.client.get(url, {'tab': 'all'})
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertTrue(data.get('ok'))
        for expected_tab in ['pending', 'in-progress', 'ready', 'specialized', 'completed', 'returned']:
            self.assertIn(expected_tab, data['tabs'])

    def test_send_job_update_message_supports_old_status(self):
        # Should execute cleanly without channel layer errors
        try:
            send_job_update_message(self.pending_job.job_code, 'Under Inspection', old_status='Pending')
        except Exception as e:
            self.fail(f"send_job_update_message raised an exception: {e}")
