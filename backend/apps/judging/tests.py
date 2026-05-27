from django.test import SimpleTestCase

from apps.judging.fuzzy import fuzzy_match, normalize_answer


class FuzzyJudgingTests(SimpleTestCase):
    def test_normalizes_articles_punctuation_and_case(self):
        self.assertEqual(normalize_answer(" The Wave-Function! "), "wavefunction")

    def test_accepts_close_variant(self):
        verdict = fuzzy_match(
            "time evolution of wavefuncton",
            ["time evolution of the wavefunction"],
        )

        self.assertTrue(verdict["accepted"])

    def test_rejects_distant_answer(self):
        verdict = fuzzy_match("baseball stadium", ["time evolution of the wavefunction"])

        self.assertFalse(verdict["accepted"])

    def test_threshold_uses_normalized_answer_length(self):
        verdict = fuzzy_match("mean", ["the moon"])

        self.assertFalse(verdict["accepted"])
