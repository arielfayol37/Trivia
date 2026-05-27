from __future__ import annotations

from asgiref.sync import async_to_sync
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authoring.llm import (
    LLMGenerationError,
    generate_authoring_chat_response,
    generate_quiz_document,
)
from apps.authoring.ops import (
    AuthoringContext,
    AuthoringError,
    apply_quiz_op,
    create_quiz_from_document,
)
from apps.quizzes.models import Quiz
from apps.quizzes.serializers import QuizSerializer


class GenerateQuizRequestSerializer(serializers.Serializer):
    prompt = serializers.CharField()
    source_text = serializers.CharField(required=False, allow_blank=True)


class AuthoringChatMessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["user", "assistant"])
    content = serializers.CharField()


class AuthoringChatRequestSerializer(serializers.Serializer):
    messages = AuthoringChatMessageSerializer(many=True)
    mode = serializers.CharField(required=False, allow_blank=True, default="auto")
    current_quiz = serializers.DictField(required=False, allow_empty=True, allow_null=True)
    recent_quizzes = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        allow_empty=True,
    )
    source_text = serializers.CharField(required=False, allow_blank=True)


class AuthoringChatView(APIView):
    def post(self, request):
        serializer = AuthoringChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            reply = async_to_sync(generate_authoring_chat_response)(
                serializer.validated_data["messages"],
                mode=serializer.validated_data.get("mode", "auto"),
                current_quiz=serializer.validated_data.get("current_quiz"),
                recent_quizzes=serializer.validated_data.get("recent_quizzes", []),
                source_text=serializer.validated_data.get("source_text", ""),
            )
        except LLMGenerationError as exc:
            return Response(
                {"detail": f"LLM chat failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"reply": reply})


class GenerateQuizView(APIView):
    def post(self, request):
        serializer = GenerateQuizRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            document = async_to_sync(generate_quiz_document)(
                serializer.validated_data["prompt"],
                serializer.validated_data.get("source_text", ""),
            )
        except LLMGenerationError as exc:
            return Response(
                {"detail": f"LLM generation failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        try:
            quiz = create_quiz_from_document(
                document,
                AuthoringContext(
                    user=request.user if request.user and request.user.is_authenticated else None
                ),
            )
        except AuthoringError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(QuizSerializer(quiz).data, status=status.HTTP_201_CREATED)


class ApplyQuizOpView(APIView):
    def post(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, pk=quiz_id)

        try:
            updated_quiz = apply_quiz_op(quiz, request.data)
        except AuthoringError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(QuizSerializer(updated_quiz).data)
