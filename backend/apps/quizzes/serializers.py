from rest_framework import serializers

from apps.quizzes.models import Question, Quiz, Round, SourceMaterial


class SourceMaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceMaterial
        fields = ["id", "kind", "content", "original_url", "created_at"]


class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = [
            "id",
            "order",
            "prompt_blocks",
            "answer_widget",
            "canonical_answer",
            "acceptable_answers",
            "judge_mode",
            "judge_config",
            "metadata",
        ]


class RoundSerializer(serializers.ModelSerializer):
    questions = QuestionSerializer(many=True, read_only=True)

    class Meta:
        model = Round
        fields = ["id", "order", "type", "config", "questions"]


class QuizSerializer(serializers.ModelSerializer):
    rounds = RoundSerializer(many=True, read_only=True)
    source_material = SourceMaterialSerializer(read_only=True)

    class Meta:
        model = Quiz
        fields = [
            "id",
            "title",
            "description",
            "category",
            "topic",
            "difficulty",
            "status",
            "visibility",
            "anticheat_strictness",
            "schema_version",
            "metadata",
            "source_material",
            "rounds",
            "created_at",
            "updated_at",
        ]
