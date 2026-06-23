from datetime import timedelta
from tempfile import TemporaryDirectory

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from djapps.datasets.models import (
    Category,
    Dataset,
    DatasetFile,
    DatasetMetadata,
    DatasetStatus,
    DatasetTag,
    DatasetVersion,
    FileValidationStatus,
    Tag,
)
from djapps.user_management.models import User

from .models import APIConsumer, APIUsageLog
from .serializers import OpenDatasetSerializer
from .services import generate_api_key, get_key_prefix, issue_api_key, verify_api_key


class APIKeyServiceTests(SimpleTestCase):
    def test_generate_api_key_returns_raw_prefix_and_password_hash(self):
        generated_key = generate_api_key()

        self.assertTrue(generated_key.raw_key.startswith("smartdata_"))
        self.assertEqual(generated_key.prefix, generated_key.raw_key[:20])
        self.assertEqual(generated_key.prefix, get_key_prefix(generated_key.raw_key))
        self.assertTrue(verify_api_key(generated_key.raw_key, generated_key.hashed_key))

    def test_verify_api_key_rejects_wrong_value(self):
        generated_key = generate_api_key()

        self.assertFalse(verify_api_key("wrong-key", generated_key.hashed_key))

    def test_generate_api_key_rejects_invalid_lengths(self):
        with self.assertRaisesMessage(ValueError, "prefix_length must be greater than 0."):
            generate_api_key(prefix_length=0)

        with self.assertRaisesMessage(ValueError, "token_bytes must be greater than 0."):
            generate_api_key(token_bytes=0)

    def test_get_key_prefix_rejects_invalid_lengths(self):
        with self.assertRaisesMessage(ValueError, "prefix_length must be greater than 0."):
            get_key_prefix("smartdata_example", prefix_length=0)


class OpenDatasetFixtureMixin:
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
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="publisher@example.com",
            password="password123",
            first_name="Data",
            last_name="Editor",
        )
        developer_group, _ = Group.objects.get_or_create(name="developer")
        self.user.groups.add(developer_group)
        self.category = Category.objects.create(name="Climate", slug="climate")
        self.tag = Tag.objects.create(name="Open Data", slug="open-data")
        self.dataset = Dataset.objects.create(
            publisher_user=self.user,
            category=self.category,
            slug="public-climate-data",
            status=DatasetStatus.PUBLISHED,
            visibility=True,
            published_at=timezone.now(),
        )
        DatasetMetadata.objects.create(
            dataset=self.dataset,
            title="Climate Statistics",
            description="Annual climate observations.",
            license="CC-BY-4.0",
            frequency="annual",
            region="East Africa",
            year=2024,
        )
        DatasetTag.objects.create(dataset=self.dataset, tag=self.tag)
        self.version = DatasetVersion.objects.create(
            dataset=self.dataset,
            created_by=self.user,
            version_number="1.0",
            changelog="Initial published release.",
        )
        self.public_file = DatasetFile.objects.create(
            dataset_version=self.version,
            uploaded_by=self.user,
            file=SimpleUploadedFile(
                "climate.csv",
                b"country,value\nTZ,10\n",
                content_type="text/csv",
            ),
            filename="climate.csv",
            file_size=20,
            file_format="csv",
            checksum="abc123",
            is_primary=True,
            validation_status=FileValidationStatus.VALIDATED,
            validated_at=timezone.now(),
            validation_notes="Automatic validation passed.",
            is_safe=True,
        )
        DatasetFile.objects.create(
            dataset_version=self.version,
            uploaded_by=self.user,
            file=SimpleUploadedFile(
                "unsafe.json",
                b'{"unsafe": true}',
                content_type="application/json",
            ),
            filename="unsafe.json",
            file_size=16,
            file_format="json",
            checksum="def456",
            is_primary=False,
            validation_status=FileValidationStatus.REJECTED,
            validated_at=timezone.now(),
            validation_notes="Rejected during validation.",
            is_safe=False,
        )
        self.api_consumer = APIConsumer.objects.create(
            user=self.user,
            name="Gateway Consumer",
            consumer_type="developer",
            organization_name="Smarthub Labs",
            email=self.user.email,
            status="active",
        )
        self.api_key, self.raw_api_key = issue_api_key(
            consumer=self.api_consumer,
            name="Gateway Key",
        )

    def gateway_headers(self, raw_key=None):
        return {"HTTP_X_API_KEY": raw_key or self.raw_api_key}

    def authenticate_developer(self):
        self.client.force_authenticate(user=self.user)

    def create_public_version(
        self,
        dataset,
        *,
        version_number,
        filename,
        content,
        file_format="csv",
        is_primary=True,
        content_type=None,
    ):
        version = DatasetVersion.objects.create(
            dataset=dataset,
            created_by=self.user,
            version_number=version_number,
            changelog=f"Release {version_number}.",
        )
        dataset_file = DatasetFile.objects.create(
            dataset_version=version,
            uploaded_by=self.user,
            file=SimpleUploadedFile(
                filename,
                content,
                content_type=content_type or ("text/csv" if file_format == "csv" else "application/octet-stream"),
            ),
            filename=filename,
            file_size=len(content),
            file_format=file_format,
            checksum=f"checksum-{version_number}",
            is_primary=is_primary,
            validation_status=FileValidationStatus.VALIDATED,
            validated_at=timezone.now(),
            validation_notes="Automatic validation passed.",
            is_safe=True,
        )
        return version, dataset_file

    def create_public_dataset(
        self,
        *,
        slug,
        title,
        license_name,
        frequency,
        region,
        year,
        category=None,
        tag=None,
        publisher_user=None,
        file_name="dataset.csv",
        file_content=b"key,value\nsample,1\n",
        file_format="csv",
    ):
        category = category or self.category
        publisher_user = publisher_user or self.user
        dataset = Dataset.objects.create(
            publisher_user=publisher_user,
            category=category,
            slug=slug,
            status=DatasetStatus.PUBLISHED,
            visibility=True,
            published_at=timezone.now(),
        )
        DatasetMetadata.objects.create(
            dataset=dataset,
            title=title,
            description=f"{title} description.",
            license=license_name,
            frequency=frequency,
            region=region,
            year=year,
        )
        if tag is not None:
            DatasetTag.objects.create(dataset=dataset, tag=tag)
        version, dataset_file = self.create_public_version(
            dataset,
            version_number="1.0",
            filename=file_name,
            content=file_content,
            file_format=file_format,
        )
        return dataset, version, dataset_file


class OpenDatasetSerializerTests(OpenDatasetFixtureMixin, TestCase):

    def test_open_dataset_serializer_exposes_public_dataset_shape(self):
        data = OpenDatasetSerializer(self.dataset).data

        self.assertEqual(data["slug"], "public-climate-data")
        self.assertEqual(data["category"]["slug"], "climate")
        self.assertEqual(data["metadata"][0]["publisher_name"], "Data Editor")
        self.assertEqual(data["metadata"][0]["frequency"], "annual")
        self.assertEqual(data["tags"][0]["slug"], "open-data")
        self.assertEqual(len(data["versions"]), 1)
        self.assertEqual(len(data["versions"][0]["files"]), 1)
        self.assertEqual(data["versions"][0]["files"][0]["id"], str(self.public_file.id))
        self.assertEqual(
            data["versions"][0]["files"][0]["download_url"],
            f"/api/gateway/files/{self.public_file.id}/download/",
        )
        self.assertEqual(
            data["versions"][0]["files"][0]["data_url"],
            f"/api/gateway/files/{self.public_file.id}/data/",
        )
        self.assertTrue(data["versions"][0]["files"][0]["data_available"])


class GatewayDatasetViewTests(OpenDatasetFixtureMixin, TestCase):
    def test_gateway_dataset_list_requires_api_key(self):
        response = self.client.get("/api/gateway/datasets/")

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"]["code"], "not_authenticated")

    def test_gateway_dataset_list_returns_paginated_public_datasets_only(self):
        private_dataset = Dataset.objects.create(
            publisher_user=self.user,
            category=self.category,
            slug="private-climate-draft",
            status=DatasetStatus.DRAFT,
            visibility=False,
        )
        DatasetMetadata.objects.create(
            dataset=private_dataset,
            title="Private Draft",
            description="Should not be exposed publicly.",
            license="CC-BY-4.0",
            frequency="annual",
            region="East Africa",
            year=2024,
        )

        response = self.client.get(
            "/api/gateway/datasets/",
            {
                "q": "climate",
                "publisher": "Data Editor",
                "frequency": "annual",
            },
            **self.gateway_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(len(response.data["data"]["items"]), 1)
        self.assertEqual(response.data["data"]["items"][0]["slug"], "public-climate-data")
        self.assertEqual(response.data["data"]["pagination"]["total_items"], 1)

    def test_gateway_dataset_detail_supports_slug_lookup(self):
        response = self.client.get(
            f"/api/gateway/datasets/{self.dataset.slug}/",
            **self.gateway_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["slug"], "public-climate-data")
        self.assertTrue(
            response.data["data"]["versions"][0]["files"][0]["download_url"].endswith(
                f"/api/gateway/files/{self.public_file.id}/download/"
            )
        )

    def test_gateway_dataset_metadata_endpoint_returns_metadata(self):
        response = self.client.get(
            f"/api/gateway/datasets/{self.dataset.slug}/metadata/",
            **self.gateway_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(len(response.data["data"]), 1)
        self.assertEqual(response.data["data"][0]["title"], "Climate Statistics")
        self.assertEqual(response.data["data"][0]["publisher_name"], "Data Editor")

    def test_gateway_dataset_detail_hides_private_dataset(self):
        private_dataset = Dataset.objects.create(
            publisher_user=self.user,
            category=self.category,
            slug="private-climate-draft",
            status=DatasetStatus.DRAFT,
            visibility=False,
        )

        response = self.client.get(
            f"/api/gateway/datasets/{private_dataset.slug}/",
            **self.gateway_headers(),
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"]["code"], "http_404")

    def test_gateway_dataset_list_rejects_invalid_api_key(self):
        response = self.client.get(
            "/api/gateway/datasets/",
            HTTP_X_API_KEY="smartdata_invalid",
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"]["code"], "authentication_failed")

    def test_gateway_categories_endpoint_lists_public_categories(self):
        Category.objects.create(name="Unused", slug="unused")

        response = self.client.get("/api/gateway/categories/", **self.gateway_headers())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(len(response.data["data"]), 1)
        self.assertEqual(response.data["data"][0]["slug"], "climate")

    def test_gateway_formats_endpoint_lists_public_safe_formats(self):
        response = self.client.get(
            "/api/gateway/datasets/formats/",
            **self.gateway_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"][0]["file_format"], "csv")
        self.assertEqual(response.data["data"][0]["dataset_count"], 1)
        self.assertEqual(response.data["data"][0]["file_count"], 1)
        self.assertTrue(response.data["data"][0]["structured_data_supported"])

    def test_gateway_dataset_files_endpoint_lists_public_safe_files(self):
        response = self.client.get(
            f"/api/gateway/datasets/{self.dataset.slug}/files/",
            **self.gateway_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(len(response.data["data"]), 1)
        self.assertEqual(response.data["data"][0]["filename"], "climate.csv")
        self.assertEqual(response.data["data"][0]["version_number"], "1.0")
        self.assertEqual(
            response.data["data"][0]["data_url"],
            f"/api/gateway/files/{self.public_file.id}/data/",
        )

    def test_gateway_dataset_download_endpoint_downloads_latest_public_file(self):
        response = self.client.get(
            f"/api/gateway/datasets/{self.dataset.slug}/download/",
            **self.gateway_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response.headers["Content-Disposition"])
        self.assertIn("climate.csv", response.headers["Content-Disposition"])

    def test_gateway_download_endpoint_downloads_public_safe_file(self):
        response = self.client.get(
            f"/api/gateway/files/{self.public_file.id}/download/",
            **self.gateway_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response.headers["Content-Disposition"])

    def test_gateway_download_endpoint_rejects_unsafe_file(self):
        unsafe_file = DatasetFile.objects.exclude(pk=self.public_file.pk).get()

        response = self.client.get(
            f"/api/gateway/files/{unsafe_file.id}/download/",
            **self.gateway_headers(),
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.data["success"])

    def test_gateway_file_data_endpoint_returns_structured_content(self):
        response = self.client.get(
            f"/api/gateway/files/{self.public_file.id}/data/",
            {"offset": 0, "limit": 10},
            **self.gateway_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        payload = response.data["data"]
        self.assertEqual(payload["file_format"], "csv")
        self.assertEqual(payload["columns"], ["country", "value"])
        self.assertEqual(payload["rows"], [{"country": "TZ", "value": "10"}])
        self.assertEqual(payload["total_rows"], 1)
        self.assertFalse(payload["has_more"])

    def test_gateway_discovery_endpoints_list_public_taxonomy_and_filter_values(self):
        unused_tag = Tag.objects.create(name="Unused Tag", slug="unused-tag")
        unused_category = Category.objects.create(name="Unused", slug="unused")
        self.create_public_dataset(
            slug="population-updates",
            title="Population Updates",
            license_name="ODC-BY-1.0",
            frequency="monthly",
            region="Global",
            year=2025,
            category=unused_category,
            tag=unused_tag,
            file_name="population.csv",
            file_content=b"country,value\nKE,20\n",
        )

        tag_response = self.client.get("/api/gateway/tags/", **self.gateway_headers())
        license_response = self.client.get("/api/gateway/licenses/", **self.gateway_headers())
        publisher_response = self.client.get("/api/gateway/publishers/", **self.gateway_headers())
        frequency_response = self.client.get("/api/gateway/frequencies/", **self.gateway_headers())
        region_response = self.client.get("/api/gateway/regions/", **self.gateway_headers())

        self.assertEqual(tag_response.status_code, 200)
        self.assertEqual(len(tag_response.data["data"]), 2)
        self.assertEqual(tag_response.data["data"][0]["dataset_count"], 1)

        self.assertEqual(license_response.status_code, 200)
        self.assertEqual(
            [item["value"] for item in license_response.data["data"]],
            ["CC-BY-4.0", "ODC-BY-1.0"],
        )

        self.assertEqual(publisher_response.status_code, 200)
        self.assertEqual(publisher_response.data["data"][0]["value"], "Data Editor")
        self.assertEqual(publisher_response.data["data"][0]["dataset_count"], 2)

        self.assertEqual(frequency_response.status_code, 200)
        self.assertEqual(
            [(item["value"], item["label"]) for item in frequency_response.data["data"]],
            [("annual", "Annual"), ("monthly", "Monthly")],
        )

        self.assertEqual(region_response.status_code, 200)
        self.assertEqual(
            [item["value"] for item in region_response.data["data"]],
            ["East Africa", "Global"],
        )

    def test_gateway_versions_latest_stats_schema_and_preview_endpoints(self):
        latest_version, latest_file = self.create_public_version(
            self.dataset,
            version_number="1.1",
            filename="climate-v2.csv",
            content=b"country,value\nTZ,11\n",
        )

        versions_response = self.client.get(
            f"/api/gateway/datasets/{self.dataset.slug}/versions/",
            **self.gateway_headers(),
        )
        version_detail_response = self.client.get(
            f"/api/gateway/datasets/{self.dataset.slug}/versions/{latest_version.id}/",
            **self.gateway_headers(),
        )
        latest_response = self.client.get(
            f"/api/gateway/datasets/{self.dataset.slug}/latest/",
            **self.gateway_headers(),
        )
        latest_data_response = self.client.get(
            f"/api/gateway/datasets/{self.dataset.slug}/latest/data/",
            **self.gateway_headers(),
        )
        stats_response = self.client.get(
            f"/api/gateway/datasets/{self.dataset.slug}/stats/",
            **self.gateway_headers(),
        )
        schema_response = self.client.get(
            f"/api/gateway/files/{latest_file.id}/schema/",
            **self.gateway_headers(),
        )
        preview_response = self.client.get(
            f"/api/gateway/files/{latest_file.id}/preview/",
            **self.gateway_headers(),
        )

        self.assertEqual(versions_response.status_code, 200)
        self.assertEqual(len(versions_response.data["data"]), 2)
        self.assertEqual(versions_response.data["data"][0]["version_number"], "1.1")

        self.assertEqual(version_detail_response.status_code, 200)
        self.assertEqual(version_detail_response.data["data"]["id"], str(latest_version.id))

        self.assertEqual(latest_response.status_code, 200)
        self.assertEqual(latest_response.data["data"]["version_number"], "1.1")

        self.assertEqual(latest_data_response.status_code, 200)
        self.assertEqual(
            latest_data_response.data["data"]["rows"],
            [{"country": "TZ", "value": "11"}],
        )

        self.assertEqual(stats_response.status_code, 200)
        self.assertEqual(stats_response.data["data"]["version_count"], 2)
        self.assertEqual(stats_response.data["data"]["downloadable_file_count"], 2)
        self.assertEqual(stats_response.data["data"]["structured_file_count"], 2)
        self.assertEqual(stats_response.data["data"]["latest_version_number"], "1.1")
        self.assertEqual(stats_response.data["data"]["latest_filename"], "climate-v2.csv")

        self.assertEqual(schema_response.status_code, 200)
        self.assertEqual(schema_response.data["data"]["row_count"], 1)
        self.assertEqual(
            [column["name"] for column in schema_response.data["data"]["columns"]],
            ["country", "value"],
        )

        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(
            preview_response.data["data"]["rows"],
            [{"country": "TZ", "value": "11"}],
        )

    def test_gateway_facets_and_changes_endpoints_support_public_filters(self):
        category_two = Category.objects.create(name="Population", slug="population")
        tag_two = Tag.objects.create(name="Population Data", slug="population-data")
        other_dataset, _, _ = self.create_public_dataset(
            slug="population-stats",
            title="Population Statistics",
            license_name="ODC-BY-1.0",
            frequency="quarterly",
            region="Africa",
            year=2023,
            category=category_two,
            tag=tag_two,
            file_name="population.csv",
            file_content=b"country,value\nUG,30\n",
        )

        old_timestamp = timezone.now() - timedelta(days=10)
        Dataset.objects.filter(pk=other_dataset.pk).update(
            updated_at=old_timestamp,
            published_at=old_timestamp,
        )
        DatasetMetadata.objects.filter(dataset=other_dataset).update(updated_at=old_timestamp)
        DatasetVersion.objects.filter(dataset=other_dataset).update(updated_at=old_timestamp, created_at=old_timestamp)
        DatasetFile.objects.filter(dataset_version__dataset=other_dataset).update(
            updated_at=old_timestamp,
            created_at=old_timestamp,
        )
        DatasetTag.objects.filter(dataset=other_dataset).update(updated_at=old_timestamp, created_at=old_timestamp)

        cutoff = timezone.now() - timedelta(days=1)

        facets_response = self.client.get("/api/gateway/datasets/facets/", **self.gateway_headers())
        changes_response = self.client.get(
            "/api/gateway/datasets/changes/",
            {"updated_since": cutoff.isoformat()},
            **self.gateway_headers(),
        )
        filtered_list_response = self.client.get(
            "/api/gateway/datasets/",
            {"updated_since": cutoff.isoformat()},
            **self.gateway_headers(),
        )

        self.assertEqual(facets_response.status_code, 200)
        self.assertEqual(facets_response.data["data"]["total_datasets"], 2)
        self.assertEqual(len(facets_response.data["data"]["categories"]), 2)
        self.assertEqual(len(facets_response.data["data"]["tags"]), 2)
        self.assertEqual(
            [item["value"] for item in facets_response.data["data"]["years"]],
            [2024, 2023],
        )

        self.assertEqual(changes_response.status_code, 200)
        self.assertEqual(len(changes_response.data["data"]["items"]), 1)
        self.assertEqual(changes_response.data["data"]["items"][0]["slug"], self.dataset.slug)

        self.assertEqual(filtered_list_response.status_code, 200)
        self.assertEqual(len(filtered_list_response.data["data"]["items"]), 1)
        self.assertEqual(filtered_list_response.data["data"]["items"][0]["slug"], self.dataset.slug)


class DeveloperAPIKeyManagementTests(OpenDatasetFixtureMixin, TestCase):
    def test_developer_can_request_list_and_retrieve_api_keys(self):
        self.authenticate_developer()

        request_response = self.client.post(
            "/api/v1/developer/api-keys/request/",
            {
                "name": "CLI Key",
                "consumer_name": "CLI Consumer",
                "organization_name": "Smarthub CLI",
            },
            format="json",
        )

        self.assertEqual(request_response.status_code, 201)
        self.assertTrue(request_response.data["success"])
        issued_key = request_response.data["data"]["api_key"]
        key_id = request_response.data["data"]["id"]
        self.assertTrue(issued_key.startswith("smartdata_"))

        list_response = self.client.get("/api/v1/developer/api-keys/")

        self.assertEqual(list_response.status_code, 200)
        self.assertTrue(list_response.data["success"])
        self.assertGreaterEqual(len(list_response.data["data"]["items"]), 2)

        detail_response = self.client.get(f"/api/v1/developer/api-keys/{key_id}/")

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.data["data"]["name"], "CLI Key")
        self.assertEqual(detail_response.data["data"]["consumer"]["name"], "CLI Consumer")

    def test_developer_can_regenerate_and_revoke_api_key(self):
        self.authenticate_developer()
        previous_prefix = self.api_key.prefix
        old_raw_key = self.raw_api_key

        regenerate_response = self.client.post(
            f"/api/v1/developer/api-keys/{self.api_key.id}/regenerate/",
            format="json",
        )

        self.assertEqual(regenerate_response.status_code, 200)
        self.assertTrue(regenerate_response.data["success"])
        new_raw_key = regenerate_response.data["data"]["api_key"]
        self.api_key.refresh_from_db()
        self.assertNotEqual(self.api_key.prefix, previous_prefix)
        self.assertNotEqual(new_raw_key, old_raw_key)

        self.client.force_authenticate(user=None)
        old_key_response = self.client.get("/api/gateway/datasets/", **self.gateway_headers(old_raw_key))
        self.assertEqual(old_key_response.status_code, 401)

        new_key_response = self.client.get("/api/gateway/datasets/", **self.gateway_headers(new_raw_key))
        self.assertEqual(new_key_response.status_code, 200)

        self.authenticate_developer()
        revoke_response = self.client.post(
            f"/api/v1/developer/api-keys/{self.api_key.id}/revoke/",
            format="json",
        )

        self.assertEqual(revoke_response.status_code, 200)
        self.assertTrue(revoke_response.data["success"])
        self.api_key.refresh_from_db()
        self.assertEqual(self.api_key.status, "revoked")
        self.assertIsNotNone(self.api_key.revoked_at)

        self.client.force_authenticate(user=None)
        revoked_key_response = self.client.get("/api/gateway/datasets/", **self.gateway_headers(new_raw_key))
        self.assertEqual(revoked_key_response.status_code, 401)

    def test_developer_usage_endpoints_return_logs(self):
        self.client.get("/api/gateway/datasets/", **self.gateway_headers())
        self.client.get(
            f"/api/gateway/datasets/{self.dataset.slug}/metadata/",
            **self.gateway_headers(),
        )

        self.authenticate_developer()
        key_usage_response = self.client.get(
            f"/api/v1/developer/api-keys/{self.api_key.id}/usage/"
        )
        all_usage_response = self.client.get("/api/v1/developer/api-usage/")

        self.assertEqual(key_usage_response.status_code, 200)
        self.assertTrue(key_usage_response.data["success"])
        self.assertGreaterEqual(len(key_usage_response.data["data"]["items"]), 2)
        self.assertEqual(
            key_usage_response.data["data"]["items"][0]["api_key_id"],
            str(self.api_key.id),
        )

        self.assertEqual(all_usage_response.status_code, 200)
        self.assertTrue(all_usage_response.data["success"])
        self.assertGreaterEqual(len(all_usage_response.data["data"]["items"]), 2)
        self.assertGreaterEqual(APIUsageLog.objects.count(), 2)

    def test_non_developer_cannot_manage_api_keys(self):
        outsider = User.objects.create_user(
            email="outsider@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=outsider)

        response = self.client.get("/api/v1/developer/api-keys/")

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.data["success"])
