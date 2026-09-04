from django.db import migrations


DEFAULT_PRESETS = {
    'device_type': [
        'Laptop',
        'Desktop',
        'Printer',
        'Mobile',
        'Tablet',
        'CCTV DVR',
    ],
    'device_brand': [
        'HP',
        'Dell',
        'Lenovo',
        'ASUS',
        'Acer',
        'Canon',
        'Epson',
    ],
    'reported_issue': [
        'Not powering on',
        'Slow performance',
        'Display issue',
        'No boot / OS issue',
        'Overheating',
        'Keyboard not working',
    ],
    'additional_items': [
        'Charger',
        'Power cable',
        'Bag',
        'Battery',
        'Mouse',
        'Adapter',
    ],
}


def seed_defaults(apps, schema_editor):
    JobFieldPreset = apps.get_model('job_tickets', 'JobFieldPreset')
    rows = []
    for field_name, values in DEFAULT_PRESETS.items():
        for index, value in enumerate(values, start=1):
            rows.append(
                JobFieldPreset(
                    field_name=field_name,
                    value=value,
                    sort_order=index,
                    is_active=True,
                )
            )
    JobFieldPreset.objects.bulk_create(rows, ignore_conflicts=True)


def rollback_defaults(apps, schema_editor):
    JobFieldPreset = apps.get_model('job_tickets', 'JobFieldPreset')
    for field_name, values in DEFAULT_PRESETS.items():
        JobFieldPreset.objects.filter(field_name=field_name, value__in=values).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('job_tickets', '0035_jobfieldpreset'),
    ]

    operations = [
        migrations.RunPython(seed_defaults, rollback_defaults),
    ]

