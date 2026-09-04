from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('job_tickets', '0072_companyprofile_print_paper_sizes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='jobticket',
            name='customer_phone',
            field=models.CharField(max_length=50),
        ),
    ]
