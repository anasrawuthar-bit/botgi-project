from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType

from .models import (
    Assignment,
    Client,
    CompanyProfile,
    DailyJobCodeSequence,
    JobTicket,
    JobTicketLog,
    Product,
    ServiceLog,
    SpecializedService,
    TechnicianProfile,
    Vendor,
)

ROLE_SUPER_ADMIN = 'Super Admin'
ROLE_STAFF_ADMIN = 'Staff Admin'
ROLE_READ_ONLY = 'Read Only'


def _permission_codenames_for_model(model, actions):
    model_name = model._meta.model_name
    return [f'{action}_{model_name}' for action in actions]


def _collect_permissions(model_actions):
    permission_ids = []
    for model, actions in model_actions:
        content_type = ContentType.objects.get_for_model(model)
        codenames = _permission_codenames_for_model(model, actions)
        permission_ids.extend(
            Permission.objects.filter(content_type=content_type, codename__in=codenames).values_list('id', flat=True)
        )
    return Permission.objects.filter(id__in=permission_ids).distinct()


def sync_admin_roles():
    """Create/update admin role groups and their model permissions."""
    super_admin_models = [
        (JobTicket, ('add', 'change', 'delete', 'view')),
        (ServiceLog, ('add', 'change', 'delete', 'view')),
        (Assignment, ('add', 'change', 'delete', 'view')),
        (JobTicketLog, ('view',)),
        (Vendor, ('add', 'change', 'delete', 'view')),
        (SpecializedService, ('add', 'change', 'delete', 'view')),
        (Client, ('add', 'change', 'delete', 'view')),
        (Product, ('add', 'change', 'delete', 'view')),
        (CompanyProfile, ('add', 'change', 'delete', 'view')),
        (TechnicianProfile, ('add', 'change', 'delete', 'view')),
        (DailyJobCodeSequence, ('view',)),
        (User, ('add', 'change', 'delete', 'view')),
        (Group, ('add', 'change', 'delete', 'view')),
    ]

    staff_admin_models = [
        (JobTicket, ('add', 'change', 'view')),
        (ServiceLog, ('add', 'change', 'view')),
        (Assignment, ('view',)),
        (JobTicketLog, ('view',)),
        (Vendor, ('add', 'change', 'view')),
        (SpecializedService, ('add', 'change', 'view')),
        (Client, ('add', 'change', 'view')),
        (Product, ('add', 'change', 'view')),
        (CompanyProfile, ('view', 'change')),
        (TechnicianProfile, ('view',)),
        (DailyJobCodeSequence, ('view',)),
    ]

    read_only_models = [
        (JobTicket, ('view',)),
        (ServiceLog, ('view',)),
        (Assignment, ('view',)),
        (JobTicketLog, ('view',)),
        (Vendor, ('view',)),
        (SpecializedService, ('view',)),
        (Client, ('view',)),
        (Product, ('view',)),
        (CompanyProfile, ('view',)),
        (TechnicianProfile, ('view',)),
        (DailyJobCodeSequence, ('view',)),
    ]

    group_permission_map = {
        ROLE_SUPER_ADMIN: _collect_permissions(super_admin_models),
        ROLE_STAFF_ADMIN: _collect_permissions(staff_admin_models),
        ROLE_READ_ONLY: _collect_permissions(read_only_models),
    }

    summary = {}
    for group_name, permissions in group_permission_map.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        group.permissions.set(permissions)
        summary[group_name] = permissions.count()

    return summary
