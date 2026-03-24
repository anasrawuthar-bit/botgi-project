from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('job_tickets', '0050_alter_jobticket_feedback_rating'),
    ]

    operations = [
        migrations.AlterField(
            model_name='jobticketphoto',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='job_ticket_photos/'),
        ),
        migrations.AddField(
            model_name='jobticketphoto',
            name='image_content_type',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='jobticketphoto',
            name='image_data',
            field=models.BinaryField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='jobticketphoto',
            name='image_name',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
