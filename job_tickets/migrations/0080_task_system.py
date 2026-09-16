import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('job_tickets', '0079_alter_assignment_unique_together_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='assignment',
            unique_together={('job', 'technician')},
        ),
        migrations.RemoveField(
            model_name='assignment',
            name='assigned_by',
        ),
        migrations.RemoveField(
            model_name='assignment',
            name='due_date',
        ),
        migrations.RemoveField(
            model_name='assignment',
            name='instructions',
        ),
        migrations.RemoveField(
            model_name='assignment',
            name='priority',
        ),
        migrations.CreateModel(
            name='Task',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('priority', models.CharField(choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('urgent', 'Urgent / Rush')], db_index=True, default='medium', max_length=16)),
                ('due_date', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(choices=[('open', 'Open'), ('in_progress', 'In Progress'), ('done', 'Done'), ('cancelled', 'Cancelled')], db_index=True, default='open', max_length=16)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('assigned_to', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tasks', to='job_tickets.technicianprofile')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_tasks', to=settings.AUTH_USER_MODEL)),
                ('job_reference', models.ForeignKey(blank=True, help_text='Optional: link this task to a job ticket for traceability.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tasks', to='job_tickets.jobticket')),
                ('workspace', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='tasks', to='job_tickets.companyworkspace')),
            ],
            options={
                'ordering': [
                    models.Case(
                        models.When(priority='urgent', then=models.Value(0)),
                        models.When(priority='high', then=models.Value(1)),
                        models.When(priority='medium', then=models.Value(2)),
                        models.When(priority='low', then=models.Value(3)),
                        default=models.Value(4),
                        output_field=models.IntegerField(),
                    ),
                    models.OrderBy(models.F('due_date'), nulls_last=True),
                    '-created_at',
                ],
            },
        ),
        migrations.RemoveField(
            model_name='taskattachment',
            name='assignment',
        ),
        migrations.AddField(
            model_name='taskattachment',
            name='task',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='job_tickets.task'),
            preserve_default=False,
        ),
        migrations.CreateModel(
            name='TaskMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('body', models.TextField()),
                ('sent_at', models.DateTimeField(auto_now_add=True)),
                ('is_read', models.BooleanField(default=False)),
                ('sender', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='task_messages', to=settings.AUTH_USER_MODEL)),
                ('task', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='job_tickets.task')),
            ],
            options={
                'ordering': ['sent_at'],
            },
        ),
    ]
