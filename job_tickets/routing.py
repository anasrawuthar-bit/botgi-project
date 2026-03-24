# job_tickets/routing.py (UPDATED)

from django.urls import re_path
from . import consumers

# A list of all WebSocket URL patterns your app supports
websocket_urlpatterns = [
    # 1. Job-specific status for client/detail pages
    re_path(r'ws/job_status/(?P<job_code>\w+)/$', consumers.JobStatusConsumer.as_asgi()),
    
    # 2. General updates for Staff Dashboard
    re_path(r'ws/staff_updates/$', consumers.StaffDashboardConsumer.as_asgi()),

    # 3. General updates for Technician Dashboard (ADDED)
    re_path(r'ws/technician_updates/$', consumers.TechnicianDashboardConsumer.as_asgi()),
]