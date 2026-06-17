from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Category, Dataset, DatasetAuditLog, DatasetStatus, Tag


class DatasetWorkflowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_dir = TemporaryDirectory()
        cls.media_override = override_settings(MEDIA_ROOT=cls.media_dir.name)
        cls.media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls.media_override.disable()
        cls.media_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.client = APIClient()
        self.user_model = get_user_model()

        self.category = Category.objects.create(name="Climate", slug="climate")
        self.tag = Tag.objects.create(name="Open Data", slug="open-data")

        self.editor = self.user_model.objects.create_user(
            email="editor@example.com",
            password="password123",
        )
        self.admin = self.user_model.objects.create_user(
            email="admin@example.com",
            password="password123",
        )
        self.viewer = self.user_model.objects.create_user(
            email="viewer@example.com",
            password="password123",
        )

        editor_group, _ = Group.objects.get_or_create(name="editor")
        admin_group, _ = Group.objects.get_or_create(name="admin")
        viewer_group, _ = Group.objects.get_or_create(name="user")
        self.editor.groups.add(editor_group)
        self.admin.groups.add(admin_group)
        self.viewer.groups.add(viewer_group)

        permission_sets = {
            editor_group: (
                "datasets.view_dataset",
                "datasets.add_dataset",
                "datasets.change_dataset",
                "datasets.delete_dataset",
            ),
            admin_group: (
                "datasets.view_dataset",
                "datasets.view_all_dataset",
                "datasets.add_dataset",
                "datasets.change_dataset",
                "datasets.delete_dataset",
                "datasets.review_dataset",
                "datasets.publish_dataset",
            ),
            viewer_group: (
                "datasets.view_dataset",
            ),
        }
        for group, permission_labels in permission_sets.items():
            permissions = [
                Permission.objects.get(
                    content_type__app_label=app_label,
                    codename=codename,
                )
                for app_label, codename in (
                    label.split(".", 1) for label in permission_labels
                )
            ]
            group.permissions.set(permissions)

    def create_draft_dataset(self, slug="climate-draft"):
        self.client.force_authenticate(user=self.editor)
        response = self.client.post(
            "/dataset/",
            {
                "category": str(self.category.id),
                "slug": slug,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        return Dataset.objects.get(slug=slug)

    def upload_valid_file(self, dataset, filename="climate.csv"):
        self.client.force_authenticate(user=self.editor)
        response = self.client.post(
            "/dataset/files/",
            {
                "dataset_id": str(dataset.id),
                "file": SimpleUploadedFile(
                    filename,
                    b"country,value\nTZ,10\n",
                    content_type="text/csv",
                ),
                "is_primary": True,
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201)
        return response

    def add_metadata(self, dataset):
        self.client.force_authenticate(user=self.editor)
        response = self.client.post(
            "/dataset/metadata/",
            {
                "dataset_id": str(dataset.id),
                "title": "Climate Statistics",
                "description": "Annual climate observations.",
                "license": "CC-BY-4.0",
                "frequency": "annual",
                "region": "East Africa",
                "year": 2024,
                "publisher_name": "SmartHub Data Office",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def add_tag(self, dataset):
        self.client.force_authenticate(user=self.editor)
        response = self.client.post(
            "/dataset/tag-links/",
            {
                "dataset_id": str(dataset.id),
                "tag_id": str(self.tag.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def make_dataset_ready_for_review(self, slug="review-ready-dataset"):
        dataset = self.create_draft_dataset(slug=slug)
        self.upload_valid_file(dataset)
        self.add_metadata(dataset)
        self.add_tag(dataset)
        dataset.refresh_from_db()
        return dataset

    def submit_for_review(self, dataset):
        self.client.force_authenticate(user=self.editor)
        return self.client.post(
            f"/dataset/{dataset.id}/submit-review/",
            {"reason": "Ready for admin review."},
            format="json",
        )

    def approve_dataset(self, dataset):
        self.client.force_authenticate(user=self.admin)
        return self.client.post(
            f"/dataset/{dataset.id}/review/",
            {"action": "approve", "reason": "Checks passed."},
            format="json",
        )

    def publish_dataset(self, dataset):
        self.client.force_authenticate(user=self.admin)
        return self.client.post(
            f"/dataset/{dataset.id}/publish/",
            {"reason": "Publishing approved dataset."},
            format="json",
        )

    def test_editor_creates_draft_and_submission_requires_complete_dataset(self):
        dataset = self.create_draft_dataset()

        self.client.force_authenticate(user=self.editor)
        response = self.client.post(
            f"/dataset/{dataset.id}/submit-review/",
            {"reason": "Attempting early review."},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertIn("metadata", response.data["error"]["details"]["fields"])
        dataset.refresh_from_db()
        self.assertEqual(dataset.status, DatasetStatus.DRAFT)

    def test_upload_file_validates_and_auto_creates_initial_version(self):
        dataset = self.create_draft_dataset(slug="file-validation-draft")

        response = self.upload_valid_file(dataset, filename="climate-data.csv")

        self.assertTrue(response.data["success"])
        payload = response.data["data"]
        self.assertEqual(payload["file_format"], "csv")
        self.assertEqual(payload["validation_status"], "validated")
        self.assertTrue(payload["is_safe"])
        self.assertEqual(len(payload["checksum"]), 64)

        dataset.refresh_from_db()
        self.assertEqual(dataset.versions.count(), 1)
        self.assertEqual(dataset.versions.first().version_number, "1.0")

    def test_invalid_file_type_is_rejected(self):
        dataset = self.create_draft_dataset(slug="bad-file-draft")

        self.client.force_authenticate(user=self.editor)
        response = self.client.post(
            "/dataset/files/",
            {
                "dataset_id": str(dataset.id),
                "file": SimpleUploadedFile(
                    "payload.exe",
                    b"not-allowed",
                    content_type="application/octet-stream",
                ),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"]["code"], "validation_error")

    def test_editor_can_submit_complete_dataset_but_cannot_publish(self):
        dataset = self.make_dataset_ready_for_review()

        response = self.submit_for_review(dataset)
        self.assertEqual(response.status_code, 200)
        dataset.refresh_from_db()
        self.assertEqual(dataset.status, DatasetStatus.IN_REVIEW)

        self.client.force_authenticate(user=self.editor)
        publish_response = self.client.post(
            f"/dataset/{dataset.id}/publish/",
            {"reason": "Trying to bypass review."},
            format="json",
        )
        self.assertEqual(publish_response.status_code, 403)

    def test_admin_can_review_publish_and_public_can_discover_and_download(self):
        dataset = self.make_dataset_ready_for_review(slug="public-climate-data")
        submit_response = self.submit_for_review(dataset)
        self.assertEqual(submit_response.status_code, 200)

        approve_response = self.approve_dataset(dataset)
        self.assertEqual(approve_response.status_code, 200)
        dataset.refresh_from_db()
        self.assertEqual(dataset.status, DatasetStatus.APPROVED)

        publish_response = self.publish_dataset(dataset)
        self.assertEqual(publish_response.status_code, 200)
        dataset.refresh_from_db()
        self.assertEqual(dataset.status, DatasetStatus.PUBLISHED)
        self.assertTrue(dataset.visibility)

        self.client.force_authenticate(user=None)
        discovery_response = self.client.get(
            "/dataset/",
            {
                "q": "climate",
                "region": "East Africa",
                "year": 2024,
                "frequency": "annual",
                "tag": "open-data",
            },
        )
        self.assertEqual(discovery_response.status_code, 200)
        self.assertEqual(len(discovery_response.data["data"]), 1)
        self.assertEqual(discovery_response.data["data"][0]["slug"], "public-climate-data")

        detail_response = self.client.get(f"/dataset/{dataset.id}/")
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.data["data"]["status"], DatasetStatus.PUBLISHED)
        self.assertEqual(detail_response.data["data"]["metadata"][0]["region"], "East Africa")
        self.assertEqual(detail_response.data["data"]["metadata"][0]["frequency"], "annual")

        dataset_file = dataset.versions.first().files.first()
        download_response = self.client.get(f"/dataset/files/{dataset_file.id}/download/")
        self.assertEqual(download_response.status_code, 200)
        self.assertIn("attachment;", download_response.headers["Content-Disposition"])

        actions = set(DatasetAuditLog.objects.filter(dataset=dataset).values_list("action", flat=True))
        self.assertIn("dataset_review_submitted", actions)
        self.assertIn("dataset_review_approved", actions)
        self.assertIn("dataset_published", actions)
        self.assertIn("file_downloaded", actions)

    def test_audit_logs_are_visible_to_owner_and_admin_only(self):
        dataset = self.make_dataset_ready_for_review(slug="audited-dataset")

        self.client.force_authenticate(user=self.editor)
        owner_response = self.client.get("/dataset/audit-logs/")
        self.assertEqual(owner_response.status_code, 200)
        self.assertTrue(owner_response.data["success"])
        self.assertGreater(len(owner_response.data["data"]), 0)
        self.assertTrue(
            any(
                str(item["dataset"]) == str(dataset.id)
                for item in owner_response.data["data"]
            )
        )

        self.client.force_authenticate(user=self.viewer)
        viewer_response = self.client.get("/dataset/audit-logs/")
        self.assertEqual(viewer_response.status_code, 200)
        self.assertEqual(viewer_response.data["data"], [])

    def test_dataset_delete_is_soft_and_hides_dataset_and_related_records(self):
        dataset = self.make_dataset_ready_for_review(slug="soft-delete-dataset")
        dataset_file = dataset.versions.first().files.first()

        self.client.force_authenticate(user=self.editor)
        response = self.client.delete(f"/dataset/{dataset.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])

        dataset.refresh_from_db()
        self.assertIsNotNone(dataset.deleted_at)
        self.assertFalse(Dataset.objects.filter(id=dataset.id).exists())
        self.assertTrue(Dataset.all_objects.filter(id=dataset.id).exists())

        self.client.force_authenticate(user=self.editor)
        detail_response = self.client.get(f"/dataset/{dataset.id}/")
        self.assertEqual(detail_response.status_code, 404)

        related_response = self.client.get(f"/dataset/files/{dataset_file.id}/")
        self.assertEqual(related_response.status_code, 404)

        audit_response = self.client.get("/dataset/audit-logs/")
        self.assertEqual(audit_response.status_code, 200)
        self.assertEqual(audit_response.data["data"], [])

        self.client.force_authenticate(user=None)
        public_response = self.client.get("/dataset/")
        self.assertEqual(public_response.status_code, 200)
        self.assertEqual(public_response.data["data"], [])

    def test_category_delete_is_blocked_when_dataset_references_it(self):
        self.create_draft_dataset(slug="protected-category-draft")

        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(f"/dataset/categories/{self.category.id}/")

        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"]["code"], "protected_resource")
