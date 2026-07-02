from drf_spectacular.extensions import OpenApiAuthenticationExtension


class VersionedJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "djapps.user_management.api.authentication.VersionedJWTAuthentication"
    name = "BearerAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": (
                "JWT bearer authentication. Send `Authorization: Bearer <access_token>`. "
                "Browser clients may also authenticate with the SmartHub access-token cookie."
            ),
        }
