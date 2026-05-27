from django.test import Client, TestCase

from apps.authoring.ops import AuthoringContext, create_quiz_from_document
from apps.authoring.sample import sample_quiz_document
from apps.quizzes.models import QuizStatus


class QuizApiTests(TestCase):
    def test_play_catalog_lists_only_ready_quizzes_by_default(self):
        ready_quiz = create_quiz_from_document(sample_quiz_document("ready physics"), AuthoringContext())
        ready_quiz.status = QuizStatus.READY
        ready_quiz.save(update_fields=["status"])
        draft_quiz = create_quiz_from_document(sample_quiz_document("draft physics"), AuthoringContext())

        response = Client().get("/api/quizzes/")

        self.assertEqual(response.status_code, 200)
        quiz_ids = {item["id"] for item in response.json()}
        self.assertIn(str(ready_quiz.id), quiz_ids)
        self.assertNotIn(str(draft_quiz.id), quiz_ids)

    def test_authoring_catalog_includes_drafts(self):
        draft_quiz = create_quiz_from_document(sample_quiz_document("draft physics"), AuthoringContext())

        response = Client().get("/api/quizzes/?scope=authoring")

        self.assertEqual(response.status_code, 200)
        quiz_ids = {item["id"] for item in response.json()}
        self.assertIn(str(draft_quiz.id), quiz_ids)
