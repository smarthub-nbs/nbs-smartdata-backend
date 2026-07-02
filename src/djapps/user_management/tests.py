import re
import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Group
from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from djapps.datasets.models import Category, Dataset, DatasetAuditLog, DatasetStatus
from djapps.gateway.models import APIConsumer, APIUsageLog
from djapps.gateway.services import issue_api_key
from .models import User
from .roles import ensure_group_permissions


def assert_access_cookie_set(test_case, response):
    cookie = response.cookies[settings.AUTH_ACCESS_COOKIE_NAME]
    test_case.assertTrue(cookie.value)
    test_case.assertEqual(cookie["path"], settings.AUTH_ACCESS_COOKIE_PATH)
    test_case.assertEqual(cookie["samesite"], settings.AUTH_ACCESS_COOKIE_SAMESITE)
    test_case.assertEqual(
        bool(cookie["httponly"]), settings.AUTH_ACCESS_COOKIE_HTTP_ONLY
    )
    test_case.assertEqual(bool(cookie["secure"]), settings.AUTH_ACCESS_COOKIE_SECURE)


def assert_refresh_cookie_set(test_case, response):
    cookie = response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]
    test_case.assertTrue(cookie.value)
    test_case.assertEqual(cookie["path"], settings.AUTH_REFRESH_COOKIE_PATH)
    test_case.assertEqual(cookie["samesite"], settings.AUTH_REFRESH_COOKIE_SAMESITE)
    test_case.assertEqual(
        bool(cookie["httponly"]), settings.AUTH_REFRESH_COOKIE_HTTP_ONLY
    )
    test_case.assertEqual(bool(cookie["secure"]), settings.AUTH_REFRESH_COOKIE_SECURE)


def fetch_csrf_token(test_case, client, **extra_headers):
    response = client.get("/api/v1/auth/csrf/", **extra_headers)
    test_case.assertEqual(response.status_code, 200)
    test_case.assertTrue(response.data["success"])
    return response.data["data"]["csrf_token"], response


def assert_refresh_token_rejected(test_case, refresh_token):
    client = APIClient()
    client.cookies[settings.AUTH_REFRESH_COOKIE_NAME] = refresh_token
    response = client.post("/api/v1/auth/refresh/", {}, format="json")
    test_case.assertEqual(response.status_code, 401)
    test_case.assertFalse(response.data["success"])
    return response


def assert_access_token_rejected(test_case, access_token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
    response = client.get("/api/v1/auth/me/")
    test_case.assertEqual(response.status_code, 401)
    test_case.assertFalse(response.data["success"])
    return response


def assert_auth_cookies_cleared(test_case, response):
    test_case.assertEqual(
        str(response.cookies[settings.AUTH_ACCESS_COOKIE_NAME]["max-age"]),
        "0",
    )
    test_case.assertEqual(
        str(response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]["max-age"]),
        "0",
    )


class APIResponseFormatTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_success_uses_standard_success_response(self):
        response = self.client.post(
            "/api/v1/auth/register/",
            {
                "email": "format-test@example.com",
                "password": "StrongPass123!",
                "first_name": "Format",
                "last_name": "Test",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["message"], "User registered successfully.")
        self.assertEqual(response.data["data"]["email"], "format-test@example.com")
        self.assertIn("access", response.data["data"])
        self.assertNotIn("refresh", response.data["data"])
        assert_access_cookie_set(self, response)
        assert_refresh_cookie_set(self, response)
        created_user = User.objects.get(email="format-test@example.com")
        self.assertIn("user", created_user.groups.values_list("name", flat=True))

    def test_register_rejects_password_that_does_not_meet_strength_policy(self):
        response = self.client.post(
            "/api/v1/auth/register/",
            {
                "email": "weak-password@example.com",
                "password": "alllowercase",
                "first_name": "Weak",
                "last_name": "Password",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertCountEqual(
            response.data["error"]["details"]["fields"]["password"],
            [
                "Password must contain at least one uppercase letter.",
                "Password must contain at least one number.",
                "Password must contain at least one special character.",
            ],
        )

    def test_validation_errors_include_request_id_and_standard_structure(self):
        response = self.client.post(
            "/api/v1/auth/register/",
            {
                "email": "broken@example.com",
            },
            format="json",
            HTTP_X_REQUEST_ID="req-validation-001",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertEqual(response.data["error"]["message"], "Validation failed.")
        self.assertEqual(response.data["error"]["request_id"], "req-validation-001")
        self.assertEqual(response.headers["X-Request-ID"], "req-validation-001")
        self.assertEqual(
            response.data["error"]["details"]["fields"]["password"],
            ["This field is required."],
        )
        self.assertEqual(response.data["error"]["details"]["non_field_errors"], [])

    @patch("djapps.user_management.api.views.fetch_provider_json")
    @patch("djapps.user_management.api.views.exchange_github_code_for_access_token")
    def test_github_social_login_uses_oauth_code_exchange(
        self,
        exchange_github_code_for_access_token,
        fetch_provider_json,
    ):
        exchange_github_code_for_access_token.return_value = "gho_example_token"
        fetch_provider_json.side_effect = [
            {
                "name": "Lodyne Example",
            },
            [
                {
                    "email": "lodyne@example.com",
                    "primary": True,
                    "verified": True,
                }
            ],
        ]

        response = self.client.post(
            "/api/v1/auth/social/github/",
            {
                "code": "github_temp_code",
                "redirect_uri": "http://localhost:3000/auth/github/callback",
                "code_verifier": "uD5Stn6W2vEx8f3nF0Y6nQKq6C7eB1hW4rT9mLp2aXy",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["message"], "Login successful.")
        self.assertEqual(response.data["data"]["user"]["email"], "lodyne@example.com")
        self.assertIn("access", response.data["data"])
        self.assertNotIn("refresh", response.data["data"])
        assert_access_cookie_set(self, response)
        assert_refresh_cookie_set(self, response)
        exchange_github_code_for_access_token.assert_called_once_with(
            code="github_temp_code",
            redirect_uri="http://localhost:3000/auth/github/callback",
            code_verifier="uD5Stn6W2vEx8f3nF0Y6nQKq6C7eB1hW4rT9mLp2aXy",
        )

    def test_github_social_login_requires_oauth_code_payload(self):
        response = self.client.post(
            "/api/v1/auth/social/github/",
            {
                "access_token": "github_pat_legacy_token",
            },
            format="json",
            HTTP_X_REQUEST_ID="req-github-oauth-001",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertEqual(
            response.data["error"]["details"]["fields"]["code"],
            ["This field is required."],
        )
        self.assertEqual(
            response.data["error"]["details"]["fields"]["redirect_uri"],
            ["This field is required."],
        )
        self.assertEqual(
            response.data["error"]["details"]["fields"]["code_verifier"],
            ["This field is required."],
        )


class GitHubOAuthSettingsTests(TestCase):
    @patch("djapps.user_management.api.social.urlopen")
    @patch.object(
        settings,
        "GITHUB_OAUTH_ALLOWED_REDIRECT_URIS",
        ("http://localhost:3000/auth/github/callback",),
    )
    @patch.object(settings, "GITHUB_OAUTH_CLIENT_ID", "github-client-id")
    @patch.object(settings, "GITHUB_OAUTH_CLIENT_SECRET", "github-client-secret")
    def test_exchange_rejects_redirect_uri_outside_allowlist(self, _urlopen):
        from djapps.user_management.api.social import (
            exchange_github_code_for_access_token,
        )
        from rest_framework.exceptions import ValidationError

        with self.assertRaises(ValidationError) as context:
            exchange_github_code_for_access_token(
                code="temp-code",
                redirect_uri="http://malicious.example.com/callback",
                code_verifier="uD5Stn6W2vEx8f3nF0Y6nQKq6C7eB1hW4rT9mLp2aXy",
            )

        self.assertEqual(
            context.exception.detail["redirect_uri"],
            ["Redirect URI is not allowed for GitHub OAuth."],
        )

    @patch("djapps.user_management.api.social.urlopen")
    def test_fetch_provider_json_rejects_non_utf8_response(self, mock_urlopen):
        from djapps.user_management.api.social import fetch_provider_json
        from rest_framework.exceptions import ValidationError

        mock_response = MagicMock()
        mock_response.__enter__.return_value.read.return_value = b"\xff"
        mock_urlopen.return_value = mock_response

        with self.assertRaises(ValidationError) as context:
            fetch_provider_json("https://example.com/profile", "provider-token")

        self.assertEqual(
            context.exception.detail["access_token"],
            ["Could not verify provider token."],
        )

    @patch("djapps.user_management.api.social.urlopen")
    @patch.object(settings, "GITHUB_OAUTH_CLIENT_ID", "github-client-id")
    @patch.object(settings, "GITHUB_OAUTH_CLIENT_SECRET", "github-client-secret")
    def test_exchange_rejects_non_utf8_token_response(self, _urlopen):
        from djapps.user_management.api.social import (
            exchange_github_code_for_access_token,
        )
        from rest_framework.exceptions import ValidationError

        mock_response = MagicMock()
        mock_response.__enter__.return_value.read.return_value = b"\xff"
        _urlopen.return_value = mock_response

        with self.assertRaises(ValidationError) as context:
            exchange_github_code_for_access_token(
                code="temp-code",
                redirect_uri="http://localhost:3000/auth/github/callback",
                code_verifier="uD5Stn6W2vEx8f3nF0Y6nQKq6C7eB1hW4rT9mLp2aXy",
            )

        self.assertEqual(
            context.exception.detail["code"],
            ["Could not complete GitHub authorization."],
        )


class PasswordManagerPolicyTests(TestCase):
    def test_create_user_rejects_weak_password(self):
        with self.assertRaises(ValidationError) as context:
            User.objects.create_user(
                email="manager-weak@example.com",
                password="password123",
            )

        self.assertIn(
            "Password must contain at least one uppercase letter.",
            context.exception.messages,
        )
        self.assertIn(
            "Password must contain at least one special character.",
            context.exception.messages,
        )


class CookieAuthSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.user = User.objects.create_user(
            email="csrf-user@example.com",
            password="Password123!",
        )

    def test_csrf_bootstrap_issues_cookie_and_token_metadata(self):
        csrf_token, response = fetch_csrf_token(self, self.client)

        self.assertTrue(csrf_token)
        self.assertEqual(
            response.data["data"]["cookie_name"], settings.CSRF_COOKIE_NAME
        )
        self.assertEqual(response.data["data"]["header_name"], "X-CSRFToken")
        self.assertIn(settings.CSRF_COOKIE_NAME, response.cookies)
        self.assertEqual(
            response.cookies[settings.CSRF_COOKIE_NAME]["path"],
            settings.CSRF_COOKIE_PATH,
        )

    def test_login_requires_csrf_token_for_cookie_auth_flow(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {
                "email": "csrf-user@example.com",
                "password": "Password123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"]["code"], "permission_denied")
        self.assertIn("CSRF Failed", response.data["error"]["message"])

        csrf_token, _ = fetch_csrf_token(self, self.client)
        success_response = self.client.post(
            "/api/v1/auth/login/",
            {
                "email": "csrf-user@example.com",
                "password": "Password123!",
            },
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(success_response.status_code, 200)
        self.assertTrue(success_response.data["success"])

    def test_refresh_requires_csrf_token(self):
        csrf_token, _ = fetch_csrf_token(self, self.client)
        login_response = self.client.post(
            "/api/v1/auth/login/",
            {
                "email": "csrf-user@example.com",
                "password": "Password123!",
            },
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(login_response.status_code, 200)

        missing_csrf_response = self.client.post(
            "/api/v1/auth/refresh/",
            {},
            format="json",
        )
        self.assertEqual(missing_csrf_response.status_code, 403)
        self.assertFalse(missing_csrf_response.data["success"])
        self.assertIn("CSRF Failed", missing_csrf_response.data["error"]["message"])

        refreshed_csrf_token, _ = fetch_csrf_token(self, self.client)
        refresh_response = self.client.post(
            "/api/v1/auth/refresh/",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=refreshed_csrf_token,
        )

        self.assertEqual(refresh_response.status_code, 200)
        self.assertTrue(refresh_response.data["success"])

    @override_settings(
        CORS_ALLOWED_ORIGINS=("http://localhost:3000",),
        CSRF_TRUSTED_ORIGINS=("http://localhost:3000",),
    )
    def test_auth_csrf_endpoint_and_preflight_return_credentialed_cors_headers(self):
        origin = "http://localhost:3000"

        csrf_response = self.client.get(
            "/api/v1/auth/csrf/",
            HTTP_ORIGIN=origin,
        )

        self.assertEqual(csrf_response.status_code, 200)
        self.assertEqual(csrf_response.headers["Access-Control-Allow-Origin"], origin)
        self.assertEqual(
            csrf_response.headers["Access-Control-Allow-Credentials"],
            "true",
        )

        preflight_response = self.client.options(
            "/api/v1/auth/refresh/",
            HTTP_ORIGIN=origin,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,x-csrftoken",
        )

        self.assertEqual(preflight_response.status_code, 204)
        self.assertEqual(
            preflight_response.headers["Access-Control-Allow-Origin"], origin
        )
        self.assertEqual(
            preflight_response.headers["Access-Control-Allow-Credentials"],
            "true",
        )
        self.assertIn(
            "POST", preflight_response.headers["Access-Control-Allow-Methods"]
        )
        self.assertEqual(
            preflight_response.headers["Access-Control-Allow-Headers"],
            "content-type,x-csrftoken",
        )


class UserManagementFeatureTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="user@example.com",
            password="Password123!",
            first_name="Normal",
            last_name="User",
        )
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="Password123!",
            first_name="Admin",
            last_name="User",
        )
        self.editor_group = Group.objects.create(name="editor")
        self.developer_group = Group.objects.create(name="developer")

    def test_me_patch_updates_profile_and_marks_email_unverified_when_changed(self):
        self.user.is_verified = True
        self.user.save(update_fields=["is_verified"])
        self.client.force_authenticate(user=self.user)

        response = self.client.patch(
            "/api/v1/auth/me/",
            {
                "email": "updated@example.com",
                "first_name": "Updated",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "updated@example.com")
        self.assertEqual(self.user.first_name, "Updated")
        self.assertFalse(self.user.is_verified)

    def test_me_get_supports_access_cookie_auth_without_bearer_header(self):
        login_response = self.client.post(
            "/api/v1/auth/login/",
            {
                "email": "user@example.com",
                "password": "Password123!",
            },
            format="json",
        )

        self.assertEqual(login_response.status_code, 200)
        response = self.client.get("/api/v1/auth/me/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["email"], "user@example.com")

    def test_me_patch_supports_access_cookie_auth_with_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        csrf_token, _ = fetch_csrf_token(self, client)
        login_response = client.post(
            "/api/v1/auth/login/",
            {
                "email": "user@example.com",
                "password": "Password123!",
            },
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(login_response.status_code, 200)

        missing_csrf_response = client.patch(
            "/api/v1/auth/me/",
            {"first_name": "Cookie"},
            format="json",
        )
        self.assertEqual(missing_csrf_response.status_code, 403)
        self.assertFalse(missing_csrf_response.data["success"])
        self.assertIn("CSRF Failed", missing_csrf_response.data["error"]["message"])

        refreshed_csrf_token, _ = fetch_csrf_token(self, client)
        response = client.patch(
            "/api/v1/auth/me/",
            {"first_name": "Cookie"},
            format="json",
            HTTP_X_CSRFTOKEN=refreshed_csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Cookie")

    def test_change_password_updates_password_hash(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            "/api/v1/auth/password/change/",
            {
                "current_password": "Password123!",
                "new_password": "NewPassword123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewPassword123!"))

    def test_change_password_rejects_weak_password(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            "/api/v1/auth/password/change/",
            {
                "current_password": "Password123!",
                "new_password": "newpassword123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertEqual(
            response.data["error"]["details"]["fields"]["new_password"],
            [
                "Password must contain at least one uppercase letter.",
                "Password must contain at least one special character.",
            ],
        )

    def test_change_password_revokes_existing_tokens_and_clears_auth_cookies(self):
        login_response = self.client.post(
            "/api/v1/auth/login/",
            {
                "email": "user@example.com",
                "password": "Password123!",
            },
            format="json",
        )
        self.assertEqual(login_response.status_code, 200)
        old_refresh_token = login_response.cookies[
            settings.AUTH_REFRESH_COOKIE_NAME
        ].value
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login_response.data['data']['access']}"
        )
        old_access_token = login_response.data["data"]["access"]

        response = self.client.post(
            "/api/v1/auth/password/change/",
            {
                "current_password": "Password123!",
                "new_password": "NewPassword123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewPassword123!"))
        assert_auth_cookies_cleared(self, response)
        assert_refresh_token_rejected(self, old_refresh_token)
        assert_access_token_rejected(self, old_access_token)

    def test_login_sets_auth_cookies_and_returns_access_token_only(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {
                "email": "user@example.com",
                "password": "Password123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertIn("access", response.data["data"])
        self.assertNotIn("refresh", response.data["data"])
        assert_access_cookie_set(self, response)
        assert_refresh_cookie_set(self, response)

    def test_refresh_uses_refresh_cookie_and_rotates_access_cookie(self):
        login_response = self.client.post(
            "/api/v1/auth/login/",
            {
                "email": "user@example.com",
                "password": "Password123!",
            },
            format="json",
        )
        self.assertEqual(login_response.status_code, 200)
        refresh_cookie = login_response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]
        self.client.cookies[settings.AUTH_REFRESH_COOKIE_NAME] = refresh_cookie.value

        response = self.client.post(
            "/api/v1/auth/refresh/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertIn("access", response.data["data"])
        self.assertNotIn("refresh", response.data["data"])
        assert_access_cookie_set(self, response)
        rotated_cookie = response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]
        self.assertTrue(rotated_cookie.value)
        self.assertNotEqual(rotated_cookie.value, refresh_cookie.value)

    def test_refresh_ignores_invalid_access_cookie_when_refresh_cookie_is_valid(self):
        login_response = self.client.post(
            "/api/v1/auth/login/",
            {
                "email": "user@example.com",
                "password": "Password123!",
            },
            format="json",
        )
        self.assertEqual(login_response.status_code, 200)

        self.client.cookies[settings.AUTH_ACCESS_COOKIE_NAME] = "invalid-access-token"
        self.client.cookies[settings.AUTH_REFRESH_COOKIE_NAME] = login_response.cookies[
            settings.AUTH_REFRESH_COOKIE_NAME
        ].value

        response = self.client.post(
            "/api/v1/auth/refresh/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        assert_access_cookie_set(self, response)

    def test_refresh_rotation_blacklists_previous_refresh_cookie(self):
        login_response = self.client.post(
            "/api/v1/auth/login/",
            {
                "email": "user@example.com",
                "password": "Password123!",
            },
            format="json",
        )
        self.assertEqual(login_response.status_code, 200)
        original_refresh_cookie = login_response.cookies[
            settings.AUTH_REFRESH_COOKIE_NAME
        ].value
        self.client.cookies[settings.AUTH_REFRESH_COOKIE_NAME] = original_refresh_cookie

        refresh_response = self.client.post(
            "/api/v1/auth/refresh/",
            {},
            format="json",
        )

        self.assertEqual(refresh_response.status_code, 200)
        rotated_refresh_cookie = refresh_response.cookies[
            settings.AUTH_REFRESH_COOKIE_NAME
        ].value
        self.assertNotEqual(rotated_refresh_cookie, original_refresh_cookie)

        self.client.cookies[settings.AUTH_REFRESH_COOKIE_NAME] = original_refresh_cookie
        reused_response = self.client.post(
            "/api/v1/auth/refresh/",
            {},
            format="json",
        )

        self.assertEqual(reused_response.status_code, 401)
        self.assertFalse(reused_response.data["success"])

    def test_refresh_rejects_body_token_without_refresh_cookie(self):
        login_response = self.client.post(
            "/api/v1/auth/login/",
            {
                "email": "user@example.com",
                "password": "Password123!",
            },
            format="json",
        )
        self.assertEqual(login_response.status_code, 200)
        refresh_cookie = login_response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]
        self.client.cookies.pop(settings.AUTH_REFRESH_COOKIE_NAME, None)

        response = self.client.post(
            "/api/v1/auth/refresh/",
            {
                "refresh": refresh_cookie.value,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertEqual(
            response.data["error"]["details"]["fields"]["refresh"],
            ["Refresh token cookie is missing."],
        )

    def test_logout_with_cookie_auth_blacklists_refresh_cookie_and_clears_auth_cookies(
        self,
    ):
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_token, _ = fetch_csrf_token(self, csrf_client)
        login_response = csrf_client.post(
            "/api/v1/auth/login/",
            {
                "email": "user@example.com",
                "password": "Password123!",
            },
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(login_response.status_code, 200)
        refreshed_csrf_token, _ = fetch_csrf_token(self, csrf_client)

        response = csrf_client.post(
            "/api/v1/auth/logout/",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=refreshed_csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.cookies[settings.AUTH_ACCESS_COOKIE_NAME]["path"],
            settings.AUTH_ACCESS_COOKIE_PATH,
        )
        self.assertEqual(
            response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]["path"],
            settings.AUTH_REFRESH_COOKIE_PATH,
        )
        assert_auth_cookies_cleared(self, response)

    @patch.object(
        settings, "FRONTEND_PASSWORD_RESET_URL", "http://localhost:3000/reset-password"
    )
    def test_password_reset_request_and_confirm_clears_auth_cookies(self):
        login_response = self.client.post(
            "/api/v1/auth/login/",
            {
                "email": "user@example.com",
                "password": "Password123!",
            },
            format="json",
        )
        self.assertEqual(login_response.status_code, 200)
        old_access_token = login_response.data["data"]["access"]
        old_refresh_token = login_response.cookies[
            settings.AUTH_REFRESH_COOKIE_NAME
        ].value

        response = self.client.post(
            "/api/v1/auth/password/reset/request/",
            {"email": "user@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        token = self._extract_token(mail.outbox[0].body)

        confirm_response = self.client.post(
            "/api/v1/auth/password/reset/confirm/",
            {
                "token": token,
                "new_password": "ChangedPassword123!",
            },
            format="json",
        )

        self.assertEqual(confirm_response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("ChangedPassword123!"))
        assert_auth_cookies_cleared(self, confirm_response)
        assert_refresh_token_rejected(self, old_refresh_token)
        assert_access_token_rejected(self, old_access_token)

    @patch.object(
        settings, "FRONTEND_PASSWORD_RESET_URL", "http://localhost:3000/reset-password"
    )
    def test_password_reset_confirm_rejects_weak_password(self):
        response = self.client.post(
            "/api/v1/auth/password/reset/request/",
            {"email": "user@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        token = self._extract_token(mail.outbox[0].body)

        confirm_response = self.client.post(
            "/api/v1/auth/password/reset/confirm/",
            {
                "token": token,
                "new_password": "changedpassword123",
            },
            format="json",
        )

        self.assertEqual(confirm_response.status_code, 400)
        self.assertFalse(confirm_response.data["success"])
        self.assertEqual(
            confirm_response.data["error"]["details"]["fields"]["new_password"],
            [
                "Password must contain at least one uppercase letter.",
                "Password must contain at least one special character.",
            ],
        )

    @patch.object(
        settings,
        "FRONTEND_EMAIL_VERIFICATION_URL",
        "http://localhost:3000/verify-email",
    )
    def test_email_verification_request_and_confirm(self):
        self.client.force_authenticate(user=self.user)

        request_response = self.client.post(
            "/api/v1/auth/email/verify/request/",
            {},
            format="json",
        )

        self.assertEqual(request_response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        token = self._extract_token(mail.outbox[0].body)

        confirm_response = self.client.post(
            "/api/v1/auth/email/verify/confirm/",
            {"token": token},
            format="json",
        )

        self.assertEqual(confirm_response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_verified)

    def test_admin_user_list_create_and_group_assignment(self):
        self.client.force_authenticate(user=self.admin)

        create_response = self.client.post(
            "/api/v1/users/",
            {
                "email": "created@example.com",
                "password": "CreatedPassword123!",
                "first_name": "Created",
                "last_name": "User",
                "groups": ["editor"],
            },
            format="json",
        )

        self.assertEqual(create_response.status_code, 201)
        created_user_id = create_response.data["data"]["id"]

        list_response = self.client.get("/api/v1/users/?group=editor")
        self.assertEqual(list_response.status_code, 200)
        self.assertGreaterEqual(
            list_response.data["data"]["pagination"]["total_items"], 1
        )

        group_response = self.client.post(
            f"/api/v1/users/{created_user_id}/groups/",
            {"groups": ["developer"]},
            format="json",
        )
        self.assertEqual(group_response.status_code, 200)
        created_user = User.objects.get(pk=created_user_id)
        self.assertEqual(
            set(created_user.groups.values_list("name", flat=True)),
            {"developer", "user"},
        )

    def test_admin_user_create_rejects_weak_password(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            "/api/v1/users/",
            {
                "email": "weak-created@example.com",
                "password": "createdpassword123",
                "first_name": "Created",
                "last_name": "User",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertEqual(
            response.data["error"]["details"]["fields"]["password"],
            [
                "Password must contain at least one uppercase letter.",
                "Password must contain at least one special character.",
            ],
        )

    def test_group_permission_helper_assigns_gateway_permissions(self):
        developer_group, missing = ensure_group_permissions("developer")

        self.assertEqual(missing, [])
        self.assertTrue(
            developer_group.permissions.filter(codename="view_apikey").exists()
        )

    def test_ensure_group_permissions_rejects_unknown_group_names(self):
        with self.assertRaises(ValueError):
            ensure_group_permissions("not_a_valid_role")

    def test_sync_user_groups_preserves_custom_group_permissions(self):
        permission = Permission.objects.filter(codename="view_dataset").first()
        custom_group = Group.objects.create(name="custom_role")
        custom_group.permissions.add(permission)

        user = User.objects.create_user(
            email="custom-role@example.com",
            password="Password123!",
            first_name="Custom",
            last_name="Role",
        )

        sync_user_groups(user, [custom_group])

        custom_group.refresh_from_db()
        self.assertTrue(
            custom_group.permissions.filter(codename="view_dataset").exists()
        )
        self.assertSetEqual(
            set(user.groups.values_list("name", flat=True)),
            {"custom_role", "user"},
        )

    def test_admin_can_deactivate_and_reactivate_user(self):
        login_response = self.client.post(
            "/api/v1/auth/login/",
            {
                "email": "user@example.com",
                "password": "Password123!",
            },
            format="json",
        )
        self.assertEqual(login_response.status_code, 200)
        old_access_token = login_response.data["data"]["access"]
        old_refresh_token = login_response.cookies[
            settings.AUTH_REFRESH_COOKIE_NAME
        ].value

        self.client.force_authenticate(user=self.admin)

        deactivate_response = self.client.post(
            f"/api/v1/users/{self.user.id}/deactivate/",
            {},
            format="json",
        )
        self.assertEqual(deactivate_response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        assert_refresh_token_rejected(self, old_refresh_token)
        assert_access_token_rejected(self, old_access_token)

        reactivate_response = self.client.post(
            f"/api/v1/users/{self.user.id}/reactivate/",
            {},
            format="json",
        )
        self.assertEqual(reactivate_response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        assert_access_token_rejected(self, old_access_token)

    def test_admin_dashboard_summary_returns_platform_counts(self):
        category = Category.objects.create(name="Economy", slug="economy")
        Dataset.objects.create(
            publisher_user=self.user,
            category=category,
            slug="admin-summary-draft",
            status=DatasetStatus.DRAFT,
            visibility=False,
        )
        Dataset.objects.create(
            publisher_user=self.user,
            category=category,
            slug="admin-summary-published",
            status=DatasetStatus.PUBLISHED,
            visibility=True,
        )
        deleted_dataset = Dataset.objects.create(
            publisher_user=self.user,
            category=category,
            slug="admin-summary-deleted",
            status=DatasetStatus.REJECTED,
            visibility=False,
        )
        deleted_dataset.delete()

        consumer = APIConsumer.objects.create(
            user=self.user,
            name="Admin Summary Consumer",
            consumer_type="developer",
            email=self.user.email,
            status="active",
        )
        api_key, _ = issue_api_key(consumer=consumer, name="Summary Key")
        APIUsageLog.objects.create(
            api_key=api_key,
            consumer=consumer,
            endpoint="/api/v1/gateway/datasets/",
            method="GET",
            status_code=200,
        )
        APIUsageLog.objects.create(
            api_key=api_key,
            consumer=consumer,
            endpoint="/api/v1/gateway/files/data/",
            method="GET",
            status_code=500,
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/v1/admin/dashboard/summary/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        payload = response.data["data"]
        self.assertEqual(payload["users"]["total"], 2)
        self.assertEqual(payload["datasets"]["total"], 3)
        self.assertEqual(payload["datasets"]["active"], 2)
        self.assertEqual(payload["datasets"]["deleted"], 1)
        self.assertEqual(payload["datasets"]["draft"], 1)
        self.assertEqual(payload["datasets"]["published"], 1)
        self.assertEqual(payload["api"]["consumers_total"], 1)
        self.assertEqual(payload["api"]["api_keys_total"], 1)
        self.assertEqual(payload["api"]["requests_total"], 2)
        self.assertEqual(payload["api"]["error_requests_last_24h"], 1)
        self.assertEqual(payload["activity"]["api_usage_logs_total"], 2)

    def test_admin_activity_returns_recent_dataset_and_api_events(self):
        category = Category.objects.create(name="Health", slug="health")
        dataset = Dataset.objects.create(
            publisher_user=self.user,
            category=category,
            slug="admin-activity-dataset",
            status=DatasetStatus.APPROVED,
            visibility=False,
        )
        DatasetAuditLog.objects.create(
            dataset=dataset,
            actor=self.admin,
            action="dataset_review_approved",
            target_model="datasets.dataset",
            target_id=dataset.id,
            details={"reason": "Approved by admin."},
        )

        consumer = APIConsumer.objects.create(
            user=self.user,
            name="Admin Activity Consumer",
            consumer_type="developer",
            email=self.user.email,
            status="active",
        )
        api_key, _ = issue_api_key(consumer=consumer, name="Activity Key")
        APIUsageLog.objects.create(
            api_key=api_key,
            consumer=consumer,
            endpoint="/api/v1/gateway/datasets/",
            method="GET",
            status_code=200,
            dataset_id=dataset.id,
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/v1/admin/activity/?page_size=10")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        payload = response.data["data"]
        self.assertGreaterEqual(payload["pagination"]["total_items"], 2)
        activity_types = {item["activity_type"] for item in payload["items"]}
        self.assertIn("dataset_audit", activity_types)
        self.assertIn("api_usage", activity_types)
        dataset_audit_entry = next(
            item
            for item in payload["items"]
            if item["activity_type"] == "dataset_audit"
        )
        self.assertEqual(dataset_audit_entry["dataset_slug"], "admin-activity-dataset")
        api_usage_entry = next(
            item for item in payload["items"] if item["activity_type"] == "api_usage"
        )
        self.assertEqual(api_usage_entry["dataset_slug"], "admin-activity-dataset")

    def test_admin_dashboard_aggregation_endpoints_return_expected_metrics(self):
        category = Category.objects.create(name="Transport", slug="transport")
        dataset = Dataset.objects.create(
            publisher_user=self.user,
            category=category,
            slug="admin-metrics-dataset",
            status=DatasetStatus.PUBLISHED,
            visibility=True,
        )
        other_dataset = Dataset.objects.create(
            publisher_user=self.user,
            category=category,
            slug="admin-metrics-dataset-two",
            status=DatasetStatus.APPROVED,
            visibility=False,
        )

        consumer = APIConsumer.objects.create(
            user=self.user,
            name="Metrics Consumer",
            consumer_type="developer",
            email=self.user.email,
            status="active",
        )
        api_key, _ = issue_api_key(consumer=consumer, name="Metrics Key")
        APIUsageLog.objects.create(
            api_key=api_key,
            consumer=consumer,
            endpoint="/api/v1/gateway/datasets/",
            method="GET",
            status_code=200,
            response_time_ms=120,
        )
        APIUsageLog.objects.create(
            api_key=api_key,
            consumer=consumer,
            endpoint=f"/api/v1/gateway/datasets/{dataset.slug}/",
            method="GET",
            status_code=500,
            response_time_ms=240,
        )

        DatasetAuditLog.objects.create(
            dataset=dataset,
            actor=self.admin,
            action="file_downloaded",
            target_model="datasets.datasetfile",
            target_id=uuid.uuid4(),
            details={},
        )
        DatasetAuditLog.objects.create(
            dataset=dataset,
            actor=None,
            action="file_downloaded",
            target_model="datasets.datasetfile",
            target_id=uuid.uuid4(),
            details={},
        )
        DatasetAuditLog.objects.create(
            dataset=dataset,
            actor=self.user,
            action="file_previewed",
            target_model="datasets.datasetfile",
            target_id=uuid.uuid4(),
            details={},
        )
        DatasetAuditLog.objects.create(
            dataset=dataset,
            actor=self.user,
            action="file_data_accessed",
            target_model="datasets.datasetfile",
            target_id=uuid.uuid4(),
            details={},
        )
        DatasetAuditLog.objects.create(
            dataset=other_dataset,
            actor=self.admin,
            action="file_schema_accessed",
            target_model="datasets.datasetfile",
            target_id=uuid.uuid4(),
            details={},
        )
        DatasetAuditLog.objects.create(
            dataset=dataset,
            actor=self.admin,
            action="dataset_created",
            target_model="datasets.dataset",
            target_id=dataset.id,
            details={},
        )
        DatasetAuditLog.objects.create(
            dataset=dataset,
            actor=self.admin,
            action="dataset_review_submitted",
            target_model="datasets.dataset",
            target_id=dataset.id,
            details={},
        )
        DatasetAuditLog.objects.create(
            dataset=dataset,
            actor=self.admin,
            action="dataset_review_approved",
            target_model="datasets.dataset",
            target_id=dataset.id,
            details={},
        )
        DatasetAuditLog.objects.create(
            dataset=dataset,
            actor=self.admin,
            action="metadata_updated",
            target_model="datasets.datasetmetadata",
            target_id=uuid.uuid4(),
            details={},
        )
        DatasetAuditLog.objects.create(
            dataset=dataset,
            actor=self.admin,
            action="tag_linked",
            target_model="datasets.datasettag",
            target_id=uuid.uuid4(),
            details={},
        )
        DatasetAuditLog.objects.create(
            dataset=dataset,
            actor=self.admin,
            action="version_created",
            target_model="datasets.datasetversion",
            target_id=uuid.uuid4(),
            details={},
        )
        DatasetAuditLog.objects.create(
            dataset=dataset,
            actor=self.admin,
            action="file_validated",
            target_model="datasets.datasetfile",
            target_id=uuid.uuid4(),
            details={},
        )

        self.client.force_authenticate(user=self.admin)

        api_calls_response = self.client.get(
            "/api/v1/admin/dashboard/api-calls/summary/?days=7"
        )
        self.assertEqual(api_calls_response.status_code, 200)
        api_calls_payload = api_calls_response.data["data"]
        self.assertEqual(api_calls_payload["days"], 7)
        self.assertEqual(api_calls_payload["totals"]["total_requests"], 2)
        self.assertEqual(api_calls_payload["totals"]["success_requests"], 1)
        self.assertEqual(api_calls_payload["totals"]["error_requests"], 1)
        self.assertEqual(api_calls_payload["totals"]["unique_consumers"], 1)
        self.assertEqual(api_calls_payload["totals"]["unique_api_keys"], 1)
        self.assertEqual(api_calls_payload["totals"]["average_response_time_ms"], 180.0)
        self.assertEqual(len(api_calls_payload["by_day"]), 7)
        self.assertEqual(api_calls_payload["top_endpoints"][0]["request_count"], 1)

        downloads_response = self.client.get(
            "/api/v1/admin/dashboard/downloads/summary/?days=7"
        )
        self.assertEqual(downloads_response.status_code, 200)
        downloads_payload = downloads_response.data["data"]
        self.assertEqual(downloads_payload["totals"]["total_downloads"], 2)
        self.assertEqual(downloads_payload["totals"]["unique_datasets"], 1)
        self.assertEqual(downloads_payload["totals"]["unique_files"], 2)
        self.assertEqual(downloads_payload["totals"]["authenticated_downloads"], 1)
        self.assertEqual(downloads_payload["totals"]["anonymous_downloads"], 1)
        self.assertEqual(
            downloads_payload["top_datasets"][0]["dataset_slug"], dataset.slug
        )
        self.assertEqual(downloads_payload["top_datasets"][0]["count"], 2)

        views_response = self.client.get(
            "/api/v1/admin/dashboard/views/summary/?days=7"
        )
        self.assertEqual(views_response.status_code, 200)
        views_payload = views_response.data["data"]
        self.assertEqual(views_payload["totals"]["total_views"], 3)
        self.assertEqual(views_payload["totals"]["unique_datasets"], 2)
        self.assertEqual(views_payload["totals"]["unique_files"], 3)
        self.assertEqual(views_payload["totals"]["preview_views"], 1)
        self.assertEqual(views_payload["totals"]["data_views"], 1)
        self.assertEqual(views_payload["totals"]["schema_views"], 1)
        self.assertEqual(views_payload["top_datasets"][0]["dataset_slug"], dataset.slug)
        self.assertEqual(views_payload["top_datasets"][0]["count"], 2)

        dataset_activity_response = self.client.get(
            "/api/v1/admin/dashboard/datasets/activity/summary/?days=7"
        )
        self.assertEqual(dataset_activity_response.status_code, 200)
        dataset_activity_payload = dataset_activity_response.data["data"]
        self.assertEqual(dataset_activity_payload["totals"]["total_events"], 7)
        self.assertEqual(dataset_activity_payload["totals"]["unique_datasets"], 1)
        self.assertEqual(dataset_activity_payload["totals"]["dataset_events"], 1)
        self.assertEqual(dataset_activity_payload["totals"]["workflow_events"], 2)
        self.assertEqual(dataset_activity_payload["totals"]["file_events"], 1)
        self.assertEqual(dataset_activity_payload["totals"]["metadata_events"], 1)
        self.assertEqual(dataset_activity_payload["totals"]["tag_events"], 1)
        self.assertEqual(dataset_activity_payload["totals"]["version_events"], 1)
        self.assertEqual(dataset_activity_payload["by_action"][0]["count"], 1)
        self.assertEqual(
            dataset_activity_payload["top_datasets"][0]["dataset_slug"],
            dataset.slug,
        )
        self.assertEqual(dataset_activity_payload["top_datasets"][0]["count"], 7)

    def test_admin_activity_and_summary_require_admin_permissions(self):
        self.client.force_authenticate(user=self.user)

        protected_paths = (
            "/api/v1/admin/activity/",
            "/api/v1/admin/dashboard/summary/",
            "/api/v1/admin/dashboard/api-calls/summary/",
            "/api/v1/admin/dashboard/downloads/summary/",
            "/api/v1/admin/dashboard/views/summary/",
            "/api/v1/admin/dashboard/datasets/activity/summary/",
        )

        for path in protected_paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 403)

    def _extract_token(self, body):
        match = re.search(r"Token:\s*(\S+)", body)
        self.assertIsNotNone(match)
        return match.group(1)
