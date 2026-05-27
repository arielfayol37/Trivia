from __future__ import annotations

import secrets
import uuid

from django.conf import settings
from django.db import models

INVITE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def make_invite_code(length: int = 6) -> str:
    return "".join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(length))


class SessionStatus(models.TextChoices):
    LOBBY = "lobby", "Lobby"
    PLAYING = "playing", "Playing"
    FINISHED = "finished", "Finished"
    ABANDONED = "abandoned", "Abandoned"


class SessionRole(models.TextChoices):
    PLAYER = "player", "Player"
    SPECTATOR = "spectator", "Spectator"


class AntiCheatSeverity(models.TextChoices):
    SOFT = "soft", "Soft"
    HARD = "hard", "Hard"


class Session(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quiz = models.ForeignKey("quizzes.Quiz", on_delete=models.CASCADE, related_name="sessions")
    invite_code = models.CharField(max_length=10, unique=True, db_index=True)
    status = models.CharField(max_length=16, choices=SessionStatus.choices, default=SessionStatus.LOBBY)
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hosted_sessions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    current_round_idx = models.PositiveIntegerField(default=0)
    current_question_idx = models.PositiveIntegerField(default=0)
    state = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["quiz", "status"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.quiz} / {self.status}"

    def save(self, *args, **kwargs):
        if not self.invite_code:
            while True:
                invite_code = make_invite_code()
                if not Session.objects.filter(invite_code=invite_code).exists():
                    self.invite_code = invite_code
                    break
        super().save(*args, **kwargs)


class SessionPlayer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="players")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="session_players",
    )
    display_name = models.CharField(max_length=80)
    role = models.CharField(max_length=16, choices=SessionRole.choices, default=SessionRole.PLAYER)
    is_host = models.BooleanField(default=False)
    guest_token_hash = models.CharField(max_length=128, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)
    is_ready = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["session", "role"]),
            models.Index(fields=["session", "is_host"]),
        ]

    def __str__(self) -> str:
        return f"{self.display_name} / {self.session}"


class AnswerSubmission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="answer_submissions")
    question = models.ForeignKey(
        "quizzes.Question",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="answer_submissions",
    )
    round = models.ForeignKey("quizzes.Round", on_delete=models.CASCADE, related_name="answer_submissions")
    player = models.ForeignKey(
        SessionPlayer, on_delete=models.CASCADE, related_name="answer_submissions"
    )
    submitted_text = models.TextField(blank=True)
    submitted_payload = models.JSONField(default=dict, blank=True)
    accepted = models.BooleanField(default=False)
    points_awarded = models.FloatField(default=0)
    judge_mode_used = models.CharField(max_length=16, blank=True)
    judge_latency_ms = models.PositiveIntegerField(default=0)
    judge_metadata = models.JSONField(default=dict, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["session", "round", "player"]),
            models.Index(fields=["question", "player"]),
        ]


class RoundResult(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="round_results")
    round = models.ForeignKey("quizzes.Round", on_delete=models.CASCADE, related_name="round_results")
    player = models.ForeignKey(SessionPlayer, on_delete=models.CASCADE, related_name="round_results")
    raw_score = models.FloatField(default=0)
    normalized_score = models.FloatField(default=0)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("session", "round", "player")]


class AntiCheatEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="anticheat_events")
    player = models.ForeignKey(SessionPlayer, on_delete=models.CASCADE, related_name="anticheat_events")
    kind = models.CharField(max_length=40)
    severity = models.CharField(max_length=16, choices=AntiCheatSeverity.choices)
    question = models.ForeignKey(
        "quizzes.Question",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="anticheat_events",
    )
    payload = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["session", "player", "kind"]),
            models.Index(fields=["occurred_at"]),
        ]
