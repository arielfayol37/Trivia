from django.urls import path

from apps.quizzes.views import QuizDetailView, QuizListView

urlpatterns = [
    path("", QuizListView.as_view(), name="quiz-list"),
    path("<uuid:pk>/", QuizDetailView.as_view(), name="quiz-detail"),
]

