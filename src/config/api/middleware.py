import uuid

from django.conf import settings
from django.http import HttpResponse
from django.utils.cache import patch_vary_headers


class RequestIDMiddleware:
    request_header = "HTTP_X_REQUEST_ID"
    response_header = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = request.META.get(self.request_header) or str(uuid.uuid4())
        response = self.get_response(request)
        response[self.response_header] = request.request_id
        return response


class FrontendCredentialCorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.headers.get("Origin")

        if self._is_preflight_request(request, origin):
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        return self._add_cors_headers(request, response, origin)

    def _is_allowed_origin(self, origin):
        return bool(origin) and origin in settings.CORS_ALLOWED_ORIGINS

    def _is_preflight_request(self, request, origin):
        return (
            request.method == "OPTIONS"
            and self._is_allowed_origin(origin)
            and bool(request.headers.get("Access-Control-Request-Method"))
        )

    def _add_cors_headers(self, request, response, origin):
        if not self._is_allowed_origin(origin):
            return response

        patch_vary_headers(response, ("Origin",))
        response["Access-Control-Allow-Origin"] = origin

        if settings.CORS_ALLOW_CREDENTIALS:
            response["Access-Control-Allow-Credentials"] = "true"

        response["Access-Control-Expose-Headers"] = ", ".join(
            settings.CORS_EXPOSE_HEADERS
        )

        if request.method == "OPTIONS":
            response["Access-Control-Allow-Methods"] = ", ".join(
                settings.CORS_ALLOW_METHODS
            )
            response["Access-Control-Allow-Headers"] = ", ".join(
                settings.CORS_ALLOW_HEADERS
            )
            response["Access-Control-Max-Age"] = str(settings.CORS_PREFLIGHT_MAX_AGE)

        return response
