"""DRF permission classes for the two-tier access model.

**Platform tier** — ``client=None`` + ``is_superuser``. Manages tenants, owns no
tenant data. Only ``IsPlatformAdmin`` lets them in, and it is the only class here
they satisfy: every tenant class below requires a client, so a superadmin poking
at tenant endpoints gets a clean 403 rather than a confusing empty result.

**Tenant tier** — a user with a client, and one of three roles:

===========  ===========================================================
admin        everything within their client, including managing its users
scheduler    builds rosters and records attendance; reads setup data
member       read-only view of published rosters
===========  ===========================================================

Which class an endpoint uses is what actually enforces this — the frontend hides
what a role can't do, but that is cosmetic. Anything not explicitly opened to a
role must be closed to it here.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission


def _tenant_user(request):
    """The requesting user if they're a signed-in tenant user, else None."""
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated and user.client_id is not None):
        return None
    return user


class IsPlatformAdmin(BasePermission):
    """Allows access only to platform-level superadmins.

    A platform admin has no client (client=None) and is a Django superuser.
    These accounts manage clients (tenants) but do not own tenant data.
    """

    message = 'Platform administrator access required.'

    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        return bool(
            user
            and user.is_authenticated
            and user.client_id is None
            and user.is_superuser
        )


class IsTenantUser(BasePermission):
    """Any signed-in user belonging to a client, whatever their role.

    The floor for tenant endpoints. Use it only where every role — members
    included — is meant to have access.
    """

    message = 'You must belong to a client to use this endpoint.'

    def has_permission(self, request, view):
        return _tenant_user(request) is not None


class IsClientAdmin(BasePermission):
    """Admins of their own client. For destructive or organisation-wide actions."""

    message = 'Administrator access required.'

    def has_permission(self, request, view):
        user = _tenant_user(request)
        return bool(user and user.is_client_admin)


class CanSchedule(BasePermission):
    """Admins and schedulers — the two roles that run the rostering workflow.

    Covers generating, editing and saving rosters, and recording attendance.
    """

    message = 'Scheduler or administrator access required.'

    def has_permission(self, request, view):
        user = _tenant_user(request)
        return bool(user and user.can_schedule)


class IsClientAdminOrSchedulerReadOnly(BasePermission):
    """Admins may write; schedulers may only read; members are refused.

    This is the setup data — people, roles, events. A scheduler has to read it to
    build a roster at all, but changing the shape of the organisation is an
    admin's job.
    """

    message = 'Administrator access required to make changes.'

    def has_permission(self, request, view):
        user = _tenant_user(request)
        if not user:
            return False
        if user.is_client_admin:
            return True
        return user.can_schedule and request.method in SAFE_METHODS
