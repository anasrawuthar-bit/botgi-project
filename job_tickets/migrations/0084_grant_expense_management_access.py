# Generated data migration to grant Expense Management access to existing staff
from django.db import migrations


def grant_expense_management_access(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    expense_group, _ = Group.objects.get_or_create(name='Access: Expense Management')

    staff_dashboard_group = Group.objects.filter(name='Access: Staff Dashboard').first()
    if staff_dashboard_group:
        for user in staff_dashboard_group.user_set.all():
            user.groups.add(expense_group)


def reverse_expense_management_access(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    expense_group = Group.objects.filter(name='Access: Expense Management').first()
    if expense_group:
        expense_group.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('job_tickets', '0083_expense'),
    ]

    operations = [
        migrations.RunPython(grant_expense_management_access, reverse_expense_management_access),
    ]
