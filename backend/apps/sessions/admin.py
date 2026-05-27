from django.contrib import admin

from apps.sessions.models import (
    AnswerSubmission,
    AntiCheatEvent,
    RoundResult,
    Session,
    SessionPlayer,
)


class SessionPlayerInline(admin.TabularInline):
    model = SessionPlayer
    extra = 0


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("quiz", "status", "created_at", "started_at", "ended_at")
    list_filter = ("status",)
    inlines = [SessionPlayerInline]


@admin.register(SessionPlayer)
class SessionPlayerAdmin(admin.ModelAdmin):
    list_display = ("display_name", "session", "role", "is_host", "is_ready", "joined_at")
    list_filter = ("role", "is_host", "is_ready")


@admin.register(AnswerSubmission)
class AnswerSubmissionAdmin(admin.ModelAdmin):
    list_display = ("session", "round", "player", "accepted", "points_awarded", "submitted_at")
    list_filter = ("accepted", "judge_mode_used")


@admin.register(RoundResult)
class RoundResultAdmin(admin.ModelAdmin):
    list_display = ("session", "round", "player", "raw_score", "normalized_score")


@admin.register(AntiCheatEvent)
class AntiCheatEventAdmin(admin.ModelAdmin):
    list_display = ("session", "player", "kind", "severity", "occurred_at")
    list_filter = ("kind", "severity")

