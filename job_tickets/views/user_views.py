from .helpers import *  # noqa: F401,F403


@login_required
def staff_technicians(request):
    denied = _staff_access_required(request, "team_management")
    if denied:
        return denied
    
    # Ensure groups exist
    technicians_group, _ = Group.objects.get_or_create(name='Technicians')
    staff_group, _ = Group.objects.get_or_create(name='Staff')
    tech_form = TechnicianCreationForm(request.POST or None)
    access_keys = {option['key'] for option in ACCESS_OPTIONS}
    staff_access_options = [option for option in ACCESS_OPTIONS if option.get('section') == 'general']
    staff_report_access_options = [option for option in ACCESS_OPTIONS if option.get('section') == 'reports']
    selected_access_keys = set()

    if request.method == 'POST':
        # Handle user creation
        if 'add_technician_submit' in request.POST:
            selected_access_keys = parse_access_keys(request.POST)
            if tech_form.is_valid():
                user = tech_form.save(commit=False)
                role = tech_form.cleaned_data['role']
                unique_id = (tech_form.cleaned_data.get('unique_id') or '').strip()

                if role == 'technician' and not unique_id:
                    tech_form.add_error('unique_id', 'Unique ID is required for technicians.')
                else:
                    user.save()
                    if role == 'technician':
                        TechnicianProfile.objects.update_or_create(
                            user=user,
                            defaults={'unique_id': unique_id}
                        )
                        user.groups.add(technicians_group)
                        user.groups.remove(staff_group)
                        user.is_staff = False
                        user.save(update_fields=['is_staff'])
                        messages.success(request, 'Technician created successfully.')
                    else:
                        user.groups.add(staff_group)
                        user.groups.remove(technicians_group)
                        user.is_staff = True
                        user.save(update_fields=['is_staff'])
                        apply_staff_access(user, selected_access_keys)
                        messages.success(request, 'Staff member created successfully.')
                    return redirect('staff_technicians')

        # Handle user toggle (enable/disable)
        if 'toggle_technician' in request.POST:
            user_id = request.POST.get('toggle_technician')
            managed_user = User.objects.filter(id=user_id).first()
            if not managed_user:
                messages.error(request, 'User not found.')
                return redirect('staff_technicians')
            if managed_user.is_superuser:
                messages.error(request, 'Superuser status cannot be changed here.')
                return redirect('staff_technicians')
            if managed_user.id == request.user.id and managed_user.is_active:
                messages.error(request, 'You cannot disable your own account.')
                return redirect('staff_technicians')

            managed_user.is_active = not managed_user.is_active
            managed_user.save(update_fields=['is_active'])
            action = 'enabled' if managed_user.is_active else 'disabled'
            messages.success(request, f'User {managed_user.username} {action} successfully.')
            return redirect('staff_technicians')

    latest_session_activity = UserSessionActivity.objects.filter(user=OuterRef('pk')).order_by('-login_at')
    managed_users = (
        User.objects.filter(
            Q(groups__name='Technicians') | Q(groups__name='Staff') | Q(is_staff=True)
        )
        .exclude(is_superuser=True)
        .distinct()
        .order_by('username')
        .prefetch_related('groups')
        .select_related('technician_profile')
        .annotate(
            latest_session_login_at=Subquery(latest_session_activity.values('login_at')[:1]),
            latest_session_last_activity_at=Subquery(latest_session_activity.values('last_activity_at')[:1]),
            latest_session_status=Subquery(latest_session_activity.values('status')[:1]),
            latest_session_ip=Subquery(latest_session_activity.values('ip_address')[:1]),
            latest_session_user_agent=Subquery(latest_session_activity.values('user_agent')[:1]),
            active_session_count=Count(
                'session_activities',
                filter=Q(
                    session_activities__status=UserSessionActivity.STATUS_ACTIVE,
                    session_activities__expires_at__gt=timezone.now(),
                ),
                distinct=True,
            ),
        )
    )

    for managed_user in managed_users:
        try:
            profile = managed_user.technician_profile
        except TechnicianProfile.DoesNotExist:
            profile = None
        managed_user.display_unique_id = profile.unique_id if profile else ''
        managed_access = get_staff_access(managed_user, group_names=[g.name for g in managed_user.groups.all()])
        managed_user.staff_access_keys = {
            key for key in access_keys if managed_access.get(key)
        }
        managed_user.latest_session_device = _summarize_user_agent(getattr(managed_user, 'latest_session_user_agent', ''))

    context = {
        'tech_form': tech_form,
        'managed_users': managed_users,
        'staff_access_options': staff_access_options,
        'staff_report_access_options': staff_report_access_options,
        'selected_access_keys': selected_access_keys,
    }
    return render(request, 'job_tickets/staff_technicians.html', context)

@login_required
@require_POST
def edit_user(request, user_id):
    """Edit an existing user."""
    denied = _staff_access_required(request, "team_management")
    if denied:
        return denied
    
    user = User.objects.filter(id=user_id).first()
    if not user:
        messages.error(request, 'User not found.')
        return redirect('staff_technicians')
    if user.is_superuser and not request.user.is_superuser:
        messages.error(request, 'Superuser cannot be modified from this page.')
        return redirect('staff_technicians')
    
    # Update user fields
    new_username = request.POST.get('username', '').strip()
    if new_username and new_username != user.username:
        # Check if username is already taken
        if User.objects.filter(username=new_username).exclude(id=user.id).exists():
            messages.error(request, f'Username "{new_username}" is already taken.')
            return redirect('staff_technicians')
        user.username = new_username
    
    user.email = (request.POST.get('email', user.email) or '').strip()

    unique_id = (request.POST.get('unique_id', '') or '').strip()
    new_role = request.POST.get('role', 'technician')
    selected_access_keys = parse_access_keys(request.POST)
    technicians_group, _ = Group.objects.get_or_create(name='Technicians')
    staff_group, _ = Group.objects.get_or_create(name='Staff')
    
    if new_role == 'staff':
        if user.id == request.user.id and not request.user.is_superuser:
            user.is_staff = True
        user.groups.remove(technicians_group)
        user.groups.add(staff_group)
        user.is_staff = True
        if unique_id and hasattr(user, 'technician_profile'):
            conflict = TechnicianProfile.objects.filter(unique_id=unique_id).exclude(user=user).exists()
            if conflict:
                messages.error(request, f'Unique ID "{unique_id}" is already assigned to another user.')
                return redirect('staff_technicians')
            user.technician_profile.unique_id = unique_id
            user.technician_profile.save(update_fields=['unique_id'])
        apply_staff_access(user, selected_access_keys)
    else:  # technician
        if user.id == request.user.id:
            messages.error(request, 'You cannot change your own role to Technician.')
            return redirect('staff_technicians')
        if not unique_id:
            messages.error(request, 'Unique ID is required for technicians.')
            return redirect('staff_technicians')
        conflict = TechnicianProfile.objects.filter(unique_id=unique_id).exclude(user=user).exists()
        if conflict:
            messages.error(request, f'Unique ID "{unique_id}" is already assigned to another user.')
            return redirect('staff_technicians')
        TechnicianProfile.objects.update_or_create(
            user=user,
            defaults={'unique_id': unique_id}
        )
        user.groups.remove(staff_group)
        user.groups.add(technicians_group)
        user.is_staff = False
        clear_staff_access(user)
    
    user.save()
    
    messages.success(request, f'User "{user.username}" updated successfully.')
    return redirect('staff_technicians')

@login_required
@require_POST
def delete_user(request, user_id):
    """Delete a user."""
    denied = _staff_access_required(request, "team_management")
    if denied:
        return denied
    
    user = User.objects.filter(id=user_id).first()
    if not user:
        messages.error(request, 'User not found.')
        return redirect('staff_technicians')
    if user.is_superuser:
        messages.error(request, 'Superuser cannot be deleted from this page.')
        return redirect('staff_technicians')
    if user.id == request.user.id:
        messages.error(request, 'You cannot delete your own account.')
        return redirect('staff_technicians')

    username = user.username
    try:
        user.delete()
        messages.success(request, f'User "{username}" deleted successfully.')
    except Exception as e:
        messages.error(request, f'Error deleting user: {str(e)}')
    
    return redirect('staff_technicians')

@login_required
@require_POST
def change_user_password(request, user_id):
    """Change password for staff/technician user from team management page."""
    denied = _staff_access_required(request, "team_management")
    if denied:
        return denied

    user = User.objects.filter(id=user_id).first()
    if not user:
        messages.error(request, 'User not found.')
        return redirect('staff_technicians')
    if user.is_superuser and not request.user.is_superuser:
        messages.error(request, 'Superuser password cannot be changed from this page.')
        return redirect('staff_technicians')

    new_password = (request.POST.get('new_password') or '').strip()
    confirm_password = (request.POST.get('confirm_password') or '').strip()

    if not new_password or not confirm_password:
        messages.error(request, 'Both password fields are required.')
        return redirect('staff_technicians')
    if new_password != confirm_password:
        messages.error(request, 'Password and confirm password do not match.')
        return redirect('staff_technicians')

    try:
        validate_password(new_password, user=user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect('staff_technicians')

    user.set_password(new_password)
    user.save(update_fields=['password'])

    if request.user.id == user.id:
        update_session_auth_hash(request, user)

    messages.success(request, f'Password updated successfully for "{user.username}".')
    return redirect('staff_technicians')
