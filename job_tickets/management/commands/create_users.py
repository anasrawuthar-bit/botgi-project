from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = 'Create missing users for data import'

    def handle(self, *args, **options):
        # Create users with IDs that are referenced in the backup
        user_ids = [7, 8, 9, 10, 11, 12, 13, 15, 16, 17]
        
        for user_id in user_ids:
            if not User.objects.filter(id=user_id).exists():
                User.objects.create_user(
                    id=user_id,
                    username=f'user_{user_id}',
                    password='temp123',
                    email=f'user_{user_id}@example.com'
                )
                self.stdout.write(f'Created user with ID {user_id}')
        
        self.stdout.write(self.style.SUCCESS('Missing users created'))