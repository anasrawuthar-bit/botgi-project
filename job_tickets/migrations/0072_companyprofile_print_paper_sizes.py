from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('job_tickets', '0071_alter_jobfieldpreset_unique_together_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='companyprofile',
            name='bill_print_paper_size',
            field=models.CharField(
                choices=[('a4', 'A4'), ('a5', 'A5'), ('thermal_80', 'Thermal 80mm')],
                default='a4',
                help_text='Default paper size for service and inventory bill prints.',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='job_ticket_print_paper_size',
            field=models.CharField(
                choices=[('a4', 'A4'), ('a5', 'A5'), ('thermal_80', 'Thermal 80mm')],
                default='a5',
                help_text='Default paper size for job ticket / receipt prints.',
                max_length=20,
            ),
        ),
    ]
