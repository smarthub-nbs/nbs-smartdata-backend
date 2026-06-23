from rest_framework.permissions import BasePermission


class HasAPIKey(BasePermission):
    message = "A valid API key is required."

    def has_permission(self, request, view):
        return bool(getattr(request, "api_key", None))


class HasAPIScope(BasePermission):
    required_scopes = []

    def has_permission(self, request, view):
        api_key = getattr(request, "api_key", None)

        if not api_key:
            return False

        required_scopes = getattr(view, "required_scopes", self.required_scopes)

        if not required_scopes:
            return True

        api_key_scopes = set(
            api_key.scopes.filter(is_active=True).values_list("code", flat=True)
        )

        return all(scope in api_key_scopes for scope in required_scopes)
