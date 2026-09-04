from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('job_tickets', '0073_alter_customer_phone_max_length'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='jobticket',
            index=models.Index(fields=['status', 'updated_at'], name='jt_status_updated_idx'),
        ),
        migrations.AddIndex(
            model_name='jobticket',
            index=models.Index(fields=['status', 'created_at'], name='jt_status_created_idx'),
        ),
        migrations.AddIndex(
            model_name='jobticket',
            index=models.Index(fields=['workspace', 'status'], name='jt_workspace_status_idx'),
        ),
        migrations.AddIndex(
            model_name='jobticket',
            index=models.Index(fields=['customer_phone'], name='jt_customer_phone_idx'),
        ),
        migrations.AddIndex(
            model_name='jobticket',
            index=models.Index(fields=['closed_at'], name='jt_closed_at_idx'),
        ),
        migrations.AddIndex(
            model_name='servicelog',
            index=models.Index(fields=['job_ticket'], name='sl_job_ticket_idx'),
        ),
        migrations.AddIndex(
            model_name='jobticketlog',
            index=models.Index(fields=['job_ticket', 'action'], name='jtl_ticket_action_idx'),
        ),
        migrations.AddIndex(
            model_name='specializedservice',
            index=models.Index(fields=['status', 'returned_date'], name='ss_status_returned_idx'),
        ),
        migrations.AddIndex(
            model_name='inventoryentry',
            index=models.Index(fields=['entry_type', 'entry_date'], name='ie_type_date_idx'),
        ),
        migrations.AddIndex(
            model_name='inventoryentry',
            index=models.Index(fields=['party', 'entry_type'], name='ie_party_type_idx'),
        ),
        migrations.AddIndex(
            model_name='client',
            index=models.Index(fields=['phone'], name='client_phone_idx'),
        ),
        migrations.AddIndex(
            model_name='jobreminder',
            index=models.Index(fields=['status', 'due_at'], name='jr_status_due_idx'),
        ),
    ]
