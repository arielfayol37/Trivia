from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({"ok": True, "service": "trivia-api"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/authoring/", include("apps.authoring.urls")),
    path("api/quizzes/", include("apps.quizzes.urls")),
    path("api/sessions/", include("apps.sessions.urls")),
    path("accounts/", include("allauth.urls")),
]
