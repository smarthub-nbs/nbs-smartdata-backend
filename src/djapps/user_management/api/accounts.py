from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from ..models import User

EMAIL_VERIFICATION_PURPOSE = "email_verification"
PASSWORD_RESET_PURPOSE = "password_reset"

TOKEN_SALT_BY_PURPOSE = {
    EMAIL_VERIFICATION_PURPOSE: "user_management.email_verification",
    PASSWORD_RESET_PURPOSE: "user_management.password_reset",
}


def mark_user_logged_in(user):
    now = timezone.now()
    user.last_login = now
    user.last_login_at = now
    user.save(update_fields=["last_login", "last_login_at"])


def revoke_user_refresh_tokens(user):
    revoked_count = 0
    outstanding_tokens = OutstandingToken.objects.filter(user=user)
    for outstanding_token in outstanding_tokens.iterator():
        _, created = BlacklistedToken.objects.get_or_create(token=outstanding_token)
        revoked_count += int(created)
    return revoked_count


def invalidate_user_tokens(user):
    User.objects.filter(pk=user.pk).update(token_version=F("token_version") + 1)
    user.refresh_from_db(fields=["token_version"])
    return revoke_user_refresh_tokens(user)


def build_user_action_token(user, purpose):
    if purpose not in TOKEN_SALT_BY_PURPOSE:
        raise ValueError(f"Unsupported token purpose: {purpose}")

    return signing.dumps(
        {
            "uid": str(user.pk),
            "email": user.email,
            "password": user.password,
        },
        salt=TOKEN_SALT_BY_PURPOSE[purpose],
    )


def resolve_user_action_token(token, purpose):
    max_age = _get_token_max_age(purpose)

    try:
        payload = signing.loads(
            token,
            salt=TOKEN_SALT_BY_PURPOSE[purpose],
            max_age=max_age,
        )
    except signing.SignatureExpired:
        raise ValidationError({"token": ["This token has expired."]})
    except signing.BadSignature:
        raise ValidationError({"token": ["Invalid token."]})

    user = User.objects.filter(pk=payload.get("uid")).first()
    if user is None:
        raise ValidationError({"token": ["Invalid token."]})

    if payload.get("email") != user.email or payload.get("password") != user.password:
        raise ValidationError({"token": ["Invalid token."]})

    return user


def send_password_reset_email(user):
    token = build_user_action_token(user, PASSWORD_RESET_PURPOSE)
    link = _build_frontend_token_link(settings.FRONTEND_PASSWORD_RESET_URL, token)
    subject = "Smarthub password reset"
    body = _compose_email_body(
        intro="A request was received to reset your Smarthub password.",
        token=token,
        link=link,
        instruction="Use this token or link to complete the password reset.",
    )
    _send_user_email(subject, body, user.email)


def send_email_verification_email(user):
    token = build_user_action_token(user, EMAIL_VERIFICATION_PURPOSE)
    link = _build_frontend_token_link(settings.FRONTEND_EMAIL_VERIFICATION_URL, token)
    subject = "Verify your Smarthub email"
    body = _compose_email_body(
        intro="Verify your email address for Smarthub.",
        token=token,
        link=link,
        instruction="Use this token or link to confirm your email address.",
    )
    _send_user_email(subject, body, user.email)


def _get_token_max_age(purpose):
    if purpose == PASSWORD_RESET_PURPOSE:
        return settings.PASSWORD_RESET_TOKEN_MAX_AGE
    if purpose == EMAIL_VERIFICATION_PURPOSE:
        return settings.EMAIL_VERIFICATION_TOKEN_MAX_AGE
    raise ValueError(f"Unsupported token purpose: {purpose}")


def _build_frontend_token_link(base_url, token):
    if not base_url:
        return ""

    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["token"] = token
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


def _compose_email_body(*, intro, token, link, instruction):
    lines = [
        intro,
        "",
        instruction,
        f"Token: {token}",
    ]
    if link:
        lines.extend(["", f"Link: {link}"])
    return "\n".join(lines)


def _send_user_email(subject, body, recipient):
    sent_count = send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient],
        fail_silently=False,
    )
    if sent_count != 1:
        raise APIException("Could not send the requested email.")
