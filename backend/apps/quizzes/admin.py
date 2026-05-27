from django.contrib import admin

from apps.quizzes.models import LeaderboardEntry, Question, Quiz, Round, SourceMaterial


class RoundInline(admin.TabularInline):
    model = Round
    extra = 0
    fields = ("order", "type", "config")


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0
    fields = ("order", "judge_mode", "canonical_answer", "acceptable_answers")


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "topic", "difficulty", "status", "visibility", "updated_at")
    list_filter = ("category", "difficulty", "status", "visibility", "anticheat_strictness")
    search_fields = ("title", "category", "topic", "description")
    inlines = [RoundInline]


@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
    list_display = ("quiz", "order", "type")
    list_filter = ("type",)
    inlines = [QuestionInline]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("round", "order", "judge_mode", "canonical_answer")
    list_filter = ("judge_mode",)
    search_fields = ("canonical_answer",)


@admin.register(SourceMaterial)
class SourceMaterialAdmin(admin.ModelAdmin):
    list_display = ("kind", "uploaded_by", "created_at")
    list_filter = ("kind",)


@admin.register(LeaderboardEntry)
class LeaderboardEntryAdmin(admin.ModelAdmin):
    list_display = ("quiz", "user", "best_normalized_score", "plays_count", "last_played_at")
