from io import BytesIO
from functools import lru_cache
from pathlib import Path

from celery import shared_task
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .models import ImageOperation, ProcessingStatus, StorageQuota, TemporaryDownload, UploadedImage
from .services import delete_image_and_files


@lru_cache(maxsize=2)
def _background_session(model_name):
    from rembg import new_session

    return new_session(model_name)


def _open_source(operation):
    operation.image.original_file.open("rb")
    try:
        image = Image.open(operation.image.original_file)
        image.load()
        return ImageOps.exif_transpose(image)
    finally:
        operation.image.original_file.close()


def _resize(image, width=None, height=None):
    if width and height:
        size = (width, height)
    elif width:
        size = (width, max(1, round(image.height * width / image.width)))
    else:
        size = (max(1, round(image.width * height / image.height)), height)
    return image.resize(size, Image.Resampling.LANCZOS)


def _render_operation(operation):
    image = _open_source(operation)
    params = operation.parameters
    operation_type = operation.operation_type
    quality = params.get("quality", 82)
    source_format = (image.format or Path(operation.image.original_name).suffix.lstrip(".")).upper()
    output_format = "PNG" if source_format == "PNG" else "JPEG"

    if operation_type == ImageOperation.OperationType.RESIZE:
        image = _resize(image, params.get("width"), params.get("height"))
    elif operation_type == ImageOperation.OperationType.THUMBNAIL:
        image.thumbnail((params["width"], params["height"]), Image.Resampling.LANCZOS)
    elif operation_type == ImageOperation.OperationType.WEBP:
        output_format = "WEBP"
    elif operation_type == ImageOperation.OperationType.REMOVE_BACKGROUND:
        try:
            from rembg import remove
        except ImportError as exc:
            raise RuntimeError("Background removal requires the optional 'rembg' package.") from exc
        source = BytesIO()
        image.save(source, format="PNG")
        model_name = params.get("background_model", "birefnet-general")
        image = Image.open(BytesIO(remove(
            source.getvalue(),
            session=_background_session(model_name),
            alpha_matting=params.get("refine_edges", True),
            alpha_matting_foreground_threshold=240,
            alpha_matting_background_threshold=10,
            alpha_matting_erode_size=10,
        )))
        image.load()
        output_format = "PNG"
    elif operation_type == ImageOperation.OperationType.WATERMARK:
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        font = ImageFont.load_default(size=max(14, min(image.size) // 18))
        text = params["watermark_text"]
        bounds = draw.textbbox((0, 0), text, font=font)
        padding = max(10, min(image.size) // 40)
        x = max(padding, image.width - (bounds[2] - bounds[0]) - padding)
        y = max(padding, image.height - (bounds[3] - bounds[1]) - padding)
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 190), stroke_width=2, stroke_fill=(0, 0, 0, 150))
        image = Image.alpha_composite(image, layer)

    if output_format == "JPEG" and image.mode not in {"RGB", "L"}:
        background = Image.new("RGB", image.size, "white")
        if "A" in image.getbands():
            background.paste(image, mask=image.getchannel("A"))
        else:
            background.paste(image.convert("RGB"))
        image = background

    output = BytesIO()
    save_options = {}
    if output_format in {"JPEG", "WEBP"}:
        save_options = {"quality": quality, "optimize": True}
    elif output_format == "PNG":
        save_options = {"optimize": True, "compress_level": max(1, min(9, round((100 - quality) / 11)))}
    image.save(output, format=output_format, **save_options)
    extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[output_format]
    filename = f"{Path(operation.image.original_name).stem}-{operation.operation_type}-{operation.id}{extension}"
    return output.getvalue(), filename, image.width, image.height


@shared_task(bind=True, max_retries=2, autoretry_for=(OSError,), retry_backoff=True)
def process_image_operation(self, operation_id):
    operation = ImageOperation.objects.select_related("image").get(pk=operation_id)
    if operation.status == ProcessingStatus.COMPLETED:
        return str(operation.id)

    now = timezone.now()
    claimed = ImageOperation.objects.filter(
        pk=operation.pk, status__in=[ProcessingStatus.PENDING, ProcessingStatus.FAILED]
    ).update(status=ProcessingStatus.PROCESSING, progress_percent=10, started_at=now, error_message="")
    if not claimed:
        return None
    UploadedImage.objects.filter(pk=operation.image_id).update(status=ProcessingStatus.PROCESSING, error_message="")
    operation.status = ProcessingStatus.PROCESSING
    operation.progress_percent = 10

    reserved = 0
    try:
        ImageOperation.objects.filter(pk=operation.pk).update(progress_percent=25)
        operation.progress_percent = 25
        data, filename, width, height = _render_operation(operation)
        ImageOperation.objects.filter(pk=operation.pk).update(progress_percent=85)
        operation.progress_percent = 85
        with transaction.atomic():
            quota = StorageQuota.objects.select_for_update().get(owner_id=operation.owner_id)
            if len(data) > quota.remaining_bytes:
                raise RuntimeError("The processed file would exceed your storage quota.")
            quota.used_bytes += len(data)
            quota.save(update_fields=["used_bytes", "updated_at"])
            reserved = len(data)
            operation.output_file.save(filename, ContentFile(data), save=False)
            operation.output_size = len(data)
            operation.output_width = width
            operation.output_height = height
            operation.status = ProcessingStatus.COMPLETED
            operation.progress_percent = 100
            operation.completed_at = timezone.now()
            operation.error_message = ""
            operation.save()
            UploadedImage.objects.filter(pk=operation.image_id).update(status=ProcessingStatus.COMPLETED, error_message="")
        return str(operation.id)
    except Exception as exc:
        if operation.output_file:
            operation.output_file.delete(save=False)
        if reserved:
            with transaction.atomic():
                quota = StorageQuota.objects.select_for_update().get(owner_id=operation.owner_id)
                quota.used_bytes = max(0, quota.used_bytes - reserved)
                quota.save(update_fields=["used_bytes", "updated_at"])
        message = str(exc)[:2000] or exc.__class__.__name__
        ImageOperation.objects.filter(pk=operation.pk).update(
            status=ProcessingStatus.FAILED, error_message=message, completed_at=timezone.now()
        )
        UploadedImage.objects.filter(pk=operation.image_id).update(status=ProcessingStatus.FAILED, error_message=message)
        if isinstance(exc, OSError):
            raise
        return None


@shared_task
def cleanup_expired_images():
    TemporaryDownload.objects.filter(expires_at__lte=timezone.now()).delete()
    count = 0
    for image in UploadedImage.objects.filter(expires_at__lte=timezone.now()).prefetch_related("operations"):
        delete_image_and_files(image)
        count += 1
    return count


@shared_task
def recalculate_storage_quota(owner_id):
    original = UploadedImage.objects.filter(owner_id=owner_id).aggregate(total=Sum("file_size"))["total"] or 0
    processed = ImageOperation.objects.filter(owner_id=owner_id).aggregate(total=Sum("output_size"))["total"] or 0
    quota, _ = StorageQuota.objects.get_or_create(owner_id=owner_id)
    quota.used_bytes = min(quota.limit_bytes, original + processed)
    quota.save(update_fields=["used_bytes", "updated_at"])
    return quota.used_bytes
