from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from .views import (
    ImageOperationViewSet,
    QuotaView,
    UploadedImageViewSet,
    logout_token,
    register,
)

router = DefaultRouter()
router.register("images", UploadedImageViewSet, basename="image")
router.register("operations", ImageOperationViewSet, basename="operation")

urlpatterns = [
    path("", include(router.urls)),
    path("quota/", QuotaView.as_view(), name="quota"),
    path("auth/register/", register, name="api-register"),
    path("auth/token/", obtain_auth_token, name="api-token"),
    path("auth/logout/", logout_token, name="api-logout"),
]
