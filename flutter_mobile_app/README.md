# Flutter Mobile App

This app provides:
- Login screen
- JWT token handling (save/restore/logout)
- Authenticated API fetch
- Jobs list display
- Job detail screen with action buttons
- Status timeline UI
- Profile settings with runtime server switch (Dev/Prod/Custom URL)
- Shared design system (theme, typography scale, reusable cards/status pills)

## Backend APIs used

- `POST /api/mobile/login/`
- `GET /api/mobile/me/`
- `GET /api/mobile/jobs/`
- `GET /api/mobile/jobs/<job_code>/`
- `POST /api/mobile/jobs/<job_code>/action/`

These endpoints are implemented in the Django project under `job_tickets/views.py` and `job_tickets/urls.py`.

## Base URL setup

Update `lib/config/app_config.dart`:
- Android emulator: `http://10.0.2.2:8000`
- iOS simulator: `http://127.0.0.1:8000`
- Physical device: `http://<your-lan-ip>:8000`

## Run

1. Start Django server from project root:
   `python manage.py runserver 0.0.0.0:8000`
2. Start Flutter app:
   `cd flutter_mobile_app`
   `flutter pub get`
   `flutter run`
