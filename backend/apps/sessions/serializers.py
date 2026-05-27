from rest_framework import serializers

from apps.quizzes.serializers import QuizSerializer
from apps.sessions.models import Session, SessionPlayer


class SessionPlayerSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionPlayer
        fields = [
            "id",
            "display_name",
            "role",
            "is_host",
            "is_ready",
            "joined_at",
            "left_at",
        ]


class SessionSerializer(serializers.ModelSerializer):
    players = SessionPlayerSerializer(many=True, read_only=True)
    quiz = QuizSerializer(read_only=True)

    class Meta:
        model = Session
        fields = [
            "id",
            "invite_code",
            "quiz",
            "status",
            "current_round_idx",
            "current_question_idx",
            "state",
            "players",
            "created_at",
            "started_at",
            "ended_at",
        ]


class CreateSessionSerializer(serializers.Serializer):
    quiz_id = serializers.UUIDField()
    display_name = serializers.CharField(required=False, allow_blank=True, max_length=80)
    question_count = serializers.IntegerField(required=False, min_value=1, max_value=50)


class JoinSessionSerializer(serializers.Serializer):
    invite_code = serializers.CharField(required=False, allow_blank=True, max_length=10)
    session_id = serializers.UUIDField(required=False)
    display_name = serializers.CharField(max_length=80)

    def validate(self, attrs):
        if not attrs.get("invite_code") and not attrs.get("session_id"):
            raise serializers.ValidationError("invite_code or session_id is required")
        return attrs


class ReadySerializer(serializers.Serializer):
    is_ready = serializers.BooleanField()


class SubmitAnswerSerializer(serializers.Serializer):
    submitted_text = serializers.CharField(required=False, allow_blank=True)
    submitted_payload = serializers.JSONField(required=False)


class ChatMessageSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=500, trim_whitespace=True)
