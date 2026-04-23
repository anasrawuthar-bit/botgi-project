import hashlib
import hmac
import json
from decimal import Decimal
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Group, User
from django.http import HttpResponse
from django.test import Client as DjangoTestClient, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .admin import InventoryEntryAdmin, JobTicketAdmin
from .admin_roles import ROLE_SUPER_ADMIN
from .forms import (
    AssignJobForm,
    ClientForm,
    CompanyProfileForm,
    InventoryEntryForm,
    InventoryPartyForm,
    ProductForm,
    WhatsAppIntegrationSettingsForm,
)
from .models import (
    Client,
    CompanyProfile,
    InventoryBill,
    InventoryEntry,
    InventoryParty,
    JobTicket,
    MessageQueue,
    Product,
    ProductSale,
    ServiceLog,
    TechnicianProfile,
    UserSessionActivity,
    WhatsAppIntegrationSettings,
)
from .phone_utils import normalize_indian_phone
from .whatsapp_service import send_job_whatsapp_notification
from .views import client_login, get_phone_service_snapshot, issue_mobile_jwt, staff_job_detail, technician_report_print


class IndianPhoneUtilsTests(TestCase):
    def test_normalize_accepts_formatted_number_and_removes_prefix(self):
        phone, error = normalize_indian_phone('+91 98765 43210')
        self.assertIsNone(error)
        self.assertEqual(phone, '9876543210')

    def test_normalize_rejects_alphabets(self):
        phone, error = normalize_indian_phone('98AB5 43210')
        self.assertEqual(phone, '')
        self.assertEqual(error, 'Phone number can contain numbers only. Alphabets are not allowed.')

    def test_normalize_rejects_more_than_ten_digits(self):
        phone, error = normalize_indian_phone('987654321012')
        self.assertEqual(phone, '')
        self.assertEqual(error, 'Phone number must be exactly 10 digits.')


class ClientFormPhoneValidationTests(TestCase):
    def test_client_form_saves_clean_phone_digits(self):
        form = ClientForm(data={'name': 'Arun', 'phone': '98765 43210', 'address': '', 'notes': ''})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['phone'], '9876543210')

    def test_client_form_rejects_empty_phone(self):
        form = ClientForm(data={'name': 'Arun', 'phone': '', 'address': '', 'notes': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('phone', form.errors)


class ClientLoginPhoneNormalizationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.job = JobTicket.objects.create(
            job_code='GI-260324-001',
            customer_name='Arun',
            customer_phone='9876543210',
            device_type='Laptop',
            device_brand='Dell',
            device_model='Inspiron',
            reported_issue='No display',
        )

    def test_client_login_accepts_spaced_phone_format(self):
        response = self.client.post(
            reverse('client_login'),
            {'job_code': self.job.job_code, 'phone_number': '98765 43210'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('client_status', args=[self.job.job_code]))

    def test_client_login_accepts_plus_91_phone_format(self):
        response = self.client.post(
            reverse('client_login'),
            {'job_code': self.job.job_code, 'phone_number': '+91 98765 43210'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('client_status', args=[self.job.job_code]))

    def test_client_login_shows_clear_phone_error_for_short_number(self):
        request = self.factory.post(
            reverse('client_login'),
            {'job_code': self.job.job_code, 'phone_number': '98765'},
        )
        response = client_login(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Phone Number must be exactly 10 digits.', response.content)


class PhoneLookupSnapshotTests(TestCase):
    def test_snapshot_matches_existing_plus_91_client_record(self):
        Client.objects.create(name='Existing Client', phone='+91 98765 43210')
        JobTicket.objects.create(
            job_code='GI-260324-002',
            customer_name='Existing Client',
            customer_phone='9876543210',
            device_type='Mobile',
            device_brand='Samsung',
            device_model='M31',
            reported_issue='Charging issue',
        )

        snapshot = get_phone_service_snapshot('9876543210')

        self.assertTrue(snapshot['exists'])
        self.assertEqual(snapshot['client_name'], 'Existing Client')
        self.assertEqual(snapshot['total_jobs'], 1)


@override_settings(WEB_RELEASE_VERSION='2026.04.20.1', WEB_RELEASE_POLL_INTERVAL_SECONDS=180)
class AppReleaseMetaTests(TestCase):
    def test_release_meta_endpoint_returns_current_web_version(self):
        response = self.client.get(reverse('app_release_meta'))

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertTrue(payload['ok'])
        self.assertEqual(payload['web_version'], '2026.04.20.1')
        self.assertEqual(payload['poll_interval_seconds'], 180)
        self.assertIn('generated_at', payload)

    def test_base_template_includes_release_refresh_banner(self):
        template_path = Path(settings.BASE_DIR) / 'job_tickets' / 'templates' / 'job_tickets' / 'base.html'
        template_text = template_path.read_text(encoding='utf-8')

        self.assertIn('data-botgi-web-version="{{ release_info.web_version }}"', template_text)
        self.assertIn('data-botgi-release-meta-url="{% url \'app_release_meta\' %}"', template_text)
        self.assertIn('id="app-release-banner"', template_text)
        self.assertIn("job_tickets/js/app-release-monitor.js", template_text)


class SessionSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='session-user', password='StrongPass123!')

    def test_secure_cookie_settings_are_enabled(self):
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertTrue(settings.CSRF_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, 'Lax')
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, 'Lax')
        self.assertEqual(settings.SESSION_COOKIE_AGE, settings.SESSION_IDLE_TIMEOUT_SECONDS)

    def test_successful_login_creates_session_activity(self):
        response = self.client.post(
            reverse('login'),
            {'username': 'session-user', 'password': 'StrongPass123!'},
            REMOTE_ADDR='192.168.1.55',
            HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36',
        )

        self.assertEqual(response.status_code, 302)
        activity = UserSessionActivity.objects.get(user=self.user)
        self.assertEqual(activity.status, UserSessionActivity.STATUS_ACTIVE)
        self.assertEqual(activity.channel, UserSessionActivity.CHANNEL_WEB)
        self.assertTrue(activity.session_key)
        self.assertIsNotNone(activity.last_activity_at)
        self.assertEqual(activity.ip_address, '192.168.1.55')
        self.assertEqual(activity.device_label, 'Chrome on Windows')

    def test_logout_marks_session_as_logged_out(self):
        self.client.login(username='session-user', password='StrongPass123!')
        activity = UserSessionActivity.objects.get(user=self.user)

        response = self.client.get(reverse('logout'))

        self.assertEqual(response.status_code, 302)
        activity.refresh_from_db()
        self.assertEqual(activity.status, UserSessionActivity.STATUS_LOGGED_OUT)
        self.assertIsNotNone(activity.logout_at)

    def test_inactive_session_expires_and_redirects_to_login(self):
        self.client.login(username='session-user', password='StrongPass123!')
        session = self.client.session
        session['_last_activity_ts'] = int((timezone.now() - timedelta(seconds=settings.SESSION_IDLE_TIMEOUT_SECONDS + 5)).timestamp())
        session.save()

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(f"{reverse('login')}?next="))

        activity = UserSessionActivity.objects.get(user=self.user)
        self.assertEqual(activity.status, UserSessionActivity.STATUS_EXPIRED)
        self.assertEqual(activity.logout_reason, UserSessionActivity.STATUS_EXPIRED)

    def test_login_ignores_unresolved_next_url(self):
        response = self.client.post(
            reverse('login'),
            {
                'username': 'session-user',
                'password': 'StrongPass123!',
                'next': '/missing-page/',
            },
            REMOTE_ADDR='192.168.1.55',
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home'))

    def test_login_preserves_valid_next_url(self):
        valid_next = reverse('client_login')
        response = self.client.post(
            reverse('login'),
            {
                'username': 'session-user',
                'password': 'StrongPass123!',
                'next': valid_next,
            },
            REMOTE_ADDR='192.168.1.56',
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, valid_next)

    def test_second_login_invalidates_previous_active_session(self):
        first_client = DjangoTestClient()
        second_client = DjangoTestClient()

        first_response = first_client.post(
            reverse('login'),
            {'username': 'session-user', 'password': 'StrongPass123!'},
            REMOTE_ADDR='192.168.1.55',
        )
        self.assertEqual(first_response.status_code, 302)

        first_session_key = first_client.session.session_key
        self.assertTrue(
            UserSessionActivity.objects.filter(
                session_key=first_session_key,
                status=UserSessionActivity.STATUS_ACTIVE,
            ).exists()
        )

        second_response = second_client.post(
            reverse('login'),
            {'username': 'session-user', 'password': 'StrongPass123!'},
            REMOTE_ADDR='192.168.1.56',
        )
        self.assertEqual(second_response.status_code, 302)

        first_activity = UserSessionActivity.objects.get(session_key=first_session_key)
        self.assertEqual(first_activity.status, UserSessionActivity.STATUS_LOGGED_OUT)
        self.assertEqual(first_activity.logout_reason, UserSessionActivity.LOGOUT_REASON_NEW_LOGIN)
        self.assertEqual(
            UserSessionActivity.objects.filter(
                user=self.user,
                status=UserSessionActivity.STATUS_ACTIVE,
            ).count(),
            1,
        )

        kicked_response = first_client.get(reverse('home'))
        self.assertEqual(kicked_response.status_code, 302)
        self.assertTrue(kicked_response.url.startswith(f"{reverse('login')}?next="))
        self.assertIn('reason=session_replaced', kicked_response.url)

        login_notice_response = first_client.get(kicked_response.url)
        self.assertEqual(login_notice_response.status_code, 200)
        self.assertContains(login_notice_response, 'Signed Out From Another Device')
        self.assertContains(login_notice_response, 'this account signed in on another device')


class AdminDeletePermissionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.inventory_admin = InventoryEntryAdmin(InventoryEntry, self.site)
        self.job_admin = JobTicketAdmin(JobTicket, self.site)

        self.super_admin = User.objects.create_user(
            username='super-admin',
            password='StrongPass123!',
            is_staff=True,
        )
        super_admin_group, _ = Group.objects.get_or_create(name=ROLE_SUPER_ADMIN)
        self.super_admin.groups.add(super_admin_group)

        self.regular_staff = User.objects.create_user(
            username='regular-staff',
            password='StrongPass123!',
            is_staff=True,
        )

    def test_super_admin_can_delete_inventory_entry_and_stock_is_restored(self):
        supplier = InventoryParty.objects.create(name='Main Supplier', party_type='supplier')
        product = Product.objects.create(
            name='SSD 512GB',
            stock_quantity=5,
            unit_price=Decimal('4500.00'),
            cost_price=Decimal('3200.00'),
        )
        bill = InventoryBill.objects.create(
            bill_number='PB-260401-001',
            entry_type='purchase',
            entry_date=timezone.localdate(),
            party=supplier,
        )
        entry = InventoryEntry.objects.create(
            bill=bill,
            entry_number='PE-260401-001',
            entry_type='purchase',
            entry_date=timezone.localdate(),
            party=supplier,
            product=product,
            quantity=5,
            unit_price=Decimal('3200.00'),
            taxable_amount=Decimal('16000.00'),
            total_amount=Decimal('16000.00'),
            stock_before=0,
            stock_after=5,
        )

        request = self.factory.post('/admin/job_tickets/inventoryentry/')
        request.user = self.super_admin

        self.assertTrue(self.inventory_admin.has_delete_permission(request, entry))
        self.inventory_admin.delete_model(request, entry)

        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 0)
        self.assertFalse(InventoryEntry.objects.filter(pk=entry.pk).exists())
        self.assertFalse(InventoryBill.objects.filter(pk=bill.pk).exists())

        request.user = self.regular_staff
        self.assertFalse(self.inventory_admin.has_delete_permission(request, None))

    def test_super_admin_can_delete_protected_job_and_linked_inventory_is_cleaned(self):
        customer = InventoryParty.objects.create(name='Walk-in Customer', party_type='customer')
        product = Product.objects.create(
            name='Laptop Battery',
            stock_quantity=3,
            unit_price=Decimal('2500.00'),
            cost_price=Decimal('1500.00'),
        )
        job = JobTicket.objects.create(
            job_code='GI-260401-900',
            customer_name='Anas',
            customer_phone='9876543210',
            device_type='Laptop',
            reported_issue='Battery not charging',
            status='Completed',
            vyapar_invoice_number='INV-900',
        )
        ServiceLog.objects.create(
            job_ticket=job,
            description='Battery replacement',
            part_cost=Decimal('2500.00'),
            service_charge=Decimal('300.00'),
        )
        bill = InventoryBill.objects.create(
            bill_number='SB-260401-001',
            entry_type='sale',
            entry_date=timezone.localdate(),
            invoice_number='INV-900',
            job_ticket=job,
            party=customer,
        )
        entry = InventoryEntry.objects.create(
            bill=bill,
            entry_number='SE-260401-001',
            entry_type='sale',
            entry_date=timezone.localdate(),
            invoice_number='INV-900',
            job_ticket=job,
            party=customer,
            product=product,
            quantity=2,
            unit_price=Decimal('2500.00'),
            taxable_amount=Decimal('5000.00'),
            total_amount=Decimal('5000.00'),
            stock_before=5,
            stock_after=3,
        )

        request = self.factory.post('/admin/job_tickets/jobticket/')
        request.user = self.super_admin

        self.assertTrue(self.job_admin.has_delete_permission(request, job))
        self.job_admin.delete_model(request, job)

        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 5)
        self.assertFalse(JobTicket.objects.filter(pk=job.pk).exists())
        self.assertFalse(InventoryEntry.objects.filter(pk=entry.pk).exists())
        self.assertFalse(InventoryBill.objects.filter(pk=bill.pk).exists())

        request.user = self.regular_staff
        self.assertFalse(self.job_admin.has_delete_permission(request, None))


class TechnicianAssignmentAndChecklistTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            username='dashboard-admin',
            password='StrongPass123!',
            is_staff=True,
            is_superuser=True,
        )
        self.technician_user = User.objects.create_user(
            username='actual-tech',
            password='StrongPass123!',
        )
        self.technician = TechnicianProfile.objects.create(
            user=self.technician_user,
            unique_id='TECH100',
        )
        self.staff_with_profile = User.objects.create_user(
            username='staff-profile-user',
            password='StrongPass123!',
            is_staff=True,
        )
        self.staff_profile = TechnicianProfile.objects.create(
            user=self.staff_with_profile,
            unique_id='STF100',
        )

    def test_assign_form_excludes_staff_users_even_if_profile_exists(self):
        form = AssignJobForm()

        technician_ids = list(form.fields['technician'].queryset.values_list('id', flat=True))

        self.assertIn(self.technician.id, technician_ids)
        self.assertNotIn(self.staff_profile.id, technician_ids)

    def test_staff_job_detail_reassign_list_excludes_staff_profiles(self):
        job = JobTicket.objects.create(
            job_code='GI-260407-001',
            customer_name='Reassign Customer',
            customer_phone='9876543210',
            device_type='Laptop',
            device_brand='Dell',
            device_model='Latitude',
            reported_issue='No power',
            assigned_to=self.technician,
        )

        request = RequestFactory().get(reverse('staff_job_detail', args=[job.job_code]))
        request.user = self.staff_user
        captured = {}

        def fake_render(_request, _template_name, context):
            captured['context'] = context
            return HttpResponse('ok')

        with patch('job_tickets.views.staff_views.render', side_effect=fake_render):
            response = staff_job_detail(request, job.job_code)

        self.assertEqual(response.status_code, 200)
        technician_ids = [tech.id for tech in captured['context']['technician_list']]
        self.assertIn(self.technician.id, technician_ids)
        self.assertNotIn(self.staff_profile.id, technician_ids)

    def test_laptop_job_can_be_completed_without_checklist_when_toggle_is_off(self):
        job = JobTicket.objects.create(
            job_code='GI-260407-002',
            customer_name='Checklist Optional',
            customer_phone='9876543211',
            device_type='Laptop',
            device_brand='HP',
            device_model='15s',
            reported_issue='Boot issue',
            status='Under Inspection',
            assigned_to=self.technician,
            requires_laptop_inspection_checklist=False,
        )
        self.client.force_login(self.technician_user)

        response = self.client.post(reverse('job_mark_completed', args=[job.job_code]))

        self.assertEqual(response.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.status, 'Completed')

    def test_laptop_job_still_requires_checklist_when_toggle_is_on(self):
        job = JobTicket.objects.create(
            job_code='GI-260407-003',
            customer_name='Checklist Required',
            customer_phone='9876543212',
            device_type='Laptop',
            device_brand='Lenovo',
            device_model='ThinkPad',
            reported_issue='Slow performance',
            status='Under Inspection',
            assigned_to=self.technician,
            requires_laptop_inspection_checklist=True,
        )
        self.client.force_login(self.technician_user)

        response = self.client.post(reverse('job_mark_completed', args=[job.job_code]))

        self.assertEqual(response.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.status, 'Under Inspection')


class GstMasterFormTests(TestCase):
    def test_inventory_party_form_normalizes_gst_fields_and_derives_state_codes(self):
        form = InventoryPartyForm(
            data={
                'name': 'Acme Systems',
                'legal_name': 'Acme Systems Private Limited',
                'contact_person': 'Arun',
                'gst_registration_type': 'registered',
                'phone': '9876543210',
                'gstin': '32abcde1234f1z5',
                'state_code': '',
                'default_place_of_supply_state': '',
                'pan': 'abcde1234f',
                'email': 'billing@example.com',
                'address': 'Main billing address',
                'shipping_address': '',
                'city': 'Kochi',
                'state': 'Kerala',
                'country': '',
                'pincode': '682001',
                'opening_balance': '0.00',
                'is_active': 'on',
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        party = form.save()

        self.assertEqual(party.gstin, '32ABCDE1234F1Z5')
        self.assertEqual(party.pan, 'ABCDE1234F')
        self.assertEqual(party.state_code, '32')
        self.assertEqual(party.default_place_of_supply_state, '32')
        self.assertEqual(party.country, 'India')
        self.assertEqual(party.party_type, 'both')

    def test_inventory_party_form_rejects_state_code_mismatch(self):
        form = InventoryPartyForm(
            data={
                'name': 'Mismatch Traders',
                'legal_name': '',
                'contact_person': '',
                'gst_registration_type': 'registered',
                'phone': '',
                'gstin': '32ABCDE1234F1Z5',
                'state_code': '33',
                'default_place_of_supply_state': '',
                'pan': '',
                'email': '',
                'address': '',
                'shipping_address': '',
                'city': '',
                'state': '',
                'country': 'India',
                'pincode': '',
                'opening_balance': '0.00',
                'is_active': 'on',
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn('state_code', form.errors)

    def test_product_form_normalizes_codes(self):
        form = ProductForm(
            data={
                'name': 'Premium SSD',
                'category': 'Storage',
                'brand': 'WD',
                'item_type': 'goods',
                'hsn_sac_code': '8471',
                'uqc': 'nos',
                'tax_category': 'taxable',
                'gst_rate': '18.00',
                'cess_rate': '0.00',
                'is_tax_inclusive_default': 'on',
                'cost_price': '3200.00',
                'unit_price': '4500.00',
                'stock_quantity': '10',
                'reserved_stock': '2',
                'description': '',
                'purchase_price_tax_mode': 'without_tax',
                'sales_price_tax_mode': 'without_tax',
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        product = form.save()

        self.assertEqual(product.hsn_sac_code, '8471')
        self.assertEqual(product.uqc, 'NOS')
        self.assertEqual(product.tax_category, 'taxable')

    def test_product_form_requires_zero_tax_for_exempt_items(self):
        form = ProductForm(
            data={
                'name': 'Exempt Service',
                'category': 'Support',
                'brand': '',
                'item_type': 'service',
                'hsn_sac_code': '9987',
                'uqc': '',
                'tax_category': 'exempt',
                'gst_rate': '18.00',
                'cess_rate': '0.00',
                'cost_price': '0.00',
                'unit_price': '1500.00',
                'stock_quantity': '0',
                'reserved_stock': '0',
                'description': '',
                'purchase_price_tax_mode': 'without_tax',
                'sales_price_tax_mode': 'without_tax',
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn('gst_rate', form.errors)

    def test_company_profile_form_normalizes_tax_identity_and_defaults_pos(self):
        profile = CompanyProfile.get_profile()
        form = CompanyProfileForm(
            data={
                'company_name': 'GI Service Billing',
                'legal_name': 'GI Hostings Private Limited',
                'tagline': 'Service Billing',
                'logo': '',
                'logo_url': '',
                'address': 'Kochi',
                'city': 'Kochi',
                'state': 'Kerala',
                'pincode': '682001',
                'phone1': '9876543210',
                'phone2': '',
                'email': 'hello@example.com',
                'website': 'https://example.com',
                'gstin': '32abcde1234f1z5',
                'pan': 'abcde1234f',
                'state_code': '',
                'registration_type': 'regular',
                'filing_frequency': 'quarterly',
                'qrmp_enabled': 'on',
                'lut_bond_enabled': '',
                'annual_turnover_band': 'up_to_5cr',
                'e_invoice_applicable': '',
                'e_way_bill_enabled': 'on',
                'default_place_of_supply_state': '',
                'bank_name': '',
                'account_number': '',
                'ifsc_code': '',
                'branch': '',
                'upi_id': '',
                'job_code_prefix': 'GI',
                'enable_gst': 'on',
                'gst_rate': '18.00',
                'terms_conditions': 'Standard terms',
            },
            instance=profile,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved_profile = form.save()

        self.assertEqual(saved_profile.gstin, '32ABCDE1234F1Z5')
        self.assertEqual(saved_profile.pan, 'ABCDE1234F')
        self.assertEqual(saved_profile.state_code, '32')
        self.assertEqual(saved_profile.default_place_of_supply_state, '32')

    def test_company_profile_form_rejects_qrmp_with_monthly_filing(self):
        profile = CompanyProfile.get_profile()
        form = CompanyProfileForm(
            data={
                'company_name': 'GI Service Billing',
                'legal_name': 'GI Hostings Private Limited',
                'tagline': 'Service Billing',
                'logo': '',
                'logo_url': '',
                'address': 'Kochi',
                'city': 'Kochi',
                'state': 'Kerala',
                'pincode': '682001',
                'phone1': '9876543210',
                'phone2': '',
                'email': 'hello@example.com',
                'website': 'https://example.com',
                'gstin': '32ABCDE1234F1Z5',
                'pan': 'ABCDE1234F',
                'state_code': '32',
                'registration_type': 'regular',
                'filing_frequency': 'monthly',
                'qrmp_enabled': 'on',
                'lut_bond_enabled': '',
                'annual_turnover_band': 'up_to_5cr',
                'e_invoice_applicable': '',
                'e_way_bill_enabled': 'on',
                'default_place_of_supply_state': '32',
                'bank_name': '',
                'account_number': '',
                'ifsc_code': '',
                'branch': '',
                'upi_id': '',
                'job_code_prefix': 'GI',
                'enable_gst': 'on',
                'gst_rate': '18.00',
                'terms_conditions': 'Standard terms',
            },
            instance=profile,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('filing_frequency', form.errors)


class WhatsAppCloudApiTests(TestCase):
    def setUp(self):
        self.settings_obj = WhatsAppIntegrationSettings.get_settings()

    def test_enabled_settings_require_cloud_api_credentials_and_template_names(self):
        form = WhatsAppIntegrationSettingsForm(
            data={
                'is_enabled': 'on',
                'api_version': '',
                'phone_number_id': '',
                'access_token': '',
                'webhook_verify_token': '',
                'app_secret': '',
                'public_site_url': 'https://example.com',
                'default_country_code': '91',
                'template_language_code': '',
                'test_template_name': 'hello_world',
                'notify_on_created': 'on',
                'notify_on_completed': 'on',
                'notify_on_delivered': 'on',
                'created_template_name': '',
                'created_template': 'Hello {customer_name}',
                'completed_template_name': 'job_completed_update',
                'completed_template': 'Hello {customer_name}',
                'delivered_template_name': '',
                'delivered_template': 'Hello {customer_name}',
            },
            instance=self.settings_obj,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('api_version', form.errors)
        self.assertIn('phone_number_id', form.errors)
        self.assertIn('access_token', form.errors)
        self.assertIn('template_language_code', form.errors)
        self.assertIn('created_template_name', form.errors)
        self.assertIn('delivered_template_name', form.errors)

    @patch('job_tickets.whatsapp_service.transaction.on_commit', side_effect=lambda callback: callback())
    @patch('job_tickets.whatsapp_service.requests.request')
    def test_job_notification_uses_cloud_template_delivery(self, mock_request, _mock_on_commit):
        job = JobTicket.objects.create(
            job_code='GI-260420-301',
            customer_name='Anand',
            customer_phone='9876543210',
            device_type='Laptop',
            device_brand='Dell',
            device_model='Latitude',
            reported_issue='Battery issue',
        )

        self.settings_obj.is_enabled = True
        self.settings_obj.api_version = 'v23.0'
        self.settings_obj.phone_number_id = '123456789012345'
        self.settings_obj.access_token = 'token-123'
        self.settings_obj.public_site_url = 'https://botgi.example.com'
        self.settings_obj.template_language_code = 'en_US'
        self.settings_obj.notify_on_created = True
        self.settings_obj.created_template_name = 'job_created_update'
        self.settings_obj.created_template = 'Hello {customer_name}, ticket {job_code}. Receipt: {receipt_link}'
        self.settings_obj.save()

        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {'messages': [{'id': 'wamid.HBgM123'}]}
        mock_request.return_value = mock_response

        result = send_job_whatsapp_notification(job, MessageQueue.EVENT_CREATED)

        self.assertTrue(result['ok'])
        queue = MessageQueue.objects.get(job_ticket=job, event_type=MessageQueue.EVENT_CREATED)
        self.assertEqual(queue.status, MessageQueue.STATUS_SENT)
        self.assertEqual(queue.transport, 'whatsapp-cloud-api-template')
        self.assertEqual(queue.bridge_message_id, 'wamid.HBgM123')

        payload = mock_request.call_args.kwargs['json']
        self.assertEqual(payload['template']['name'], 'job_created_update')
        body_component = payload['template']['components'][0]
        button_component = payload['template']['components'][1]
        parameters = body_component['parameters']
        self.assertEqual(parameters[0]['text'], 'Anand')
        self.assertEqual(parameters[1]['text'], job.job_code)
        self.assertIn('/client-receipt/', parameters[2]['text'])
        self.assertEqual(button_component['type'], 'button')
        self.assertEqual(button_component['sub_type'], 'url')
        self.assertEqual(button_component['parameters'][0]['text'], f'{job.job_code}/')


class WhatsAppCloudWebhookTests(TestCase):
    def setUp(self):
        self.settings_obj = WhatsAppIntegrationSettings.get_settings()
        self.settings_obj.webhook_verify_token = 'verify-token'
        self.settings_obj.app_secret = 'app-secret'
        self.settings_obj.save(update_fields=['webhook_verify_token', 'app_secret', 'updated_at'])

        self.queue = MessageQueue.objects.create(
            channel=MessageQueue.CHANNEL_WHATSAPP,
            event_type=MessageQueue.EVENT_MANUAL,
            target_phone='919876543210',
            message='Queued test',
            status=MessageQueue.STATUS_PENDING,
            bridge_message_id='wamid.status.1',
        )

    def _signature(self, body: bytes) -> str:
        digest = hmac.new(b'app-secret', body, hashlib.sha256).hexdigest()
        return f'sha256={digest}'

    def test_webhook_verification_returns_challenge(self):
        response = self.client.get(
            reverse('whatsapp_cloud_webhook_api'),
            {
                'hub.mode': 'subscribe',
                'hub.verify_token': 'verify-token',
                'hub.challenge': 'challenge-123',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'challenge-123')

    def test_webhook_status_update_marks_queue_sent(self):
        payload = {
            'entry': [
                {
                    'changes': [
                        {
                            'value': {
                                'statuses': [
                                    {
                                        'id': 'wamid.status.1',
                                        'status': 'delivered',
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        raw_body = json.dumps(payload).encode('utf-8')

        response = self.client.post(
            reverse('whatsapp_cloud_webhook_api'),
            data=raw_body,
            content_type='application/json',
            HTTP_X_HUB_SIGNATURE_256=self._signature(raw_body),
        )

        self.assertEqual(response.status_code, 200)
        self.queue.refresh_from_db()
        self.assertEqual(self.queue.status, MessageQueue.STATUS_SENT)
        self.assertEqual(self.queue.transport, 'whatsapp-cloud-api-webhook')


class DiscountAwareReportsTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            username='reports-admin',
            password='StrongPass123!',
            is_staff=True,
            is_superuser=True,
        )
        self.technician_user = User.objects.create_user(
            username='tech-report-user',
            password='StrongPass123!',
        )
        self.technician = TechnicianProfile.objects.create(
            user=self.technician_user,
            unique_id='TECH001',
        )
        self.client.force_login(self.staff_user)
        self.report_date = timezone.localdate()
        self.report_timestamp = timezone.make_aware(
            datetime.combine(self.report_date, datetime.min.time())
        ) + timedelta(hours=11)

    def _create_finished_job(self, job_code, part_cost, service_charge, discount_amount):
        job = JobTicket.objects.create(
            job_code=job_code,
            customer_name='Report Customer',
            customer_phone='9876543210',
            device_type='Laptop',
            reported_issue='No power',
            status='Completed',
            assigned_to=self.technician,
            discount_amount=Decimal(discount_amount),
        )
        ServiceLog.objects.create(
            job_ticket=job,
            description='Board repair',
            part_cost=Decimal(part_cost),
            service_charge=Decimal(service_charge),
        )
        JobTicket.objects.filter(pk=job.pk).update(updated_at=self.report_timestamp)
        return JobTicket.objects.get(pk=job.pk)

    def test_reports_chart_data_subtracts_discount_from_income(self):
        self._create_finished_job('GI-260403-901', '120.00', '280.00', '50.00')

        response = self.client.get(
            reverse('reports_chart_data'),
            {
                'start_date': self.report_date.isoformat(),
                'end_date': self.report_date.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['monthly'][0]['discount_total'], 50.0)
        self.assertEqual(payload['monthly'][0]['total_income'], 350.0)
        self.assertEqual(payload['monthly'][0]['net_profit'], 350.0)
        self.assertEqual(payload['yearly'][0]['discount_total'], 50.0)
        self.assertEqual(payload['yearly'][0]['total_income'], 350.0)

    def test_technician_report_print_uses_net_totals(self):
        self._create_finished_job('GI-260403-902', '150.00', '250.00', '40.00')

        request = RequestFactory().get(
            reverse('technician_report_print', args=[self.technician.id]),
            {
                'start_date': self.report_date.isoformat(),
                'end_date': self.report_date.isoformat(),
            },
        )
        request.user = self.staff_user

        captured = {}

        def fake_render(_request, _template_name, context):
            captured['context'] = context
            return HttpResponse('ok')

        with patch('job_tickets.views.report_views.render', side_effect=fake_render):
            response = technician_report_print(request, self.technician.id)

        self.assertEqual(response.status_code, 200)
        context = captured['context']
        self.assertEqual(context['total_discounts'], Decimal('40.00'))
        self.assertEqual(context['total_income'], Decimal('360.00'))
        self.assertEqual(context['jobs'][0].discount_total, Decimal('40.00'))
        self.assertEqual(context['jobs'][0].net_total, Decimal('360.00'))


class InventoryUxDefaultsTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            username='inventory-admin',
            password='StrongPass123!',
            is_staff=True,
            is_superuser=True,
        )

    def test_product_form_prefills_zero_values_for_new_product(self):
        form = ProductForm()

        self.assertEqual(form.fields['cost_price'].initial, Decimal('0.00'))
        self.assertEqual(form.fields['unit_price'].initial, Decimal('0.00'))
        self.assertEqual(form.fields['stock_quantity'].initial, 0)
        self.assertEqual(form.fields['reserved_stock'].initial, 0)

    def test_inventory_party_dashboard_creates_shared_party(self):
        self.client.force_login(self.staff_user)

        response = self.client.post(
            reverse('inventory_party_dashboard'),
            {
                'add_inventory_party_submit': '1',
                'name': 'Walk In Customer',
                'gst_registration_type': 'unregistered',
                'phone': '9876543210',
                'country': 'India',
                'opening_balance': '0.00',
                'is_active': 'on',
            },
        )

        self.assertEqual(response.status_code, 302)
        party = InventoryParty.objects.get(name='Walk In Customer')
        self.assertEqual(party.party_type, 'both')

    def test_inventory_party_dashboard_updates_party_profile(self):
        self.client.force_login(self.staff_user)
        party = InventoryParty.objects.create(
            name='Old Party Name',
            phone='9999999999',
            city='Old City',
        )

        response = self.client.post(
            reverse('inventory_party_dashboard'),
            {
                'edit_inventory_party_submit': '1',
                'edit_party_id': str(party.id),
                'edit-name': 'Updated Party Name',
                'edit-legal_name': 'Updated Legal Name',
                'edit-contact_person': 'Anas',
                'edit-gst_registration_type': 'unregistered',
                'edit-phone': '8888888888',
                'edit-gstin': '',
                'edit-state_code': '',
                'edit-default_place_of_supply_state': '',
                'edit-pan': '',
                'edit-email': 'party@example.com',
                'edit-address': 'Main Road',
                'edit-shipping_address': 'Warehouse Road',
                'edit-city': 'Kochi',
                'edit-state': 'Kerala',
                'edit-country': 'India',
                'edit-pincode': '682001',
                'edit-opening_balance': '1250.00',
                'edit-is_active': 'on',
            },
        )

        self.assertEqual(response.status_code, 302)
        party.refresh_from_db()
        self.assertEqual(party.name, 'Updated Party Name')
        self.assertEqual(party.legal_name, 'Updated Legal Name')
        self.assertEqual(party.contact_person, 'Anas')
        self.assertEqual(party.phone, '8888888888')
        self.assertEqual(party.email, 'party@example.com')
        self.assertEqual(party.address, 'Main Road')
        self.assertEqual(party.shipping_address, 'Warehouse Road')
        self.assertEqual(party.city, 'Kochi')
        self.assertEqual(party.state, 'Kerala')
        self.assertEqual(party.country, 'India')
        self.assertEqual(party.pincode, '682001')
        self.assertEqual(party.opening_balance, Decimal('1250.00'))
        self.assertEqual(party.party_type, 'both')

    def test_inventory_party_dashboard_shows_single_party_directory_section(self):
        self.client.force_login(self.staff_user)
        InventoryParty.objects.create(name='Hardware Supplier', party_type='supplier')
        InventoryParty.objects.create(name='Retail Customer', party_type='customer')

        captured = {}

        def fake_render(_request, template_name, context):
            captured['template_name'] = template_name
            captured['context'] = context
            return HttpResponse('ok')

        with patch('job_tickets.views.inventory_views.render', side_effect=fake_render):
            response = self.client.get(reverse('inventory_party_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured['template_name'], 'job_tickets/inventory_party_dashboard.html')
        self.assertEqual(
            [party.name for party in captured['context']['parties']],
            ['Hardware Supplier', 'Retail Customer'],
        )
        template_path = Path(settings.BASE_DIR) / 'job_tickets' / 'templates' / 'job_tickets' / 'inventory_party_dashboard.html'
        template_text = template_path.read_text(encoding='utf-8')
        self.assertIn('Party Directory', template_text)
        self.assertNotIn('Combined Party Directory', template_text)
        self.assertNotIn('Supplier Side', template_text)
        self.assertNotIn('Customer Side', template_text)
        self.assertNotIn('partyMasterTabs', template_text)

    def test_inventory_entry_form_uses_shared_party_queryset_for_purchase_and_sale(self):
        shared_party = InventoryParty.objects.create(name='Shared Ledger Party')

        purchase_form = InventoryEntryForm(entry_type='purchase')
        sale_form = InventoryEntryForm(entry_type='sale')

        self.assertEqual(purchase_form.fields['party'].label, 'Party')
        self.assertEqual(sale_form.fields['party'].label, 'Party')
        self.assertIn(shared_party, purchase_form.fields['party'].queryset)
        self.assertIn(shared_party, sale_form.fields['party'].queryset)

    def test_inventory_sales_dashboard_shows_quick_add_product_controls(self):
        self.client.force_login(self.staff_user)

        captured = {}

        def fake_render(_request, template_name, context):
            captured['template_name'] = template_name
            captured['context'] = context
            return HttpResponse('ok')

        with patch('job_tickets.views.helpers.render', side_effect=fake_render):
            response = self.client.get(reverse('inventory_sales_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured['template_name'], 'job_tickets/inventory_entry_dashboard.html')
        self.assertEqual(captured['context']['entry_type'], 'sale')
        template_path = Path(settings.BASE_DIR) / 'job_tickets' / 'templates' / 'job_tickets' / 'inventory_entry_dashboard.html'
        template_text = template_path.read_text(encoding='utf-8')
        self.assertIn('toggle-quick-product-btn', template_text)
        self.assertIn("entry_type == 'purchase' or entry_type == 'sale'", template_text)

    def test_inventory_entry_dashboard_wires_line_product_typeahead(self):
        template_path = Path(settings.BASE_DIR) / 'job_tickets' / 'templates' / 'job_tickets' / 'inventory_entry_dashboard.html'
        template_text = template_path.read_text(encoding='utf-8')

        self.assertIn('inventory-line-product-picker', template_text)
        self.assertIn('inventory-line-product-options', template_text)
        self.assertIn("replace(/\\s+/g, ' ').trim()", template_text)
        self.assertIn("pickerInput.setAttribute('list', listId);", template_text)
        self.assertIn('initializeLineProductPicker(row);', template_text)
        self.assertIn('refreshLineProductPickers();', template_text)


class InventorySaleStockRulesTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            username='inventory-sale-admin',
            password='StrongPass123!',
            is_staff=True,
            is_superuser=True,
        )
        self.customer = InventoryParty.objects.create(
            name='Counter Customer',
        )
        self.product = Product.objects.create(
            name='USB Keyboard',
            category='Peripherals',
            unit_price=Decimal('850.00'),
            cost_price=Decimal('500.00'),
            stock_quantity=0,
        )

    def test_inventory_sale_can_reduce_stock_below_zero(self):
        self.client.force_login(self.staff_user)

        response = self.client.post(
            reverse('inventory_sales_dashboard'),
            {
                'inventory_entry_submit': 'sale',
                'entry_date': timezone.localdate().isoformat(),
                'party': str(self.customer.id),
                'bill_discount_amount': '0.00',
                'bill_notes': '',
                'line_product_id[]': [str(self.product.id)],
                'line_quantity[]': ['2'],
                'line_unit_price[]': ['850.00'],
                'line_gst_rate[]': ['18.00'],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, -2)

        entry = InventoryEntry.objects.get(entry_type='sale', product=self.product)
        self.assertEqual(entry.stock_before, 0)
        self.assertEqual(entry.stock_after, -2)


class StaffBillingZeroStockProductTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            username='staff-billing-admin',
            password='StrongPass123!',
            is_staff=True,
            is_superuser=True,
        )
        self.job = JobTicket.objects.create(
            job_code='GI-260413-001',
            customer_name='Walk In Customer',
            customer_phone='9876543210',
            device_type='Laptop',
            device_brand='Dell',
            device_model='Vostro',
            reported_issue='Keyboard issue',
            status='Completed',
        )
        self.product = Product.objects.create(
            name='Laptop Keyboard',
            category='Peripherals',
            unit_price=Decimal('1200.00'),
            cost_price=Decimal('800.00'),
            stock_quantity=0,
        )

    def test_staff_billing_page_lists_zero_stock_products_for_sale(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse('job_billing_staff', args=[self.job.job_code]))

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.product, list(response.context['products_for_sale']))
        self.assertContains(response, 'Laptop Keyboard (Stock: 0)')

    def test_staff_billing_can_sell_zero_stock_product_and_track_negative_stock(self):
        self.client.force_login(self.staff_user)

        response = self.client.post(
            reverse('job_billing_staff', args=[self.job.job_code]),
            {
                'update_amounts_submit': '1',
                'job_sales_invoice_number': '',
                'discount_amount': '0.00',
                'product_id[]': [str(self.product.id)],
                'product_qty[]': ['2'],
                'product_service_charge[]': ['150.00'],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('job_billing_staff', args=[self.job.job_code]))

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, -2)

        sale = ProductSale.objects.get(job_ticket=self.job, product=self.product)
        self.assertEqual(sale.quantity, 2)

        entry = InventoryEntry.objects.get(entry_type='sale', job_ticket=self.job, product=self.product)
        self.assertEqual(entry.stock_before, 0)
        self.assertEqual(entry.stock_after, -2)

class InventoryApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='inventory-api-admin',
            password='StrongPass123!',
            is_staff=True,
            is_superuser=True,
        )
        self.token = issue_mobile_jwt(self.user)

    def test_mobile_inventory_summary_returns_metrics(self):
        supplier = InventoryParty.objects.create(
            name='API Supplier',
            party_type='supplier',
        )
        product = Product.objects.create(
            name='Router Board',
            category='Networking',
            unit_price=Decimal('1500.00'),
            cost_price=Decimal('900.00'),
            stock_quantity=4,
            reserved_stock=5,
        )
        bill = InventoryBill.objects.create(
            bill_number='PB-260403-001',
            entry_type='purchase',
            entry_date=timezone.localdate(),
            party=supplier,
        )
        InventoryEntry.objects.create(
            bill=bill,
            entry_number='PE-260403-001',
            entry_type='purchase',
            entry_date=timezone.localdate(),
            party=supplier,
            product=product,
            quantity=4,
            unit_price=Decimal('900.00'),
            taxable_amount=Decimal('3600.00'),
            total_amount=Decimal('3600.00'),
            stock_before=0,
            stock_after=4,
        )

        response = self.client.get(
            reverse('mobile_api_inventory_summary'),
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['summary']['party_count'], 1)
        self.assertEqual(payload['summary']['product_count'], 1)
        self.assertEqual(payload['summary']['reserved_alert_count'], 1)
        self.assertEqual(payload['summary']['monthly_purchase_total'], '3600.00')
        self.assertEqual(payload['reserved_stock_products'][0]['name'], 'Router Board')

    def test_mobile_inventory_parties_create_and_list(self):
        create_response = self.client.post(
            reverse('mobile_api_inventory_parties'),
            data='{"name":"API Customer","phone":"9876543210","opening_balance":"0.00"}',
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(create_response.status_code, 200)
        created_payload = create_response.json()
        self.assertTrue(created_payload['ok'])
        self.assertEqual(created_payload['party']['party_type'], 'both')

        list_response = self.client.get(
            reverse('mobile_api_inventory_parties'),
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(list_response.status_code, 200)
        payload = list_response.json()
        self.assertEqual(payload['summary']['total_parties'], 1)
        self.assertEqual(payload['parties'][0]['name'], 'API Customer')

    def test_mobile_inventory_party_update_normalizes_tax_identity_fields(self):
        party = InventoryParty.objects.create(
            name='Original Supplier',
            party_type='supplier',
            phone='9999999999',
        )

        response = self.client.post(
            reverse('mobile_api_inventory_party_update', kwargs={'party_id': party.id}),
            data='{"name":"Updated Supplier","phone":"8888888888","pan":"abcde1234f","gstin":"32abcde1234f1z5","shipping_address":"Warehouse lane","pincode":"682001","opening_balance":"1250.00"}',
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['party']['name'], 'Updated Supplier')
        self.assertEqual(payload['party']['pan'], 'ABCDE1234F')
        self.assertEqual(payload['party']['gstin'], '32ABCDE1234F1Z5')
        self.assertEqual(payload['party']['shipping_address'], 'Warehouse lane')
        self.assertEqual(payload['party']['pincode'], '682001')
        self.assertEqual(payload['party']['opening_balance'], '1250.00')
        self.assertEqual(payload['party']['party_type'], 'both')

    def test_mobile_products_list_includes_tax_metadata_and_history(self):
        supplier = InventoryParty.objects.create(
            name='History Supplier',
            party_type='supplier',
        )
        product = Product.objects.create(
            name='Thermal Printer Head',
            sku='TPH-01',
            category='Printer Parts',
            brand='Epson',
            item_type='goods',
            hsn_sac_code='8471',
            uqc='NOS',
            tax_category='taxable',
            gst_rate=Decimal('18.00'),
            cess_rate=Decimal('0.00'),
            cost_price=Decimal('1200.00'),
            unit_price=Decimal('1650.00'),
            stock_quantity=2,
            reserved_stock=1,
            description='Dot matrix printer replacement head',
        )
        bill = InventoryBill.objects.create(
            bill_number='PB-260403-010',
            entry_type='purchase',
            entry_date=timezone.localdate(),
            party=supplier,
            invoice_number='SUP-7788',
        )
        InventoryEntry.objects.create(
            bill=bill,
            entry_number='PUR-260403-010',
            entry_type='purchase',
            entry_date=timezone.localdate(),
            invoice_number='SUP-7788',
            party=supplier,
            product=product,
            quantity=2,
            unit_price=Decimal('1200.00'),
            gst_rate=Decimal('18.00'),
            taxable_amount=Decimal('2400.00'),
            gst_amount=Decimal('432.00'),
            total_amount=Decimal('2832.00'),
            stock_before=0,
            stock_after=2,
        )

        response = self.client.get(
            reverse('mobile_api_products'),
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['summary']['total_products'], 1)
        self.assertEqual(payload['products'][0]['hsn_sac_code'], '8471')
        self.assertEqual(payload['products'][0]['latest_purchase_party'], 'History Supplier')
        self.assertEqual(payload['products'][0]['combined_history'][0]['entry_type'], 'purchase')

    def test_mobile_inventory_register_returns_grouped_purchase_rows(self):
        supplier = InventoryParty.objects.create(
            name='Register Supplier',
            party_type='supplier',
        )
        product = Product.objects.create(
            name='SSD 512GB',
            category='Storage',
            unit_price=Decimal('4200.00'),
            cost_price=Decimal('3200.00'),
            stock_quantity=3,
        )
        bill = InventoryBill.objects.create(
            bill_number='PB-260403-020',
            entry_type='purchase',
            entry_date=timezone.localdate(),
            party=supplier,
            invoice_number='PUR-INV-20',
        )
        InventoryEntry.objects.create(
            bill=bill,
            entry_number='PUR-260403-020',
            entry_type='purchase',
            entry_date=timezone.localdate(),
            invoice_number='PUR-INV-20',
            party=supplier,
            product=product,
            quantity=3,
            unit_price=Decimal('3200.00'),
            gst_rate=Decimal('18.00'),
            taxable_amount=Decimal('9600.00'),
            gst_amount=Decimal('1728.00'),
            total_amount=Decimal('11328.00'),
            stock_before=0,
            stock_after=3,
            created_by=self.user,
        )

        response = self.client.get(
            reverse('mobile_api_inventory_register', kwargs={'entry_type': 'purchase'}),
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['config']['title'], 'Purchase')
        self.assertEqual(payload['summary']['entry_count'], 1)
        self.assertEqual(payload['register_rows'][0]['party_name'], 'Register Supplier')
        self.assertTrue(payload['register_rows'][0]['show_return_action'])
