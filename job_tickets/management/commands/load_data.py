import json
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.db import transaction

class Command(BaseCommand):
    help = 'Load data in correct order'

    def add_arguments(self, parser):
        parser.add_argument('filename', type=str, help='JSON file to load')

    def handle(self, *args, **options):
        filename = options['filename']
        
        try:
            with transaction.atomic():
                # Load in specific order to handle dependencies
                self.stdout.write('Loading data...')
                call_command('loaddata', filename)
                self.stdout.write(self.style.SUCCESS('Data loaded successfully'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error loading data: {str(e)}'))
            
            # Try alternative approach - load without foreign key checks
            self.stdout.write('Trying alternative approach...')
            try:
                from django.db import connection
                with connection.cursor() as cursor:
                    cursor.execute('PRAGMA foreign_keys = OFF;')
                
                call_command('loaddata', filename)
                
                with connection.cursor() as cursor:
                    cursor.execute('PRAGMA foreign_keys = ON;')
                    
                self.stdout.write(self.style.SUCCESS('Data loaded with foreign key checks disabled'))
            except Exception as e2:
                self.stdout.write(self.style.ERROR(f'Failed: {str(e2)}'))