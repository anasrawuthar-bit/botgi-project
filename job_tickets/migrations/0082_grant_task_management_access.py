# Generated data migration to grant Task Management access to existing staff
from django.db import migrations


def grant_task_management_access(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    task_group, _ = Group.objects.get_or_create(name='Access: Task Management')

    staff_dashboard_group = Group.objects.filter(name='Access: Staff Dashboard').first()
    if staff_dashboard_group:
        for user in staff_dashboard_group.user_set.all():
            user.groups.add(task_group)


def reverse_task_management_access(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    task_group = Group.objects.filter(name='Access: Task Management').first()
    if task_group:
        task_group.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('job_tickets', '0081_messagequeue_max_retries_messagequeue_next_retry_at_and_more'),
    ]

    operations = [
        migrations.RunPython(grant_task_management_access, reverse_task_management_access),
    ]
