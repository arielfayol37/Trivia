from __future__ import annotations

import json
import time
from typing import Any

from django.conf import settings

from apps.quizzes.models import Question


JUDGE_SYSTEM_PROMPT = """You judge whether a player's typed trivia answer should be accepted.
Return only JSON. Be fair to aliases, spelling variants, transliterations, abbreviations,
and alternate names. Reject answers that are merely related but do not answer the prompt.
Do not require exact wording for conceptual answers when the meaning is correct.
"""

OPENAI_JUDGE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "trivia_judge_verdict",
        "schema": {
            "type": "object",
            "required": ["accepted", "confidence", "reasoning"],
            "properties": {
                "accepted": {"type": "boolean"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reasoning": {"type": "string"},
                "matched_answer": {"type": ["string", "null"]},
            },
            "additionalProperties": False,
        },
    },
}


def judge_typed_answer_with_llm(
    question: Question,
    submitted_text: str,
    *,
    fuzzy_result: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    provider, model = _resolve_judge_provider()
    if not provider or not model:
        return None

    payload = _question_judge_payload(question, submitted_text, fuzzy_result or {})
    started = time.perf_counter()
    try:
        if provider == "openai":
            verdict = _judge_with_openai(model, payload)
        elif provider == "anthropic":
            verdict = _judge_with_anthropic(model, payload)
        else:
            return None
    except Exception as exc:  # pragma: no cover - provider failures vary by SDK/network
        return {
            "accepted": False,
            "judge_latency_ms": _elapsed_ms(started),
            "judge_metadata": {
                "error": str(exc),
                "fallback": fuzzy_result,
                "provider": provider,
                "model": model,
            },
        }

    return {
        "accepted": bool(verdict.get("accepted")),
        "judge_latency_ms": _elapsed_ms(started),
        "judge_metadata": {
            "llm": verdict,
            "fallback": fuzzy_result,
            "provider": provider,
            "model": model,
        },
    }


def _resolve_judge_provider() -> tuple[str | None, str | None]:
    provider = settings.LLM_PROVIDER
    if provider == "auto":
        if settings.OPENAI_API_KEY and (settings.OPENAI_JUDGE_MODEL or settings.OPENAI_AUTHOR_MODEL):
            return "openai", settings.OPENAI_JUDGE_MODEL or settings.OPENAI_AUTHOR_MODEL
        if settings.ANTHROPIC_API_KEY and (
            settings.ANTHROPIC_JUDGE_MODEL or settings.ANTHROPIC_AUTHOR_MODEL
        ):
            return "anthropic", settings.ANTHROPIC_JUDGE_MODEL or settings.ANTHROPIC_AUTHOR_MODEL
        return None, None
    if provider == "openai" and settings.OPENAI_API_KEY:
        return "openai", settings.OPENAI_JUDGE_MODEL or settings.OPENAI_AUTHOR_MODEL
    if provider == "anthropic" and settings.ANTHROPIC_API_KEY:
        return "anthropic", settings.ANTHROPIC_JUDGE_MODEL or settings.ANTHROPIC_AUTHOR_MODEL
    return None, None


def _question_judge_payload(
    question: Question,
    submitted_text: str,
    fuzzy_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "prompt": _prompt_text(question),
        "submitted_answer": submitted_text,
        "canonical_answer": question.canonical_answer,
        "acceptable_answers": question.acceptable_answers,
        "judge_config": question.judge_config,
        "fuzzy_result": fuzzy_result,
        "instructions": [
            "Return accepted=true only if the submitted answer is equivalent to the expected answer.",
            "Accept common aliases and alternate names even if they are missing from acceptable_answers.",
            "For place/person/object names, accept well-known alternate names.",
            "For conceptual answers, accept equivalent meaning, not just exact wording.",
        ],
    }


def _prompt_text(question: Question) -> str:
    parts: list[str] = []
    for block in question.prompt_blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text" and block.get("text"):
            parts.append(str(block["text"]))
        elif block_type == "math" and block.get("latex"):
            parts.append(f"LaTeX: {block['latex']}")
        elif block_type == "source_excerpt" and block.get("text"):
            parts.append(f"Excerpt: {block['text']}")
        elif block_type == "table":
            parts.append(f"Table: {json.dumps(block, default=str)[:1200]}")
        elif block_type == "image":
            alt = block.get("alt") or block.get("caption") or block.get("url")
            if alt:
                parts.append(f"Image: {alt}")
    return "\n".join(parts)[:4000]


def _judge_with_openai(model: str, payload: dict[str, Any]) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=model,
        response_format=OPENAI_JUDGE_RESPONSE_FORMAT,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, default=str)},
        ],
    )
    text = response.choices[0].message.content or "{}"
    return json.loads(text)


def _judge_with_anthropic(model: str, payload: dict[str, Any]) -> dict[str, Any]:
    from anthropic import Anthropic

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=model,
        max_tokens=300,
        temperature=0,
        system=JUDGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
    )
    text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
    return json.loads(text)


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
