import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Image_processing_API.settings")

app = Celery("image_processing_api")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
