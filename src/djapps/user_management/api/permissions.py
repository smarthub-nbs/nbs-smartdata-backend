from rest_framework.permissions import BasePermission

ROLE_GUEST = "guest"
ROLE_USER = "user"
ROLE_DEVELOPER = "developer"
ROLE_RESEARCHER = "researcher"
ROLE_EDITOR = "editor"
ROLE_ADMIN = "admin"
ROLE_SUPER_ADMIN = "super_admin"

ADMIN_GROUPS = (ROLE_ADMIN, ROLE_SUPER_ADMIN)


def is_authenticated_user(user):
    return bool(user and user.is_authenticated)


def user_has_any_group(user, group_names):
    if not is_authenticated_user(user):
        return False

    return user.groups.filter(name__in=group_names).exists()


def is_admin_like(user):
    return bool(
        is_authenticated_user(user)
        and (user.is_superuser or user.is_staff or user_has_any_group(user, ADMIN_GROUPS))
    )


class HasAnyGroup(BasePermission):
    message = "You do not have the required role."

    required_groups = ()

    def has_permission(self, request, view):
        if not is_authenticated_user(request.user):
            return False

        required_groups = getattr(view, "required_groups", self.required_groups)
        if not required_groups:
            return False

        return user_has_any_group(request.user, required_groups) or is_admin_like(
            request.user
        )


class HasPermission(BasePermission):
    message = "You do not have the required permission."

    required_permission = None
    required_permissions = ()
    require_all_permissions = True

    def get_required_permissions(self, view):
        permissions = getattr(view, "required_permissions", self.required_permissions)
        if permissions:
            return tuple(permissions)

        permission = getattr(view, "required_permission", self.required_permission)
        if not permission:
            return ()
        return (permission,)

    def has_permission(self, request, view):
        if not is_authenticated_user(request.user):
            return False

        permissions = self.get_required_permissions(view)
        if not permissions:
            return False

        require_all = getattr(
            view,
            "require_all_permissions",
            self.require_all_permissions,
        )
        permission_checks = (request.user.has_perm(permission) for permission in permissions)
        return all(permission_checks) if require_all else any(permission_checks)


class IsAdminOrSuperuser(BasePermission):
    message = "Admin access required."

    def has_permission(self, request, view):
        return is_admin_like(request.user)
