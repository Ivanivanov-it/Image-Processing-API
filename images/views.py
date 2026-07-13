from pathlib import Path

from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import FormView, TemplateView
from rest_framework import status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ImageOperation, ProcessingStatus, StorageQuota, TemporaryDownload, UploadedImage
from .serializers import (
    ImageOperationSerializer,
    ProcessImageSerializer,
    StorageQuotaSerializer,
    TemporaryDownloadSerializer,
    UploadedImageSerializer,
)
from .services import delete_image_and_files
from .tasks import process_image_operation


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "images/dashboard.html"


class ThumbnailEditorView(LoginRequiredMixin, TemplateView):
    template_name = "images/thumbnail_editor.html"


class SignupView(FormView):
    template_name = "registration/signup.html"
    form_class = UserCreationForm
    success_url = reverse_lazy("dashboard")

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        return super().form_valid(form)


class UploadedImageViewSet(viewsets.ModelViewSet):
    serializer_class = UploadedImageSerializer
    permission_classes = [IsAuthenticated]
    ordering_fields = ["created_at", "updated_at"]
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        queryset = UploadedImage.objects.filter(owner=self.request.user)
        if self.action in {"list", "retrieve"}:
            queryset = queryset.prefetch_related("operations")
        return queryset

    def perform_destroy(self, instance):
        delete_image_and_files(instance)

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        image = self.get_object()
        try:
            handle = image.original_file.open("rb")
        except (FileNotFoundError, OSError) as exc:
            raise Http404("The original image is unavailable.") from exc
        return FileResponse(handle, content_type=image.content_type)

    @action(detail=False, methods=["post"])
    def batch(self, request):
        files = request.FILES.getlist("files")
        if not files:
            return Response({"files": ["Select at least one image."]}, status=status.HTTP_400_BAD_REQUEST)
        if len(files) > 10:
            return Response({"files": ["A batch may contain at most 10 images."]}, status=status.HTTP_400_BAD_REQUEST)
        serializers = [self.get_serializer(data={"original_file": upload}) for upload in files]
        valid = all(serializer.is_valid() for serializer in serializers)
        if not valid:
            return Response({"items": [serializer.errors for serializer in serializers]}, status=status.HTTP_400_BAD_REQUEST)
        requested_bytes = sum(serializer._image_metadata["file_size"] for serializer in serializers)
        with transaction.atomic():
            quota, _ = StorageQuota.objects.select_for_update().get_or_create(owner=request.user)
            if requested_bytes > quota.remaining_bytes:
                return Response({"files": ["This batch would exceed your storage quota."]}, status=status.HTTP_400_BAD_REQUEST)
            created = [serializer.save() for serializer in serializers]
        return Response(self.get_serializer(created, many=True).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def process(self, request, pk=None):
        image = self.get_object()
        serializer = ProcessImageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parameters = {key: value for key, value in serializer.validated_data.items() if key != "operation_type"}
        with transaction.atomic():
            operation = ImageOperation.objects.create(
                image=image,
                owner=request.user,
                operation_type=serializer.validated_data["operation_type"],
                parameters=parameters,
            )
            transaction.on_commit(lambda operation_id=operation.id: process_image_operation.delay(str(operation_id)))
        return Response(ImageOperationSerializer(operation, context={"request": request}).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"])
    def operations(self, request, pk=None):
        image = self.get_object()
        serializer = ImageOperationSerializer(image.operations.all(), many=True, context={"request": request})
        return Response(serializer.data)


class ImageOperationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ImageOperationSerializer
    permission_classes = [IsAuthenticated]
    ordering_fields = ["created_at", "updated_at"]

    def get_queryset(self):
        return ImageOperation.objects.filter(owner=self.request.user).select_related("image")

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        operation = self.get_object()
        if operation.status != ProcessingStatus.COMPLETED or not operation.output_file:
            return Response({"detail": "The processed file is not ready."}, status=status.HTTP_409_CONFLICT)
        try:
            handle = operation.output_file.open("rb")
        except (FileNotFoundError, OSError) as exc:
            raise Http404("The processed file is unavailable.") from exc
        suffix = Path(operation.output_file.name).suffix.lower()
        content_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(suffix, "application/octet-stream")
        return FileResponse(handle, content_type=content_type)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        operation = self.get_object()
        if operation.status != ProcessingStatus.COMPLETED or not operation.output_file:
            return Response({"detail": "The processed file is not ready."}, status=status.HTTP_409_CONFLICT)
        return _file_response(operation)

    @action(detail=True, methods=["post"], url_path="temporary-link")
    def temporary_link(self, request, pk=None):
        operation = self.get_object()
        if operation.status != ProcessingStatus.COMPLETED or not operation.output_file:
            return Response({"detail": "The processed file is not ready."}, status=status.HTTP_409_CONFLICT)
        serializer = TemporaryDownloadSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        link = serializer.save(operation=operation, owner=request.user)
        return Response(TemporaryDownloadSerializer(link, context={"request": request}).data, status=status.HTTP_201_CREATED)


class QuotaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        quota, _ = StorageQuota.objects.get_or_create(owner=request.user)
        return Response(StorageQuotaSerializer(quota).data)


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    username = str(request.data.get("username", "")).strip()
    password = str(request.data.get("password", ""))
    if not username or len(username) > 150:
        return Response({"username": ["Enter a username of at most 150 characters."]}, status=status.HTTP_400_BAD_REQUEST)
    if User.objects.filter(username__iexact=username).exists():
        return Response({"username": ["A user with this username already exists."]}, status=status.HTTP_400_BAD_REQUEST)
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    candidate = User(username=username)
    try:
        validate_password(password, user=candidate)
    except ValidationError as exc:
        return Response({"password": list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
    try:
        with transaction.atomic():
            user = User.objects.create_user(username=username, password=password)
    except IntegrityError:
        return Response({"username": ["A user with this username already exists."]}, status=status.HTTP_400_BAD_REQUEST)
    token = Token.objects.create(user=user)
    return Response({"token": token.key, "username": user.username}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def logout_token(request):
    Token.objects.filter(user=request.user).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


def _file_response(operation):
    try:
        handle = operation.output_file.open("rb")
    except (FileNotFoundError, OSError) as exc:
        raise Http404("The processed file is unavailable.") from exc
    filename = Path(operation.output_file.name).name
    return FileResponse(handle, as_attachment=True, filename=filename)


def temporary_download(request, token):
    with transaction.atomic():
        link = get_object_or_404(
            TemporaryDownload.objects.select_for_update().select_related("operation"), token=token
        )
        if not link.is_valid or link.operation.status != ProcessingStatus.COMPLETED or not link.operation.output_file:
            raise Http404("This download link is invalid or expired.")
        link.download_count += 1
        link.save(update_fields=["download_count", "updated_at"])
        operation = link.operation
    return _file_response(operation)
from pathlib import Path

from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
