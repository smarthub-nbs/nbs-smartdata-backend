from django.conf import settings
from django.middleware.csrf import get_token, rotate_token
from rest_framework.authentication import SessionAuthentication


def enforce_request_csrf(request):
    SessionAuthentication().enforce_csrf(request)


def issue_csrf_token(request, *, rotate=False):
    if rotate:
        rotate_token(request)
    return get_token(request)


def build_csrf_response_data(request, *, rotate=False):
    token = issue_csrf_token(request, rotate=rotate)
    return {
        "csrf_token": token,
        "cookie_name": settings.CSRF_COOKIE_NAME,
        "header_name": _get_public_csrf_header_name(),
    }


def _get_public_csrf_header_name():
    if settings.CSRF_HEADER_NAME == "HTTP_X_CSRFTOKEN":
        return "X-CSRFToken"

    header_name = settings.CSRF_HEADER_NAME
    if header_name.startswith("HTTP_"):
        header_name = header_name[5:]
    return "-".join(part.title() for part in header_name.split("_"))
