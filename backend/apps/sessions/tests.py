from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import Client, TestCase, TransactionTestCase
from django.utils import timezone

from apps.authoring.ops import AuthoringContext, create_quiz_from_document
from apps.authoring.sample import sample_quiz_document
from apps.sessions.models import SessionStatus
from apps.sessions.views import (
    _auto_advance_session,
    _auto_start_session,
    _session_queryset,
    _state_advance_token,
)
from apps.quizzes.models import QuizStatus
from trivia.asgi import application


class SessionApiTests(TestCase):
    def setUp(self):
        self.quiz = create_quiz_from_document(sample_quiz_document("quantum mechanics"), AuthoringContext())
        self.quiz.status = QuizStatus.READY
        self.quiz.save(update_fields=["status"])
        self.client = Client()

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

        start_response = self.client.post(f"/api/sessions/{session_id}/start/")

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

        start_response = self.client.post(f"/api/sessions/{session_id}/start/")

        self.assertEqual(start_response.status_code, 200)
        payload = start_response.json()
        self.assertEqual(payload["state"]["question_count"], 12)
        self.assertEqual(payload["state"]["selected_question_ids"], expected_question_ids)
        self.assertEqual(payload["state"]["question_id"], expected_question_ids[0])

    def test_submit_answer_scores_current_question(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel"},
            content_type="application/json",
        )
        create_payload = create_response.json()
        session_id = create_payload["session"]["id"]
        player_id = create_payload["player_id"]
        start_response = self.client.post(f"/api/sessions/{session_id}/start/")
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
        start_response = self.client.post(f"/api/sessions/{session_id}/start/")
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

    def test_server_finishes_question_on_timeout(self):
        create_response = self.client.post(
            "/api/sessions/",
            data={"quiz_id": str(self.quiz.id), "display_name": "Ariel", "question_count": 1},
            content_type="application/json",
        )
        session_id = create_response.json()["session"]["id"]
        self.client.post(f"/api/sessions/{session_id}/start/")
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
        self.client.post(f"/api/sessions/{session_id}/start/")

        next_response = self.client.post(f"/api/sessions/{session_id}/next/")

        self.assertEqual(next_response.status_code, 200)
        payload = next_response.json()
        self.assertEqual(payload["status"], SessionStatus.FINISHED)
        self.assertEqual(payload["state"]["phase"], "finished")

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

        start_response = self.client.post(f"/api/sessions/{session_id}/start/")

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
