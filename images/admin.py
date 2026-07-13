from django.contrib import admin

from .models import ImageOperation, StorageQuota, TemporaryDownload, UploadedImage


@admin.register(UploadedImage)
class UploadedImageAdmin(admin.ModelAdmin):
    list_display = ("original_name", "owner", "status", "file_size", "created_at", "expires_at")
    list_filter = ("status", "created_at")
    search_fields = ("original_name", "owner__username")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(ImageOperation)
class ImageOperationAdmin(admin.ModelAdmin):
    list_display = ("operation_type", "image", "owner", "status", "output_size", "created_at")
    list_filter = ("operation_type", "status")
    search_fields = ("image__original_name", "owner__username")
    readonly_fields = ("id", "created_at", "updated_at")


admin.site.register(StorageQuota)
admin.site.register(TemporaryDownload)
