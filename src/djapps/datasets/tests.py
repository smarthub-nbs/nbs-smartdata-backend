import io
import json
import os
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from pypdf import PdfWriter
from rest_framework.test import APIClient
import xlwt

from .models import (
    Category,
    Dataset,
    DatasetAuditLog,
    DatasetBulkActionJob,
    DatasetBulkActionJobStatus,
    DatasetBulkUploadJob,
    DatasetBulkUploadJobItem,
    DatasetBulkUploadJobStatus,
    DatasetFile,
    DatasetMetadata,
    DatasetStatus,
    DatasetTag,
    DatasetVersion,
    FileValidationStatus,
    Tag,
)
from djapps.datasets.tasks import run_bulk_upload_job
from djapps.user_management.roles import ensure_group_permissions


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    ALLOWED_HOSTS=[
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "pixyish-chae-doziest.ngrok-free.dev",
        "testserver",
    ],
)
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
            password="Password123!",
            first_name="Data",
            last_name="Editor",
        )
        self.admin = self.user_model.objects.create_user(
            email="admin@example.com",
            password="Password123!",
            first_name="System",
            last_name="Admin",
        )
        self.viewer = self.user_model.objects.create_user(
            email="viewer@example.com",
            password="Password123!",
        )
        self.editor_two = self.user_model.objects.create_user(
            email="editor-two@example.com",
            password="Password123!",
            first_name="Second",
            last_name="Editor",
        )

        editor_group, _ = ensure_group_permissions("editor")
        admin_group, _ = ensure_group_permissions("admin")
        viewer_group, _ = ensure_group_permissions("user")
        self.editor.groups.add(editor_group)
        self.editor_two.groups.add(editor_group)
        self.admin.groups.add(admin_group)
        self.viewer.groups.add(viewer_group)

    def create_draft_dataset(self, slug="climate-draft"):
        self.client.force_authenticate(user=self.editor)
        payload = {
            "category": str(self.category.id),
        }
        if slug is not None:
            payload["slug"] = slug
        response = self.client.post("/api/v1/dataset/", payload, format="json")
        self.assertEqual(response.status_code, 201)
        return Dataset.objects.get(id=response.data["data"]["id"])

    def upload_valid_file(self, dataset, filename="climate.csv"):
        self.client.force_authenticate(user=self.editor)
        response = self.client.post(
            "/api/v1/dataset/files/",
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

    def validate_dataset_file(self, dataset_file_id, user=None, validation_notes=""):
        self.client.force_authenticate(user=user or self.admin)
        payload = {}
        if validation_notes != "":
            payload["validation_notes"] = validation_notes
        return self.client.post(
            f"/api/v1/dataset/files/{dataset_file_id}/validate/",
            payload,
            format="json",
        )

    def upload_file(self, dataset, filename, content, content_type, is_primary=True):
        self.client.force_authenticate(user=self.editor)
        response = self.client.post(
            "/api/v1/dataset/files/",
            {
                "dataset_id": str(dataset.id),
                "file": SimpleUploadedFile(
                    filename,
                    content,
                    content_type=content_type,
                ),
                "is_primary": is_primary,
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201)
        return response

    def build_xls_content(self):
        workbook = xlwt.Workbook()
        sheet = workbook.add_sheet("Sheet1")
        sheet.write(0, 0, "country")
        sheet.write(0, 1, "value")
        sheet.write(1, 0, "TZ")
        sheet.write(1, 1, 10)
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    def build_pdf_content(self):
        buffer = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=144)
        writer.write(buffer)
        return buffer.getvalue()

    def add_metadata(self, dataset):
        self.client.force_authenticate(user=self.editor)
        response = self.client.post(
            "/api/v1/dataset/metadata/",
            {
                "dataset_id": str(dataset.id),
                "title": "Climate Statistics",
                "description": "Annual climate observations.",
                "license": "CC-BY-4.0",
                "frequency": "annual",
                "region": "East Africa",
                "year": 2024,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["data"]["publisher_name"], "Data Editor")

    def add_tag(self, dataset):
        self.client.force_authenticate(user=self.editor)
        response = self.client.post(
            "/api/v1/dataset/tag-links/",
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
            f"/api/v1/dataset/{dataset.id}/submit-review/",
            {"reason": "Ready for admin review."},
            format="json",
        )

    def approve_dataset(self, dataset):
        self.client.force_authenticate(user=self.admin)
        return self.client.post(
            f"/api/v1/dataset/{dataset.id}/review/",
            {"action": "approve", "reason": "Checks passed."},
            format="json",
        )

    def publish_dataset(self, dataset):
        self.client.force_authenticate(user=self.admin)
        return self.client.post(
            f"/api/v1/dataset/{dataset.id}/publish/",
            {"reason": "Publishing approved dataset."},
            format="json",
        )

    def unpublish_dataset(self, dataset):
        self.client.force_authenticate(user=self.admin)
        return self.client.post(
            f"/api/v1/dataset/{dataset.id}/unpublish/",
            {"reason": "Temporarily withdrawing dataset."},
            format="json",
        )

    def restore_dataset(self, dataset, user=None):
        self.client.force_authenticate(user=user or self.editor)
        return self.client.post(
            f"/api/v1/dataset/{dataset.id}/restore/",
            {"reason": "Restoring deleted dataset."},
            format="json",
        )

    def transfer_dataset_owner(self, dataset, new_owner, user=None):
        self.client.force_authenticate(user=user or self.admin)
        return self.client.post(
            f"/api/v1/dataset/{dataset.id}/transfer-owner/",
            {
                "new_owner_id": str(new_owner.id),
                "reason": "Reassigning dataset ownership.",
            },
            format="json",
        )

    def test_editor_creates_draft_and_submission_requires_complete_dataset(self):
        dataset = self.create_draft_dataset()

        self.client.force_authenticate(user=self.editor)
        response = self.client.post(
            f"/api/v1/dataset/{dataset.id}/submit-review/",
            {"reason": "Attempting early review."},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertIn("metadata", response.data["error"]["details"]["fields"])
        dataset.refresh_from_db()
        self.assertEqual(dataset.status, DatasetStatus.DRAFT)

    def test_category_and_tag_creation_auto_generate_unique_slugs(self):
        self.client.force_authenticate(user=self.admin)

        category_response = self.client.post(
            "/api/v1/dataset/categories/",
            {"name": "Population"},
            format="json",
        )
        self.assertEqual(category_response.status_code, 201)
        self.assertEqual(category_response.data["data"]["slug"], "population")

        duplicate_category_response = self.client.post(
            "/api/v1/dataset/categories/",
            {"name": "Population"},
            format="json",
        )
        self.assertEqual(duplicate_category_response.status_code, 201)
        self.assertEqual(
            duplicate_category_response.data["data"]["slug"], "population-2"
        )

        tag_response = self.client.post(
            "/api/v1/dataset/tags/",
            {"name": "Open Health"},
            format="json",
        )
        self.assertEqual(tag_response.status_code, 201)
        self.assertEqual(tag_response.data["data"]["slug"], "open-health")

    def test_admin_queue_returns_paginated_dataset_status_overview(self):
        economy = Category.objects.create(name="Economy", slug="economy")
        queue_dataset = Dataset.objects.create(
            publisher_user=self.editor,
            category=economy,
            slug="national-budget-2024",
            status=DatasetStatus.DRAFT,
            visibility=False,
        )
        DatasetMetadata.objects.create(
            dataset=queue_dataset,
            title="National Budget 2024",
            description="Draft budget package.",
            region="National",
            year=2024,
        )
        DatasetTag.objects.create(dataset=queue_dataset, tag=self.tag)

        published_dataset = Dataset.objects.create(
            publisher_user=self.editor,
            category=economy,
            slug="national-budget-archive",
            status=DatasetStatus.PUBLISHED,
            visibility=True,
        )
        DatasetMetadata.objects.create(
            dataset=published_dataset,
            title="National Budget Archive",
            description="Published budget archive.",
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.get(
            "/api/v1/dataset/admin-queue/",
            {
                "q": "budget",
                "status": "draft",
                "page": 1,
                "page_size": 10,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        payload = response.data["data"]
        self.assertEqual(payload["pagination"]["page"], 1)
        self.assertEqual(payload["pagination"]["page_size"], 10)
        self.assertEqual(payload["pagination"]["total_items"], 1)
        self.assertEqual(payload["pagination"]["total_pages"], 1)
        self.assertFalse(payload["pagination"]["has_next"])
        self.assertFalse(payload["pagination"]["has_previous"])

        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["id"], str(queue_dataset.id))
        self.assertEqual(item["slug"], "national-budget-2024")
        self.assertEqual(item["title"], "National Budget 2024")
        self.assertEqual(item["status"], DatasetStatus.DRAFT)
        self.assertFalse(item["visibility"])
        self.assertEqual(item["category_slug"], "economy")
        self.assertEqual(item["category_name"], "Economy")
        self.assertTrue(item["has_metadata"])
        self.assertTrue(item["has_tag"])
        self.assertFalse(item["has_file"])
        self.assertIsNone(item["primary_file_id"])
        self.assertIsNotNone(item["updated_at"])
        self.assertIsNotNone(item["created_at"])

    def test_admin_queue_requires_dataset_admin_permissions(self):
        self.client.force_authenticate(user=self.editor)
        response = self.client.get("/api/v1/dataset/admin-queue/")

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.data["success"])

    def test_admin_queue_summary_returns_status_counts(self):
        datasets = [
            ("queue-draft-1", DatasetStatus.DRAFT, False),
            ("queue-draft-2", DatasetStatus.DRAFT, False),
            ("queue-in-review", DatasetStatus.IN_REVIEW, False),
            ("queue-approved", DatasetStatus.APPROVED, False),
            ("queue-rejected", DatasetStatus.REJECTED, False),
            ("queue-published", DatasetStatus.PUBLISHED, True),
        ]
        for slug, status_value, visibility in datasets:
            Dataset.objects.create(
                publisher_user=self.editor,
                category=self.category,
                slug=slug,
                status=status_value,
                visibility=visibility,
            )

        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/v1/dataset/admin-queue/summary/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"],
            {
                "total": 6,
                "draft": 2,
                "in_review": 1,
                "approved": 1,
                "rejected": 1,
                "published": 1,
            },
        )

    def test_admin_queue_summary_requires_dataset_admin_permissions(self):
        self.client.force_authenticate(user=self.editor)
        response = self.client.get("/api/v1/dataset/admin-queue/summary/")

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.data["success"])

    def test_admin_bulk_action_approves_datasets_and_reports_failures(self):
        review_ready_one = self.make_dataset_ready_for_review(slug="bulk-approve-one")
        review_ready_two = self.make_dataset_ready_for_review(slug="bulk-approve-two")
        draft_dataset = self.create_draft_dataset(slug="bulk-approve-draft")

        self.assertEqual(self.submit_for_review(review_ready_one).status_code, 200)
        self.assertEqual(self.submit_for_review(review_ready_two).status_code, 200)

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            "/api/v1/dataset/admin-queue/bulk-action/",
            {
                "action": "approve",
                "dataset_ids": [
                    str(review_ready_one.id),
                    str(draft_dataset.id),
                    str(review_ready_two.id),
                ],
                "reason": "Bulk approval.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.data["success"])
        payload = response.data["data"]
        job = DatasetBulkActionJob.objects.get(id=payload["id"])

        self.assertEqual(payload["action"], "approve")
        self.assertEqual(payload["requested_count"], 3)
        self.assertEqual(payload["processed_count"], 2)
        self.assertEqual(payload["failed_count"], 1)
        self.assertEqual(payload["status"], DatasetBulkActionJobStatus.COMPLETED)
        self.assertTrue(payload["task_id"])
        self.assertEqual(job.status, DatasetBulkActionJobStatus.COMPLETED)
        self.assertEqual(
            [item["dataset_id"] for item in job.processed],
            [str(review_ready_one.id), str(review_ready_two.id)],
        )
        self.assertEqual(job.processed[0]["status"], DatasetStatus.APPROVED)
        self.assertEqual(job.processed[1]["status"], DatasetStatus.APPROVED)
        self.assertEqual(job.failed[0]["dataset_id"], str(draft_dataset.id))
        self.assertEqual(
            job.failed[0]["error"],
            "Only datasets in review can be approved.",
        )

        review_ready_one.refresh_from_db()
        review_ready_two.refresh_from_db()
        draft_dataset.refresh_from_db()
        self.assertEqual(review_ready_one.status, DatasetStatus.APPROVED)
        self.assertEqual(review_ready_two.status, DatasetStatus.APPROVED)
        self.assertEqual(draft_dataset.status, DatasetStatus.DRAFT)

    def test_admin_bulk_action_publishes_approved_datasets(self):
        approved_dataset = self.make_dataset_ready_for_review(
            slug="bulk-publish-approved"
        )
        in_review_dataset = self.make_dataset_ready_for_review(
            slug="bulk-publish-in-review"
        )

        self.assertEqual(self.submit_for_review(approved_dataset).status_code, 200)
        self.assertEqual(self.approve_dataset(approved_dataset).status_code, 200)
        self.assertEqual(self.submit_for_review(in_review_dataset).status_code, 200)

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            "/api/v1/dataset/admin-queue/bulk-action/",
            {
                "action": "publish",
                "dataset_ids": [
                    str(approved_dataset.id),
                    str(in_review_dataset.id),
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.data["success"])
        payload = response.data["data"]
        job = DatasetBulkActionJob.objects.get(id=payload["id"])

        self.assertEqual(payload["action"], "publish")
        self.assertEqual(payload["requested_count"], 2)
        self.assertEqual(payload["processed_count"], 1)
        self.assertEqual(payload["failed_count"], 1)
        self.assertEqual(payload["status"], DatasetBulkActionJobStatus.COMPLETED)
        self.assertEqual(job.processed[0]["dataset_id"], str(approved_dataset.id))
        self.assertEqual(job.processed[0]["status"], DatasetStatus.PUBLISHED)
        self.assertEqual(job.failed[0]["dataset_id"], str(in_review_dataset.id))
        self.assertEqual(
            job.failed[0]["error"],
            "Only approved datasets can be published.",
        )

        approved_dataset.refresh_from_db()
        in_review_dataset.refresh_from_db()
        self.assertEqual(approved_dataset.status, DatasetStatus.PUBLISHED)
        self.assertTrue(approved_dataset.visibility)
        self.assertIsNotNone(approved_dataset.published_at)
        self.assertEqual(in_review_dataset.status, DatasetStatus.IN_REVIEW)
        self.assertFalse(in_review_dataset.visibility)

    def test_admin_bulk_action_job_list_and_detail_are_available(self):
        review_ready_dataset = self.make_dataset_ready_for_review(
            slug="bulk-job-detail-dataset"
        )
        self.assertEqual(self.submit_for_review(review_ready_dataset).status_code, 200)

        self.client.force_authenticate(user=self.admin)
        action_response = self.client.post(
            "/api/v1/dataset/admin-queue/bulk-action/",
            {
                "action": "approve",
                "dataset_ids": [str(review_ready_dataset.id)],
                "reason": "Queued for inspection.",
            },
            format="json",
        )
        self.assertEqual(action_response.status_code, 202)
        job_id = action_response.data["data"]["id"]

        list_response = self.client.get(
            "/api/v1/dataset/admin-queue/bulk-action/jobs/",
            {"status": DatasetBulkActionJobStatus.COMPLETED},
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertTrue(list_response.data["success"])
        list_payload = list_response.data["data"]
        self.assertGreaterEqual(list_payload["pagination"]["total_items"], 1)
        self.assertEqual(list_payload["items"][0]["id"], job_id)
        self.assertEqual(
            list_payload["items"][0]["status"], DatasetBulkActionJobStatus.COMPLETED
        )
        self.assertEqual(list_payload["items"][0]["processed_count"], 1)

        detail_response = self.client.get(
            f"/api/v1/dataset/admin-queue/bulk-action/jobs/{job_id}/"
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertTrue(detail_response.data["success"])
        detail_payload = detail_response.data["data"]
        self.assertEqual(detail_payload["id"], job_id)
        self.assertEqual(detail_payload["dataset_ids"], [str(review_ready_dataset.id)])
        self.assertEqual(detail_payload["reason"], "Queued for inspection.")
        self.assertEqual(detail_payload["processed_count"], 1)
        self.assertEqual(detail_payload["failed_count"], 0)
        self.assertEqual(
            detail_payload["processed"][0]["dataset_id"], str(review_ready_dataset.id)
        )

    def test_admin_bulk_action_job_endpoints_require_dataset_admin_permissions(self):
        response = self.client.get("/api/v1/dataset/admin-queue/bulk-action/jobs/")
        self.assertEqual(response.status_code, 401)

        self.client.force_authenticate(user=self.editor)
        response = self.client.get("/api/v1/dataset/admin-queue/bulk-action/jobs/")
        self.assertEqual(response.status_code, 403)

    def test_admin_bulk_upload_queues_files_and_creates_dataset_files(self):
        dataset_one = self.create_draft_dataset(slug="bulk-upload-a")
        dataset_two = self.create_draft_dataset(slug="bulk-upload-b")

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            "/api/v1/dataset/admin-queue/bulk-upload/",
            {
                "items": json.dumps(
                    [
                        {"dataset_id": str(dataset_one.id), "is_primary": True},
                        {"dataset_id": str(dataset_two.id), "is_primary": True},
                    ]
                ),
                "files": [
                    SimpleUploadedFile(
                        "bulk-upload-a.csv",
                        b"country,value\nTZ,10\n",
                        content_type="text/csv",
                    ),
                    SimpleUploadedFile(
                        "bulk-upload-b.csv",
                        b"country,value\nKE,20\n",
                        content_type="text/csv",
                    ),
                ],
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.data["success"])
        job_id = response.data["data"]["id"]

        job = DatasetBulkUploadJob.objects.get(id=job_id)
        self.assertEqual(job.status, DatasetBulkUploadJobStatus.COMPLETED)
        self.assertEqual(job.total_count, 2)
        self.assertEqual(job.processed_count, 2)
        self.assertEqual(job.failed_count, 0)

        self.assertEqual(
            DatasetFile.objects.filter(dataset_version__dataset=dataset_one).count(), 1
        )
        self.assertEqual(
            DatasetFile.objects.filter(dataset_version__dataset=dataset_two).count(), 1
        )

        list_response = self.client.get(
            "/api/v1/dataset/admin-queue/bulk-upload/jobs/",
            {"status": DatasetBulkUploadJobStatus.COMPLETED},
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertTrue(list_response.data["success"])
        self.assertGreaterEqual(
            list_response.data["data"]["pagination"]["total_items"], 1
        )
        self.assertEqual(list_response.data["data"]["items"][0]["id"], job_id)

        detail_response = self.client.get(
            f"/api/v1/dataset/admin-queue/bulk-upload/jobs/{job_id}/"
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertTrue(detail_response.data["success"])
        detail_payload = detail_response.data["data"]
        self.assertEqual(detail_payload["id"], job_id)
        self.assertEqual(detail_payload["total_count"], 2)
        self.assertEqual(len(detail_payload["items"]), 2)

    def test_admin_bulk_upload_job_endpoints_require_dataset_admin_permissions(self):
        response = self.client.get("/api/v1/dataset/admin-queue/bulk-upload/jobs/")
        self.assertEqual(response.status_code, 401)

        self.client.force_authenticate(user=self.editor)
        response = self.client.get("/api/v1/dataset/admin-queue/bulk-upload/jobs/")
        self.assertEqual(response.status_code, 403)

    def test_admin_bulk_upload_requires_publish_permission_for_publish_after_upload(
        self,
    ):
        dataset = self.create_draft_dataset(slug="bulk-upload-publish-perm")

        self.client.force_authenticate(user=self.editor)
        response = self.client.post(
            "/api/v1/dataset/admin-queue/bulk-upload/",
            {
                "items": json.dumps([{"dataset_id": str(dataset.id)}]),
                "files": [
                    SimpleUploadedFile(
                        "bulk-upload.csv",
                        b"country,value\nTZ,10\n",
                        content_type="text/csv",
                    )
                ],
                "publish_after_upload": True,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.data["success"])
        self.assertEqual(DatasetBulkUploadJob.objects.count(), 0)

    def test_admin_bulk_upload_does_not_require_publish_permission_for_false_string(
        self,
    ):
        dataset = self.create_draft_dataset(slug="bulk-upload-publish-perm-false")

        self.client.force_authenticate(user=self.editor)
        response = self.client.post(
            "/api/v1/dataset/admin-queue/bulk-upload/",
            {
                "items": json.dumps([{"dataset_id": str(dataset.id)}]),
                "files": [
                    SimpleUploadedFile(
                        "bulk-upload.csv",
                        b"country,value\nTZ,10\n",
                        content_type="text/csv",
                    )
                ],
                "publish_after_upload": "false",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.data["success"])
        self.assertEqual(DatasetBulkUploadJob.objects.count(), 1)

    @patch(
        "djapps.datasets.views.run_bulk_upload_job.run",
        side_effect=RuntimeError("queue exploded"),
    )
    def test_admin_bulk_upload_returns_error_when_enqueue_fails(self, mock_run):
        dataset = self.create_draft_dataset(slug="bulk-upload-enqueue-failure")

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            "/api/v1/dataset/admin-queue/bulk-upload/",
            {
                "items": json.dumps([{"dataset_id": str(dataset.id)}]),
                "files": [
                    SimpleUploadedFile(
                        "bulk-upload.csv",
                        b"country,value\nTZ,10\n",
                        content_type="text/csv",
                    )
                ],
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        job = DatasetBulkUploadJob.objects.get()
        self.assertEqual(job.status, DatasetBulkUploadJobStatus.FAILED)
        self.assertIn("queue exploded", job.error)
        self.assertEqual(DatasetBulkUploadJobItem.objects.count(), 1)
        self.assertEqual(mock_run.call_count, 1)

    @patch(
        "djapps.datasets.tasks.process_dataset_bulk_action",
        side_effect=RuntimeError("publish exploded"),
    )
    def test_bulk_upload_task_cleans_up_dataset_file_when_publish_fails(self, mock_publish):
        dataset = self.create_draft_dataset(slug="bulk-upload-cleanup")
        job = DatasetBulkUploadJob.objects.create(
            requested_by=self.admin,
            total_count=1,
        )
        item = DatasetBulkUploadJobItem.objects.create(
            job=job,
            dataset=dataset,
            uploaded_file=SimpleUploadedFile(
                "cleanup.csv",
                b"country,value\nTZ,10\n",
                content_type="text/csv",
            ),
            filename="cleanup.csv",
            is_primary=True,
        )

        run_bulk_upload_job(job.id)

        item.refresh_from_db()
        self.assertEqual(item.status, DatasetBulkUploadJobStatus.FAILED)
        self.assertIsNone(item.dataset_file_id)
        self.assertEqual(DatasetFile.objects.count(), 0)
        self.assertEqual(os.listdir(self.media_dir.name), [])
        self.assertEqual(item.result["status"], DatasetBulkUploadJobStatus.FAILED)
        self.assertIn("publish exploded", item.result["error"])
        self.assertEqual(mock_publish.call_count, 1)

    def test_admin_bulk_upload_rejects_invalid_dataset_version_without_saving_files(
        self,
    ):
        dataset_one = self.create_draft_dataset(slug="bulk-upload-validation-a")
        dataset_two = self.create_draft_dataset(slug="bulk-upload-validation-b")
        dataset_version_one = DatasetVersion.objects.create(
            dataset=dataset_one,
            created_by=self.editor,
            version_number="1",
        )
        DatasetVersion.objects.create(
            dataset=dataset_two,
            created_by=self.editor,
            version_number="1",
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            "/api/v1/dataset/admin-queue/bulk-upload/",
            {
                "items": json.dumps(
                    [
                        {
                            "dataset_id": str(dataset_one.id),
                            "dataset_version_id": str(dataset_version_one.id),
                            "is_primary": True,
                        },
                        {
                            "dataset_id": str(dataset_two.id),
                            "dataset_version_id": str(dataset_version_one.id),
                            "is_primary": True,
                        },
                    ]
                ),
                "files": [
                    SimpleUploadedFile(
                        "bulk-upload-a.csv",
                        b"country,value\nTZ,10\n",
                        content_type="text/csv",
                    ),
                    SimpleUploadedFile(
                        "bulk-upload-b.csv",
                        b"country,value\nKE,20\n",
                        content_type="text/csv",
                    ),
                ],
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertEqual(DatasetBulkUploadJob.objects.count(), 0)
        self.assertEqual(DatasetBulkUploadJobItem.objects.count(), 0)
        self.assertEqual(os.listdir(self.media_dir.name), [])

    def test_admin_bulk_action_reject_requires_reason(self):
        review_ready_dataset = self.make_dataset_ready_for_review(
            slug="bulk-reject-no-reason"
        )
        self.assertEqual(self.submit_for_review(review_ready_dataset).status_code, 200)

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            "/api/v1/dataset/admin-queue/bulk-action/",
            {
                "action": "reject",
                "dataset_ids": [str(review_ready_dataset.id)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertIn("reason", response.data["error"]["details"]["fields"])

    def test_admin_bulk_action_requires_dataset_admin_permissions(self):
        dataset = self.create_draft_dataset(slug="bulk-action-permission-check")

        self.client.force_authenticate(user=self.editor)
        response = self.client.post(
            "/api/v1/dataset/admin-queue/bulk-action/",
            {
                "action": "approve",
                "dataset_ids": [str(dataset.id)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.data["success"])

    def test_dataset_creation_auto_generates_slug_when_omitted(self):
        first_dataset = self.create_draft_dataset(slug=None)
        second_dataset = self.create_draft_dataset(slug=None)

        self.assertEqual(first_dataset.slug, "climate-dataset")
        self.assertEqual(second_dataset.slug, "climate-dataset-2")
        self.assertEqual(first_dataset.status, DatasetStatus.DRAFT)

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

    def test_admin_can_revalidate_dataset_file(self):
        dataset = self.create_draft_dataset(slug="admin-file-validate")
        upload_response = self.upload_valid_file(dataset, filename="climate-data.csv")
        dataset_file_id = upload_response.data["data"]["id"]
        dataset_file = DatasetFile.objects.get(id=dataset_file_id)
        dataset_file.validation_status = FileValidationStatus.REJECTED
        dataset_file.validated_at = None
        dataset_file.validation_notes = "Previously rejected."
        dataset_file.is_safe = False
        dataset_file.save(
            update_fields=[
                "validation_status",
                "validated_at",
                "validation_notes",
                "is_safe",
                "updated_at",
            ]
        )

        response = self.validate_dataset_file(
            dataset_file_id,
            validation_notes="Admin revalidated file.",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        payload = response.data["data"]
        self.assertEqual(payload["validation_status"], FileValidationStatus.VALIDATED)
        self.assertTrue(payload["is_safe"])
        self.assertEqual(payload["validation_notes"], "Admin revalidated file.")

        dataset_file.refresh_from_db()
        self.assertEqual(dataset_file.validation_status, FileValidationStatus.VALIDATED)
        self.assertTrue(dataset_file.is_safe)
        self.assertIsNotNone(dataset_file.validated_at)

        actions = set(
            DatasetAuditLog.objects.filter(
                dataset=dataset,
                target_id=dataset_file.id,
            ).values_list("action", flat=True)
        )
        self.assertIn("file_validated", actions)

    def test_admin_validation_rejects_unsupported_file(self):
        dataset = self.create_draft_dataset(slug="admin-file-reject")
        version = DatasetVersion.objects.create(
            dataset=dataset,
            created_by=self.editor,
            version_number="1.0",
            changelog="Initial version.",
        )
        dataset_file = DatasetFile.objects.create(
            dataset_version=version,
            uploaded_by=self.editor,
            file=SimpleUploadedFile(
                "payload.exe",
                b"unsafe-binary",
                content_type="application/octet-stream",
            ),
            filename="payload.exe",
            file_size=len(b"unsafe-binary"),
            file_format="exe",
            checksum="placeholder",
            is_primary=True,
            validation_status=FileValidationStatus.VALIDATED,
            validated_at=None,
            validation_notes="Pending validation.",
            is_safe=True,
        )

        response = self.validate_dataset_file(
            dataset_file.id,
            validation_notes="Rejected by admin review.",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        payload = response.data["data"]
        self.assertEqual(payload["validation_status"], FileValidationStatus.REJECTED)
        self.assertFalse(payload["is_safe"])
        self.assertIn("Unsupported file type.", payload["validation_notes"])
        self.assertIn("Rejected by admin review.", payload["validation_notes"])

        dataset_file.refresh_from_db()
        self.assertEqual(dataset_file.validation_status, FileValidationStatus.REJECTED)
        self.assertFalse(dataset_file.is_safe)

        actions = set(
            DatasetAuditLog.objects.filter(
                dataset=dataset,
                target_id=dataset_file.id,
            ).values_list("action", flat=True)
        )
        self.assertIn("file_validation_rejected", actions)

    def test_file_validation_requires_dataset_admin_permissions(self):
        dataset = self.create_draft_dataset(slug="file-validate-permission")
        upload_response = self.upload_valid_file(dataset, filename="climate-data.csv")
        dataset_file_id = upload_response.data["data"]["id"]

        response = self.validate_dataset_file(dataset_file_id, user=self.editor)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.data["success"])

    def test_invalid_file_type_is_rejected(self):
        dataset = self.create_draft_dataset(slug="bad-file-draft")

        self.client.force_authenticate(user=self.editor)
        response = self.client.post(
            "/api/v1/dataset/files/",
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
            f"/api/v1/dataset/{dataset.id}/publish/",
            {"reason": "Trying to bypass review."},
            format="json",
        )
        self.assertEqual(publish_response.status_code, 403)

    def test_admin_can_unpublish_dataset_and_remove_public_access(self):
        dataset = self.make_dataset_ready_for_review(slug="unpublished-climate-data")
        self.assertEqual(self.submit_for_review(dataset).status_code, 200)
        self.assertEqual(self.approve_dataset(dataset).status_code, 200)
        self.assertEqual(self.publish_dataset(dataset).status_code, 200)
        published_at = Dataset.objects.get(pk=dataset.pk).published_at

        unpublish_response = self.unpublish_dataset(dataset)
        self.assertEqual(unpublish_response.status_code, 200)
        self.assertTrue(unpublish_response.data["success"])
        self.assertEqual(
            unpublish_response.data["data"]["status"],
            DatasetStatus.APPROVED,
        )
        self.assertFalse(unpublish_response.data["data"]["visibility"])

        dataset.refresh_from_db()
        self.assertEqual(dataset.status, DatasetStatus.APPROVED)
        self.assertFalse(dataset.visibility)
        self.assertEqual(dataset.published_at, published_at)

        self.client.force_authenticate(user=None)
        discovery_response = self.client.get(
            "/api/v1/dataset/",
            {"q": "unpublished-climate-data"},
        )
        self.assertEqual(discovery_response.status_code, 200)
        self.assertEqual(discovery_response.data["data"], [])

        actions = set(
            DatasetAuditLog.objects.filter(dataset=dataset).values_list(
                "action", flat=True
            )
        )
        self.assertIn("dataset_published", actions)
        self.assertIn("dataset_unpublished", actions)

    def test_only_published_datasets_can_be_unpublished(self):
        dataset = self.make_dataset_ready_for_review(slug="cannot-unpublish-approved")
        self.assertEqual(self.submit_for_review(dataset).status_code, 200)
        self.assertEqual(self.approve_dataset(dataset).status_code, 200)

        response = self.unpublish_dataset(dataset)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertIn("status", response.data["error"]["details"]["fields"])

    def test_owner_can_restore_soft_deleted_dataset(self):
        dataset = self.create_draft_dataset(slug="restore-draft-dataset")
        upload_response = self.upload_valid_file(dataset, filename="restore.csv")
        dataset_file_id = upload_response.data["data"]["id"]

        self.client.force_authenticate(user=self.editor)
        delete_response = self.client.delete(f"/api/v1/dataset/{dataset.id}/")
        self.assertEqual(delete_response.status_code, 200)

        dataset.refresh_from_db()
        self.assertTrue(dataset.is_deleted)

        restore_response = self.restore_dataset(dataset)
        self.assertEqual(restore_response.status_code, 200)
        self.assertTrue(restore_response.data["success"])
        self.assertEqual(restore_response.data["data"]["id"], str(dataset.id))

        dataset.refresh_from_db()
        self.assertFalse(dataset.is_deleted)
        self.assertTrue(Dataset.objects.filter(id=dataset.id).exists())

        detail_response = self.client.get(f"/api/v1/dataset/{dataset.id}/")
        self.assertEqual(detail_response.status_code, 200)

        file_response = self.client.get(f"/api/v1/dataset/files/{dataset_file_id}/")
        self.assertEqual(file_response.status_code, 200)

        actions = set(
            DatasetAuditLog.objects.filter(dataset=dataset).values_list(
                "action", flat=True
            )
        )
        self.assertIn("dataset_deleted", actions)
        self.assertIn("dataset_restored", actions)

    def test_only_deleted_datasets_can_be_restored(self):
        dataset = self.create_draft_dataset(slug="active-restore-target")

        response = self.restore_dataset(dataset)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertIn("dataset", response.data["error"]["details"]["fields"])

    def test_restore_requires_dataset_delete_permission(self):
        dataset = self.create_draft_dataset(slug="restore-permission-dataset")
        self.client.force_authenticate(user=self.editor)
        delete_response = self.client.delete(f"/api/v1/dataset/{dataset.id}/")
        self.assertEqual(delete_response.status_code, 200)

        response = self.restore_dataset(dataset, user=self.viewer)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.data["success"])

    def test_admin_can_transfer_dataset_owner_and_sync_metadata(self):
        dataset = self.create_draft_dataset(slug="transfer-owner-dataset")
        self.add_metadata(dataset)

        response = self.transfer_dataset_owner(dataset, self.editor_two)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"]["publisher_user_id"],
            str(self.editor_two.id),
        )
        self.assertEqual(
            response.data["data"]["metadata"][0]["publisher_name"],
            "Second Editor",
        )

        dataset.refresh_from_db()
        self.assertEqual(dataset.publisher_user, self.editor_two)
        self.assertEqual(dataset.metadata.first().publisher_name, "Second Editor")

        self.client.force_authenticate(user=self.editor)
        old_owner_detail = self.client.get(f"/api/v1/dataset/{dataset.id}/")
        self.assertEqual(old_owner_detail.status_code, 403)

        self.client.force_authenticate(user=self.editor_two)
        new_owner_detail = self.client.get(f"/api/v1/dataset/{dataset.id}/")
        self.assertEqual(new_owner_detail.status_code, 200)

        actions = set(
            DatasetAuditLog.objects.filter(dataset=dataset).values_list(
                "action", flat=True
            )
        )
        self.assertIn("dataset_owner_transferred", actions)

    def test_transfer_owner_requires_dataset_admin_permissions(self):
        dataset = self.create_draft_dataset(slug="transfer-owner-permission")

        response = self.transfer_dataset_owner(
            dataset,
            self.editor_two,
            user=self.editor,
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.data["success"])

    def test_transfer_owner_rejects_user_without_dataset_management_permission(self):
        dataset = self.create_draft_dataset(slug="transfer-owner-viewer-target")

        response = self.transfer_dataset_owner(dataset, self.viewer)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertIn("new_owner_id", response.data["error"]["details"]["fields"])

    def test_metadata_publisher_name_is_derived_from_dataset_owner(self):
        dataset = self.create_draft_dataset(slug="derived-publisher-name")

        self.client.force_authenticate(user=self.editor)
        response = self.client.post(
            "/api/v1/dataset/metadata/",
            {
                "dataset_id": str(dataset.id),
                "title": "Climate Statistics",
                "description": "Annual climate observations.",
                "license": "CC-BY-4.0",
                "frequency": "annual",
                "region": "East Africa",
                "year": 2024,
                "publisher_name": "Malicious Override",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["data"]["publisher_name"], "Data Editor")
        dataset.refresh_from_db()
        self.assertEqual(dataset.metadata.first().publisher_name, "Data Editor")

    def test_public_can_access_structured_dataset_rows_via_api(self):
        dataset = self.make_dataset_ready_for_review(slug="structured-api-dataset")
        self.assertEqual(self.submit_for_review(dataset).status_code, 200)
        self.assertEqual(self.approve_dataset(dataset).status_code, 200)
        self.assertEqual(self.publish_dataset(dataset).status_code, 200)

        dataset_file = dataset.versions.first().files.first()
        self.client.force_authenticate(user=None)
        response = self.client.get(
            f"/api/v1/dataset/files/{dataset_file.id}/data/",
            {"offset": 0, "limit": 10},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        payload = response.data["data"]
        self.assertEqual(payload["file_format"], "csv")
        self.assertEqual(payload["columns"], ["country", "value"])
        self.assertEqual(payload["rows"], [{"country": "TZ", "value": "10"}])
        self.assertEqual(payload["total_rows"], 1)
        self.assertFalse(payload["has_more"])

        actions = set(
            DatasetAuditLog.objects.filter(dataset=dataset).values_list(
                "action", flat=True
            )
        )
        self.assertIn("file_data_accessed", actions)

    def test_structured_dataset_api_supports_xls_files(self):
        dataset = self.create_draft_dataset(slug="structured-xls-dataset")
        upload_response = self.upload_file(
            dataset,
            "climate.xls",
            self.build_xls_content(),
            "application/vnd.ms-excel",
        )

        dataset_file_id = upload_response.data["data"]["id"]
        response = self.client.get(f"/api/v1/dataset/files/{dataset_file_id}/data/")

        self.assertEqual(response.status_code, 200)
        payload = response.data["data"]
        self.assertEqual(payload["structure_type"], "tabular")
        self.assertEqual(payload["file_format"], "xls")
        self.assertEqual(payload["columns"], ["country", "value"])
        self.assertEqual(payload["rows"], [{"country": "TZ", "value": 10}])

    def test_structured_dataset_api_supports_sdmx_json(self):
        dataset = self.create_draft_dataset(slug="structured-sdmx-json-dataset")
        sdmx_payload = {
            "header": {"id": "climate-observations"},
            "structure": {
                "dimensions": {
                    "observation": [
                        {"id": "REF_AREA", "values": [{"id": "TZ"}, {"id": "KE"}]},
                        {"id": "TIME_PERIOD", "values": [{"id": "2024"}]},
                    ]
                },
                "attributes": {"observation": []},
                "measures": {"observation": [{"id": "OBS_VALUE"}]},
            },
            "dataSets": [
                {
                    "observations": {
                        "0:0": [10],
                        "1:0": [20],
                    }
                }
            ],
        }
        upload_response = self.upload_file(
            dataset,
            "climate-sdmx.json",
            json.dumps(sdmx_payload).encode("utf-8"),
            "application/json",
        )

        dataset_file_id = upload_response.data["data"]["id"]
        response = self.client.get(f"/api/v1/dataset/files/{dataset_file_id}/data/")

        self.assertEqual(response.status_code, 200)
        payload = response.data["data"]
        self.assertEqual(payload["structure_type"], "sdmx")
        self.assertEqual(payload["sdmx"]["format"], "json")
        self.assertEqual(payload["sdmx"]["dimensions"], ["REF_AREA", "TIME_PERIOD"])
        self.assertEqual(payload["rows"][0]["REF_AREA"], "TZ")
        self.assertEqual(payload["rows"][0]["TIME_PERIOD"], "2024")
        self.assertEqual(payload["rows"][0]["value"], 10)

    def test_structured_dataset_api_returns_document_payload_for_pdf(self):
        dataset = self.create_draft_dataset(slug="structured-pdf-dataset")
        upload_response = self.upload_file(
            dataset,
            "guide.pdf",
            self.build_pdf_content(),
            "application/pdf",
        )

        dataset_file_id = upload_response.data["data"]["id"]
        response = self.client.get(f"/api/v1/dataset/files/{dataset_file_id}/data/")

        self.assertEqual(response.status_code, 200)
        payload = response.data["data"]
        self.assertEqual(payload["structure_type"], "document")
        self.assertEqual(payload["document"]["page_count"], 1)
        self.assertEqual(len(payload["document"]["pages"]), 1)
        self.assertEqual(payload["document"]["pages"][0]["page_number"], 1)

    def test_structured_dataset_api_rejects_unsupported_file_formats(self):
        dataset = self.create_draft_dataset(slug="unsupported-structured-format")
        upload_response = self.upload_file(
            dataset,
            "guide.txt",
            b"plain text content",
            "text/plain",
        )

        dataset_file_id = upload_response.data["data"]["id"]
        response = self.client.get(f"/api/v1/dataset/files/{dataset_file_id}/data/")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn("file_format", response.data["error"]["details"]["fields"])

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
            "/api/v1/dataset/",
            {
                "q": "climate",
                "region": "East Africa",
                "year": 2024,
                "frequency": "annual",
                "tag": "open-data",
                "publisher": "Data Editor",
            },
        )
        self.assertEqual(discovery_response.status_code, 200)
        self.assertEqual(len(discovery_response.data["data"]), 1)
        self.assertEqual(
            discovery_response.data["data"][0]["slug"], "public-climate-data"
        )

        detail_response = self.client.get(f"/api/v1/dataset/{dataset.id}/")
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(
            detail_response.data["data"]["status"], DatasetStatus.PUBLISHED
        )
        self.assertEqual(
            detail_response.data["data"]["metadata"][0]["region"], "East Africa"
        )
        self.assertEqual(
            detail_response.data["data"]["metadata"][0]["frequency"], "annual"
        )

        dataset_file = dataset.versions.first().files.first()
        download_response = self.client.get(
            f"/api/v1/dataset/files/{dataset_file.id}/download/"
        )
        self.assertEqual(download_response.status_code, 200)
        self.assertIn("attachment;", download_response.headers["Content-Disposition"])

        actions = set(
            DatasetAuditLog.objects.filter(dataset=dataset).values_list(
                "action", flat=True
            )
        )
        self.assertIn("dataset_review_submitted", actions)
        self.assertIn("dataset_review_approved", actions)
        self.assertIn("dataset_published", actions)
        self.assertIn("file_downloaded", actions)

    def test_audit_logs_are_visible_to_owner_and_admin_only(self):
        dataset = self.make_dataset_ready_for_review(slug="audited-dataset")

        self.client.force_authenticate(user=self.editor)
        owner_response = self.client.get("/api/v1/dataset/audit-logs/")
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
        viewer_response = self.client.get("/api/v1/dataset/audit-logs/")
        self.assertEqual(viewer_response.status_code, 200)
        self.assertEqual(viewer_response.data["data"], [])

    def test_dataset_delete_is_soft_and_hides_dataset_and_related_records(self):
        dataset = self.make_dataset_ready_for_review(slug="soft-delete-dataset")
        dataset_file = dataset.versions.first().files.first()

        self.client.force_authenticate(user=self.editor)
        response = self.client.delete(f"/api/v1/dataset/{dataset.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])

        dataset.refresh_from_db()
        self.assertIsNotNone(dataset.deleted_at)
        self.assertFalse(Dataset.objects.filter(id=dataset.id).exists())
        self.assertTrue(Dataset.all_objects.filter(id=dataset.id).exists())

        self.client.force_authenticate(user=self.editor)
        detail_response = self.client.get(f"/api/v1/dataset/{dataset.id}/")
        self.assertEqual(detail_response.status_code, 404)

        related_response = self.client.get(f"/api/v1/dataset/files/{dataset_file.id}/")
        self.assertEqual(related_response.status_code, 404)

        audit_response = self.client.get("/api/v1/dataset/audit-logs/")
        self.assertEqual(audit_response.status_code, 200)
        self.assertEqual(audit_response.data["data"], [])

        self.client.force_authenticate(user=None)
        public_response = self.client.get("/api/v1/dataset/")
        self.assertEqual(public_response.status_code, 200)
        self.assertEqual(public_response.data["data"], [])

    def test_category_delete_is_blocked_when_dataset_references_it(self):
        self.create_draft_dataset(slug="protected-category-draft")

        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(f"/api/v1/dataset/categories/{self.category.id}/")

        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"]["code"], "protected_resource")
