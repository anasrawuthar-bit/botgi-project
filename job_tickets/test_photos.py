from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from .access_control import apply_staff_access
from .models import (
    CompanyUserMembership,
    CompanyWorkspace,
    JobTicket,
    JobTicketPhoto,
    TechnicianProfile,
)


class IntakePhotosTests(TestCase):
    def setUp(self):
        # Staff user & Workspace
        self.staff_user = User.objects.create_user(
            username='staff_test_user',
            password='TestPassword123!',
            is_staff=True,
        )
        apply_staff_access(self.staff_user, {'staff_dashboard'})
        self.workspace = CompanyWorkspace.objects.create(name='Test Workspace', owner=self.staff_user)
        CompanyUserMembership.objects.create(
            workspace=self.workspace,
            user=self.staff_user,
            role=CompanyUserMembership.ROLE_STAFF,
        )

        # Technician group & user
        self.tech_group, _ = Group.objects.get_or_create(name='Technicians')
        self.tech_user = User.objects.create_user(
            username='tech_test_user',
            password='TestPassword123!',
            is_staff=False,
        )
        self.tech_user.groups.add(self.tech_group)
        self.tech_profile = TechnicianProfile.objects.create(
            user=self.tech_user,
            workspace=self.workspace,
            unique_id='T001',
        )

        # Job ticket assigned to technician
        self.job = JobTicket.objects.create(
            workspace=self.workspace,
            job_code='GI-TEST-001',
            customer_name='John Doe',
            customer_phone='9876543210',
            device_type='Laptop',
            device_brand='Dell',
            device_model='Inspiron',
            reported_issue='Screen flicker',
            assigned_to=self.tech_profile,
        )

        # Intake Photo
        self.photo_bytes = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00testphoto'
        self.photo = JobTicketPhoto.objects.create(
            job_ticket=self.job,
            image_name='damage_front.jpg',
            image_content_type='image/jpeg',
            image_data=self.photo_bytes,
        )

    def test_technician_can_view_assigned_job_photo(self):
        """Technician assigned to the job must be able to view and load intake photos without 403/unauthorized."""
        self.client.login(username='tech_test_user', password='TestPassword123!')
        response = self.client.get(self.photo.image_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get('Content-Type'), 'image/jpeg')
        self.assertEqual(response.content, self.photo_bytes)

    def test_staff_can_view_job_photo(self):
        """Staff with staff_dashboard permission and workspace access can view the photo."""
        self.client.login(username='staff_test_user', password='TestPassword123!')
        response = self.client.get(self.photo.image_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get('Content-Type'), 'image/jpeg')
        self.assertEqual(response.content, self.photo_bytes)

    def test_unrelated_technician_from_other_workspace_cannot_view_photo(self):
        """Technician from a different workspace not assigned to the job is denied."""
        other_ws = CompanyWorkspace.objects.create(name='Other Workspace', owner=self.staff_user)
        other_tech_user = User.objects.create_user(
            username='other_tech_user',
            password='TestPassword123!',
            is_staff=False,
        )
        other_tech_user.groups.add(self.tech_group)
        TechnicianProfile.objects.create(
            user=other_tech_user,
            workspace=other_ws,
            unique_id='T002',
        )
        self.client.login(username='other_tech_user', password='TestPassword123!')
        response = self.client.get(self.photo.image_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/unauthorized/', response.url)

    def test_technician_job_detail_page_renders_preview_elements(self):
        """Technician detail page must render the preview thumbnails and popup modal."""
        self.client.login(username='tech_test_user', password='TestPassword123!')
        response = self.client.get(reverse('job_detail_technician', kwargs={'job_code': self.job.job_code}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'tech-photo-thumb-btn')
        self.assertContains(response, 'techPhotoPreviewModal')
        self.assertContains(response, self.photo.image_url)
