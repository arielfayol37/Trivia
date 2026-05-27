from rest_framework.generics import ListAPIView, RetrieveAPIView

from apps.quizzes.models import Quiz, QuizStatus
from apps.quizzes.serializers import QuizSerializer


class QuizListView(ListAPIView):
    serializer_class = QuizSerializer

    def get_queryset(self):
        queryset = Quiz.objects.prefetch_related("rounds__questions").order_by("-updated_at")
        if self.request.query_params.get("scope") == "authoring":
            return queryset.exclude(status=QuizStatus.ARCHIVED)[:50]
        return queryset.filter(status=QuizStatus.READY)[:50]


class QuizDetailView(RetrieveAPIView):
    queryset = Quiz.objects.prefetch_related("rounds__questions", "source_material")
    serializer_class = QuizSerializer
