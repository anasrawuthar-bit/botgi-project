from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import ClientForm
from .models import Client, JobTicket, UserSessionActivity
from .phone_utils import normalize_indian_phone
from .views import client_login, get_phone_service_snapshot


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
