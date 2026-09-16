import os
import sys
sys.path.insert(0, os.path.abspath('.'))
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'botgi_crm.settings')
django.setup()

from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from job_tickets.models import (
    JobTicket, TechnicianProfile, Task, TaskAttachment, TaskMessage,
    CompanyWorkspace, Assignment
)
from job_tickets.views.mobile_api_views import _serialize_task_for_mobile


def run_verification():
    print("=== Standalone Task System Verification ===")

    # 1. Setup user & technician
    staff_user, _ = User.objects.get_or_create(username='test_staff_user', defaults={'is_staff': True})
    tech_user, _ = User.objects.get_or_create(username='test_tech_user')
    tech_profile, _ = TechnicianProfile.objects.get_or_create(user=tech_user, defaults={'unique_id': 'TECH-99'})

    workspace = CompanyWorkspace.objects.first()

    # 2. Test Task Priority Ordering
    print("\n--- Testing Priority Ordering ---")
    Task.objects.filter(title__startswith='TEST_TASK_').delete()

    t_low = Task.objects.create(
        workspace=workspace,
        title='TEST_TASK_LOW',
        priority=Task.PRIORITY_LOW,
        assigned_to=tech_profile,
        created_by=staff_user,
    )
    t_urgent = Task.objects.create(
        workspace=workspace,
        title='TEST_TASK_URGENT',
        priority=Task.PRIORITY_URGENT,
        assigned_to=tech_profile,
        created_by=staff_user,
        due_date=timezone.now() + timedelta(hours=2),
    )
    t_medium = Task.objects.create(
        workspace=workspace,
        title='TEST_TASK_MEDIUM',
        priority=Task.PRIORITY_MEDIUM,
        assigned_to=tech_profile,
        created_by=staff_user,
    )
    t_high = Task.objects.create(
        workspace=workspace,
        title='TEST_TASK_HIGH',
        priority=Task.PRIORITY_HIGH,
        assigned_to=tech_profile,
        created_by=staff_user,
        due_date=timezone.now() + timedelta(hours=5),
    )

    ordered = list(Task.objects.filter(title__startswith='TEST_TASK_'))
    ordered_titles = [t.title for t in ordered]
    print("Ordered titles:", ordered_titles)

    expected = ['TEST_TASK_URGENT', 'TEST_TASK_HIGH', 'TEST_TASK_MEDIUM', 'TEST_TASK_LOW']
    assert ordered_titles == expected, f"Ordering mismatch: {ordered_titles} != {expected}"
    print("[PASS] Priority ordering verified: Urgent -> High -> Medium -> Low")

    # 3. Test Task State Transitions
    print("\n--- Testing Task State Transitions ---")
    assert t_urgent.status == Task.STATUS_OPEN
    t_urgent.mark_in_progress()
    t_urgent.refresh_from_db()
    assert t_urgent.status == Task.STATUS_IN_PROGRESS
    print("[PASS] Moved to IN_PROGRESS")

    t_urgent.mark_done()
    t_urgent.refresh_from_db()
    assert t_urgent.status == Task.STATUS_DONE
    assert t_urgent.completed_at is not None
    print(f"[PASS] Moved to DONE (completed_at: {t_urgent.completed_at})")

    # 4. Test Task Messaging
    print("\n--- Testing Task Messaging Thread ---")
    msg1 = TaskMessage.objects.create(
        task=t_urgent,
        sender=staff_user,
        body="Please diagnose the power delivery circuit immediately.",
    )
    msg2 = TaskMessage.objects.create(
        task=t_urgent,
        sender=tech_user,
        body="Understood. Found a shorted capacitor on the 19V rail.",
    )

    messages = list(t_urgent.messages.all())
    assert len(messages) == 2
    assert messages[0].sender == staff_user
    assert messages[1].sender == tech_user
    print(f"[PASS] {len(messages)} messages exchanged between staff and technician")

    # 5. Test Serialization for Mobile App
    print("\n--- Testing Mobile API Serialization ---")
    serialized = _serialize_task_for_mobile(t_urgent, user=tech_user, detailed=True)
    assert serialized['id'] == t_urgent.id
    assert serialized['priority'] == 'urgent'
    assert serialized['priority_display'] == 'Urgent / Rush'
    assert serialized['status'] == 'done'
    assert len(serialized['messages']) == 2
    assert serialized['messages'][0]['sender_is_self'] is False
    assert serialized['messages'][1]['sender_is_self'] is True
    print("[PASS] Mobile serialization verified with sender_is_self logic")

    # 6. Test Decoupled Job Assignment
    print("\n--- Testing Decoupled Job Assignment ---")
    # Verify JobTicket doesn't crash without old active_assignment properties
    job = JobTicket.objects.first()
    if job:
        job.assigned_to = tech_profile
        job.status = 'Under Inspection'
        job.save(update_fields=['assigned_to', 'status'])
        print(f"[PASS] Job {job.job_code} assigned to {tech_user.username} without directive hooks")

    # Clean up test tasks
    Task.objects.filter(title__startswith='TEST_TASK_').delete()
    print("\n[PASS] Cleaned up test data")
    print("\n=== ALL VERIFICATIONS PASSED SUCCESSFULLY ===")


if __name__ == '__main__':
    run_verification()
