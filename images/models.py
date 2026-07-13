import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


def default_expiry():
    return timezone.now() + timedelta(days=settings.IMAGE_RETENTION_DAYS)


def original_upload_path(instance, filename):
    suffix = Path(filename).suffix.lower()
    return f"users/{instance.owner_id}/originals/{instance.id}{suffix}"


def result_upload_path(instance, filename):
    suffix = Path(filename).suffix.lower()
    return f"users/{instance.image.owner_id}/results/{instance.id}{suffix}"


class ProcessingStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class UploadedImage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="uploaded_images")
    original_file = models.ImageField(upload_to=original_upload_path, max_length=500)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=50)
    file_size = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=ProcessingStatus.choices, default=ProcessingStatus.PENDING)
    error_message = models.TextField(blank=True)
    expires_at = models.DateTimeField(default=default_expiry)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "-created_at"], name="img_owner_created_idx"),
            models.Index(fields=["owner", "-updated_at"], name="img_owner_updated_idx"),
            models.Index(fields=["status", "created_at"], name="img_status_created_idx"),
            models.Index(fields=["expires_at"], name="img_expires_idx"),
        ]

    def __str__(self):
        return self.original_name


class ImageOperation(models.Model):
    class OperationType(models.TextChoices):
        RESIZE = "resize", "Resize"
        WEBP = "webp", "Convert to WebP"
        THUMBNAIL = "thumbnail", "Thumbnail"
        COMPRESS = "compress", "Compress"
        REMOVE_BACKGROUND = "remove_background", "Remove background"
        REMOVE_METADATA = "remove_metadata", "Remove metadata"
        WATERMARK = "watermark", "Watermark"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    image = models.ForeignKey(UploadedImage, on_delete=models.CASCADE, related_name="operations")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="image_operations")
    operation_type = models.CharField(max_length=30, choices=OperationType.choices)
    parameters = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=ProcessingStatus.choices, default=ProcessingStatus.PENDING)
    progress_percent = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    output_file = models.ImageField(upload_to=result_upload_path, max_length=500, blank=True)
    output_size = models.PositiveBigIntegerField(default=0)
    output_width = models.PositiveIntegerField(null=True, blank=True)
    output_height = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "-created_at"], name="op_owner_created_idx"),
            models.Index(fields=["image", "status"], name="op_image_status_idx"),
            models.Index(fields=["status", "created_at"], name="op_status_created_idx"),
        ]

    def __str__(self):
        return f"{self.get_operation_type_display()} - {self.image.original_name}"

    def save(self, *args, **kwargs):
        if self.image_id:
            self.owner_id = self.image.owner_id
        super().save(*args, **kwargs)


class StorageQuota(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="storage_quota")
    used_bytes = models.PositiveBigIntegerField(default=0)
    limit_bytes = models.PositiveBigIntegerField(default=settings.DEFAULT_STORAGE_QUOTA)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(used_bytes__lte=models.F("limit_bytes")), name="quota_used_lte_limit")]

    @property
    def remaining_bytes(self):
        return max(0, self.limit_bytes - self.used_bytes)


class TemporaryDownload(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    operation = models.ForeignKey(ImageOperation, on_delete=models.CASCADE, related_name="download_links")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="temporary_downloads")
    expires_at = models.DateTimeField()
    max_downloads = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    download_count = models.PositiveSmallIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["expires_at"], name="download_expires_idx"),
            models.Index(fields=["owner", "-created_at"], name="download_owner_idx"),
        ]

    @property
    def is_valid(self):
        return self.revoked_at is None and self.expires_at > timezone.now() and self.download_count < self.max_downloads
