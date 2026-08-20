import json
from django.core.management.base import BaseCommand
from django.core import serializers
from django.apps import apps

class Command(BaseCommand):
    help = 'Export data with proper UTF-8 encoding'

    def handle(self, *args, **options):
        # Get all models
        all_objects = []
        for model in apps.get_models():
            if model._meta.app_label == 'job_tickets':
                for obj in model.objects.all():
                    all_objects.append(obj)
        
        # Serialize with UTF-8 encoding
        data = serializers.serialize('json', all_objects, ensure_ascii=False)
        
        # Write to file with UTF-8 encoding
        with open('data_backup.json', 'w', encoding='utf-8') as f:
            f.write(data)
        
        self.stdout.write(self.style.SUCCESS('Data exported successfully to data_backup.json'))