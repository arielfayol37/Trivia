from datetime import timedelta
from unittest.mock import patch

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.authoring.ops import AuthoringContext, create_quiz_from_document
from apps.authoring.sample import sample_quiz_document
from apps.sessions.models import SessionRole, SessionStatus
from apps.sessions.views import (
    _auto_advance_session,
    _auto_start_session,
    _session_queryset,
    _state_advance_token,
)
from apps.quizzes.models import QuizStatus
from trivia.asgi import application


@override_settings(SESSION_BACKGROUND_TIMERS_ENABLED=False)
class SessionApiTests(TestCase):
    def setUp(self):
        self.quiz = create_quiz_from_document(sample_quiz_document("quantum mechanics"), AuthoringContext())
        self.quiz.status = QuizStatus.READY
        self.quiz.save(update_fields=["status"])
        self.client = Client()

    def _start_session(self, session_id: str, player_id: str):
        return self.client.post(
            f"/api/sessions/{session_id}/start/",
            data={"player_id": player_id},
            content_type="application/json",
        )

    def _force_next_question(self, session_id: str, player_id: str):
        return self.client.post(
            f"/api/sessions/{session_id}/next/",
            data={"player_id": player_id},
            content_type="application/json",
        )

    def _leave_session(self, session_id: str, player_id: str):
        return self.client.post(
            f"/api/sessions/{session_id}/players/{player_id}/leave/",
            content_type="application/json",
        )

    def test_create_session_returns_invite_code_and_host_player(self):
        response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["session"]["status"], SessionStatus.LOBBY)
        self.assertTrue(payload["session"]["invite_code"])
        self.assertEqual(payload["session"]["players"][0]["display_name"], "Ariel")
        self.assertTrue(payload["session"]["players"][0]["is_host"])
        self.assertEqual(payload["player_id"], payload["session"]["players"][0]["id"])

    def test_create_session_rejects_draft_quiz(self):
        self.quiz.status = QuizStatus.DRAFT
        self.quiz.save(update_fields=["status"])

        response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("ready", response.json()["detail"])

    def test_join_session_by_invite_code_adds_player(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        invite_code = create_response.json()["session"]["invite_code"]

        join_response = self.client.post(
            "/api/sessions/join/",
            data={"invite_code": invite_code.lower(), "display_name": "Friend"},
            content_type="application/json",
        )

        self.assertEqual(join_response.status_code, 201)
        payload = join_response.json()
        names = {player["display_name"] for player in payload["session"]["players"]}
        self.assertEqual(names, {"Ariel", "Friend"})

    def test_join_session_rejects_duplicate_display_name(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        invite_code = create_response.json()["session"]["invite_code"]

        join_response = self.client.post(
            "/api/sessions/join/",
            data={"invite_code": invite_code, "display_name": "ariel"},
            content_type="application/json",
        )

        self.assertEqual(join_response.status_code, 400)
        self.assertEqual(join_response.json()["detail"], "That name is already in this room")

    def test_join_playing_session_admits_spectator(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel", "question_count": 1},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        start_response = self._start_session(session_id, create_response.json()["player_id"])

        join_response = self.client.post(
            "/api/sessions/join/",
            data={"session_id": session_id, "display_name": "Watcher"},
            content_type="application/json",
        )

        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(join_response.status_code, 201)
        payload = join_response.json()
        self.assertEqual(payload["session"]["status"], SessionStatus.PLAYING)
        spectator = next(player for player in payload["session"]["players"] if player["display_name"] == "Watcher")
        self.assertEqual(spectator["role"], SessionRole.SPECTATOR)
        self.assertFalse(spectator["is_host"])

    def test_spectator_can_chat_but_cannot_submit_or_continue(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel", "question_count": 1},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        host_id = create_response.json()["player_id"]
        start_response = self._start_session(session_id, host_id)
        join_response = self.client.post(
            "/api/sessions/join/",
            data={"session_id": session_id, "display_name": "Watcher"},
            content_type="application/json",
        )
        spectator_id = join_response.json()["player_id"]

        chat_response = self.client.post(
            f"/api/sessions/{session_id}/players/{spectator_id}/chat/",
            data={"message": "watching this one"},
            content_type="application/json",
        )
        submit_response = self.client.post(
            f"/api/sessions/{session_id}/players/{spectator_id}/answer/",
            data={"submitted_text": start_response.json()["quiz"]["rounds"][0]["questions"][0]["canonical_answer"]},
            content_type="application/json",
        )
        wager_response = self.client.post(
            f"/api/sessions/{session_id}/players/{spectator_id}/wager/",
            data={"points": 1},
            content_type="application/json",
        )
        continue_response = self.client.post(
            f"/api/sessions/{session_id}/players/{spectator_id}/continue/",
            content_type="application/json",
        )

        self.assertEqual(chat_response.status_code, 200)
        self.assertEqual(chat_response.json()["state"]["chat_messages"][-1]["display_name"], "Watcher")
        self.assertEqual(submit_response.status_code, 403)
        self.assertIn("Spectators", submit_response.json()["detail"])
        self.assertEqual(wager_response.status_code, 403)
        self.assertIn("Spectators", wager_response.json()["detail"])
        self.assertEqual(continue_response.status_code, 403)
        self.assertIn("Spectators", continue_response.json()["detail"])

    def test_join_abandoned_session_is_rejected(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        self._leave_session(session_id, create_response.json()["player_id"])

        join_response = self.client.post(
            "/api/sessions/join/",
            data={"session_id": session_id, "display_name": "Watcher"},
            content_type="application/json",
        )

        self.assertEqual(join_response.status_code, 400)
        self.assertEqual(join_response.json()["detail"], "This room is closed")

    def test_invite_preview_returns_room_summary_without_questions(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        invite_code = create_response.json()["session"]["invite_code"]

        preview_response = self.client.get(f"/api/sessions/invite/{invite_code.lower()}/")

        self.assertEqual(preview_response.status_code, 200)
        payload = preview_response.json()
        self.assertEqual(payload["invite_code"], invite_code)
        self.assertEqual(payload["status"], SessionStatus.LOBBY)
        self.assertEqual(payload["quiz"]["title"], self.quiz.title)
        self.assertNotIn("rounds", payload["quiz"])
        self.assertEqual(payload["player_count"], 1)
        self.assertEqual(payload["players"][0]["display_name"], "Ariel")
        self.assertTrue(payload["players"][0]["is_host"])

    def test_player_leave_allows_name_reuse(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        join_response = self.client.post(
            "/api/sessions/join/",
            data={"session_id": session_id, "display_name": "Friend"},
            content_type="application/json",
        )
        player_id = join_response.json()["player_id"]

        leave_response = self._leave_session(session_id, player_id)
        rejoin_response = self.client.post(
            "/api/sessions/join/",
            data={"session_id": session_id, "display_name": "Friend"},
            content_type="application/json",
        )

        self.assertEqual(leave_response.status_code, 200)
        left_player = next(player for player in leave_response.json()["players"] if player["id"] == player_id)
        self.assertIsNotNone(left_player["left_at"])
        self.assertEqual(rejoin_response.status_code, 201)

    def test_host_leave_migrates_lobby_host(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        host_id = create_response.json()["player_id"]
        join_response = self.client.post(
            "/api/sessions/join/",
            data={"session_id": session_id, "display_name": "Friend"},
            content_type="application/json",
        )
        friend_id = join_response.json()["player_id"]

        leave_response = self._leave_session(session_id, host_id)

        self.assertEqual(leave_response.status_code, 200)
        players_by_id = {player["id"]: player for player in leave_response.json()["players"]}
        self.assertFalse(players_by_id[host_id]["is_host"])
        self.assertTrue(players_by_id[friend_id]["is_host"])
        self.assertEqual(leave_response.json()["status"], SessionStatus.LOBBY)

    def test_last_player_leave_abandons_lobby(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        player_id = create_response.json()["player_id"]

        leave_response = self._leave_session(session_id, player_id)

        self.assertEqual(leave_response.status_code, 200)
        self.assertEqual(leave_response.json()["status"], SessionStatus.ABANDONED)
        self.assertEqual(leave_response.json()["state"]["phase"], "abandoned")

    def test_ready_endpoint_updates_player_state(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        payload = create_response.json()

        ready_response = self.client.post(
            f"/api/sessions/{payload['session']['id']}/players/{payload['player_id']}/ready/",
            data={"is_ready": True},
            content_type="application/json",
        )

        self.assertEqual(ready_response.status_code, 200)
        self.assertTrue(ready_response.json()["players"][0]["is_ready"])
        self.client.post(
            f"/api/sessions/{payload['session']['id']}/players/{payload['player_id']}/ready/",
            data={"is_ready": False},
            content_type="application/json",
        )

    def test_chat_endpoint_appends_room_message(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        payload = create_response.json()

        chat_response = self.client.post(
            f"/api/sessions/{payload['session']['id']}/players/{payload['player_id']}/chat/",
            data={"message": "that was brutal"},
            content_type="application/json",
        )

        self.assertEqual(chat_response.status_code, 200)
        messages = chat_response.json()["state"]["chat_messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["display_name"], "Ariel")
        self.assertEqual(messages[0]["message"], "that was brutal")

    def test_all_ready_sets_countdown_and_auto_starts(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        create_payload = create_response.json()
        session_id = create_payload["session"]["id"]
        host_id = create_payload["player_id"]
        join_response = self.client.post(
            "/api/sessions/join/",
            data={"session_id": session_id, "display_name": "Friend"},
            content_type="application/json",
        )
        friend_id = join_response.json()["player_id"]

        host_ready_response = self.client.post(
            f"/api/sessions/{session_id}/players/{host_id}/ready/",
            data={"is_ready": True},
            content_type="application/json",
        )
        self.assertNotIn("lobby_countdown_started_at", host_ready_response.json()["state"])

        friend_ready_response = self.client.post(
            f"/api/sessions/{session_id}/players/{friend_id}/ready/",
            data={"is_ready": True},
            content_type="application/json",
        )
        countdown_started_at = friend_ready_response.json()["state"]["lobby_countdown_started_at"]
        self.assertEqual(friend_ready_response.json()["state"]["lobby_countdown_s"], 5)

        _auto_start_session(session_id, countdown_started_at)

        payload = self.client.get(f"/api/sessions/{session_id}/").json()
        self.assertEqual(payload["status"], SessionStatus.PLAYING)
        self.assertEqual(payload["state"]["phase"], "question")
        self.assertNotIn("lobby_countdown_started_at", payload["state"])

    def test_unready_cancels_lobby_countdown(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        create_payload = create_response.json()
        session_id = create_payload["session"]["id"]
        host_id = create_payload["player_id"]

        ready_response = self.client.post(
            f"/api/sessions/{session_id}/players/{host_id}/ready/",
            data={"is_ready": True},
            content_type="application/json",
        )
        self.assertIn("lobby_countdown_started_at", ready_response.json()["state"])

        unready_response = self.client.post(
            f"/api/sessions/{session_id}/players/{host_id}/ready/",
            data={"is_ready": False},
            content_type="application/json",
        )
        self.assertNotIn("lobby_countdown_started_at", unready_response.json()["state"])

    def test_start_session_sets_first_play_state(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel", "question_count": 1},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        player_id = create_response.json()["player_id"]

        start_response = self._start_session(session_id, player_id)

        self.assertEqual(start_response.status_code, 200)
        payload = start_response.json()
        self.assertEqual(payload["status"], SessionStatus.PLAYING)
        self.assertEqual(payload["state"]["phase"], "question")
        self.assertTrue(payload["state"]["round_id"])
        self.assertTrue(payload["state"]["question_id"])
        self.assertEqual(payload["state"]["question_count"], 1)
        self.assertEqual(len(payload["state"]["selected_question_ids"]), 1)

    def test_start_session_defaults_to_full_quiz_in_authored_order(self):
        ordered_quiz = create_quiz_from_document(
            {
                "title": "Ordered Geography Set",
                "description": "A complete authored quiz, not a sampled bank.",
                "topic": "geography",
                "difficulty": "medium",
                "rounds": [
                    {
                        "type": "sync_open",
                        "order": 1,
                        "config": {"answer_timeout_s": 20},
                        "questions": [
                            {
                                "order": index,
                                "prompt_blocks": [
                                    {"type": "text", "text": f"Round 1 question {index}"}
                                ],
                                "answer_widget": {"type": "text_input"},
                                "canonical_answer": f"r1-{index}",
                                "acceptable_answers": [f"r1-{index}"],
                            }
                            for index in range(1, 7)
                        ],
                    },
                    {
                        "type": "sync_open",
                        "order": 2,
                        "config": {"answer_timeout_s": 20},
                        "questions": [
                            {
                                "order": index,
                                "prompt_blocks": [
                                    {"type": "text", "text": f"Round 2 question {index}"}
                                ],
                                "answer_widget": {"type": "text_input"},
                                "canonical_answer": f"r2-{index}",
                                "acceptable_answers": [f"r2-{index}"],
                            }
                            for index in range(1, 7)
                        ],
                    },
                ],
            },
            AuthoringContext(),
        )
        ordered_quiz.status = QuizStatus.READY
        ordered_quiz.save(update_fields=["status"])
        expected_question_ids = [
            str(question.id)
            for round_obj in ordered_quiz.rounds.all()
            for question in round_obj.questions.all()
        ]
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(ordered_quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        player_id = create_response.json()["player_id"]

        start_response = self._start_session(session_id, player_id)

        self.assertEqual(start_response.status_code, 200)
        payload = start_response.json()
        self.assertEqual(payload["state"]["question_count"], 12)
        self.assertEqual(payload["state"]["selected_question_ids"], expected_question_ids)
        self.assertEqual(payload["state"]["question_id"], expected_question_ids[0])

    def test_non_host_cannot_start_session(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        join_response = self.client.post(
            "/api/sessions/join/",
            data={"session_id": session_id, "display_name": "Friend"},
            content_type="application/json",
        )

        start_response = self._start_session(session_id, join_response.json()["player_id"])

        self.assertEqual(start_response.status_code, 403)
        self.assertIn("Only the host", start_response.json()["detail"])

    def test_submit_answer_scores_current_question(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        create_payload = create_response.json()
        session_id = create_payload["session"]["id"]
        player_id = create_payload["player_id"]
        start_response = self._start_session(session_id, player_id)
        canonical_answer = start_response.json()["quiz"]["rounds"][0]["questions"][0]["canonical_answer"]

        submit_response = self.client.post(
            f"/api/sessions/{session_id}/players/{player_id}/answer/",
            data={"submitted_text": canonical_answer},
            content_type="application/json",
        )

        self.assertEqual(submit_response.status_code, 200)
        payload = submit_response.json()
        question_id = payload["state"]["question_id"]
        self.assertTrue(payload["state"]["submissions"][question_id][player_id]["accepted"])
        self.assertEqual(payload["state"]["scores"][player_id], 10.0)
        self.assertEqual(payload["state"]["submissions"][question_id][player_id]["submitted_text"], canonical_answer)

    def test_submit_answer_uses_llm_fallback_after_fuzzy_miss(self):
        quiz = create_quiz_from_document(
            {
                "title": "Cameroon Geography",
                "description": "Alias judging test.",
                "category": "geography",
                "topic": "Cameroon",
                "difficulty": "easy",
                "rounds": [
                    {
                        "type": "sync_open",
                        "order": 1,
                        "config": {"points_per_question": 10},
                        "questions": [
                            {
                                "order": 1,
                                "prompt_blocks": [
                                    {
                                        "type": "text",
                                        "text": "What is the name of Cameroon's highest mountain?",
                                    }
                                ],
                                "answer_widget": {
                                    "type": "text_input",
                                    "placeholder": "Mountain name",
                                },
                                "canonical_answer": "Mount Cameroon",
                                "acceptable_answers": ["Mount Cameroon", "Mt Cameroon"],
                                "judge_mode": "fuzzy",
                            }
                        ],
                    }
                ],
            },
            AuthoringContext(),
        )
        quiz.status = QuizStatus.READY
        quiz.save(update_fields=["status"])
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        create_payload = create_response.json()
        session_id = create_payload["session"]["id"]
        player_id = create_payload["player_id"]
        self._start_session(session_id, player_id)

        with patch(
            "apps.sessions.views.judge_typed_answer_with_llm",
            return_value={
                "accepted": True,
                "judge_latency_ms": 12,
                "judge_metadata": {
                    "llm": {
                        "accepted": True,
                        "confidence": 0.95,
                        "reasoning": "Mount Fako is a known alternate name.",
                    },
                    "fallback": {"accepted": False},
                },
            },
        ) as judge_mock:
            submit_response = self.client.post(
                f"/api/sessions/{session_id}/players/{player_id}/answer/",
                data={"submitted_text": "Mount Fako"},
                content_type="application/json",
            )

        self.assertEqual(submit_response.status_code, 200)
        judge_mock.assert_called_once()
        payload = submit_response.json()
        question_id = payload["state"]["question_id"]
        submission = payload["state"]["submissions"][question_id][player_id]
        self.assertTrue(submission["accepted"])
        self.assertEqual(submission["judge_mode_used"], "llm")
        self.assertEqual(payload["state"]["scores"][player_id], 10.0)

    def test_image_choice_question_is_playable(self):
        quiz = create_quiz_from_document(
            {
                "title": "Flag Choice",
                "category": "geography",
                "topic": "flags",
                "rounds": [
                    {
                        "type": "sync_open",
                        "config": {"points_per_question": 10},
                        "questions": [
                            {
                                "prompt_blocks": [{"type": "text", "text": "Choose Cameroon."}],
                                "answer_widget": {
                                    "type": "image_choice",
                                    "images": [
                                        {
                                            "url": "https://example.com/cm.png",
                                            "alt": "Cameroon",
                                            "label": "Cameroon",
                                        },
                                        {
                                            "url": "https://example.com/jp.png",
                                            "alt": "Japan",
                                            "label": "Japan",
                                        },
                                    ],
                                },
                                "canonical_answer": "Cameroon",
                                "acceptable_answers": ["Cameroon"],
                                "judge_mode": "fuzzy",
                            }
                        ],
                    }
                ],
            },
            AuthoringContext(),
        )
        quiz.status = QuizStatus.READY
        quiz.save(update_fields=["status"])
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        player_id = create_response.json()["player_id"]
        start_response = self._start_session(session_id, player_id)
        self.assertEqual(start_response.json()["state"]["phase"], "question")

        submit_response = self.client.post(
            f"/api/sessions/{session_id}/players/{player_id}/answer/",
            data={
                "submitted_text": "Cameroon",
                "submitted_payload": {"choice_index": 0, "label": "Cameroon"},
            },
            content_type="application/json",
        )

        self.assertEqual(submit_response.status_code, 200)
        payload = submit_response.json()
        question_id = payload["state"]["question_id"]
        self.assertTrue(payload["state"]["submissions"][question_id][player_id]["accepted"])
        self.assertEqual(payload["state"]["scores"][player_id], 10.0)

    def test_ordering_question_is_playable(self):
        quiz = create_quiz_from_document(
            {
                "title": "Ordering Quiz",
                "category": "geography",
                "topic": "population",
                "rounds": [
                    {
                        "type": "sync_open",
                        "config": {"points_per_question": 10},
                        "questions": [
                            {
                                "prompt_blocks": [
                                    {
                                        "type": "text",
                                        "text": "Order largest to smallest population.",
                                    }
                                ],
                                "answer_widget": {
                                    "type": "ordering",
                                    "items": ["Gabon", "Cameroon", "Chad"],
                                },
                                "canonical_answer": "Cameroon > Chad > Gabon",
                                "acceptable_answers": ["Cameroon > Chad > Gabon"],
                                "judge_mode": "fuzzy",
                                "metadata": {
                                    "correct_payload": ["Cameroon", "Chad", "Gabon"]
                                },
                            }
                        ],
                    }
                ],
            },
            AuthoringContext(),
        )
        quiz.status = QuizStatus.READY
        quiz.save(update_fields=["status"])
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        player_id = create_response.json()["player_id"]
        self._start_session(session_id, player_id)

        submit_response = self.client.post(
            f"/api/sessions/{session_id}/players/{player_id}/answer/",
            data={
                "submitted_payload": {
                    "order": ["Cameroon", "Chad", "Gabon"],
                }
            },
            content_type="application/json",
        )

        self.assertEqual(submit_response.status_code, 200)
        payload = submit_response.json()
        question_id = payload["state"]["question_id"]
        self.assertTrue(payload["state"]["submissions"][question_id][player_id]["accepted"])
        self.assertEqual(payload["state"]["scores"][player_id], 10.0)

    def test_matching_question_is_playable(self):
        quiz = create_quiz_from_document(
            {
                "title": "Matching Quiz",
                "category": "geography",
                "topic": "capitals",
                "rounds": [
                    {
                        "type": "sync_open",
                        "config": {"points_per_question": 10},
                        "questions": [
                            {
                                "prompt_blocks": [
                                    {"type": "text", "text": "Match countries to capitals."}
                                ],
                                "answer_widget": {
                                    "type": "matching",
                                    "left": ["Cameroon", "Japan"],
                                    "right": ["Tokyo", "Yaounde"],
                                },
                                "canonical_answer": "Cameroon-Yaounde; Japan-Tokyo",
                                "acceptable_answers": ["Cameroon-Yaounde; Japan-Tokyo"],
                                "judge_mode": "fuzzy",
                                "metadata": {
                                    "correct_payload": {
                                        "Cameroon": "Yaounde",
                                        "Japan": "Tokyo",
                                    }
                                },
                            }
                        ],
                    }
                ],
            },
            AuthoringContext(),
        )
        quiz.status = QuizStatus.READY
        quiz.save(update_fields=["status"])
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        player_id = create_response.json()["player_id"]
        self._start_session(session_id, player_id)

        submit_response = self.client.post(
            f"/api/sessions/{session_id}/players/{player_id}/answer/",
            data={
                "submitted_payload": {
                    "matches": {
                        "Cameroon": "Yaounde",
                        "Japan": "Tokyo",
                    }
                }
            },
            content_type="application/json",
        )

        self.assertEqual(submit_response.status_code, 200)
        payload = submit_response.json()
        question_id = payload["state"]["question_id"]
        self.assertTrue(payload["state"]["submissions"][question_id][player_id]["accepted"])
        self.assertEqual(payload["state"]["scores"][player_id], 10.0)

    def test_server_auto_advances_when_all_players_submit(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        create_payload = create_response.json()
        session_id = create_payload["session"]["id"]
        host_id = create_payload["player_id"]
        join_response = self.client.post(
            "/api/sessions/join/",
            data={"session_id": session_id, "display_name": "Friend"},
            content_type="application/json",
        )
        friend_id = join_response.json()["player_id"]
        start_response = self._start_session(session_id, host_id)
        first_question_id = start_response.json()["state"]["question_id"]
        canonical_answer = start_response.json()["quiz"]["rounds"][0]["questions"][0]["canonical_answer"]

        self.client.post(
            f"/api/sessions/{session_id}/players/{host_id}/answer/",
            data={"submitted_text": canonical_answer},
            content_type="application/json",
        )
        self.client.post(
            f"/api/sessions/{session_id}/players/{friend_id}/answer/",
            data={"submitted_text": canonical_answer},
            content_type="application/json",
        )
        session = _session_queryset().get(pk=session_id)
        token = _state_advance_token(session.state)

        _auto_advance_session(session_id, token, "all_submitted")

        payload = self.client.get(f"/api/sessions/{session_id}/").json()
        self.assertEqual(payload["status"], SessionStatus.PLAYING)
        self.assertEqual(payload["state"]["question_index"], 1)
        self.assertNotEqual(payload["state"]["question_id"], first_question_id)

    def test_players_can_all_continue_to_advance_after_answer_reveal(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel", "question_count": 2},
            content_type="application/json",
        )
        create_payload = create_response.json()
        session_id = create_payload["session"]["id"]
        host_id = create_payload["player_id"]
        join_response = self.client.post(
            "/api/sessions/join/",
            data={"session_id": session_id, "display_name": "Friend"},
            content_type="application/json",
        )
        friend_id = join_response.json()["player_id"]
        start_response = self._start_session(session_id, host_id)
        first_question_id = start_response.json()["state"]["question_id"]
        canonical_answer = start_response.json()["quiz"]["rounds"][0]["questions"][0]["canonical_answer"]

        self.client.post(
            f"/api/sessions/{session_id}/players/{host_id}/answer/",
            data={"submitted_text": canonical_answer},
            content_type="application/json",
        )
        self.client.post(
            f"/api/sessions/{session_id}/players/{friend_id}/answer/",
            data={"submitted_text": canonical_answer},
            content_type="application/json",
        )

        host_continue = self.client.post(
            f"/api/sessions/{session_id}/players/{host_id}/continue/",
            content_type="application/json",
        )
        self.assertEqual(host_continue.status_code, 200)
        self.assertEqual(host_continue.json()["state"]["question_id"], first_question_id)
        self.assertIn(host_id, host_continue.json()["state"]["next_ready"][first_question_id])

        friend_continue = self.client.post(
            f"/api/sessions/{session_id}/players/{friend_id}/continue/",
            content_type="application/json",
        )

        self.assertEqual(friend_continue.status_code, 200)
        self.assertEqual(friend_continue.json()["state"]["question_index"], 1)
        self.assertNotEqual(friend_continue.json()["state"]["question_id"], first_question_id)

    def test_offline_player_does_not_block_continue_advance(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel", "question_count": 2},
            content_type="application/json",
        )
        create_payload = create_response.json()
        session_id = create_payload["session"]["id"]
        host_id = create_payload["player_id"]
        join_response = self.client.post(
            "/api/sessions/join/",
            data={"session_id": session_id, "display_name": "Friend"},
            content_type="application/json",
        )
        friend_id = join_response.json()["player_id"]
        start_response = self._start_session(session_id, host_id)
        first_question_id = start_response.json()["state"]["question_id"]
        canonical_answer = start_response.json()["quiz"]["rounds"][0]["questions"][0]["canonical_answer"]

        session = _session_queryset().get(pk=session_id)
        state = session.state
        state["presence"] = {
            host_id: {"online": True, "connection_count": 1},
            friend_id: {"online": False, "connection_count": 0},
        }
        session.state = state
        session.save(update_fields=["state"])

        self.client.post(
            f"/api/sessions/{session_id}/players/{host_id}/answer/",
            data={"submitted_text": canonical_answer},
            content_type="application/json",
        )

        continue_response = self.client.post(
            f"/api/sessions/{session_id}/players/{host_id}/continue/",
            content_type="application/json",
        )

        self.assertEqual(continue_response.status_code, 200)
        self.assertEqual(continue_response.json()["state"]["question_index"], 1)
        self.assertNotEqual(continue_response.json()["state"]["question_id"], first_question_id)

    def test_stale_online_player_does_not_block_continue_advance(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel", "question_count": 2},
            content_type="application/json",
        )
        create_payload = create_response.json()
        session_id = create_payload["session"]["id"]
        host_id = create_payload["player_id"]
        join_response = self.client.post(
            "/api/sessions/join/",
            data={"session_id": session_id, "display_name": "Friend"},
            content_type="application/json",
        )
        friend_id = join_response.json()["player_id"]
        start_response = self._start_session(session_id, host_id)
        first_question_id = start_response.json()["state"]["question_id"]
        canonical_answer = start_response.json()["quiz"]["rounds"][0]["questions"][0]["canonical_answer"]

        session = _session_queryset().get(pk=session_id)
        state = session.state
        state["presence"] = {
            host_id: {"online": True, "connection_count": 1, "last_seen_at": timezone.now().isoformat()},
            friend_id: {
                "online": True,
                "connection_count": 1,
                "last_seen_at": (timezone.now() - timedelta(seconds=90)).isoformat(),
            },
        }
        session.state = state
        session.save(update_fields=["state"])

        self.client.post(
            f"/api/sessions/{session_id}/players/{host_id}/answer/",
            data={"submitted_text": canonical_answer},
            content_type="application/json",
        )

        continue_response = self.client.post(
            f"/api/sessions/{session_id}/players/{host_id}/continue/",
            content_type="application/json",
        )

        self.assertEqual(continue_response.status_code, 200)
        self.assertEqual(continue_response.json()["state"]["question_index"], 1)
        self.assertNotEqual(continue_response.json()["state"]["question_id"], first_question_id)

    def test_left_player_does_not_block_continue_advance(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel", "question_count": 2},
            content_type="application/json",
        )
        create_payload = create_response.json()
        session_id = create_payload["session"]["id"]
        host_id = create_payload["player_id"]
        join_response = self.client.post(
            "/api/sessions/join/",
            data={"session_id": session_id, "display_name": "Friend"},
            content_type="application/json",
        )
        friend_id = join_response.json()["player_id"]
        start_response = self._start_session(session_id, host_id)
        first_question_id = start_response.json()["state"]["question_id"]
        canonical_answer = start_response.json()["quiz"]["rounds"][0]["questions"][0]["canonical_answer"]

        self._leave_session(session_id, friend_id)
        self.client.post(
            f"/api/sessions/{session_id}/players/{host_id}/answer/",
            data={"submitted_text": canonical_answer},
            content_type="application/json",
        )

        continue_response = self.client.post(
            f"/api/sessions/{session_id}/players/{host_id}/continue/",
            content_type="application/json",
        )

        self.assertEqual(continue_response.status_code, 200)
        self.assertEqual(continue_response.json()["state"]["question_index"], 1)
        self.assertNotEqual(continue_response.json()["state"]["question_id"], first_question_id)

    def test_continue_requires_submission_before_deadline(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel", "question_count": 1},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        player_id = create_response.json()["player_id"]
        self._start_session(session_id, player_id)

        continue_response = self.client.post(
            f"/api/sessions/{session_id}/players/{player_id}/continue/",
            content_type="application/json",
        )

        self.assertEqual(continue_response.status_code, 400)
        self.assertIn("Submit an answer", continue_response.json()["detail"])

    def test_server_finishes_question_on_timeout(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel", "question_count": 1},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        player_id = create_response.json()["player_id"]
        self._start_session(session_id, player_id)
        session = _session_queryset().get(pk=session_id)
        state = session.state
        state["question_started_at"] = (timezone.now() - timedelta(seconds=10)).isoformat()
        state["question_timeout_s"] = 1
        session.state = state
        session.save(update_fields=["state"])
        token = _state_advance_token(session.state)

        _auto_advance_session(session_id, token, "deadline")

        payload = self.client.get(f"/api/sessions/{session_id}/").json()
        self.assertEqual(payload["status"], SessionStatus.FINISHED)
        self.assertEqual(payload["state"]["phase"], "finished")

    def test_next_question_finishes_when_sample_exhausted(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel", "question_count": 1},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        player_id = create_response.json()["player_id"]
        self._start_session(session_id, player_id)

        next_response = self._force_next_question(session_id, player_id)

        self.assertEqual(next_response.status_code, 200)
        payload = next_response.json()
        self.assertEqual(payload["status"], SessionStatus.FINISHED)
        self.assertEqual(payload["state"]["phase"], "finished")

    def test_non_host_cannot_force_next_question(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel", "question_count": 2},
            content_type="application/json",
        )
        create_payload = create_response.json()
        session_id = create_payload["session"]["id"]
        host_id = create_payload["player_id"]
        join_response = self.client.post(
            "/api/sessions/join/",
            data={"session_id": session_id, "display_name": "Friend"},
            content_type="application/json",
        )
        self._start_session(session_id, host_id)

        next_response = self._force_next_question(session_id, join_response.json()["player_id"])

        self.assertEqual(next_response.status_code, 403)
        self.assertIn("Only the host", next_response.json()["detail"])

    def test_list_race_round_can_start_and_score_items(self):
        list_race_quiz = create_quiz_from_document(
            {
                "title": "Country Flag Sprint",
                "description": "Name countries from flags.",
                "topic": "flags",
                "difficulty": "medium",
                "rounds": [
                    {
                        "type": "list_race",
                        "order": 1,
                        "config": {
                            "prompt": "Name every country shown by the flags.",
                            "time_limit_s": 1200,
                            "points_per_item": 1,
                            "items": [
                                {"canonical": "France", "acceptable": ["French Republic"]},
                                {"canonical": "Japan", "acceptable": ["Nippon"]},
                            ],
                        },
                        "questions": [],
                    }
                ],
            },
            AuthoringContext(),
        )
        list_race_quiz.status = QuizStatus.READY
        list_race_quiz.save(update_fields=["status"])
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(list_race_quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        create_payload = create_response.json()
        session_id = create_payload["session"]["id"]
        player_id = create_payload["player_id"]

        start_response = self._start_session(session_id, player_id)

        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(start_response.json()["state"]["phase"], "list_race")
        self.assertEqual(start_response.json()["state"]["list_race"]["items_count"], 2)

        submit_response = self.client.post(
            f"/api/sessions/{session_id}/players/{player_id}/answer/",
            data={"submitted_text": "france"},
            content_type="application/json",
        )

        self.assertEqual(submit_response.status_code, 200)
        payload = submit_response.json()
        self.assertEqual(payload["state"]["scores"][player_id], 1.0)
        self.assertEqual(payload["state"]["list_race"]["found"][player_id], ["0"])
        self.assertTrue(payload["state"]["list_race"]["last_submission"][player_id]["accepted"])

    def test_meta_strategy_wager_reveals_question_and_scores_bet(self):
        meta_quiz = create_quiz_from_document(
            {
                "title": "Strategic Quantum",
                "description": "Bet before answering.",
                "topic": "quantum mechanics",
                "difficulty": "medium",
                "rounds": [
                    {
                        "type": "meta_strategy",
                        "order": 1,
                        "config": {
                            "min_bet": 1,
                            "max_bet": 10,
                            "default_bet": 1,
                            "bet_window_s": 10,
                            "answer_timeout_s": 20,
                        },
                        "questions": [
                            {
                                "order": 1,
                                "prompt_blocks": [
                                    {
                                        "type": "text",
                                        "text": "What operator generates time evolution in the Schrodinger equation?",
                                    }
                                ],
                                "answer_widget": {"type": "text_input"},
                                "canonical_answer": "Hamiltonian",
                                "acceptable_answers": ["Hamiltonian", "Hamiltonian operator"],
                                "judge_mode": "fuzzy",
                                "metadata": {"category_hint": "Foundations of quantum mechanics"},
                            }
                        ],
                    }
                ],
            },
            AuthoringContext(),
        )
        meta_quiz.status = QuizStatus.READY
        meta_quiz.save(update_fields=["status"])
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(meta_quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        player_id = create_response.json()["player_id"]

        start_response = self._start_session(session_id, player_id)

        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(start_response.json()["state"]["phase"], "betting")
        self.assertEqual(
            start_response.json()["state"]["meta_strategy"]["current"]["hint"],
            "Foundations of quantum mechanics",
        )
        self.assertEqual(start_response.json()["state"]["meta_strategy"]["current"]["wager_values"], [1])

        premature_answer = self.client.post(
            f"/api/sessions/{session_id}/players/{player_id}/answer/",
            data={"submitted_text": "Hamiltonian"},
            content_type="application/json",
        )
        self.assertEqual(premature_answer.status_code, 400)

        wager_response = self.client.post(
            f"/api/sessions/{session_id}/players/{player_id}/wager/",
            data={"points": 1},
            content_type="application/json",
        )

        self.assertEqual(wager_response.status_code, 200)
        question_id = wager_response.json()["state"]["question_id"]
        self.assertEqual(
            wager_response.json()["state"]["meta_strategy"]["bets"][question_id][player_id]["points"],
            1,
        )

        session = _session_queryset().get(pk=session_id)
        token = _state_advance_token(session.state)
        _auto_advance_session(session_id, token, "all_wagered")

        revealed_payload = self.client.get(f"/api/sessions/{session_id}/").json()
        self.assertEqual(revealed_payload["state"]["phase"], "question")

        answer_response = self.client.post(
            f"/api/sessions/{session_id}/players/{player_id}/answer/",
            data={"submitted_text": "Hamiltonian"},
            content_type="application/json",
        )

        self.assertEqual(answer_response.status_code, 200)
        payload = answer_response.json()
        submission = payload["state"]["submissions"][question_id][player_id]
        self.assertTrue(submission["accepted"])
        self.assertEqual(submission["wager"], 1.0)
        self.assertEqual(submission["points_awarded"], 1.0)
        self.assertEqual(payload["state"]["scores"][player_id], 1.0)

    def test_meta_strategy_wager_values_match_round_question_count(self):
        questions = [
            {
                "order": index + 1,
                "prompt_blocks": [{"type": "text", "text": f"Answer {index + 1}?"}],
                "answer_widget": {"type": "text_input"},
                "canonical_answer": f"answer {index + 1}",
                "acceptable_answers": [f"answer {index + 1}"],
                "judge_mode": "fuzzy",
                "metadata": {"category_hint": f"Hint {index + 1}"},
            }
            for index in range(4)
        ]
        meta_quiz = create_quiz_from_document(
            {
                "title": "Strategic Spread",
                "description": "Scaled wager cards.",
                "topic": "strategy",
                "difficulty": "medium",
                "rounds": [
                    {
                        "type": "meta_strategy",
                        "order": 1,
                        "config": {
                            "min_bet": 1,
                            "max_bet": 10,
                            "default_bet": 1,
                            "bet_window_s": 10,
                            "answer_timeout_s": 20,
                        },
                        "questions": questions,
                    }
                ],
            },
            AuthoringContext(),
        )
        meta_quiz.status = QuizStatus.READY
        meta_quiz.save(update_fields=["status"])
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(meta_quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        player_id = create_response.json()["player_id"]

        start_response = self._start_session(session_id, player_id)

        current = start_response.json()["state"]["meta_strategy"]["current"]
        self.assertEqual(current["wager_values"], [1, 4, 7, 10])

        invalid_wager = self.client.post(
            f"/api/sessions/{session_id}/players/{create_response.json()['player_id']}/wager/",
            data={"points": 2},
            content_type="application/json",
        )
        self.assertEqual(invalid_wager.status_code, 400)
        self.assertIn("1, 4, 7, 10", invalid_wager.json()["detail"])

    def test_meta_strategy_defaults_wager_on_betting_timeout(self):
        meta_quiz = create_quiz_from_document(
            {
                "title": "Strategic Geography",
                "description": "Default wager test.",
                "topic": "geography",
                "difficulty": "easy",
                "rounds": [
                    {
                        "type": "meta_strategy",
                        "order": 1,
                        "config": {
                            "min_bet": 2,
                            "max_bet": 10,
                            "default_bet": 2,
                            "bet_window_s": 1,
                            "answer_timeout_s": 20,
                        },
                        "questions": [
                            {
                                "order": 1,
                                "prompt_blocks": [{"type": "text", "text": "Capital of Cameroon?"}],
                                "answer_widget": {"type": "text_input"},
                                "canonical_answer": "Yaounde",
                                "acceptable_answers": ["Yaounde"],
                                "judge_mode": "fuzzy",
                                "metadata": {"category_hint": "Capital cities"},
                            }
                        ],
                    }
                ],
            },
            AuthoringContext(),
        )
        meta_quiz.status = QuizStatus.READY
        meta_quiz.save(update_fields=["status"])
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(meta_quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        player_id = create_response.json()["player_id"]
        self._start_session(session_id, player_id)
        session = _session_queryset().get(pk=session_id)
        state = session.state
        state["question_started_at"] = (timezone.now() - timedelta(seconds=5)).isoformat()
        session.state = state
        session.save(update_fields=["state"])
        token = _state_advance_token(session.state)

        _auto_advance_session(session_id, token, "deadline")

        revealed_payload = self.client.get(f"/api/sessions/{session_id}/").json()
        question_id = revealed_payload["state"]["question_id"]
        defaulted_wager = revealed_payload["state"]["meta_strategy"]["bets"][question_id][player_id]
        self.assertEqual(revealed_payload["state"]["phase"], "question")
        self.assertEqual(defaulted_wager["points"], 2)
        self.assertTrue(defaulted_wager["defaulted"])

        answer_response = self.client.post(
            f"/api/sessions/{session_id}/players/{player_id}/answer/",
            data={"submitted_text": "Yaounde"},
            content_type="application/json",
        )

        self.assertEqual(answer_response.status_code, 200)
        self.assertEqual(answer_response.json()["state"]["scores"][player_id], 2.0)

    def test_meta_strategy_wagers_are_single_use_within_round(self):
        meta_quiz = create_quiz_from_document(
            {
                "title": "Strategic Set",
                "description": "No repeated wager cards.",
                "topic": "strategy",
                "difficulty": "medium",
                "rounds": [
                    {
                        "type": "meta_strategy",
                        "order": 1,
                        "config": {
                            "min_bet": 1,
                            "max_bet": 3,
                            "default_bet": 1,
                            "bet_window_s": 10,
                            "answer_timeout_s": 20,
                        },
                        "questions": [
                            {
                                "order": 1,
                                "prompt_blocks": [{"type": "text", "text": "First answer?"}],
                                "answer_widget": {"type": "text_input"},
                                "canonical_answer": "alpha",
                                "acceptable_answers": ["alpha"],
                                "judge_mode": "fuzzy",
                                "metadata": {"category_hint": "First clue"},
                            },
                            {
                                "order": 2,
                                "prompt_blocks": [{"type": "text", "text": "Second answer?"}],
                                "answer_widget": {"type": "text_input"},
                                "canonical_answer": "beta",
                                "acceptable_answers": ["beta"],
                                "judge_mode": "fuzzy",
                                "metadata": {"category_hint": "Second clue"},
                            },
                        ],
                    }
                ],
            },
            AuthoringContext(),
        )
        meta_quiz.status = QuizStatus.READY
        meta_quiz.save(update_fields=["status"])
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(meta_quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        player_id = create_response.json()["player_id"]
        self._start_session(session_id, player_id)
        self.client.post(
            f"/api/sessions/{session_id}/players/{player_id}/wager/",
            data={"points": 1},
            content_type="application/json",
        )
        session = _session_queryset().get(pk=session_id)
        _auto_advance_session(session_id, _state_advance_token(session.state), "all_wagered")
        self.client.post(
            f"/api/sessions/{session_id}/players/{player_id}/answer/",
            data={"submitted_text": "alpha"},
            content_type="application/json",
        )
        next_response = self._force_next_question(session_id, player_id)

        self.assertEqual(next_response.status_code, 200)
        self.assertEqual(next_response.json()["state"]["phase"], "betting")
        self.assertEqual(next_response.json()["state"]["meta_strategy"]["current"]["wager_values"], [1, 3])
        self.assertEqual(next_response.json()["state"]["meta_strategy"]["current"]["used_wagers"][player_id], [1])

        repeated_wager = self.client.post(
            f"/api/sessions/{session_id}/players/{player_id}/wager/",
            data={"points": 1},
            content_type="application/json",
        )
        self.assertEqual(repeated_wager.status_code, 400)

        accepted_wager = self.client.post(
            f"/api/sessions/{session_id}/players/{player_id}/wager/",
            data={"points": 3},
            content_type="application/json",
        )
        self.assertEqual(accepted_wager.status_code, 200)

    def test_meta_strategy_default_wager_skips_used_points(self):
        meta_quiz = create_quiz_from_document(
            {
                "title": "Strategic Defaults",
                "description": "Default card advances.",
                "topic": "strategy",
                "difficulty": "medium",
                "rounds": [
                    {
                        "type": "meta_strategy",
                        "order": 1,
                        "config": {
                            "min_bet": 1,
                            "max_bet": 3,
                            "default_bet": 1,
                            "bet_window_s": 1,
                            "answer_timeout_s": 20,
                        },
                        "questions": [
                            {
                                "order": 1,
                                "prompt_blocks": [{"type": "text", "text": "First answer?"}],
                                "answer_widget": {"type": "text_input"},
                                "canonical_answer": "alpha",
                                "acceptable_answers": ["alpha"],
                                "judge_mode": "fuzzy",
                                "metadata": {"category_hint": "First clue"},
                            },
                            {
                                "order": 2,
                                "prompt_blocks": [{"type": "text", "text": "Second answer?"}],
                                "answer_widget": {"type": "text_input"},
                                "canonical_answer": "beta",
                                "acceptable_answers": ["beta"],
                                "judge_mode": "fuzzy",
                                "metadata": {"category_hint": "Second clue"},
                            },
                        ],
                    }
                ],
            },
            AuthoringContext(),
        )
        meta_quiz.status = QuizStatus.READY
        meta_quiz.save(update_fields=["status"])
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(meta_quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        player_id = create_response.json()["player_id"]
        self._start_session(session_id, player_id)
        self.client.post(
            f"/api/sessions/{session_id}/players/{player_id}/wager/",
            data={"points": 1},
            content_type="application/json",
        )
        session = _session_queryset().get(pk=session_id)
        _auto_advance_session(session_id, _state_advance_token(session.state), "all_wagered")
        self.client.post(
            f"/api/sessions/{session_id}/players/{player_id}/answer/",
            data={"submitted_text": "alpha"},
            content_type="application/json",
        )
        self._force_next_question(session_id, player_id)
        session = _session_queryset().get(pk=session_id)
        state = session.state
        state["question_started_at"] = (timezone.now() - timedelta(seconds=5)).isoformat()
        session.state = state
        session.save(update_fields=["state"])

        _auto_advance_session(session_id, _state_advance_token(session.state), "deadline")

        payload = self.client.get(f"/api/sessions/{session_id}/").json()
        question_id = payload["state"]["question_id"]
        defaulted_wager = payload["state"]["meta_strategy"]["bets"][question_id][player_id]
        self.assertEqual(defaulted_wager["points"], 3)
        self.assertTrue(defaulted_wager["defaulted"])


class SessionRealtimeTests(TransactionTestCase):
    def setUp(self):
        self.quiz = create_quiz_from_document(sample_quiz_document("quantum mechanics"), AuthoringContext())
        self.quiz.status = QuizStatus.READY
        self.quiz.save(update_fields=["status"])
        self.client = Client()

    def test_session_websocket_sends_snapshot_and_join_updates(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]

        async_to_sync(self._assert_socket_receives_join_update)(session_id)

    def test_session_websocket_marks_player_presence(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        payload = create_response.json()

        async_to_sync(self._assert_socket_marks_player_presence)(
            payload["session"]["id"],
            payload["player_id"],
        )

    async def _assert_socket_receives_join_update(self, session_id: str):
        communicator = WebsocketCommunicator(application, f"/ws/session/{session_id}/")
        connected, _subprotocol = await communicator.connect()
        self.assertTrue(connected)

        snapshot = await communicator.receive_json_from(timeout=5)
        self.assertEqual(snapshot["type"], "session.snapshot")
        self.assertEqual(snapshot["session"]["id"], session_id)
        self.assertEqual(len(snapshot["session"]["players"]), 1)

        join_response = await database_sync_to_async(self._join_session)(session_id)

        self.assertEqual(join_response.status_code, 201)
        update = await communicator.receive_json_from(timeout=5)
        self.assertEqual(update["type"], "session.player_joined")
        names = {player["display_name"] for player in update["session"]["players"]}
        self.assertEqual(names, {"Ariel", "Friend"})
        await communicator.disconnect()

    async def _assert_socket_marks_player_presence(self, session_id: str, player_id: str):
        communicator = WebsocketCommunicator(
            application,
            f"/ws/session/{session_id}/?player_id={player_id}",
        )
        connected, _subprotocol = await communicator.connect()
        self.assertTrue(connected)

        snapshot = await communicator.receive_json_from(timeout=5)
        presence = snapshot["session"]["state"]["presence"][player_id]
        self.assertTrue(presence["online"])
        self.assertEqual(presence["connection_count"], 1)
        self.assertIn("last_seen_at", presence)

        await communicator.send_json_to({"type": "ping"})
        for _ in range(3):
            message = await communicator.receive_json_from(timeout=5)
            if message["type"] == "pong":
                break
        else:
            self.fail("Socket ping did not receive pong")

        touched_presence = await database_sync_to_async(self._player_presence)(
            session_id,
            player_id,
        )
        self.assertTrue(touched_presence["online"])
        self.assertEqual(touched_presence["connection_count"], 1)
        self.assertIn("last_seen_at", touched_presence)

        await communicator.disconnect()

        disconnected_presence = await database_sync_to_async(self._player_presence)(
            session_id,
            player_id,
        )
        self.assertFalse(disconnected_presence["online"])
        self.assertEqual(disconnected_presence["connection_count"], 0)

    def _join_session(self, session_id: str):
        return self.client.post(
            "/api/sessions/join/",
            data={"session_id": session_id, "display_name": "Friend"},
            content_type="application/json",
        )

    def _player_presence(self, session_id: str, player_id: str):
        return self.client.get(f"/api/sessions/{session_id}/").json()["state"]["presence"][player_id]
