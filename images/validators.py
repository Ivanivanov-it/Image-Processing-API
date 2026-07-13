from pathlib import Path

from django.conf import settings
from rest_framework import serializers
from PIL import Image, UnidentifiedImageError


ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png"}


def inspect_uploaded_image(upload):
    if upload.size <= 0:
        raise serializers.ValidationError("The uploaded file is empty.")
    if upload.size > settings.MAX_UPLOAD_SIZE:
        raise serializers.ValidationError(f"Images may not exceed {settings.MAX_UPLOAD_SIZE // (1024 * 1024)} MB.")

    try:
        upload.seek(0)
        with Image.open(upload) as image:
            image.verify()
        upload.seek(0)
        with Image.open(upload) as image:
            image_format = image.format
            width, height = image.size
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise serializers.ValidationError("Upload a valid, non-corrupt PNG or JPEG image.") from exc
    finally:
        upload.seek(0)

    if image_format not in ALLOWED_FORMATS:
        raise serializers.ValidationError("Only PNG and JPEG source images are supported.")
    if width * height > settings.MAX_IMAGE_PIXELS:
        raise serializers.ValidationError("The image dimensions are too large to process safely.")

    suffix = Path(upload.name).suffix.lower()
    expected = {"JPEG": {".jpg", ".jpeg"}, "PNG": {".png"}}
    if suffix not in expected[image_format]:
        raise serializers.ValidationError("The filename extension does not match the decoded image format.")

    return {
        "width": width,
        "height": height,
        "content_type": ALLOWED_FORMATS[image_format],
        "file_size": upload.size,
        "original_name": Path(upload.name).name[:255],
    }
