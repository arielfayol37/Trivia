from datetime import timedelta
import threading
import uuid

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.judging.fuzzy import fuzzy_match
from apps.judging.llm import judge_typed_answer_with_llm
from apps.quizzes.models import JudgeMode, Question, Quiz, QuizStatus, Round, RoundType
from apps.sessions.models import AnswerSubmission, Session, SessionPlayer, SessionRole, SessionStatus
from apps.sessions.realtime import broadcast_session_snapshot_sync
from apps.sessions.serializers import (
    ChatMessageSerializer,
    CreateSessionSerializer,
    JoinSessionSerializer,
    ReadySerializer,
    SessionSerializer,
    SubmitAnswerSerializer,
)

AUTO_ADVANCE_PHASES = {"question", "list_race"}
_AUTO_ADVANCE_LOCK = threading.Lock()
_AUTO_ADVANCE_TIMERS: dict[str, threading.Timer] = {}
_LOBBY_COUNTDOWN_LOCK = threading.Lock()
_LOBBY_COUNTDOWN_TIMERS: dict[str, threading.Timer] = {}


class SessionCreateView(APIView):
    def post(self, request):
        serializer = CreateSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        quiz = get_object_or_404(
            Quiz.objects.prefetch_related("rounds__questions"),
            pk=serializer.validated_data["quiz_id"],
        )
        if quiz.status != QuizStatus.READY:
            return Response(
                {"detail": "Only ready quizzes can create lobbies"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        display_name = serializer.validated_data.get("display_name", "").strip() or "Host"
        question_count = serializer.validated_data.get("question_count")
        settings = {"question_order": "sequential"}
        if question_count is not None:
            settings["question_count"] = question_count

        with transaction.atomic():
            session = Session.objects.create(
                quiz=quiz,
                host=request.user if request.user and request.user.is_authenticated else None,
                state={"settings": settings},
            )
            player = SessionPlayer.objects.create(
                session=session,
                user=request.user if request.user and request.user.is_authenticated else None,
                display_name=display_name,
                role=SessionRole.PLAYER,
                is_host=True,
            )

        broadcast_session_snapshot_sync(session.id, "session.created")
        return Response(
            _session_response(session, player.id),
            status=status.HTTP_201_CREATED,
        )


class SessionDetailView(APIView):
    def get(self, _request, session_id):
        session = get_object_or_404(_session_queryset(), pk=session_id)
        return Response(SessionSerializer(session).data)


class SessionJoinView(APIView):
    def post(self, request):
        serializer = JoinSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated = serializer.validated_data
        session = _get_join_session(validated)
        if session.status != SessionStatus.LOBBY:
            return Response(
                {"detail": "Only lobby sessions can be joined"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        display_name = validated["display_name"].strip()
        with transaction.atomic():
            locked_session = Session.objects.select_for_update().get(pk=session.pk)
            if _display_name_taken(locked_session, display_name):
                return Response(
                    {"detail": "That name is already in this room"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            player = SessionPlayer.objects.create(
                session=locked_session,
                user=request.user if request.user and request.user.is_authenticated else None,
                display_name=display_name,
                role=SessionRole.PLAYER,
            )
            _clear_lobby_countdown_state(locked_session)

        broadcast_session_snapshot_sync(locked_session.id, "session.player_joined")
        return Response(
            _session_response(locked_session, player.id),
            status=status.HTTP_201_CREATED,
        )


class SessionPlayerReadyView(APIView):
    def post(self, request, session_id, player_id):
        serializer = ReadySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        player = get_object_or_404(
            SessionPlayer.objects.select_related("session"),
            pk=player_id,
            session_id=session_id,
        )
        if player.session.status != SessionStatus.LOBBY:
            return Response(
                {"detail": "Ready state can only change in the lobby"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        player.is_ready = serializer.validated_data["is_ready"]
        player.save(update_fields=["is_ready"])
        session = _session_queryset().get(pk=session_id)
        _sync_lobby_countdown(session)
        session = _session_queryset().get(pk=session_id)
        broadcast_session_snapshot_sync(session_id, "session.player_ready")
        return Response(SessionSerializer(session).data)


class SessionStartView(APIView):
    def post(self, _request, session_id):
        session = get_object_or_404(_session_queryset(), pk=session_id)
        if session.status != SessionStatus.LOBBY:
            return Response(
                {"detail": "Only lobby sessions can be started"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not session.players.filter(role=SessionRole.PLAYER).exists():
            return Response(
                {"detail": "A session needs at least one player"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        refreshed, error_detail = _start_session(session)
        if error_detail:
            return Response(
                {"detail": error_detail},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _clear_lobby_countdown_timer(session_id)
        broadcast_session_snapshot_sync(session_id, "session.started")
        _schedule_auto_advance(refreshed)
        return Response(SessionSerializer(refreshed).data)


class SessionSubmitAnswerView(APIView):
    def post(self, request, session_id, player_id):
        serializer = SubmitAnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        session = get_object_or_404(_session_queryset(), pk=session_id)
        if session.status != SessionStatus.PLAYING:
            return Response(
                {"detail": "Answers can only be submitted while playing"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if _deadline_has_elapsed(session):
            _schedule_auto_advance(session, reason="deadline", delay_s=0)
            return Response(
                {"detail": "This question is closed"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        player = get_object_or_404(SessionPlayer, pk=player_id, session=session)
        if (session.state or {}).get("phase") == "list_race":
            return _submit_list_race_answer(session, player, serializer.validated_data)

        question = _current_question(session)
        if not question:
            return Response(
                {"detail": "No active question"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        submitted_payload = serializer.validated_data.get("submitted_payload") or {}
        submitted_text = _submitted_text(serializer.validated_data, submitted_payload)
        result = _judge_submission(question, submitted_text, submitted_payload)
        points_awarded = _points_for_question(question) if result["accepted"] else 0

        AnswerSubmission.objects.update_or_create(
            session=session,
            question=question,
            player=player,
            defaults={
                "round": question.round,
                "submitted_text": submitted_text,
                "submitted_payload": submitted_payload,
                "accepted": result["accepted"],
                "points_awarded": points_awarded,
                "judge_mode_used": result["judge_mode_used"],
                "judge_latency_ms": result.get("judge_latency_ms", 0),
                "judge_metadata": result["judge_metadata"],
            },
        )

        state = session.state or {}
        question_id = str(question.id)
        player_id_text = str(player.id)
        submissions = state.setdefault("submissions", {})
        question_submissions = submissions.setdefault(question_id, {})
        question_submissions[player_id_text] = {
            "accepted": result["accepted"],
            "points_awarded": points_awarded,
            "submitted_text": submitted_text,
            "submitted": True,
            "judge_mode_used": result["judge_mode_used"],
        }
        scores = state.setdefault("scores", {})
        scores[player_id_text] = _score_for_player(session, player)
        session.state = state
        session.save(update_fields=["state"])

        refreshed = _session_queryset().get(pk=session_id)
        broadcast_session_snapshot_sync(session_id, "session.answer_submitted")
        if _all_active_players_submitted(refreshed, question):
            _schedule_auto_advance(
                refreshed,
                reason="all_submitted",
                delay_s=_all_submitted_advance_delay_s(),
            )
        return Response(SessionSerializer(refreshed).data)


class SessionChatView(APIView):
    def post(self, request, session_id, player_id):
        serializer = ChatMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            session = get_object_or_404(Session.objects.select_for_update(), pk=session_id)
            player = get_object_or_404(SessionPlayer, pk=player_id, session=session)
            state = session.state or {}
            messages = state.setdefault("chat_messages", [])
            if not isinstance(messages, list):
                messages = []
            messages.append(
                {
                    "id": str(uuid.uuid4()),
                    "player_id": str(player.id),
                    "display_name": player.display_name,
                    "message": serializer.validated_data["message"],
                    "created_at": timezone.now().isoformat(),
                }
            )
            state["chat_messages"] = messages[-100:]
            session.state = state
            session.save(update_fields=["state"])

        refreshed = _session_queryset().get(pk=session_id)
        broadcast_session_snapshot_sync(session_id, "session.chat_message")
        return Response(SessionSerializer(refreshed).data)


class SessionNextQuestionView(APIView):
    def post(self, _request, session_id):
        session = get_object_or_404(_session_queryset(), pk=session_id)
        if session.status != SessionStatus.PLAYING:
            return Response(
                {"detail": "Only playing sessions can advance"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event = _advance_session(session)

        refreshed = _session_queryset().get(pk=session_id)
        broadcast_session_snapshot_sync(session_id, event)
        _schedule_auto_advance(refreshed)
        return Response(SessionSerializer(refreshed).data)


def _session_queryset():
    return Session.objects.select_related("quiz", "quiz__source_material").prefetch_related(
        "players",
        "quiz__rounds__questions",
    )


def _session_response(session: Session, player_id) -> dict:
    refreshed = _session_queryset().get(pk=session.pk)
    return {
        "session": SessionSerializer(refreshed).data,
        "player_id": str(player_id),
    }


def _get_join_session(validated: dict) -> Session:
    queryset = _session_queryset()
    invite_code = validated.get("invite_code", "").strip().upper()
    if invite_code:
        return get_object_or_404(queryset, invite_code=invite_code)
    return get_object_or_404(queryset, pk=validated["session_id"])


def _display_name_taken(session: Session, display_name: str) -> bool:
    return session.players.filter(display_name__iexact=display_name).exists()


def _playable_questions(session: Session) -> list[Question]:
    return [
        question
        for round_obj in session.quiz.rounds.all()
        for question in round_obj.questions.all()
        if question.answer_widget.get("type") in {"text_input", "multiple_choice"}
    ]


def _first_list_race_round(session: Session) -> Round | None:
    for round_obj in session.quiz.rounds.all():
        if round_obj.type == RoundType.LIST_RACE and _list_race_items(round_obj):
            return round_obj
    return None


def _sample_questions(session: Session) -> list[Question]:
    questions = _playable_questions(session)
    question_count = (session.state or {}).get("settings", {}).get("question_count")
    if question_count is None or len(questions) <= int(question_count):
        return questions
    return questions[: int(question_count)]


def _selected_questions(session: Session) -> list[Question]:
    state = session.state or {}
    selected_ids = state.get("selected_question_ids") or []
    if not selected_ids:
        return _sample_questions(session)

    questions_by_id = {str(question.id): question for question in _playable_questions(session)}
    return [questions_by_id[question_id] for question_id in selected_ids if question_id in questions_by_id]


def _current_question(session: Session) -> Question | None:
    question_id = (session.state or {}).get("question_id")
    if not question_id:
        return None

    for question in _playable_questions(session):
        if str(question.id) == question_id:
            return question
    return None


def _start_session(session: Session) -> tuple[Session | None, str | None]:
    list_race_round = _first_list_race_round(session)
    if list_race_round and not _playable_questions(session):
        session.status = SessionStatus.PLAYING
        session.started_at = timezone.now()
        session.current_round_idx = max(list_race_round.order - 1, 0)
        session.current_question_idx = 0
        session.state = _list_race_state(session, list_race_round)
        session.save(
            update_fields=[
                "status",
                "started_at",
                "current_round_idx",
                "current_question_idx",
                "state",
            ]
        )
        return _session_queryset().get(pk=session.id), None

    selected_questions = _sample_questions(session)
    if not selected_questions:
        return None, "Quiz has no playable questions"

    first_question = selected_questions[0]
    session.status = SessionStatus.PLAYING
    session.started_at = timezone.now()
    session.current_round_idx = 0
    session.current_question_idx = 0
    session.state = _question_state(session, first_question, 0, selected_questions)
    session.save(
        update_fields=[
            "status",
            "started_at",
            "current_round_idx",
            "current_question_idx",
            "state",
        ]
    )
    return _session_queryset().get(pk=session.id), None


def _advance_session(session: Session) -> str:
    if (session.state or {}).get("phase") == "list_race":
        _finish_session(session)
        _clear_auto_advance_timer(session.id)
        return "session.finished"

    selected_questions = _selected_questions(session)
    next_index = session.current_question_idx + 1
    if next_index >= len(selected_questions):
        _finish_session(session)
        _clear_auto_advance_timer(session.id)
        return "session.finished"

    next_question = selected_questions[next_index]
    session.current_question_idx = next_index
    session.state = _question_state(session, next_question, next_index, selected_questions)
    session.save(update_fields=["current_question_idx", "state"])
    return "session.question_advanced"


def _finish_session(session: Session) -> None:
    state = session.state or {}
    state["phase"] = "finished"
    session.status = SessionStatus.FINISHED
    session.ended_at = timezone.now()
    session.state = state
    session.save(update_fields=["status", "ended_at", "state"])


def _schedule_auto_advance(
    session: Session,
    *,
    reason: str = "deadline",
    delay_s: float | None = None,
) -> None:
    state = session.state or {}
    if session.status != SessionStatus.PLAYING or state.get("phase") not in AUTO_ADVANCE_PHASES:
        _clear_auto_advance_timer(session.id)
        return

    token = _state_advance_token(state)
    if not token:
        return

    if delay_s is None:
        deadline = _question_deadline(session)
        if deadline is None:
            return
        delay_s = max(0.0, (deadline - timezone.now()).total_seconds() + _timer_grace_s())

    timer_key = str(session.id)
    timer = threading.Timer(delay_s, _auto_advance_session, args=(session.id, token, reason))
    timer.daemon = True

    with _AUTO_ADVANCE_LOCK:
        existing = _AUTO_ADVANCE_TIMERS.pop(timer_key, None)
        if existing:
            existing.cancel()
        _AUTO_ADVANCE_TIMERS[timer_key] = timer
        timer.start()


def _auto_advance_session(session_id, token: str, reason: str) -> None:
    with _AUTO_ADVANCE_LOCK:
        _AUTO_ADVANCE_TIMERS.pop(str(session_id), None)

    try:
        with transaction.atomic():
            session = Session.objects.select_for_update().get(pk=session_id)
            if session.status != SessionStatus.PLAYING:
                return
            if _state_advance_token(session.state or {}) != token:
                return
            if not _auto_advance_condition_met(session, reason):
                return
            event = _advance_session(session)
    except Session.DoesNotExist:
        return

    refreshed = _session_queryset().get(pk=session_id)
    broadcast_session_snapshot_sync(session_id, event)
    _schedule_auto_advance(refreshed)


def _auto_advance_condition_met(session: Session, reason: str) -> bool:
    if reason == "all_submitted":
        question = _current_question(session)
        return bool(question and _all_active_players_submitted(session, question))
    return _deadline_has_elapsed(session)


def _all_active_players_submitted(session: Session, question: Question) -> bool:
    player_ids = [
        str(player_id)
        for player_id in session.players.filter(
            role=SessionRole.PLAYER,
            left_at__isnull=True,
        ).values_list("id", flat=True)
    ]
    if not player_ids:
        return False

    submissions = (session.state or {}).get("submissions") or {}
    question_submissions = submissions.get(str(question.id)) or {}
    return all((question_submissions.get(player_id) or {}).get("submitted") is True for player_id in player_ids)


def _deadline_has_elapsed(session: Session) -> bool:
    deadline = _question_deadline(session)
    return bool(deadline and timezone.now() >= deadline)


def _question_deadline(session: Session):
    state = session.state or {}
    started_at = state.get("question_started_at")
    timeout_s = state.get("question_timeout_s")
    if not started_at or timeout_s is None:
        return None

    parsed = parse_datetime(str(started_at))
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())

    return parsed + timedelta(seconds=int(timeout_s))


def _state_advance_token(state: dict) -> str | None:
    phase = state.get("phase")
    started_at = state.get("question_started_at")
    if phase == "question" and state.get("question_id"):
        return f"question:{state['question_id']}:{started_at}"
    if phase == "list_race" and state.get("round_id"):
        return f"list-race:{state['round_id']}:{started_at}"
    return None


def _clear_auto_advance_timer(session_id) -> None:
    with _AUTO_ADVANCE_LOCK:
        existing = _AUTO_ADVANCE_TIMERS.pop(str(session_id), None)
        if existing:
            existing.cancel()


def _sync_lobby_countdown(session: Session) -> None:
    if session.status != SessionStatus.LOBBY:
        _clear_lobby_countdown_timer(session.id)
        return

    if not _all_lobby_players_ready(session):
        _clear_lobby_countdown_state(session)
        return

    state = session.state or {}
    if not state.get("lobby_countdown_started_at"):
        state["lobby_countdown_started_at"] = timezone.now().isoformat()
        state["lobby_countdown_s"] = _lobby_countdown_s()
        session.state = state
        session.save(update_fields=["state"])

    _schedule_lobby_countdown(session)


def _schedule_lobby_countdown(session: Session) -> None:
    state = session.state or {}
    started_at = state.get("lobby_countdown_started_at")
    countdown_s = state.get("lobby_countdown_s")
    if not started_at or countdown_s is None:
        return

    parsed = parse_datetime(str(started_at))
    if parsed is None:
        return
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())

    delay_s = max(0.0, (parsed + timedelta(seconds=int(countdown_s)) - timezone.now()).total_seconds())
    token = str(started_at)
    timer_key = str(session.id)
    timer = threading.Timer(delay_s, _auto_start_session, args=(session.id, token))
    timer.daemon = True

    with _LOBBY_COUNTDOWN_LOCK:
        existing = _LOBBY_COUNTDOWN_TIMERS.pop(timer_key, None)
        if existing:
            existing.cancel()
        _LOBBY_COUNTDOWN_TIMERS[timer_key] = timer
        timer.start()


def _auto_start_session(session_id, token: str) -> None:
    with _LOBBY_COUNTDOWN_LOCK:
        _LOBBY_COUNTDOWN_TIMERS.pop(str(session_id), None)

    try:
        with transaction.atomic():
            session = Session.objects.select_for_update().get(pk=session_id)
            if session.status != SessionStatus.LOBBY:
                return
            if (session.state or {}).get("lobby_countdown_started_at") != token:
                return
            session = _session_queryset().get(pk=session_id)
            if not _all_lobby_players_ready(session):
                _clear_lobby_countdown_state(session)
                return
            refreshed, error_detail = _start_session(session)
            if error_detail:
                _clear_lobby_countdown_state(session)
                return
    except Session.DoesNotExist:
        return

    broadcast_session_snapshot_sync(session_id, "session.started")
    _schedule_auto_advance(refreshed)


def _all_lobby_players_ready(session: Session) -> bool:
    players = [
        player
        for player in session.players.all()
        if player.role == SessionRole.PLAYER and player.left_at is None
    ]
    return bool(players) and all(player.is_ready for player in players)


def _clear_lobby_countdown_state(session: Session) -> None:
    _clear_lobby_countdown_timer(session.id)
    state = session.state or {}
    if "lobby_countdown_started_at" not in state and "lobby_countdown_s" not in state:
        return
    state.pop("lobby_countdown_started_at", None)
    state.pop("lobby_countdown_s", None)
    session.state = state
    session.save(update_fields=["state"])


def _clear_lobby_countdown_timer(session_id) -> None:
    with _LOBBY_COUNTDOWN_LOCK:
        existing = _LOBBY_COUNTDOWN_TIMERS.pop(str(session_id), None)
        if existing:
            existing.cancel()


def _lobby_countdown_s() -> int:
    return int(getattr(settings, "SESSION_LOBBY_COUNTDOWN_S", 5))


def _without_lobby_countdown(state: dict) -> dict:
    cleaned = {**state}
    cleaned.pop("lobby_countdown_started_at", None)
    cleaned.pop("lobby_countdown_s", None)
    return cleaned


def _all_submitted_advance_delay_s() -> float:
    return float(getattr(settings, "SESSION_ALL_SUBMITTED_ADVANCE_DELAY_S", 4.0))


def _timer_grace_s() -> float:
    return float(getattr(settings, "SESSION_TIMER_ADVANCE_GRACE_S", 4.0))


def _question_state(
    session: Session,
    question: Question,
    index: int,
    selected_questions: list[Question],
) -> dict:
    previous_state = _without_lobby_countdown(session.state or {})
    timeout_s = question.round.config.get("answer_timeout_s") or question.round.config.get("time_limit_s") or 25
    return {
        **previous_state,
        "phase": "question",
        "selected_question_ids": [str(selected_question.id) for selected_question in selected_questions],
        "question_count": len(selected_questions),
        "question_index": index,
        "round_id": str(question.round.id),
        "question_id": str(question.id),
        "question_started_at": timezone.now().isoformat(),
        "question_timeout_s": int(timeout_s),
    }


def _list_race_state(session: Session, round_obj: Round) -> dict:
    previous_state = _without_lobby_countdown(session.state or {})
    timeout_s = round_obj.config.get("time_limit_s") or 1200
    return {
        **previous_state,
        "phase": "list_race",
        "round_id": str(round_obj.id),
        "question_count": 1,
        "question_index": 0,
        "question_started_at": timezone.now().isoformat(),
        "question_timeout_s": int(timeout_s),
        "list_race": {
            "prompt": round_obj.config.get("prompt", ""),
            "items_count": len(_list_race_items(round_obj)),
            "found": {},
            "last_submission": {},
        },
    }


def _submitted_text(validated: dict, submitted_payload: dict) -> str:
    submitted_text = str(validated.get("submitted_text", "")).strip()
    if submitted_text:
        return submitted_text
    for key in ["choice", "answer", "text"]:
        value = submitted_payload.get(key)
        if value:
            return str(value).strip()
    return ""


def _judge_submission(question: Question, submitted_text: str, submitted_payload: dict) -> dict:
    widget_type = question.answer_widget.get("type")
    acceptable_answers = question.acceptable_answers or [question.canonical_answer]

    if widget_type == "multiple_choice":
        accepted = submitted_text == question.canonical_answer or submitted_text in acceptable_answers
        return {
            "accepted": accepted,
            "judge_mode_used": "exact",
            "judge_metadata": {"submitted_payload": submitted_payload},
        }

    result = fuzzy_match(submitted_text, acceptable_answers)
    if not result["accepted"]:
        llm_result = judge_typed_answer_with_llm(
            question,
            submitted_text,
            fuzzy_result=result,
        )
        if llm_result:
            return {
                "accepted": llm_result["accepted"],
                "judge_mode_used": JudgeMode.LLM,
                "judge_latency_ms": llm_result.get("judge_latency_ms", 0),
                "judge_metadata": llm_result["judge_metadata"],
            }

    return {
        "accepted": result["accepted"],
        "judge_mode_used": JudgeMode.FUZZY,
        "judge_latency_ms": 0,
        "judge_metadata": result,
    }


def _submit_list_race_answer(session: Session, player: SessionPlayer, validated: dict) -> Response:
    round_obj = _current_round(session)
    if not round_obj or round_obj.type != RoundType.LIST_RACE:
        return Response(
            {"detail": "No active list race round"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    submitted_payload = validated.get("submitted_payload") or {}
    submitted_text = _submitted_text(validated, submitted_payload)
    if not submitted_text:
        return Response(
            {"detail": "Answer cannot be blank"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    state = session.state or {}
    list_race = state.setdefault("list_race", {})
    found = list_race.setdefault("found", {})
    player_key = str(player.id)
    player_found = found.setdefault(player_key, [])
    item_result = _match_list_race_item(round_obj, submitted_text)
    accepted = item_result["accepted"] and item_result["item_id"] not in player_found
    duplicate = item_result["accepted"] and item_result["item_id"] in player_found
    points_awarded = float(round_obj.config.get("points_per_item", 1)) if accepted else 0

    if accepted:
        player_found.append(item_result["item_id"])

    AnswerSubmission.objects.create(
        session=session,
        question=None,
        round=round_obj,
        player=player,
        submitted_text=submitted_text,
        submitted_payload=submitted_payload,
        accepted=accepted,
        points_awarded=points_awarded,
        judge_mode_used=JudgeMode.FUZZY,
        judge_metadata=item_result,
    )

    scores = state.setdefault("scores", {})
    scores[player_key] = _score_for_player(session, player)
    last_submission = list_race.setdefault("last_submission", {})
    last_submission[player_key] = {
        "accepted": accepted,
        "duplicate": duplicate,
        "canonical": item_result["canonical"],
        "submitted": submitted_text,
        "points_awarded": points_awarded,
        "found_count": len(player_found),
    }
    session.state = state
    session.save(update_fields=["state"])

    refreshed = _session_queryset().get(pk=session.id)
    broadcast_session_snapshot_sync(session.id, "session.answer_submitted")
    return Response(SessionSerializer(refreshed).data)


def _current_round(session: Session) -> Round | None:
    round_id = (session.state or {}).get("round_id")
    if not round_id:
        return None
    for round_obj in session.quiz.rounds.all():
        if str(round_obj.id) == round_id:
            return round_obj
    return None


def _list_race_items(round_obj: Round) -> list[dict]:
    items = round_obj.config.get("items")
    if not isinstance(items, list):
        return []

    normalized_items = []
    for index, item in enumerate(items):
        if isinstance(item, dict):
            canonical = str(item.get("canonical", "")).strip()
            acceptable = item.get("acceptable", [])
            if not isinstance(acceptable, list):
                acceptable = []
        else:
            canonical = str(item).strip()
            acceptable = []
        if canonical:
            normalized_items.append(
                {
                    "id": str(index),
                    "canonical": canonical,
                    "acceptable": [canonical, *[str(value) for value in acceptable if value]],
                }
            )
    return normalized_items


def _match_list_race_item(round_obj: Round, submitted_text: str) -> dict:
    best_result = {
        "accepted": False,
        "item_id": None,
        "canonical": None,
        "distance": None,
    }
    for item in _list_race_items(round_obj):
        result = fuzzy_match(submitted_text, item["acceptable"])
        if result["accepted"]:
            return {
                "accepted": True,
                "item_id": item["id"],
                "canonical": item["canonical"],
                "distance": result["distance"],
            }
        if best_result["distance"] is None or (
            result["distance"] is not None and result["distance"] < best_result["distance"]
        ):
            best_result = {
                "accepted": False,
                "item_id": item["id"],
                "canonical": item["canonical"],
                "distance": result["distance"],
            }
    return best_result


def _points_for_question(question: Question) -> float:
    return float(question.round.config.get("points_per_question", 10))


def _score_for_player(session: Session, player: SessionPlayer) -> float:
    aggregate = sum(
        submission.points_awarded
        for submission in AnswerSubmission.objects.filter(session=session, player=player)
    )
    return float(aggregate)
