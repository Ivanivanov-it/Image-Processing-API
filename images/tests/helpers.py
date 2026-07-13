from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image


def image_upload(name="sample.jpg", size=(80, 60), image_format="JPEG", color=(39, 120, 86)):
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format=image_format)
    return SimpleUploadedFile(name, output.getvalue(), content_type=f"image/{image_format.lower()}")
