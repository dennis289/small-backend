from rest_framework.permissions import BasePermission


class IsPlatformAdmin(BasePermission):
    """Allows access only to platform-level superadmins.

    A platform admin has no client (client=None) and is a Django superuser.
    These accounts manage clients (tenants) but do not own tenant data.
    """

    message = 'Platform administrator access required.'

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.client_id is None
            and user.is_superuser
        )
