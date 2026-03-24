import json
from channels.generic.websocket import WebsocketConsumer
from asgiref.sync import async_to_sync

# --- GLOBAL GROUPS ---
STAFF_GROUP = 'staff_dashboard_updates'
TECH_GROUP = 'tech_dashboard_updates'
# ---------------------

class JobStatusConsumer(WebsocketConsumer):
    # This consumer handles connections to specific jobs (e.g., client status page)
    
    def connect(self):
        # The job code from the URL path, e.g., 'BOTGI-251005-001'
        self.job_code = self.scope['url_route']['kwargs']['job_code']
        # The group name to send messages to, e.g., 'job_BOTGI-251005-001'
        self.job_group_name = 'job_%s' % self.job_code

        # Join the job-specific group
        async_to_sync(self.channel_layer.group_add)(
            self.job_group_name,
            self.channel_name
        )
        self.accept()

    def disconnect(self, close_code):
        # Leave the job-specific group
        async_to_sync(self.channel_layer.group_discard)(
            self.job_group_name,
            self.channel_name
        )

    def receive(self, text_data):
        pass # Not used for detail page listening

    # Receive message from job-specific group (sent from views.py)
    def job_status_update(self, event):
        # Send the entire event dictionary to the WebSocket
        self.send(text_data=json.dumps(event))


class StaffDashboardConsumer(WebsocketConsumer):
    # This consumer handles connections for the Staff Dashboard
    def connect(self):
        # Join the global staff update group
        async_to_sync(self.channel_layer.group_add)(
            STAFF_GROUP,
            self.channel_name
        )
        self.accept()

    def disconnect(self, close_code):
        async_to_sync(self.channel_layer.group_discard)(
            STAFF_GROUP,
            self.channel_name
        )

    def receive(self, text_data):
        pass

    # Receive message from staff update group (sent from views.py)
    def job_status_update(self, event):
        self.send(text_data=json.dumps(event))
        

class TechnicianDashboardConsumer(WebsocketConsumer):
    # This consumer handles connections for the Technician Dashboard
    def connect(self):
        # Join the global technician update group
        # NOTE: This consumer is not yet referenced in routing.py, but is needed for views.py logic
        async_to_sync(self.channel_layer.group_add)(
            TECH_GROUP,
            self.channel_name
        )
        self.accept()

    def disconnect(self, close_code):
        async_to_sync(self.channel_layer.group_discard)(
            TECH_GROUP,
            self.channel_name
        )
        
    def receive(self, text_data):
        pass

    # Receive message from technician update group (sent from views.py)
    def job_status_update(self, event):
        self.send(text_data=json.dumps(event))