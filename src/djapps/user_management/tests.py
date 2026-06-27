import re
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.conf import settings
from django.core import mail
from django.test import TestCase
from rest_framework.test import APIClient
from .models import User
from .roles import ensure_group_permissions


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
        self.assertIn("refresh", response.data["data"])
        created_user = User.objects.get(email="format-test@example.com")
        self.assertIn("user", created_user.groups.values_list("name", flat=True))

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
        self.assertIn("refresh", response.data["data"])
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
    @patch.object(settings, "GITHUB_OAUTH_ALLOWED_REDIRECT_URIS", ("http://localhost:3000/auth/github/callback",))
    @patch.object(settings, "GITHUB_OAUTH_CLIENT_ID", "github-client-id")
    @patch.object(settings, "GITHUB_OAUTH_CLIENT_SECRET", "github-client-secret")
    def test_exchange_rejects_redirect_uri_outside_allowlist(self, _urlopen):
        from djapps.user_management.api.social import exchange_github_code_for_access_token
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


class UserManagementFeatureTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="user@example.com",
            password="password123",
            first_name="Normal",
            last_name="User",
        )
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="password123",
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

    def test_change_password_updates_password_hash(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            "/api/v1/auth/password/change/",
            {
                "current_password": "password123",
                "new_password": "newpassword123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("newpassword123"))

    @patch.object(settings, "FRONTEND_PASSWORD_RESET_URL", "http://localhost:3000/reset-password")
    def test_password_reset_request_and_confirm(self):
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

        self.assertEqual(confirm_response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("changedpassword123"))

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
                "password": "createdpassword123",
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
        self.assertGreaterEqual(list_response.data["data"]["pagination"]["total_items"], 1)

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

    def test_group_permission_helper_assigns_gateway_permissions(self):
        developer_group, missing = ensure_group_permissions("developer")

        self.assertEqual(missing, [])
        self.assertTrue(
            developer_group.permissions.filter(codename="view_apikey").exists()
        )

    def test_admin_can_deactivate_and_reactivate_user(self):
        self.client.force_authenticate(user=self.admin)

        deactivate_response = self.client.post(
            f"/api/v1/users/{self.user.id}/deactivate/",
            {},
            format="json",
        )
        self.assertEqual(deactivate_response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

        reactivate_response = self.client.post(
            f"/api/v1/users/{self.user.id}/reactivate/",
            {},
            format="json",
        )
        self.assertEqual(reactivate_response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def _extract_token(self, body):
        match = re.search(r"Token:\s*(\S+)", body)
        self.assertIsNotNone(match)
        return match.group(1)
