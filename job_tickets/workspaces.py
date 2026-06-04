from django.contrib.auth.models import User

from .models import CompanyUserMembership, CompanyWorkspace


def get_user_workspace_queryset(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return CompanyWorkspace.objects.none()

    if getattr(user, 'is_superuser', False):
        return CompanyWorkspace.objects.all().order_by('name')

    return (
        CompanyWorkspace.objects.filter(memberships__user=user, memberships__is_active=True)
        .distinct()
        .order_by('name')
    )


def get_current_workspace(request):
    if getattr(request, 'current_workspace', None) is not None:
        return request.current_workspace

    workspace = get_user_workspace_queryset(getattr(request, 'user', None)).first()
    request.current_workspace = workspace
    return workspace


def ensure_user_workspace_membership(user, workspace, role=CompanyUserMembership.ROLE_STAFF):
    if not isinstance(user, User) or not workspace:
        return None
    membership, _ = CompanyUserMembership.objects.get_or_create(
        workspace=workspace,
        user=user,
        defaults={'role': role},
    )
    return membership
