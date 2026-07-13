import shutil
import tempfile
import uuid

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from images.models import ImageOperation, ProcessingStatus, StorageQuota, UploadedImage
from .helpers import image_upload


class ImageModelTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self.user = User.objects.create_user("owner", password="long-test-password")

    def make_image(self, owner=None):
        upload = image_upload()
        return UploadedImage.objects.create(
            owner=owner or self.user,
            original_file=upload,
            original_name=upload.name,
            content_type="image/jpeg",
            file_size=upload.size,
            width=80,
            height=60,
        )

    def test_image_uses_uuid_and_timestamp_defaults(self):
        image = self.make_image()
        self.assertIsInstance(image.id, uuid.UUID)
        self.assertEqual(image.status, ProcessingStatus.PENDING)
        self.assertIsNotNone(image.created_at)
        self.assertIsNotNone(image.updated_at)
        self.assertGreater(image.expires_at, image.created_at)

    def test_relationships_and_operation_owner_are_safe(self):
        image = self.make_image()
        attacker = User.objects.create_user("attacker")
        operation = ImageOperation.objects.create(
            image=image, owner=attacker, operation_type=ImageOperation.OperationType.WEBP
        )
        self.assertEqual(operation.owner, self.user)
        self.assertEqual(list(image.operations.all()), [operation])

    def test_quota_remaining_bytes(self):
        quota = StorageQuota.objects.create(owner=self.user, used_bytes=25, limit_bytes=100)
        self.assertEqual(quota.remaining_bytes, 75)

    def test_expected_query_indexes_exist(self):
        names = {index.name for index in UploadedImage._meta.indexes}
        self.assertTrue({"img_owner_created_idx", "img_owner_updated_idx", "img_status_created_idx", "img_expires_idx"}.issubset(names))
