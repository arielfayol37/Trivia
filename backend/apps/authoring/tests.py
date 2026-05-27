from unittest.mock import AsyncMock, patch

from django.test import Client, TestCase, override_settings

from apps.authoring.llm import _user_prompt
from apps.authoring.ops import (
    AuthoringContext,
    AuthoringError,
    apply_quiz_op,
    create_quiz_from_document,
)
from apps.authoring.sample import sample_quiz_document
from apps.quizzes.models import QuizCategory, QuizStatus


@override_settings(LLM_PROVIDER="sample", OPENAI_API_KEY="", OPENAI_AUTHOR_MODEL="")
class AuthoringSmokeTests(TestCase):
    def test_sample_document_creates_interactive_quiz(self):
        document = sample_quiz_document(
            "hard quantum mechanics focused on the Schrodinger equation"
        )

        quiz = create_quiz_from_document(document, AuthoringContext())

        self.assertEqual(quiz.rounds.count(), 2)
        first_question = quiz.rounds.first().questions.first()
        self.assertEqual(first_question.prompt_blocks[0]["type"], "text")
        self.assertIn(first_question.answer_widget["type"], {"text_input", "multiple_choice"})
        self.assertIn(first_question.canonical_answer, first_question.acceptable_answers)

    def test_generate_endpoint_returns_saved_quiz(self):
        response = Client().post(
            "/api/authoring/generate/",
            data={"prompt": "hard quantum mechanics"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["status"], QuizStatus.DRAFT)
        self.assertEqual(payload["rounds"][0]["questions"][0]["prompt_blocks"][0]["type"], "text")

    def test_generate_endpoint_keeps_source_text_when_model_omits_source_material(self):
        document = {
            "title": "Flag Quiz",
            "category": "geography",
            "topic": "flags",
            "rounds": [
                {
                    "type": "sync_open",
                    "questions": [
                        {
                            "prompt_blocks": [
                                {
                                    "type": "image",
                                    "url": "https://example.com/flags/cm.png",
                                    "alt": "Flag",
                                }
                            ],
                            "answer_widget": {"type": "text_input"},
                            "canonical_answer": "Cameroon",
                            "acceptable_answers": ["Cameroon"],
                            "judge_mode": "fuzzy",
                        }
                    ],
                }
            ],
        }

        with patch(
            "apps.authoring.views.generate_quiz_document",
            new=AsyncMock(return_value=document),
        ):
            response = Client().post(
                "/api/authoring/generate/",
                data={
                    "prompt": "make a flag sprint",
                    "source_text": '<img src="https://example.com/flags/cm.png"> Cameroon',
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["source_material"]["kind"], "text")
        self.assertIn("Cameroon", payload["source_material"]["content"])

    def test_authoring_prompt_includes_flag_sprint_image_example(self):
        payload = _user_prompt("Create a flag sprint from these rows", "Cameroon, https://example.com/flags/cm.png")
        flag_example = payload["format_examples"]["flag_sprint"]["round"]
        question = flag_example["questions"][0]

        self.assertEqual(flag_example["type"], "sync_open")
        self.assertEqual(question["prompt_blocks"][0]["type"], "image")
        self.assertEqual(question["answer_widget"]["type"], "text_input")
        self.assertIn("Do not use list_race for flag_sprint", " ".join(payload["requirements"]))

    def test_image_prompt_blocks_are_preserved(self):
        document = {
            "title": "Flag Quiz",
            "rounds": [
                {
                    "type": "sync_open",
                    "questions": [
                        {
                            "prompt_blocks": [
                                {
                                    "type": "image",
                                    "url": "https://example.com/flags/cm.png",
                                    "alt": "Flag of Cameroon",
                                    "caption": "Name the country.",
                                }
                            ],
                            "answer_widget": {"type": "text_input"},
                            "canonical_answer": "Cameroon",
                            "acceptable_answers": ["Cameroon", "Republic of Cameroon"],
                            "judge_mode": "fuzzy",
                        }
                    ],
                }
            ],
        }

        quiz = create_quiz_from_document(document, AuthoringContext())
        question = quiz.rounds.first().questions.first()

        self.assertEqual(question.prompt_blocks[0]["type"], "image")
        self.assertEqual(question.prompt_blocks[0]["url"], "https://example.com/flags/cm.png")
        self.assertEqual(question.prompt_blocks[0]["alt"], "Flag of Cameroon")

    def test_chat_endpoint_returns_conversation_reply_without_saving_quiz(self):
        before_count = Client().get("/api/quizzes/").json()

        response = Client().post(
            "/api/authoring/chat/",
            data={
                "mode": "auto",
                "messages": [{"role": "user", "content": "can you do a geography quiz"}],
                "recent_quizzes": [],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("reply", response.json())
        self.assertEqual(len(Client().get("/api/quizzes/").json()), len(before_count))

    def test_rejects_missing_text_answer_key(self):
        document = {
            "title": "Broken Quiz",
            "rounds": [
                {
                    "type": "sync_open",
                    "questions": [
                        {
                            "prompt_blocks": [{"type": "text", "text": "Explain X."}],
                            "answer_widget": {"type": "text_input"},
                            "canonical_answer": "",
                            "acceptable_answers": [],
                            "judge_mode": "fuzzy",
                        }
                    ],
                }
            ],
        }

        with self.assertRaisesRegex(AuthoringError, "needs canonical_answer"):
            create_quiz_from_document(document, AuthoringContext())

    def test_normalizes_multiple_choice_options_shape(self):
        document = {
            "title": "Multiple Choice Quiz",
            "rounds": [
                {
                    "type": "sync_open",
                    "questions": [
                        {
                            "prompt_blocks": [{"type": "text", "text": "Pick the phase factor."}],
                            "answer_widget": {
                                "type": "multiple_choice",
                                "options": [
                                    {"id": "A", "text": "wrong"},
                                    {"id": "B", "text": "right"},
                                ],
                            },
                            "canonical_answer": "right",
                            "acceptable_answers": [],
                            "judge_mode": "fuzzy",
                        }
                    ],
                }
            ],
        }

        quiz = create_quiz_from_document(document, AuthoringContext())
        question = quiz.rounds.first().questions.first()

        self.assertEqual(question.answer_widget["choices"], ["wrong", "right"])

    def test_normalizes_multiple_choice_correct_id_alias(self):
        document = {
            "title": "Multiple Choice Quiz",
            "rounds": [
                {
                    "type": "sync_open",
                    "questions": [
                        {
                            "prompt_blocks": [{"type": "text", "text": "Pick the phase factor."}],
                            "answer_widget": {
                                "type": "multiple_choice",
                                "options": [
                                    {"id": "A", "text": "wrong"},
                                    {"id": "B", "text": "right"},
                                ],
                            },
                            "answer_key": "B",
                            "judge_mode": "fuzzy",
                        }
                    ],
                }
            ],
        }

        quiz = create_quiz_from_document(document, AuthoringContext())
        question = quiz.rounds.first().questions.first()

        self.assertEqual(question.canonical_answer, "right")

    def test_normalizes_text_answer_aliases(self):
        document = {
            "title": "Text Quiz",
            "rounds": [
                {
                    "type": "sync_open",
                    "questions": [
                        {
                            "prompt_blocks": [{"type": "text", "text": "What evolves?"}],
                            "answer_widget": {"type": "text_input"},
                            "correct_answer": "the wavefunction",
                            "aliases": ["wave function"],
                            "judge_mode": "fuzzy",
                        }
                    ],
                }
            ],
        }

        quiz = create_quiz_from_document(document, AuthoringContext())
        question = quiz.rounds.first().questions.first()

        self.assertEqual(question.canonical_answer, "the wavefunction")
        self.assertEqual(question.acceptable_answers, ["the wavefunction", "wave function"])

    def test_rejects_multiple_choice_without_matching_canonical_answer(self):
        document = {
            "title": "Broken Multiple Choice Quiz",
            "rounds": [
                {
                    "type": "sync_open",
                    "questions": [
                        {
                            "prompt_blocks": [{"type": "text", "text": "Pick one."}],
                            "answer_widget": {"type": "multiple_choice", "choices": ["A", "B"]},
                            "canonical_answer": "C",
                            "acceptable_answers": [],
                            "judge_mode": "fuzzy",
                        }
                    ],
                }
            ],
        }

        with self.assertRaisesRegex(AuthoringError, "must exactly match one choice"):
            create_quiz_from_document(document, AuthoringContext())

    def test_normalizes_list_race_items(self):
        document = {
            "title": "List Race Quiz",
            "rounds": [
                {
                    "type": "list_race",
                    "config": {
                        "prompt": "Name the quarks.",
                        "items": [{"canonical": "up", "acceptable": ["u"]}],
                    },
                }
            ],
        }

        quiz = create_quiz_from_document(document, AuthoringContext())
        items = quiz.rounds.first().config["items"]

        self.assertEqual(items[0]["acceptable"], ["up", "u"])

    def test_update_metadata_op_endpoint_returns_updated_quiz(self):
        quiz = create_quiz_from_document(sample_quiz_document("hard quantum mechanics"))

        response = Client().post(
            f"/api/authoring/quizzes/{quiz.id}/ops/",
            data={
                "op": "quiz.update_metadata",
                "patch": {
                    "title": "Edited Schrodinger Night",
                    "category": "science",
                    "topic": "Schrodinger equation",
                    "difficulty": "hard",
                    "status": "ready",
                    "anticheat_strictness": "strict",
                },
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["title"], "Edited Schrodinger Night")
        self.assertEqual(payload["category"], QuizCategory.SCIENCE)
        self.assertEqual(payload["topic"], "Schrodinger equation")
        self.assertEqual(payload["status"], QuizStatus.READY)
        self.assertEqual(payload["anticheat_strictness"], "strict")

    def test_question_update_op_normalizes_answer_key(self):
        quiz = create_quiz_from_document(sample_quiz_document("hard quantum mechanics"))
        question = quiz.rounds.first().questions.first()

        updated_quiz = apply_quiz_op(
            quiz,
            {
                "op": "question.update",
                "question_id": str(question.id),
                "patch": {
                    "canonical_answer": "stationary state",
                    "acceptable_answers": ["energy eigenstate"],
                },
            },
        )

        question.refresh_from_db()
        self.assertEqual(question.canonical_answer, "stationary state")
        self.assertEqual(question.acceptable_answers, ["stationary state", "energy eigenstate"])
        self.assertEqual(updated_quiz.rounds.first().questions.first().canonical_answer, "stationary state")

    def test_question_update_rejects_broken_multiple_choice_answer_key(self):
        quiz = create_quiz_from_document(
            {
                "title": "Multiple Choice Quiz",
                "rounds": [
                    {
                        "type": "sync_open",
                        "questions": [
                            {
                                "prompt_blocks": [{"type": "text", "text": "Pick one."}],
                                "answer_widget": {"type": "multiple_choice", "choices": ["A", "B"]},
                                "canonical_answer": "A",
                                "acceptable_answers": ["A"],
                                "judge_mode": "fuzzy",
                            }
                        ],
                    }
                ],
            },
            AuthoringContext(),
        )
        question = quiz.rounds.first().questions.first()

        with self.assertRaisesRegex(AuthoringError, "must exactly match one choice"):
            apply_quiz_op(
                quiz,
                {
                    "op": "question.update",
                    "question_id": str(question.id),
                    "patch": {"canonical_answer": "C"},
                },
            )

    def test_items_bulk_set_op_normalizes_list_race_answers(self):
        quiz = create_quiz_from_document(sample_quiz_document("hard quantum mechanics"))
        list_round = quiz.rounds.get(type="list_race")

        apply_quiz_op(
            quiz,
            {
                "op": "items.bulk_set",
                "round_id": str(list_round.id),
                "items": [{"canonical": "up quark", "acceptable": ["u"]}],
            },
        )

        list_round.refresh_from_db()
        self.assertEqual(list_round.config["items"][0]["acceptable"], ["up quark", "u"])
