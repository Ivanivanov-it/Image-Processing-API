import shutil
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from images.models import ImageOperation, ProcessingStatus, StorageQuota, UploadedImage
from images.tasks import _background_session, cleanup_expired_images, process_image_operation
from .helpers import image_upload


class ProcessingTaskTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self.user = User.objects.create_user("worker-user")
        upload = image_upload(size=(100, 50))
        self.image = UploadedImage.objects.create(
            owner=self.user, original_file=upload, original_name=upload.name,
            content_type="image/jpeg", file_size=upload.size, width=100, height=50,
        )
        StorageQuota.objects.create(owner=self.user, used_bytes=upload.size)

    def test_webp_task_creates_real_output_and_updates_quota(self):
        operation = ImageOperation.objects.create(
            image=self.image, owner=self.user, operation_type=ImageOperation.OperationType.WEBP,
            parameters={"quality": 75},
        )
        process_image_operation(str(operation.id))
        operation.refresh_from_db()
        self.assertEqual(operation.status, ProcessingStatus.COMPLETED, operation.error_message)
        with Image.open(operation.output_file.path) as result:
            self.assertEqual(result.format, "WEBP")
            self.assertEqual(result.size, (100, 50))
        self.assertEqual(StorageQuota.objects.get(owner=self.user).used_bytes, self.image.file_size + operation.output_size)

    def test_cleanup_deletes_expired_image(self):
        UploadedImage.objects.filter(pk=self.image.pk).update(expires_at=timezone.now())
        self.assertEqual(cleanup_expired_images(), 1)
        self.assertFalse(UploadedImage.objects.exists())
        self.assertEqual(StorageQuota.objects.get(owner=self.user).used_bytes, 0)

    def test_background_removal_pipeline_uses_png_output(self):
        operation = ImageOperation.objects.create(
            image=self.image, owner=self.user,
            operation_type=ImageOperation.OperationType.REMOVE_BACKGROUND,
        )
        calls = {}
        fake_session = object()
        def fake_remove(source, **kwargs):
            calls.update(kwargs)
            return source
        fake_new_session = Mock(return_value=fake_session)
        fake_module = SimpleNamespace(remove=fake_remove, new_session=fake_new_session)
        _background_session.cache_clear()
        with patch.dict(sys.modules, {"rembg": fake_module}):
            process_image_operation(str(operation.id))
        operation.refresh_from_db()
        self.assertEqual(operation.status, ProcessingStatus.COMPLETED, operation.error_message)
        with Image.open(operation.output_file.path) as result:
            self.assertEqual(result.format, "PNG")
        fake_new_session.assert_called_once_with("birefnet-general")
        self.assertIs(calls["session"], fake_session)
        self.assertTrue(calls["alpha_matting"])
        _background_session.cache_clear()
