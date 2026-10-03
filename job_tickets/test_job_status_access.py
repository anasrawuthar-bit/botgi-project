from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .access_control import ACCESS_OPTIONS, apply_staff_access, get_staff_access
from .models import (
    CompanyUserMembership,
    CompanyWorkspace,
    JobTicket,
)


class JobStatusAccessTests(TestCase):
    def setUp(self):
        self.staff_with_status_perm = User.objects.create_user(
            username='status_allowed_staff',
            password='TestPassword123!',
            is_staff=True,
        )
        apply_staff_access(self.staff_with_status_perm, {'staff_dashboard', 'job_status_change'})

        self.staff_without_status_perm = User.objects.create_user(
            username='status_denied_staff',
            password='TestPassword123!',
            is_staff=True,
        )
        apply_staff_access(self.staff_without_status_perm, {'staff_dashboard'})

        self.workspace = CompanyWorkspace.objects.create(name='Status WS', owner=self.staff_with_status_perm)
        CompanyUserMembership.objects.create(
            workspace=self.workspace,
            user=self.staff_with_status_perm,
            role=CompanyUserMembership.ROLE_STAFF,
        )
        CompanyUserMembership.objects.create(
            workspace=self.workspace,
            user=self.staff_without_status_perm,
            role=CompanyUserMembership.ROLE_STAFF,
        )

        self.job = JobTicket.objects.create(
            workspace=self.workspace,
            job_code='GI-STATUS-001',
            customer_name='John Doe',
            customer_phone='9876543210',
            device_type='Laptop',
            status='Pending',
        )

    def test_permission_definition_exists_in_options(self):
        """job_status_change should exist in ACCESS_OPTIONS under general section."""
        option = next((opt for opt in ACCESS_OPTIONS if opt['key'] == 'job_status_change'), None)
        self.assertIsNotNone(option)
        self.assertEqual(option['label'], 'Change Job Status')
        self.assertEqual(option['section'], 'general')

    def test_staff_with_permission_can_see_form_and_update_status(self):
        """Staff with job_status_change permission sees select dropdown and can update status."""
        self.client.login(username='status_allowed_staff', password='TestPassword123!')
        response = self.client.get(reverse('staff_job_detail', kwargs={'job_code': self.job.job_code}))
        self.assertEqual(response.status_code, 200)

        # Dropdown and update button should be visible
        self.assertContains(response, 'name="action" value="update_status"')
        self.assertContains(response, 'name="status"')

        # POST update status
        post_response = self.client.post(
            reverse('staff_job_detail', kwargs={'job_code': self.job.job_code}),
            {'action': 'update_status', 'status': 'Under Inspection'},
            follow=True,
        )
        self.assertEqual(post_response.status_code, 200)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'Under Inspection')

    def test_staff_without_permission_cannot_see_form_and_cannot_update_status(self):
        """Staff without job_status_change sees only read-only badge and POST is rejected."""
        self.client.login(username='status_denied_staff', password='TestPassword123!')
        response = self.client.get(reverse('staff_job_detail', kwargs={'job_code': self.job.job_code}))
        self.assertEqual(response.status_code, 200)

        # Form and select should NOT be rendered
        self.assertNotContains(response, 'name="action" value="update_status"')
        # Read-only badge should be rendered
        self.assertContains(response, '<span class="badge badge-status badge-info">Pending</span>')

        # Attempt to POST update status anyway
        post_response = self.client.post(
            reverse('staff_job_detail', kwargs={'job_code': self.job.job_code}),
            {'action': 'update_status', 'status': 'Completed'},
            follow=True,
        )
        self.assertEqual(post_response.status_code, 200)
        self.assertContains(post_response, 'You do not have permission to change job status.')
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'Pending')

    def test_mark_ready_for_pickup_permission(self):
        """mark_ready_for_pickup checks job_status_change permission."""
        self.job.status = 'Completed'
        self.job.save()

        # Denied staff cannot mark ready
        self.client.login(username='status_denied_staff', password='TestPassword123!')
        resp = self.client.get(reverse('mark_ready_for_pickup', kwargs={'job_code': self.job.job_code}), follow=True)
        self.assertContains(resp, 'You do not have permission to change job status.')
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'Completed')

        # Allowed staff can mark ready
        self.client.login(username='status_allowed_staff', password='TestPassword123!')
        resp = self.client.get(reverse('mark_ready_for_pickup', kwargs={'job_code': self.job.job_code}), follow=True)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'Ready for Pickup')
