import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from job_tickets.models import (
    AccountTransaction,
    CompanyProfile,
    CompanyUserMembership,
    CompanyWorkspace,
    FinancialAccount,
    JobTicket,
    WhatsAppIntegrationSettings,
    WhatsAppNotificationLog,
)
from job_tickets.whatsapp_service import (
    generate_daily_report_context,
    render_daily_report_message,
    send_daily_whatsapp_report,
)


class WhatsAppDailyReportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="shop_owner",
            password="password123",
            is_staff=True,
        )
        self.workspace = CompanyWorkspace.objects.create(
            name="Test Mobile Center",
            slug="test-mobile-center",
            owner=self.user,
            status=CompanyWorkspace.STATUS_ACTIVE,
        )
        CompanyUserMembership.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=CompanyUserMembership.ROLE_OWNER,
            is_active=True,
        )
        self.profile = CompanyProfile.objects.filter(workspace=self.workspace).first()
        if not self.profile:
            self.profile = CompanyProfile.objects.first()
        if self.profile:
            self.profile.workspace = self.workspace
            self.profile.company_name = "Test Mobile Center"
            self.profile.phone1 = "9876543210"
            self.profile.save()
        else:
            self.profile = CompanyProfile.objects.create(
                workspace=self.workspace,
                company_name="Test Mobile Center",
                phone1="9876543210",
            )
        self.cash_acc = FinancialAccount.objects.create(
            workspace=self.workspace,
            name="Cash Drawer",
            account_type=FinancialAccount.ACCOUNT_TYPE_CASH,
            is_default_cash=True,
            current_balance=Decimal('5000.00'),
        )
        self.bank_acc = FinancialAccount.objects.create(
            workspace=self.workspace,
            name="Main Bank",
            account_type=FinancialAccount.ACCOUNT_TYPE_BANK,
            is_default_bank=True,
            current_balance=Decimal('20000.00'),
        )

        self.wa_settings = WhatsAppIntegrationSettings.get_settings(workspace=self.workspace)
        self.wa_settings.is_enabled = True
        self.wa_settings.delivery_method = WhatsAppIntegrationSettings.DELIVERY_BRIDGE
        self.wa_settings.notify_daily_report = True
        self.wa_settings.daily_report_phone = "9876543210"
        self.wa_settings.daily_report_time = datetime.time(20, 0)
        self.wa_settings.save()

    def test_generate_daily_report_context_and_render(self):
        today = timezone.localdate()

        # Create a sample ticket today
        JobTicket.objects.create(
            workspace=self.workspace,
            job_code="GI-261001-001",
            customer_name="Test Customer",
            customer_phone="9876543210",
            device_type="Smartphone",
            status="In Progress",
            created_by=self.user,
        )

        # Record a cash payment today
        AccountTransaction.objects.create(
            account=self.cash_acc,
            transaction_type=AccountTransaction.TYPE_INFLOW,
            amount=Decimal('1500.00'),
            transaction_date=today,
            balance_after=Decimal('6500.00'),
            created_by=self.user,
        )

        ctx = generate_daily_report_context(target_date=today, workspace=self.workspace)
        self.assertEqual(ctx['company_name'], "Test Mobile Center")
        self.assertEqual(ctx['tickets_created_count'], 1)
        self.assertEqual(ctx['cash_inflows'], "1500.00")

        msg, _ = render_daily_report_message(target_date=today, workspace=self.workspace)
        self.assertIn("DAILY BUSINESS SUMMARY - Test Mobile Center", msg)
        self.assertIn("New Jobs Received: 1", msg)
        self.assertIn("Cash Receipts: ₹1500.00", msg)

    @patch('job_tickets.whatsapp_service.send_bridge_text_message')
    def test_send_daily_whatsapp_report_success(self, mock_bridge):
        mock_bridge.return_value = {
            'ok': True,
            'status': 200,
            'message_id': 'bridge-msg-12345',
            'data': {'status': 'sent'},
        }

        today = timezone.localdate()
        result = send_daily_whatsapp_report(
            target_date=today,
            target_phone="9876543210",
            workspace=self.workspace,
            is_automatic=True,
        )

        self.assertTrue(result['ok'])
        self.assertEqual(result['sent_count'], 1)
        mock_bridge.assert_called_once()

        # Check notification log was created with job_ticket=None
        log = WhatsAppNotificationLog.objects.filter(event_type='daily_report').first()
        self.assertIsNotNone(log)
        self.assertIsNone(log.job_ticket)
        self.assertTrue(log.was_successful)

        # Check last sent date updated
        self.wa_settings.refresh_from_db()
        self.assertEqual(self.wa_settings.daily_report_last_sent_date, today)

    def test_send_daily_whatsapp_report_disabled(self):
        self.wa_settings.is_enabled = False
        self.wa_settings.save()

        result = send_daily_whatsapp_report(workspace=self.workspace)
        self.assertFalse(result['ok'])
        self.assertIn("disabled", result['error'].lower())

    @patch('job_tickets.whatsapp_service.send_bridge_text_message')
    def test_whatsapp_daily_report_send_api(self, mock_bridge):
        mock_bridge.return_value = {'ok': True, 'status': 200, 'data': {}}
        self.client.force_login(self.user)

        # Provide workspace in session
        session = self.client.session
        session['active_workspace_id'] = self.workspace.id
        session.save()

        response = self.client.post(
            reverse('whatsapp_daily_report_send_api'),
            data={'phone': '9876543210', 'date': str(timezone.localdate())},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['sent_count'], 1)

    def test_whatsapp_daily_report_preview_api(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['active_workspace_id'] = self.workspace.id
        session.save()

        response = self.client.get(reverse('whatsapp_daily_report_preview_api'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertIn('DAILY BUSINESS SUMMARY', data['message'])

    @patch('job_tickets.whatsapp_service.send_bridge_text_message')
    def test_management_command_execution(self, mock_bridge):
        mock_bridge.return_value = {'ok': True, 'status': 200, 'data': {}}

        # Force command run
        call_command('send_daily_whatsapp_report', '--force')
        mock_bridge.assert_called()

        self.wa_settings.refresh_from_db()
        self.assertEqual(self.wa_settings.daily_report_last_sent_date, timezone.localdate())
