from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .access_control import apply_staff_access
from .models import (
    CompanyProfile,
    CompanyUserMembership,
    CompanyWorkspace,
    DeviceChecklistField,
    DeviceChecklistTemplate,
    JobFieldPreset,
    JobTicket,
)
from .views.helpers import _apply_job_checklist_rules, get_active_checklist_templates, get_job_field_presets


class IntakePresetsAndChecklistsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff_user = User.objects.create_user(
            username='settings_admin_user',
            password='TestPassword123!',
            is_staff=True,
        )
        apply_staff_access(self.staff_user, {'company_settings', 'staff_dashboard'})

        self.restricted_staff = User.objects.create_user(
            username='restricted_user',
            password='TestPassword123!',
            is_staff=True,
        )
        apply_staff_access(self.restricted_staff, {'staff_dashboard'})

        self.workspace = CompanyWorkspace.objects.create(name='Preset WS', owner=self.staff_user)
        CompanyUserMembership.objects.create(
            workspace=self.workspace,
            user=self.staff_user,
            role=CompanyUserMembership.ROLE_ADMIN,
        )
        CompanyUserMembership.objects.create(
            workspace=self.workspace,
            user=self.restricted_staff,
            role=CompanyUserMembership.ROLE_STAFF,
        )
        self.profile = CompanyProfile.objects.filter(workspace=self.workspace).first()
        if not self.profile:
            self.profile = CompanyProfile.objects.filter(workspace__isnull=True).first()
        if self.profile:
            self.profile.workspace = self.workspace
            self.profile.company_name = 'Test Workshop'
            self.profile.save()
        else:
            self.profile = CompanyProfile.objects.create(company_name='Test Workshop', workspace=self.workspace)

    def test_preset_crud_and_cache(self):
        """Staff with company_settings can create, edit, and delete field presets."""
        self.client.login(username='settings_admin_user', password='TestPassword123!')

        # 1. Create presets
        res_create = self.client.post(reverse('preset_create'), {
            'field_name': 'device_type',
            'value': 'Drone Quadcopter',
            'sort_order': '15',
        })
        self.assertEqual(res_create.status_code, 302)
        preset = JobFieldPreset.objects.filter(field_name='device_type', value='Drone Quadcopter').first()
        self.assertIsNotNone(preset)
        self.assertEqual(preset.sort_order, 15)

        # Check helper retrieval
        presets = get_job_field_presets()
        self.assertIn('Drone Quadcopter', presets['device_type'])

        # 2. Edit preset
        res_edit = self.client.post(reverse('preset_edit', kwargs={'preset_id': preset.id}), {
            'value': 'Drone Hexacopter',
            'sort_order': '25',
            'is_active': 'on',
        })
        self.assertEqual(res_edit.status_code, 302)
        preset.refresh_from_db()
        self.assertEqual(preset.value, 'Drone Hexacopter')
        self.assertEqual(preset.sort_order, 25)

        # Cache refreshed
        presets_after_edit = get_job_field_presets()
        self.assertIn('Drone Hexacopter', presets_after_edit['device_type'])
        self.assertNotIn('Drone Quadcopter', presets_after_edit['device_type'])

        # 3. Delete preset
        res_del = self.client.post(reverse('preset_delete', kwargs={'preset_id': preset.id}))
        self.assertEqual(res_del.status_code, 302)
        self.assertFalse(JobFieldPreset.objects.filter(id=preset.id).exists())

    def test_preset_permission_denial(self):
        """Staff without company_settings cannot modify presets."""
        self.client.login(username='restricted_user', password='TestPassword123!')
        res = self.client.post(reverse('preset_create'), {
            'field_name': 'device_brand',
            'value': 'Razer',
        })
        self.assertRedirects(res, reverse('unauthorized'))
        self.assertFalse(JobFieldPreset.objects.filter(value='Razer').exists())

    def test_checklist_template_and_fields_crud(self):
        """Staff can create, edit, delete checklist templates and their fields."""
        self.client.login(username='settings_admin_user', password='TestPassword123!')

        # 1. Create Checklist Template
        res_template_create = self.client.post(reverse('checklist_template_create'), {
            'device_type': 'Gaming Console',
            'name': 'Console Intake Check',
            'notes': 'Check HDMI port pins and fan noise.',
        })
        self.assertEqual(res_template_create.status_code, 302)
        template = DeviceChecklistTemplate.objects.filter(device_type__iexact='Gaming Console').first()
        self.assertIsNotNone(template)
        self.assertEqual(template.name, 'Console Intake Check')

        # Auto-created device_type preset
        self.assertTrue(JobFieldPreset.objects.filter(field_name='device_type', value__iexact='Gaming Console').exists())

        # 2. Add Fields to Template
        res_field_create = self.client.post(reverse('checklist_field_create', kwargs={'template_id': template.id}), {
            'label': 'HDMI Port Physical Condition',
            'field_type': 'checkbox',
            'is_required': 'on',
            'sort_order': '10',
        })
        self.assertEqual(res_field_create.status_code, 302)

        res_field_create_select = self.client.post(reverse('checklist_field_create', kwargs={'template_id': template.id}), {
            'label': 'Fan Noise Level',
            'field_type': 'select',
            'options': 'Quiet / Normal\nLoud Whine\nGrinding / Stopped',
            'sort_order': '20',
        })
        self.assertEqual(res_field_create_select.status_code, 302)

        fields = list(template.fields.all())
        self.assertEqual(len(fields), 2)
        select_field = template.fields.get(field_type='select')
        self.assertEqual(len(select_field.get_option_list()), 3)

        # 3. Edit Field
        res_field_edit = self.client.post(reverse('checklist_field_edit', kwargs={'field_id': select_field.id}), {
            'label': 'Fan Noise & Airflow',
            'field_type': 'select',
            'options': 'Normal\nNoisy\nBlocked',
            'sort_order': '30',
            'is_active': 'on',
        })
        self.assertEqual(res_field_edit.status_code, 302)
        select_field.refresh_from_db()
        self.assertEqual(select_field.label, 'Fan Noise & Airflow')
        self.assertEqual(select_field.sort_order, 30)

        # 4. Edit Template
        res_template_edit = self.client.post(reverse('checklist_template_edit', kwargs={'template_id': template.id}), {
            'name': 'Console Quality Control Check',
            'notes': 'Updated instructions.',
            'is_active': 'on',
        })
        self.assertEqual(res_template_edit.status_code, 302)
        template.refresh_from_db()
        self.assertEqual(template.name, 'Console Quality Control Check')

        # 5. Delete Field
        res_field_del = self.client.post(reverse('checklist_field_delete', kwargs={'field_id': select_field.id}))
        self.assertEqual(res_field_del.status_code, 302)
        self.assertEqual(template.fields.count(), 1)

        # 6. Delete Template
        res_template_del = self.client.post(reverse('checklist_template_delete', kwargs={'template_id': template.id}))
        self.assertEqual(res_template_del.status_code, 302)
        self.assertFalse(DeviceChecklistTemplate.objects.filter(id=template.id).exists())

    def test_settings_page_intake_presets_tab_render(self):
        """Settings page renders #intake-presets tab with preset categories, templates, and modals."""
        template = DeviceChecklistTemplate.objects.create(
            workspace=self.workspace,
            device_type='Laptop',
            name='Laptop Inspection',
            is_active=True,
        )
        field = DeviceChecklistField.objects.create(
            template=template,
            field_key='screen_check',
            label='Screen Inspection',
            field_type='checkbox',
            is_required=True,
            sort_order=10,
        )
        self.client.login(username='settings_admin_user', password='TestPassword123!')
        response = self.client.get(f"{reverse('company_profile_settings')}?tab=intake-presets")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="intake-presets"')
        self.assertContains(response, 'Job Intake Field Presets')
        self.assertContains(response, 'Device Inspection Checklists')
        self.assertContains(response, 'id="addPresetModal"')
        self.assertContains(response, 'id="editPresetModal"')
        self.assertContains(response, 'id="addChecklistTemplateModal"')
        self.assertContains(response, 'id="editChecklistTemplateModal"')
        self.assertContains(response, 'id="addChecklistFieldModal"')
        self.assertContains(response, 'id="editChecklistFieldModal"')
        self.assertContains(response, f'id="template-panel-{template.id}"')
        self.assertContains(response, 'Screen Inspection')

    def test_staff_dashboard_checklist_templates_context(self):
        """Staff dashboard context includes active checklist templates mapping."""
        # Create template
        DeviceChecklistTemplate.objects.create(
            workspace=self.workspace,
            device_type='Tablet',
            name='Tablet Inspection Checklist',
            is_active=True,
        )
        self.client.login(username='settings_admin_user', password='TestPassword123!')
        response = self.client.get(reverse('staff_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('active_checklist_templates', response.context)
        self.assertIn('tablet', response.context['active_checklist_templates'])
        self.assertContains(response, 'Require Inspection Checklist')

    def test_apply_job_checklist_rules_dynamic(self):
        """Checklist requirements correctly adapt based on requires_laptop_inspection_checklist."""
        job_required = JobTicket(
            device_type='Desktop',
            requires_laptop_inspection_checklist=True,
        )
        schema = [{'key': 'power_supply', 'label': 'PSU Check', 'required': True}]
        result_schema, notes = _apply_job_checklist_rules(job_required, 'desktop', schema, '')
        self.assertTrue(result_schema[0]['required'])
        self.assertIn('must be completed', notes)

        job_optional = JobTicket(
            device_type='Desktop',
            requires_laptop_inspection_checklist=False,
        )
        result_schema_opt, notes_opt = _apply_job_checklist_rules(job_optional, 'desktop', schema, '')
        self.assertFalse(result_schema_opt[0]['required'])
        self.assertIn('optional for this job', notes_opt)
