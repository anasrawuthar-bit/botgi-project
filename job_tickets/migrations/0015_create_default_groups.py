from django.db import migrations

def create_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    
    # Create Staff group if it doesn't exist
    Group.objects.get_or_create(name='Staff')
    
    # Create Technicians group if it doesn't exist
    Group.objects.get_or_create(name='Technicians')

def delete_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name__in=['Staff', 'Technicians']).delete()

class Migration(migrations.Migration):

    dependencies = [
        ('job_tickets', '0014_jobticket_vyapar_invoice_number'),
    ]

    operations = [
        migrations.RunPython(create_groups, delete_groups),
    ]