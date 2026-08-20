import json
from django.core.management.base import BaseCommand
from django.core import serializers
from django.apps import apps

class Command(BaseCommand):
    help = 'Export all data including auth models'

    def handle(self, *args, **options):
        # Get all models from all apps
        all_objects = []
        
        # First add auth models (users, groups, permissions)
        auth_models = ['auth.user', 'auth.group', 'auth.permission', 'contenttypes.contenttype']
        for model_name in auth_models:
            try:
                app_label, model_name = model_name.split('.')
                model = apps.get_model(app_label, model_name)
                for obj in model.objects.all():
                    all_objects.append(obj)
            except:
                continue
        
        # Then add job_tickets models
        for model in apps.get_models():
            if model._meta.app_label == 'job_tickets':
                for obj in model.objects.all():
                    all_objects.append(obj)
        
        # Serialize with UTF-8 encoding
        data = serializers.serialize('json', all_objects, ensure_ascii=False, indent=2)
        
        # Write to file with UTF-8 encoding
        with open('complete_backup.json', 'w', encoding='utf-8') as f:
            f.write(data)
        
        self.stdout.write(self.style.SUCCESS('Complete data exported to complete_backup.json'))