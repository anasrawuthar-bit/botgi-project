from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


ENTRY_TYPE_CHOICES = [
    ('purchase', 'Purchase'),
    ('purchase_return', 'Purchase Return'),
    ('sale', 'Sales'),
    ('sale_return', 'Sales Return'),
]


PREFIX_MAP = {
    'purchase': 'PB',
    'purchase_return': 'PRB',
    'sale': 'SB',
    'sale_return': 'SRB',
}


def _build_group_key(entry):
    invoice_number = (entry.invoice_number or '').strip()
    if invoice_number:
        return (
            entry.entry_type,
            entry.party_id,
            entry.job_ticket_id,
            invoice_number.lower(),
        )
    return (
        entry.entry_type,
        entry.party_id,
        entry.job_ticket_id,
        f'entry-{entry.pk}',
    )


def _generate_bill_number(entry_type, entry_date, counters, used_numbers):
    prefix = PREFIX_MAP.get(entry_type, 'IB')
    date_part = entry_date.strftime('%Y%m%d')
    counter_key = (entry_type, entry_date.isoformat())
    sequence = counters.get(counter_key, 1)
    bill_number = f'{prefix}-{date_part}-{sequence:03d}'
    while bill_number in used_numbers:
        sequence += 1
        bill_number = f'{prefix}-{date_part}-{sequence:03d}'
    counters[counter_key] = sequence + 1
    used_numbers.add(bill_number)
    return bill_number


def backfill_inventory_bills(apps, schema_editor):
    InventoryBill = apps.get_model('job_tickets', 'InventoryBill')
    InventoryEntry = apps.get_model('job_tickets', 'InventoryEntry')

    created_bills = {}
    counters = {}
    used_numbers = set()

    for entry in InventoryEntry.objects.order_by('entry_date', 'id'):
        bill_key = _build_group_key(entry)
        bill = created_bills.get(bill_key)
        if bill is None:
            bill = InventoryBill.objects.create(
                bill_number=_generate_bill_number(entry.entry_type, entry.entry_date, counters, used_numbers),
                entry_type=entry.entry_type,
                entry_date=entry.entry_date,
                invoice_number=(entry.invoice_number or '').strip() or None,
                job_ticket_id=entry.job_ticket_id,
                party_id=entry.party_id,
                notes=(entry.notes or '').strip(),
                created_by_id=entry.created_by_id,
            )
            created_bills[bill_key] = bill

        entry.bill_id = bill.id
        entry.save(update_fields=['bill'])


class Migration(migrations.Migration):

    dependencies = [
        ('job_tickets', '0043_seed_device_checklist_templates'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='InventoryBill',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('bill_number', models.CharField(max_length=40, unique=True)),
                ('entry_type', models.CharField(choices=ENTRY_TYPE_CHOICES, max_length=20)),
                ('entry_date', models.DateField(default=django.utils.timezone.localdate)),
                ('invoice_number', models.CharField(blank=True, help_text='Supplier/customer invoice number for reference.', max_length=50, null=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inventory_bills', to=settings.AUTH_USER_MODEL)),
                ('job_ticket', models.ForeignKey(blank=True, help_text='Linked job ticket when this bill is generated from service billing.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inventory_bills', to='job_tickets.jobticket')),
                ('party', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='inventory_bills', to='job_tickets.inventoryparty')),
            ],
            options={
                'ordering': ['-entry_date', '-id'],
            },
        ),
        migrations.AddField(
            model_name='inventoryentry',
            name='bill',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='job_tickets.inventorybill'),
        ),
        migrations.RunPython(backfill_inventory_bills, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='inventoryentry',
            name='bill',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='job_tickets.inventorybill'),
        ),
    ]
