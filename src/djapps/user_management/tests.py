from django.test import TestCase
from rest_framework.test import APIClient


class APIResponseFormatTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_success_uses_standard_success_response(self):
        response = self.client.post(
            "/api/auth/register/",
            {
                "email": "format-test@example.com",
                "password": "password123",
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

    def test_validation_errors_include_request_id_and_standard_structure(self):
        response = self.client.post(
            "/api/auth/register/",
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
