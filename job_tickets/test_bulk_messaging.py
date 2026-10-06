import json
from decimal import Decimal
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from job_tickets.bulk_messaging_service import (
    build_client_context,
    create_bulk_campaign_and_queue,
    generate_clients_csv,
    generate_clients_vcf,
    render_bulk_message,
    resolve_spintax,
)
from job_tickets.models import BulkCampaign, Client, CompanyWorkspace, JobTicket, MessageQueue


class BulkMessagingServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="testowner", password="password123", email="admin@example.com")
        self.workspace = CompanyWorkspace.objects.create(name="Test Service Hub", owner=self.user)
        self.client1 = Client.objects.create(
            workspace=self.workspace,
            name="John Doe",
            phone="9876543210",
            company_name="Acme Corp",
            notes="VIP Client",
        )
        self.client2 = Client.objects.create(
            workspace=self.workspace,
            name="Sarah Smith",
            phone="9123456789",
            company_name="",
        )

    def test_spintax_resolution(self):
        text = "{Hello|Hi|Greetings} friend!"
        results = set()
        for _ in range(30):
            res = resolve_spintax(text)
            self.assertTrue(res.endswith("friend!"))
            results.add(res)
        self.assertGreater(len(results), 1)

    def test_render_bulk_message_with_tags_and_spintax(self):
        template = "{Hello|Hi} {{name}}, your balance is Rs {{balance}} for {{device}}."
        ctx = {
            'name': 'John',
            'balance': '450.00',
            'device': 'Dell Laptop',
        }
        rendered = render_bulk_message(template, ctx)
        self.assertIn("John", rendered)
        self.assertIn("Rs 450.00", rendered)
        self.assertIn("Dell Laptop", rendered)
        self.assertTrue(rendered.startswith("Hello") or rendered.startswith("Hi"))

    def test_vcf_generation(self):
        qs = Client.objects.filter(workspace=self.workspace)
        vcf = generate_clients_vcf(qs)
        self.assertIn("BEGIN:VCARD", vcf)
        self.assertIn("VERSION:3.0", vcf)
        self.assertIn("FN:BotGI - John Doe", vcf)
        self.assertIn("TEL;TYPE=CELL:+919876543210", vcf)
        self.assertIn("ORG:Acme Corp", vcf)
        self.assertIn("NOTE:VIP Client", vcf)
        self.assertIn("FN:BotGI - Sarah Smith", vcf)
        self.assertIn("TEL;TYPE=CELL:+919123456789", vcf)
        self.assertIn("END:VCARD", vcf)

    def test_csv_generation(self):
        data = [
            {
                'id': self.client1.id,
                'name': self.client1.name,
                'phone': self.client1.phone,
                'email': '',
                'company_name': self.client1.company_name,
                'total_jobs': 2,
                'total_billed': Decimal('1500.00'),
                'amount_paid': Decimal('1000.00'),
                'balance_due': Decimal('500.00'),
                'created_at': '2026-10-06',
            }
        ]
        csv_text = generate_clients_csv(data)
        self.assertIn("John Doe", csv_text)
        self.assertIn("9876543210", csv_text)
        self.assertIn("500.00", csv_text)

    def test_campaign_creation_and_queue(self):
        campaign = create_bulk_campaign_and_queue(
            workspace=self.workspace,
            user=self.user,
            title="October Festival Offer",
            target_filter="all",
            template_text="{Hello|Dear} {{name}}, visit us for 20% off on laptop cleaning!",
            recipient_clients=[self.client1, self.client2],
        )
        self.assertEqual(campaign.total_recipients, 2)
        self.assertEqual(campaign.status, BulkCampaign.STATUS_PENDING)

        queued_items = MessageQueue.objects.filter(bulk_campaign=campaign)
        self.assertEqual(queued_items.count(), 2)
        for item in queued_items:
            self.assertEqual(item.event_type, MessageQueue.EVENT_BULK)
            self.assertEqual(item.status, MessageQueue.STATUS_PENDING)
            self.assertTrue(item.message)

    def test_sync_historical_contacts_view(self):
        # Create a JobTicket for a customer who is NOT in Client table yet
        JobTicket.objects.create(
            workspace=self.workspace,
            job_code="GI-TEST-001",
            customer_name="Alice Brown",
            customer_phone="9988776655",
            device_type="MacBook Pro",
            status="Completed",
        )
        self.client.force_login(self.user)
        resp = self.client.post(reverse('sync_historical_contacts'), follow=True)
        self.assertEqual(resp.status_code, 200)

        synced = Client.objects.filter(workspace=self.workspace, phone="9988776655").first()
        self.assertIsNotNone(synced)
        self.assertEqual(synced.name, "Alice Brown")

    def test_export_clients_vcf_view(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('export_clients_vcf'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/vcard; charset=utf-8')
        body = resp.content.decode('utf-8')
        self.assertIn("BEGIN:VCARD", body)
        self.assertIn("FN:BotGI - John Doe", body)

    def test_export_clients_csv_view(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('export_clients_csv'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv; charset=utf-8')
        body = resp.content.decode('utf-8')
        self.assertIn("John Doe", body)

    def test_preview_bulk_campaign_view(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse('preview_bulk_campaign'),
            data=json.dumps({'template': '{Hello|Hi} {{name}}', 'target_filter': 'all'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertGreaterEqual(data['recipient_count'], 2)
        self.assertTrue(data['sample_preview'])

    def test_create_bulk_campaign_view(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse('create_bulk_campaign'),
            data=json.dumps({
                'title': 'Test Announcement',
                'template': '{Hi|Hello} {{name}}, your balance is Rs {{balance}}.',
                'target_filter': 'all',
            }),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        campaign_id = data['campaign_id']

        campaign = BulkCampaign.objects.get(pk=campaign_id)
        self.assertEqual(campaign.title, 'Test Announcement')
        self.assertEqual(campaign.total_recipients, 2)

    def test_bulk_campaign_status_api(self):
        campaign = BulkCampaign.objects.create(
            workspace=self.workspace,
            title="Status Test",
            target_filter="all",
            message_template="Hello",
            total_recipients=5,
            sent_count=3,
            failed_count=0,
            status=BulkCampaign.STATUS_IN_PROGRESS,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse('bulk_campaign_status_api', args=[campaign.id]))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['sent'], 3)
        self.assertEqual(data['percent'], 60)
