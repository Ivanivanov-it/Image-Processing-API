from django.db import transaction
from django.db.models import F

from .models import StorageQuota


def delete_image_and_files(image):
    operations = list(image.operations.all())
    total_size = image.file_size + sum(op.output_size for op in operations)
    for operation in operations:
        if operation.output_file:
            operation.output_file.delete(save=False)
    if image.original_file:
        image.original_file.delete(save=False)
    owner_id = image.owner_id
    with transaction.atomic():
        image.delete()
        quota = StorageQuota.objects.select_for_update().filter(owner_id=owner_id).first()
        if quota:
            quota.used_bytes = max(0, quota.used_bytes - total_size)
            quota.save(update_fields=["used_bytes", "updated_at"])


def add_quota_usage(owner_id, byte_count):
    with transaction.atomic():
        quota = StorageQuota.objects.select_for_update().get(owner_id=owner_id)
        if byte_count > quota.remaining_bytes:
            return False
        quota.used_bytes = F("used_bytes") + byte_count
        quota.save(update_fields=["used_bytes", "updated_at"])
    return True
