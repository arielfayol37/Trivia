from __future__ import annotations

import re
import string

from Levenshtein import distance


ARTICLES_RE = re.compile(r"\b(the|a|an)\b", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")
PUNCT_TRANSLATION = str.maketrans("", "", string.punctuation)


def normalize_answer(value: str) -> str:
    normalized = value.strip().lower()
    normalized = normalized.translate(PUNCT_TRANSLATION)
    normalized = ARTICLES_RE.sub(" ", normalized)
    normalized = WHITESPACE_RE.sub(" ", normalized)
    return normalized.strip()


def default_threshold(answer: str) -> int:
    if len(answer) <= 4:
        return 1
    if len(answer) <= 6:
        return 2
    return 3


def fuzzy_match(submitted: str, acceptable_answers: list[str], threshold: int | None = None) -> dict:
    normalized_submitted = normalize_answer(submitted)
    answer_pairs: list[tuple[str, str]] = []
    for answer in acceptable_answers:
        if not answer:
            continue
        normalized = normalize_answer(answer)
        if normalized:
            answer_pairs.append((answer, normalized))

    for original, normalized in answer_pairs:
        if normalized_submitted == normalized:
            return {"accepted": True, "matched_against": original, "distance": 0}

    best: tuple[str, str, int] | None = None
    for original, normalized in answer_pairs:
        current = distance(normalized_submitted, normalized)
        if best is None or current < best[2]:
            best = (original, normalized, current)

    if best is None:
        return {"accepted": False, "matched_against": None, "distance": None}

    allowed = threshold if threshold is not None else default_threshold(best[1])
    return {
        "accepted": best[2] <= allowed,
        "matched_against": best[0] if best[2] <= allowed else None,
        "distance": best[2],
    }
