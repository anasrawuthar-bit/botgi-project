import re
from datetime import datetime
from django.db import migrations, models


def populate_intake_dates(apps, schema_editor):
    JobTicket = apps.get_model('job_tickets', 'JobTicket')
    JobTicketLog = apps.get_model('job_tickets', 'JobTicketLog')

    for job in JobTicket.objects.all().iterator(chunk_size=500):
        created_log = JobTicketLog.objects.filter(job_ticket_id=job.id, action='CREATED').order_by('id').first()
        intake_date = None
        if created_log and created_log.details:
            match = re.search(r'Intake date:\s*(\d{2}-\d{2}-\d{4})', created_log.details)
            if match:
                try:
                    intake_date = datetime.strptime(match.group(1), '%d-%m-%Y').date()
                except Exception:
                    pass
        if not intake_date and job.created_at:
            intake_date = job.created_at.date()

        real_created_at = created_log.timestamp if created_log else None

        if real_created_at and job.created_at and job.created_at < real_created_at:
            JobTicket.objects.filter(pk=job.pk).update(intake_date=intake_date, created_at=real_created_at)
        else:
            JobTicket.objects.filter(pk=job.pk).update(intake_date=intake_date)


class Migration(migrations.Migration):

    dependencies = [
        ('job_tickets', '0100_specializedservice_vendor_bill_number'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobticket',
            name='intake_date',
            field=models.DateField(blank=True, db_index=True, help_text='Date when device was physically received at the shop.', null=True),
        ),
        migrations.RunPython(populate_intake_dates, migrations.RunPython.noop),
    ]
