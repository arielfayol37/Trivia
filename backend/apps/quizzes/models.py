from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class SourceKind(models.TextChoices):
    TOPIC = "topic", "Topic"
    TEXT = "text", "Text"
    PDF = "pdf", "PDF"
    URL = "url", "URL"


class QuizVisibility(models.TextChoices):
    PRIVATE = "private", "Private"
    PUBLIC = "public", "Public"


class QuizStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    READY = "ready", "Ready"
    ARCHIVED = "archived", "Archived"


class QuizCategory(models.TextChoices):
    SCIENCE = "science", "Science"
    TV = "tv", "TV & Movies"
    SPORTS = "sports", "Sports"
    GEOGRAPHY = "geography", "Geography"
    HISTORY = "history", "History"
    GENERAL = "general", "General"


class Difficulty(models.TextChoices):
    EASY = "easy", "Easy"
    MEDIUM = "medium", "Medium"
    HARD = "hard", "Hard"


class AntiCheatStrictness(models.TextChoices):
    STRICT = "strict", "Strict"
    FRIENDLY = "friendly", "Friendly"
    OFF = "off", "Off"


class RoundType(models.TextChoices):
    META_STRATEGY = "meta_strategy", "Meta-strategy"
    LIST_RACE = "list_race", "List race"
    BUZZ_IN = "buzz_in", "Buzz-in"
    SYNC_OPEN = "sync_open", "Synchronized open-answer"


class JudgeMode(models.TextChoices):
    FUZZY = "fuzzy", "Fuzzy"
    LLM = "llm", "LLM"


class SourceMaterial(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=16, choices=SourceKind.choices)
    content = models.TextField()
    original_url = models.URLField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_materials",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.kind}:{self.id}"


class Quiz(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=32, choices=QuizCategory.choices, default=QuizCategory.GENERAL)
    topic = models.CharField(max_length=180, blank=True)
    difficulty = models.CharField(max_length=16, choices=Difficulty.choices, default=Difficulty.MEDIUM)
    status = models.CharField(max_length=16, choices=QuizStatus.choices, default=QuizStatus.DRAFT)
    visibility = models.CharField(
        max_length=16, choices=QuizVisibility.choices, default=QuizVisibility.PRIVATE
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quizzes",
    )
    source_material = models.ForeignKey(
        SourceMaterial,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quizzes",
    )
    anticheat_strictness = models.CharField(
        max_length=16,
        choices=AntiCheatStrictness.choices,
        default=AntiCheatStrictness.FRIENDLY,
    )
    schema_version = models.PositiveIntegerField(default=1)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "-updated_at"]),
            models.Index(fields=["category", "-updated_at"]),
            models.Index(fields=["visibility", "-updated_at"]),
            models.Index(fields=["topic"]),
        ]

    def __str__(self) -> str:
        return self.title


class Round(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="rounds")
    order = models.PositiveIntegerField()
    type = models.CharField(max_length=32, choices=RoundType.choices)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["order", "id"]
        unique_together = [("quiz", "order")]

    def __str__(self) -> str:
        return f"{self.quiz.title} / {self.order}. {self.type}"


class Question(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveIntegerField()
    prompt_blocks = models.JSONField(default=list, blank=True)
    answer_widget = models.JSONField(default=dict, blank=True)
    canonical_answer = models.TextField(blank=True)
    acceptable_answers = models.JSONField(default=list, blank=True)
    judge_mode = models.CharField(max_length=16, choices=JudgeMode.choices, default=JudgeMode.FUZZY)
    judge_config = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["order", "id"]
        unique_together = [("round", "order")]

    def __str__(self) -> str:
        return f"{self.round} / Q{self.order}"


class LeaderboardEntry(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="leaderboard_entries")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    best_normalized_score = models.FloatField(default=0)
    plays_count = models.PositiveIntegerField(default=0)
    last_played_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("quiz", "user")]
        indexes = [
            models.Index(fields=["quiz", "-best_normalized_score"]),
        ]

    def __str__(self) -> str:
        return f"{self.quiz} / {self.user} / {self.best_normalized_score:.1f}"
