from decimal import Decimal
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .access_control import apply_staff_access
from .models import (
    CompanyUserMembership, CompanyWorkspace, DeviceRack, JobTicket,
    TechnicianProfile,
)


def _make_workspace_and_user(username='rack_user', access_keys=None):
    user = User.objects.create_user(
        username=username,
        password='TestPassword123!',
        is_staff=True,
    )
    if access_keys is None:
        access_keys = {'staff_dashboard', 'company_settings'}
    apply_staff_access(user, access_keys)
    ws = CompanyWorkspace.objects.create(name=f'Workspace {username}', owner=user)
    CompanyUserMembership.objects.create(
        workspace=ws,
        user=user,
        role=CompanyUserMembership.ROLE_ADMIN,
    )
    return ws, user


class DeviceRackTests(TestCase):
    def setUp(self):
        self.workspace, self.user = _make_workspace_and_user('rack_admin', {'staff_dashboard', 'company_settings'})
        self.client.login(username='rack_admin', password='TestPassword123!')

        # Create a sample rack
        self.rack_shop = DeviceRack.objects.create(
            workspace=self.workspace,
            name='Rack A1',
            group=DeviceRack.GROUP_SHOP,
            description='Front counter top shelf',
        )
        self.rack_godown = DeviceRack.objects.create(
            workspace=self.workspace,
            name='Shelf G2',
            group=DeviceRack.GROUP_GODOWN,
            description='Back warehouse aisle 2',
        )

    def test_rack_model_properties(self):
        self.assertEqual(str(self.rack_shop), 'Rack A1 (Shop)')
        self.assertEqual(self.rack_shop.total_columns, 10)
        self.assertEqual(self.rack_shop.active_jobs_count, 0)

        # Create a job ticket in this rack in Column 3
        job = JobTicket.objects.create(
            workspace=self.workspace,
            job_code='JOB-1001',
            customer_name='John Doe',
            customer_phone='9876543210',
            device_type='Laptop',
            device_brand='Dell',
            device_model='Latitude 7490',
            reported_issue='No power',
            status='Pending',
            rack=self.rack_shop,
            rack_column=3,
        )

        self.assertEqual(self.rack_shop.active_jobs_count, 1)
        self.assertIn(job, self.rack_shop.active_job_tickets)
        self.assertEqual(job.rack_location_display, 'Rack A1 - Col 3 (Shop)')
        self.assertEqual(job.rack_short_display, 'Rack A1 - Col 3')

        # Test get_columns_data helper for slot grid visualization
        col_data = self.rack_shop.get_columns_data()
        self.assertEqual(col_data['total_slots'], 10)
        self.assertEqual(col_data['occupied_slots_count'], 1)
        self.assertEqual(len(col_data['columns']), 10)
        self.assertEqual(col_data['overflow_jobs'], [])
        slot_3 = col_data['columns'][2]  # 0-indexed -> Col 3
        self.assertEqual(slot_3['column_num'], 3)
        self.assertTrue(slot_3['is_occupied'])
        self.assertEqual(slot_3['primary_job'], job)
        slot_1 = col_data['columns'][0]
        self.assertFalse(slot_1['is_occupied'])

        # Once job is closed, active count decreases and slot becomes free
        job.status = 'Closed'
        job.save()
        self.assertEqual(self.rack_shop.active_jobs_count, 0)
        col_data_after = self.rack_shop.get_columns_data()
        self.assertEqual(col_data_after['occupied_slots_count'], 0)

    def test_settings_tab_rack_management_context(self):
        # Create an active job in rack_shop
        JobTicket.objects.create(
            workspace=self.workspace,
            job_code='JOB-1002',
            customer_name='Alice',
            customer_phone='9876543211',
            device_type='Desktop',
            device_brand='HP',
            device_model='Pavilion',
            reported_issue='Beeps on boot',
            status='Repairing',
            rack=self.rack_shop,
            rack_column=1,
        )

        # Create an unassigned active job
        unassigned_job = JobTicket.objects.create(
            workspace=self.workspace,
            job_code='JOB-1099',
            customer_name='Eve',
            customer_phone='9876543219',
            device_type='Tablet',
            device_brand='Apple',
            device_model='iPad Air',
            reported_issue='Broken glass',
            status='Pending',
            rack=None,
        )

        response = self.client.get(reverse('company_profile_settings') + '?tab=rack-management')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_racks'], 2)
        self.assertEqual(response.context['occupied_racks'], 1)
        self.assertEqual(response.context['empty_racks'], 1)
        self.assertEqual(response.context['total_devices_stored'], 1)
        self.assertIn('Shop', response.context['rack_groups'])
        self.assertIn('Godown', response.context['rack_groups'])
        self.assertContains(response, 'Col 1')
        self.assertContains(response, 'Column / Slot Grid')
        self.assertIn(unassigned_job, response.context['unassigned_jobs'])
        self.assertContains(response, 'id="moveSlotModal"')
        self.assertContains(response, 'id="assignSlotModal"')

    def test_rack_create_success(self):
        response = self.client.post(reverse('rack_create'), {
            'name': 'Bench B1',
            'group': 'Bench',
            'description': 'Technician bench 1 tray',
            'total_columns': '12',
            'is_active': 'on',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        created = DeviceRack.objects.filter(workspace=self.workspace, name='Bench B1').first()
        self.assertIsNotNone(created)
        self.assertEqual(created.group, 'Bench')
        self.assertEqual(created.total_columns, 12)
        self.assertTrue(created.is_active)

    def test_rack_create_duplicate_rejected(self):
        response = self.client.post(reverse('rack_create'), {
            'name': 'Rack A1',
            'group': 'Shop',
            'total_columns': '10',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        # Only 1 Rack A1 in Shop
        self.assertEqual(DeviceRack.objects.filter(workspace=self.workspace, name='Rack A1', group='Shop').count(), 1)

    def test_rack_edit_success(self):
        response = self.client.post(reverse('rack_edit', args=[self.rack_shop.id]), {
            'name': 'Rack A1 Updated',
            'group': 'Shop',
            'description': 'Updated description',
            'total_columns': '16',
            'is_active': 'on',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.rack_shop.refresh_from_db()
        self.assertEqual(self.rack_shop.name, 'Rack A1 Updated')
        self.assertEqual(self.rack_shop.description, 'Updated description')
        self.assertEqual(self.rack_shop.total_columns, 16)

    def test_rack_delete_empty_rack(self):
        response = self.client.post(reverse('rack_delete', args=[self.rack_godown.id]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DeviceRack.objects.filter(id=self.rack_godown.id).exists())

    def test_rack_delete_occupied_blocked(self):
        # Place an active job in rack_shop
        JobTicket.objects.create(
            workspace=self.workspace,
            job_code='JOB-1003',
            customer_name='Bob',
            customer_phone='9876543212',
            device_type='Laptop',
            device_brand='Asus',
            device_model='ZenBook',
            reported_issue='Keyboard issue',
            status='Pending',
            rack=self.rack_shop,
        )

        response = self.client.post(reverse('rack_delete', args=[self.rack_shop.id]), follow=True)
        self.assertEqual(response.status_code, 200)
        # Rack should still exist because active devices are inside
        self.assertTrue(DeviceRack.objects.filter(id=self.rack_shop.id).exists())

    def test_job_intake_creates_job_with_rack_and_column(self):
        response = self.client.post(reverse('staff_dashboard'), {
            'job_ticket_form_submit': '1',
            'customer_name': 'Charlie',
            'customer_phone': '9876543213',
            'device_forms[0].device_type': 'Laptop',
            'device_forms[0].device_brand': 'Lenovo',
            'device_forms[0].device_model': 'ThinkPad E14',
            'device_forms[0].reported_issue': 'Screen flickering',
            'device_forms[0].additional_items': 'Charger',
            'device_forms[0].rack': str(self.rack_shop.id),
            'device_forms[0].rack_column': '4',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        created_job = JobTicket.objects.filter(customer_name='Charlie').first()
        self.assertIsNotNone(created_job)
        self.assertEqual(created_job.rack, self.rack_shop)
        self.assertEqual(created_job.rack_column, 4)

    def test_staff_update_job_rack_and_column(self):
        job = JobTicket.objects.create(
            workspace=self.workspace,
            job_code='JOB-1004',
            customer_name='David',
            customer_phone='9876543214',
            device_type='Mobile',
            device_brand='Samsung',
            device_model='S21',
            reported_issue='Battery draining fast',
            status='Pending',
            rack=self.rack_shop,
            rack_column=1,
        )

        # Move to rack_godown slot 5
        response = self.client.post(reverse('staff_update_job_rack', args=[job.job_code]), {
            'rack_id': str(self.rack_godown.id),
            'rack_column': '5',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.rack, self.rack_godown)
        self.assertEqual(job.rack_column, 5)

        # Release from rack
        response = self.client.post(reverse('staff_update_job_rack', args=[job.job_code]), {
            'rack_id': '',
            'rack_column': '',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        job.refresh_from_db()
        self.assertIsNone(job.rack)
        self.assertIsNone(job.rack_column)

    def test_job_card_receipt_print_displays_rack_and_column(self):
        job = JobTicket.objects.create(
            workspace=self.workspace,
            job_code='JOB-1005',
            customer_name='Eve',
            customer_phone='9876543215',
            device_type='Tablet',
            device_brand='Apple',
            device_model='iPad Air',
            reported_issue='Broken screen',
            status='Pending',
            rack=self.rack_shop,
            rack_column=2,
        )

        response = self.client.get(reverse('job_creation_receipt_print', args=[job.job_code]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Rack Location:')
        self.assertContains(response, '<strong>Rack A1</strong> - Col 2 (Shop)')

    def test_technician_can_view_and_update_rack_and_column(self):
        tech_user = User.objects.create_user(username='tech_jim', password='Password123!', is_staff=False)
        tech_group, _ = Group.objects.get_or_create(name='Technicians')
        tech_user.groups.add(tech_group)
        tech_profile = TechnicianProfile.objects.create(workspace=self.workspace, user=tech_user, unique_id='TECH01')
        CompanyUserMembership.objects.create(workspace=self.workspace, user=tech_user, role=CompanyUserMembership.ROLE_STAFF)

        job = JobTicket.objects.create(
            workspace=self.workspace,
            job_code='JOB-1006',
            customer_name='Frank',
            customer_phone='9876543216',
            device_type='Laptop',
            device_brand='Dell',
            device_model='Inspiron',
            reported_issue='No boot',
            status='Under Inspection',
            rack=self.rack_shop,
            rack_column=3,
            assigned_to=tech_profile,
        )

        self.client.login(username='tech_jim', password='Password123!')
        response = self.client.get(reverse('job_detail_technician', args=[job.job_code]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Rack A1 - Col 3 (Shop)')

        # Move rack as technician via AJAX to rack_godown slot 7
        post_response = self.client.post(
            reverse('job_detail_technician', args=[job.job_code]),
            {
                'action': 'update_rack',
                'rack_id': str(self.rack_godown.id),
                'rack_column': '7',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(post_response.status_code, 200)
        self.assertEqual(post_response.json()['rack_column'], 7)
        job.refresh_from_db()
        self.assertEqual(job.rack, self.rack_godown)
        self.assertEqual(job.rack_column, 7)


