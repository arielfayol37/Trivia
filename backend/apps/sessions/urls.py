from django.urls import path

from apps.sessions.views import (
    SessionCreateView,
    SessionChatView,
    SessionDetailView,
    SessionJoinView,
    SessionNextQuestionView,
    SessionPlayerReadyView,
    SessionPlaceWagerView,
    SessionStartView,
    SessionSubmitAnswerView,
)

urlpatterns = [
    path("", SessionCreateView.as_view(), name="session-create"),
    path("join/", SessionJoinView.as_view(), name="session-join"),
    path("<uuid:session_id>/", SessionDetailView.as_view(), name="session-detail"),
    path("<uuid:session_id>/start/", SessionStartView.as_view(), name="session-start"),
    path("<uuid:session_id>/next/", SessionNextQuestionView.as_view(), name="session-next"),
    path(
        "<uuid:session_id>/players/<uuid:player_id>/ready/",
        SessionPlayerReadyView.as_view(),
        name="session-player-ready",
    ),
    path(
        "<uuid:session_id>/players/<uuid:player_id>/answer/",
        SessionSubmitAnswerView.as_view(),
        name="session-submit-answer",
    ),
    path(
        "<uuid:session_id>/players/<uuid:player_id>/wager/",
        SessionPlaceWagerView.as_view(),
        name="session-place-wager",
    ),
    path(
        "<uuid:session_id>/players/<uuid:player_id>/chat/",
        SessionChatView.as_view(),
        name="session-chat",
    ),
]
