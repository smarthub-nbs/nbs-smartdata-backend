import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from rest_framework.exceptions import APIException, ValidationError

GITHUB_OAUTH_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Smarthub",
}


def fetch_provider_json(
    url,
    access_token,
    *,
    error_field="access_token",
    invalid_message="Invalid provider token.",
    failure_message="Could not verify provider token.",
):
    request = Request(
        url,
        headers={
            **GITHUB_DEFAULT_HEADERS,
            "Authorization": f"Bearer {access_token}",
        },
    )

    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise ValidationError({error_field: [invalid_message]})
        raise ValidationError({error_field: [failure_message]})
    except (URLError, TimeoutError, json.JSONDecodeError):
        raise ValidationError({error_field: [failure_message]})


def exchange_github_code_for_access_token(code, redirect_uri, code_verifier):
    client_id = settings.GITHUB_OAUTH_CLIENT_ID
    client_secret = settings.GITHUB_OAUTH_CLIENT_SECRET

    if not client_id or not client_secret:
        raise APIException("GitHub OAuth is not configured on the server.")

    allowed_redirect_uris = tuple(
        uri
        for uri in settings.GITHUB_OAUTH_ALLOWED_REDIRECT_URIS
        if uri
    )
    if allowed_redirect_uris and redirect_uri not in allowed_redirect_uris:
        raise ValidationError(
            {
                "redirect_uri": [
                    "Redirect URI is not allowed for GitHub OAuth."
                ]
            }
        )

    payload = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
    ).encode("utf-8")

    request = Request(
        GITHUB_OAUTH_ACCESS_TOKEN_URL,
        data=payload,
        headers={
            **GITHUB_DEFAULT_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=10) as response:
            token_payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        token_payload = _read_error_payload(exc)
        _raise_github_oauth_error(token_payload)
    except (URLError, TimeoutError, json.JSONDecodeError):
        raise ValidationError(
            {"code": ["Could not complete GitHub authorization."]}
        )

    if not isinstance(token_payload, dict):
        raise ValidationError({"code": ["Invalid GitHub token response."]})

    if token_payload.get("error"):
        _raise_github_oauth_error(token_payload)

    access_token = token_payload.get("access_token")
    if not access_token:
        raise ValidationError({"code": ["GitHub did not return an access token."]})

    return access_token


def _read_error_payload(exc):
    try:
        return json.loads(exc.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _raise_github_oauth_error(token_payload):
    error_code = token_payload.get("error")
    error_description = token_payload.get("error_description")

    if error_code == "bad_verification_code":
        raise ValidationError({"code": ["Invalid or expired GitHub authorization code."]})

    if error_code == "redirect_uri_mismatch":
        raise ValidationError(
            {
                "redirect_uri": [
                    "Redirect URI does not match the GitHub OAuth app configuration."
                ]
            }
        )

    if error_code == "incorrect_client_credentials":
        raise APIException("GitHub OAuth client credentials are misconfigured.")

    if error_code == "access_denied":
        raise ValidationError({"code": ["GitHub authorization was denied."]})

    if error_description:
        raise ValidationError({"code": [error_description]})

    raise ValidationError({"code": ["Could not complete GitHub authorization."]})
