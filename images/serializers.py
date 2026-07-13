from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import ImageOperation, ProcessingStatus, StorageQuota, TemporaryDownload, UploadedImage
from .validators import inspect_uploaded_image


class ImageOperationSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()
    output_name = serializers.SerializerMethodField()
    source_image_id = serializers.UUIDField(source="image_id", read_only=True)

    class Meta:
        model = ImageOperation
        fields = [
            "id", "operation_type", "parameters", "status", "progress_percent", "output_size",
            "output_width", "output_height", "error_message", "download_url",
            "preview_url", "output_name", "source_image_id",
            "started_at", "completed_at", "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_download_url(self, obj):
        if obj.status != ProcessingStatus.COMPLETED or not obj.output_file:
            return None
        request = self.context.get("request")
        path = f"/api/operations/{obj.id}/download/"
        return request.build_absolute_uri(path) if request else path

    def get_preview_url(self, obj):
        if obj.status != ProcessingStatus.COMPLETED or not obj.output_file:
            return None
        request = self.context.get("request")
        path = f"/api/operations/{obj.id}/preview/"
        return request.build_absolute_uri(path) if request else path

    def get_output_name(self, obj):
        return obj.output_file.name.rsplit("/", 1)[-1] if obj.output_file else None


class UploadedImageSerializer(serializers.ModelSerializer):
    owner = serializers.CharField(source="owner.username", read_only=True)
    original_file = serializers.ImageField(write_only=True)
    operations = ImageOperationSerializer(many=True, read_only=True)
    preview_url = serializers.SerializerMethodField()

    class Meta:
        model = UploadedImage
        fields = [
            "id", "owner", "original_file", "original_name", "content_type",
            "file_size", "width", "height", "status", "error_message",
            "expires_at", "preview_url", "operations", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "owner", "original_name", "content_type", "file_size", "width",
            "height", "status", "error_message", "expires_at", "operations",
            "preview_url", "created_at", "updated_at",
        ]

    def get_preview_url(self, obj):
        request = self.context.get("request")
        path = f"/api/images/{obj.id}/preview/"
        return request.build_absolute_uri(path) if request else path

    def validate_original_file(self, value):
        self._image_metadata = inspect_uploaded_image(value)
        return value

    def create(self, validated_data):
        owner = self.context["request"].user
        metadata = self._image_metadata
        with transaction.atomic():
            quota, _ = StorageQuota.objects.select_for_update().get_or_create(owner=owner)
            if metadata["file_size"] > quota.remaining_bytes:
                raise serializers.ValidationError({"original_file": "Your storage quota would be exceeded."})
            image = UploadedImage.objects.create(owner=owner, **validated_data, **metadata)
            quota.used_bytes += metadata["file_size"]
            quota.save(update_fields=["used_bytes", "updated_at"])
        return image


class ProcessImageSerializer(serializers.Serializer):
    BACKGROUND_MODELS = [
        ("birefnet-general", "BiRefNet general (best quality)"),
        ("birefnet-portrait", "BiRefNet portrait"),
        ("isnet-anime", "IS-Net anime"),
        ("birefnet-general-lite", "BiRefNet general lite (faster)"),
    ]

    operation_type = serializers.ChoiceField(choices=ImageOperation.OperationType.choices)
    width = serializers.IntegerField(min_value=1, max_value=8000, required=False)
    height = serializers.IntegerField(min_value=1, max_value=8000, required=False)
    quality = serializers.IntegerField(min_value=1, max_value=95, default=82, required=False)
    watermark_text = serializers.CharField(max_length=120, required=False, allow_blank=False)
    background_model = serializers.ChoiceField(choices=BACKGROUND_MODELS, required=False)
    refine_edges = serializers.BooleanField(required=False)

    def validate(self, attrs):
        operation = attrs["operation_type"]
        if operation == ImageOperation.OperationType.RESIZE and not (attrs.get("width") or attrs.get("height")):
            raise serializers.ValidationError("Resize requires a width, a height, or both.")
        if operation == ImageOperation.OperationType.THUMBNAIL and not (attrs.get("width") and attrs.get("height")):
            raise serializers.ValidationError("Thumbnail requires both width and height.")
        if operation == ImageOperation.OperationType.WATERMARK and not attrs.get("watermark_text"):
            raise serializers.ValidationError("Watermarking requires watermark_text.")
        allowed = {"operation_type"}
        if operation in {ImageOperation.OperationType.RESIZE, ImageOperation.OperationType.THUMBNAIL}:
            allowed |= {"width", "height", "quality"}
        elif operation in {ImageOperation.OperationType.WEBP, ImageOperation.OperationType.COMPRESS}:
            allowed |= {"quality"}
        elif operation == ImageOperation.OperationType.WATERMARK:
            allowed |= {"watermark_text", "quality"}
        elif operation == ImageOperation.OperationType.REMOVE_BACKGROUND:
            allowed |= {"background_model", "refine_edges"}
        unexpected = set(self.initial_data) - allowed
        if unexpected:
            raise serializers.ValidationError({key: "This parameter is not valid for the selected operation." for key in unexpected})
        if operation == ImageOperation.OperationType.REMOVE_BACKGROUND:
            attrs.setdefault("background_model", "birefnet-general")
            attrs.setdefault("refine_edges", True)
        return {key: value for key, value in attrs.items() if key in allowed}


class TemporaryDownloadSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    expires_in_minutes = serializers.IntegerField(write_only=True, min_value=1, max_value=1440, default=15)

    class Meta:
        model = TemporaryDownload
        fields = ["id", "url", "expires_at", "max_downloads", "download_count", "expires_in_minutes", "created_at"]
        read_only_fields = ["id", "url", "expires_at", "download_count", "created_at"]

    def create(self, validated_data):
        minutes = validated_data.pop("expires_in_minutes", 15)
        return TemporaryDownload.objects.create(expires_at=timezone.now() + timedelta(minutes=minutes), **validated_data)

    def get_url(self, obj):
        request = self.context.get("request")
        path = f"/downloads/{obj.token}/"
        return request.build_absolute_uri(path) if request else path


class StorageQuotaSerializer(serializers.ModelSerializer):
    remaining_bytes = serializers.IntegerField(read_only=True)
    usage_percent = serializers.SerializerMethodField()

    class Meta:
        model = StorageQuota
        fields = ["used_bytes", "limit_bytes", "remaining_bytes", "usage_percent", "updated_at"]
        read_only_fields = fields

    def get_usage_percent(self, obj):
        return round((obj.used_bytes / obj.limit_bytes) * 100, 1) if obj.limit_bytes else 100
