from django.urls import path

from apps.authoring.views import ApplyQuizOpView, AuthoringChatView, GenerateQuizView

urlpatterns = [
    path("chat/", AuthoringChatView.as_view(), name="authoring-chat"),
    path("generate/", GenerateQuizView.as_view(), name="authoring-generate"),
    path("quizzes/<uuid:quiz_id>/ops/", ApplyQuizOpView.as_view(), name="authoring-quiz-ops"),
]
