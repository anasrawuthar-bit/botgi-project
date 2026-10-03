from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from job_tickets.models import JobTicket, ServiceLog, ProductSale, Product, InventoryEntry, InventoryBill

User = get_user_model()

class BillingSeparatedCardsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='stafftest',
            email='staff@test.com',
            password='password123',
            is_staff=True
        )
        self.client.login(username='stafftest', password='password123')

        self.job = JobTicket.objects.create(
            job_code='GI-260930-001',
            customer_name='John Doe',
            customer_phone='9876543210',
            device_type='Laptop',
            device_brand='Dell',
            device_model='Inspiron 15',
            reported_issue='Broken Display & Slow Performance',
            status='In Progress',
            created_by=self.user
        )

        # Create an existing service log
        self.service = ServiceLog.objects.create(
            job_ticket=self.job,
            description='Screen Replacement Labor',
            part_cost=Decimal('0.00'),
            service_charge=Decimal('1500.00')
        )

        # Create an inventory product with cost_price and unit_price
        self.product = Product.objects.create(
            name='15.6 Inch FHD IPS Display',
            sku='SCR-156-FHD',
            stock_quantity=10,
            cost_price=Decimal('2800.00'),
            unit_price=Decimal('4500.00')
        )

    def test_billing_get_separates_services_and_products(self):
        url = reverse('job_billing_staff', kwargs={'job_code': self.job.job_code})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Context has separated lists
        self.assertIn('pure_service_logs', response.context)
        self.assertIn('existing_product_sales', response.context)
        self.assertIn('products_for_sale', response.context)

        self.assertEqual(len(response.context['pure_service_logs']), 1)
        self.assertEqual(len(response.context['existing_product_sales']), 0)
        self.assertContains(response, 'Repair Services &amp; Labor')
        self.assertContains(response, 'Spare Parts &amp; Inventory Products')
        self.assertContains(response, 'Purchase Price')

    def test_add_product_to_bill_with_custom_selling_price(self):
        url = reverse('job_billing_staff', kwargs={'job_code': self.job.job_code})
        post_data = {
            'update_amounts_submit': '1',
            f'description_{self.service.id}': 'Screen Replacement Labor',
            f'part_cost_{self.service.id}': '0.00',
            f'service_charge_{self.service.id}': '1500.00',
            'product_id[]': [str(self.product.id)],
            'product_qty[]': ['1'],
            'product_unit_price[]': ['4800.00'], # Custom selling price above base 4500
            'discount_amount': '300.00',
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)

        # Verify product stock deducted
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 9)

        # Verify ProductSale created with accurate cost and profit
        sale = ProductSale.objects.filter(job_ticket=self.job).first()
        self.assertIsNotNone(sale)
        self.assertEqual(sale.product, self.product)
        self.assertEqual(sale.quantity, 1)
        self.assertEqual(sale.cost_price, Decimal('2800.00'))
        self.assertEqual(sale.unit_price, Decimal('4800.00'))
        self.assertEqual(sale.line_total, Decimal('4800.00'))
        self.assertEqual(sale.line_profit, Decimal('2000.00')) # 4800 - 2800

        # Verify job amounts:
        # total_cost = 1500 (service) + 4800 (product) - 300 (discount) = 6000
        self.job.refresh_from_db()
        self.assertEqual(self.job.discount_amount, Decimal('300.00'))
        self.assertEqual(self.job.total_cost, Decimal('6000.00'))

    def test_update_existing_product_sale_unit_price(self):
        # First add product sale
        url = reverse('job_billing_staff', kwargs={'job_code': self.job.job_code})
        self.client.post(url, {
            'update_amounts_submit': '1',
            f'description_{self.service.id}': self.service.description,
            f'part_cost_{self.service.id}': '0.00',
            f'service_charge_{self.service.id}': '1500.00',
            'product_id[]': [str(self.product.id)],
            'product_qty[]': ['1'],
            'product_unit_price[]': ['4500.00'],
        })

        sale = ProductSale.objects.get(job_ticket=self.job)
        log_id = sale.service_log_id

        # Update existing product unit price to 4200
        response = self.client.post(url, {
            'update_amounts_submit': '1',
            f'description_{self.service.id}': self.service.description,
            f'part_cost_{self.service.id}': '0.00',
            f'service_charge_{self.service.id}': '1500.00',
            f'product_unit_price_{log_id}': '4200.00',
        })
        self.assertEqual(response.status_code, 302)

        sale.refresh_from_db()
        self.assertEqual(sale.unit_price, Decimal('4200.00'))
        self.assertEqual(sale.line_total, Decimal('4200.00'))
        self.assertEqual(sale.line_profit, Decimal('1400.00')) # 4200 - 2800

    def test_delete_product_sale_restocks_inventory(self):
        # Add product sale
        url = reverse('job_billing_staff', kwargs={'job_code': self.job.job_code})
        self.client.post(url, {
            'update_amounts_submit': '1',
            f'description_{self.service.id}': self.service.description,
            f'part_cost_{self.service.id}': '0.00',
            f'service_charge_{self.service.id}': '1500.00',
            'product_id[]': [str(self.product.id)],
            'product_qty[]': ['2'],
            'product_unit_price[]': ['4500.00'],
        })
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 8) # 10 - 2

        sale = ProductSale.objects.get(job_ticket=self.job)
        log_id = sale.service_log_id

        # Now delete product sale
        self.client.post(url, {
            'update_amounts_submit': '1',
            f'description_{self.service.id}': self.service.description,
            f'part_cost_{self.service.id}': '0.00',
            f'service_charge_{self.service.id}': '1500.00',
            'delete_service_ids[]': [str(log_id)],
        })

        # Product must be restocked
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)
        self.assertFalse(ProductSale.objects.filter(id=sale.id).exists())
