import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from images.models import ImageOperation, ProcessingStatus, StorageQuota, TemporaryDownload, UploadedImage
from .helpers import image_upload


class ImageApiTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root, CELERY_TASK_ALWAYS_EAGER=True)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self.user = User.objects.create_user("alice", password="a-secure-password-123")
        self.other = User.objects.create_user("bob", password="a-secure-password-123")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def upload(self, name="photo.jpg"):
        return self.client.post("/api/images/", {"original_file": image_upload(name)}, format="multipart")

    def test_authentication_is_required(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/images/").status_code, 401)

    def test_upload_sets_owner_and_ignores_supplied_owner(self):
        response = self.client.post(
            "/api/images/",
            {"original_file": image_upload(), "owner": self.other.username},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.data)
        image = UploadedImage.objects.get()
        self.assertEqual(image.owner, self.user)
        self.assertEqual(response.data["owner"], self.user.username)
        self.assertNotIn("original_file", response.data)

    def test_users_cannot_access_another_users_image_or_preview(self):
        self.client.force_authenticate(self.other)
        image_id = self.upload().data["id"]
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(f"/api/images/{image_id}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/images/{image_id}/preview/").status_code, 404)

    def test_only_supported_real_images_are_accepted(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        fake = SimpleUploadedFile("fake.jpg", b"not an image", content_type="image/jpeg")
        response = self.client.post("/api/images/", {"original_file": fake}, format="multipart")
        self.assertEqual(response.status_code, 400)
        mismatch = image_upload("wrong.png", image_format="JPEG")
        response = self.client.post("/api/images/", {"original_file": mismatch}, format="multipart")
        self.assertEqual(response.status_code, 400)

    def test_ordering_is_limited_and_supported(self):
        first = self.upload("first.jpg").data["id"]
        second = self.upload("second.jpg").data["id"]
        response = self.client.get("/api/images/?ordering=created_at")
        self.assertEqual([item["id"] for item in response.data["results"]], [first, second])
        response = self.client.get("/api/images/?ordering=-updated_at")
        self.assertEqual(response.status_code, 200)

    def test_batch_upload_and_quota_accounting(self):
        response = self.client.post(
            "/api/images/batch/",
            {"files": [image_upload("one.jpg"), image_upload("two.jpg")]},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(UploadedImage.objects.filter(owner=self.user).count(), 2)
        quota = StorageQuota.objects.get(owner=self.user)
        self.assertEqual(quota.used_bytes, sum(image.file_size for image in UploadedImage.objects.all()))

    def test_batch_rejects_quota_overflow_without_creating_rows(self):
        StorageQuota.objects.create(owner=self.user, limit_bytes=1)
        response = self.client.post("/api/images/batch/", {"files": [image_upload()]}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(UploadedImage.objects.exists())

    def test_process_resize_and_authenticated_download(self):
        image_id = self.upload().data["id"]
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/images/{image_id}/process/",
                {"operation_type": "resize", "width": 40, "quality": 80},
                format="json",
            )
        self.assertEqual(response.status_code, 202, response.data)
        operation = ImageOperation.objects.get()
        self.assertEqual(operation.status, ProcessingStatus.COMPLETED, operation.error_message)
        self.assertEqual(operation.progress_percent, 100)
        self.assertEqual((operation.output_width, operation.output_height), (40, 30))
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f"/api/operations/{operation.id}/download/").status_code, 404)
        self.client.force_authenticate(self.user)
        download = self.client.get(f"/api/operations/{operation.id}/download/")
        self.assertEqual(download.status_code, 200)
        detail = self.client.get(f"/api/images/{image_id}/").data
        self.assertEqual(detail["operations"][0]["progress_percent"], 100)
        self.assertIn(f"/api/operations/{operation.id}/preview/", detail["operations"][0]["preview_url"])
        self.assertEqual(self.client.get(f"/api/operations/{operation.id}/preview/").status_code, 200)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f"/api/operations/{operation.id}/preview/").status_code, 404)

    def test_processing_parameters_are_validated(self):
        image_id = self.upload().data["id"]
        response = self.client.post(f"/api/images/{image_id}/process/", {"operation_type": "resize"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_background_model_is_validated_and_high_quality_default_is_saved(self):
        image_id = self.upload().data["id"]
        response = self.client.post(
            f"/api/images/{image_id}/process/",
            {"operation_type": "remove_background", "background_model": "not-a-model"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            f"/api/images/{image_id}/process/",
            {"operation_type": "remove_background"},
            format="json",
        )
        self.assertEqual(response.status_code, 202, response.data)
        operation = ImageOperation.objects.get()
        self.assertEqual(operation.parameters["background_model"], "birefnet-general")
        self.assertTrue(operation.parameters["refine_edges"])
        response = self.client.post(
            f"/api/images/{image_id}/process/",
            {"operation_type": "remove_metadata", "width": 99},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_temporary_link_expires_and_is_limited(self):
        image_id = self.upload().data["id"]
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/api/images/{image_id}/process/", {"operation_type": "webp"}, format="json")
        operation = ImageOperation.objects.get()
        response = self.client.post(
            f"/api/operations/{operation.id}/temporary-link/",
            {"expires_in_minutes": 10, "max_downloads": 1},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        link = TemporaryDownload.objects.get()
        anonymous = APIClient()
        self.assertEqual(anonymous.get(f"/downloads/{link.token}/").status_code, 200)
        self.assertEqual(anonymous.get(f"/downloads/{link.token}/").status_code, 404)
        link.download_count = 0
        link.expires_at = timezone.now() - timedelta(seconds=1)
        link.save()
        self.assertEqual(anonymous.get(f"/downloads/{link.token}/").status_code, 404)

    def test_delete_removes_rows_files_and_quota_usage(self):
        image_id = self.upload().data["id"]
        image = UploadedImage.objects.get(pk=image_id)
        stored_name = image.original_file.path
        response = self.client.delete(f"/api/images/{image_id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(UploadedImage.objects.exists())
        self.assertEqual(StorageQuota.objects.get(owner=self.user).used_bytes, 0)
        from pathlib import Path
        self.assertFalse(Path(stored_name).exists())


class AuthenticationAndDashboardTests(TestCase):
    def test_registration_validates_password_and_returns_token(self):
        client = APIClient()
        weak = client.post("/api/auth/register/", {"username": "new-user", "password": "123"}, format="json")
        self.assertEqual(weak.status_code, 400)
        response = client.post(
            "/api/auth/register/",
            {"username": "new-user", "password": "portfolio-safe-password-918!"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn("token", response.data)

    def test_dashboard_requires_login_and_renders_workspace(self):
        response = self.client.get("/")
        self.assertRedirects(response, "/accounts/login/?next=/")
        user = User.objects.create_user("studio-user", password="portfolio-safe-password-918!")
        self.client.force_login(user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PixelForge")
        self.assertContains(response, 'id="uploadForm"')
        self.assertContains(response, 'id="processForm"')
        self.assertContains(response, 'id="backgroundModel"')
        self.assertContains(response, 'id="imagePreviewDialog"')
        self.assertContains(response, 'id="selectFromPreview"')
        self.assertContains(response, 'id="downloadFromPreview"')
