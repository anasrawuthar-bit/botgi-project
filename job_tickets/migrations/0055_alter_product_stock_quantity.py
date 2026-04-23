from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('job_tickets', '0054_jobticket_requires_laptop_inspection_checklist'),
    ]

    operations = [
        migrations.AlterField(
            model_name='product',
            name='stock_quantity',
            field=models.IntegerField(default=0),
        ),
    ]
