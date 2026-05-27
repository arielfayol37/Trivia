from __future__ import annotations

import json

from django.conf import settings

from apps.authoring.ops import validate_quiz_document
from apps.authoring.sample import sample_quiz_document


class LLMGenerationError(RuntimeError):
    pass


AUTHORING_SYSTEM_PROMPT = """You create static multiplayer quiz documents.
Return only valid JSON matching the product schema. Do not include Markdown fences.
Prefer deep, specific questions over shallow trivia. Use prompt_blocks and answer_widget;
do not assume every question is plain text.
Supported prompt block types: text, image, table, math, source_excerpt, diagram_spec.
Supported answer widget types: text_input, list_input, multiple_choice, ordering,
matching, image_choice, hotspot.
"""

AUTHORING_CHAT_SYSTEM_PROMPT = """You are an expert quiz producer inside a multiplayer trivia authoring tool.
Have a concise, useful planning conversation. Do not generate a full quiz JSON unless the
user explicitly asks to draft now. Ask focused follow-up questions when the request is broad.
Help choose game formats such as flag sprint, list race, synchronized open-answer,
meta-strategy, buzz-in, image prompts, maps, tables, math blocks, and source-based questions.
When a current draft is present, discuss concrete edits and tradeoffs.
"""

OPENAI_QUIZ_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "trivia_quiz_document",
        "schema": {
            "type": "object",
            "required": ["title", "description", "rounds"],
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "description": {"type": "string"},
                "category": {
                    "type": "string",
                    "enum": ["science", "tv", "sports", "geography", "history", "general"],
                },
                "topic": {"type": "string"},
                "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
                "status": {"type": "string", "enum": ["draft", "ready", "archived"]},
                "visibility": {"type": "string", "enum": ["private", "public"]},
                "anticheat_strictness": {
                    "type": "string",
                    "enum": ["strict", "friendly", "off"],
                },
                "source_material": {"type": ["object", "null"]},
                "rounds": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["type", "config", "questions"],
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    "sync_open",
                                    "list_race",
                                    "meta_strategy",
                                    "buzz_in",
                                ],
                            },
                            "order": {"type": "integer"},
                            "config": {"type": "object"},
                            "questions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": [
                                        "prompt_blocks",
                                        "answer_widget",
                                        "canonical_answer",
                                        "acceptable_answers",
                                        "judge_mode",
                                    ],
                                    "properties": {
                                        "order": {"type": "integer"},
                                        "prompt_blocks": {
                                            "type": "array",
                                            "minItems": 1,
                                            "items": {
                                                "type": "object",
                                                "required": ["type"],
                                                "properties": {
                                                    "type": {
                                                        "type": "string",
                                                        "enum": [
                                                            "text",
                                                            "image",
                                                            "table",
                                                            "math",
                                                            "source_excerpt",
                                                            "diagram_spec",
                                                        ],
                                                    },
                                                    "text": {"type": "string"},
                                                    "url": {"type": "string"},
                                                    "alt": {"type": "string"},
                                                    "caption": {"type": "string"},
                                                    "latex": {"type": "string"},
                                                    "columns": {
                                                        "type": "array",
                                                        "items": {"type": "string"},
                                                    },
                                                    "rows": {
                                                        "type": "array",
                                                        "items": {"type": "array"},
                                                    },
                                                },
                                                "additionalProperties": True,
                                            },
                                        },
                                        "answer_widget": {
                                            "type": "object",
                                            "required": ["type"],
                                            "properties": {
                                                "type": {
                                                    "type": "string",
                                                    "enum": [
                                                        "text_input",
                                                        "list_input",
                                                        "multiple_choice",
                                                        "ordering",
                                                        "matching",
                                                        "image_choice",
                                                        "hotspot",
                                                    ],
                                                },
                                                "placeholder": {"type": "string"},
                                                "choices": {
                                                    "type": "array",
                                                    "items": {"type": "string"},
                                                },
                                            },
                                            "additionalProperties": True,
                                        },
                                        "canonical_answer": {"type": "string", "minLength": 1},
                                        "acceptable_answers": {
                                            "type": "array",
                                            "minItems": 1,
                                            "items": {"type": "string", "minLength": 1},
                                        },
                                        "judge_mode": {"type": "string", "enum": ["fuzzy", "llm"]},
                                        "judge_config": {"type": "object"},
                                        "metadata": {"type": "object"},
                                    },
                                    "additionalProperties": True,
                                },
                            },
                        },
                        "additionalProperties": True,
                    },
                },
            },
            "additionalProperties": True,
        },
    },
}


async def generate_quiz_document(prompt: str, source_text: str = "") -> dict:
    provider = _resolve_provider()
    if provider == "openai":
        document = await _generate_with_openai(prompt, source_text)
        return await _repair_if_needed(provider, prompt, source_text, document)
    if provider == "anthropic":
        document = await _generate_with_anthropic(prompt, source_text)
        return await _repair_if_needed(provider, prompt, source_text, document)
    return sample_quiz_document(prompt, source_text)


async def generate_authoring_chat_response(
    messages: list[dict],
    *,
    mode: str = "auto",
    current_quiz: dict | None = None,
    recent_quizzes: list[dict] | None = None,
    source_text: str = "",
) -> str:
    provider = _resolve_provider()
    if provider == "openai":
        return await _chat_with_openai(messages, mode, current_quiz, recent_quizzes or [], source_text)
    if provider == "anthropic":
        return await _chat_with_anthropic(messages, mode, current_quiz, recent_quizzes or [], source_text)
    return _sample_chat_response(messages, mode, current_quiz)


def _resolve_provider() -> str:
    provider = settings.LLM_PROVIDER
    if provider == "auto":
        if settings.OPENAI_API_KEY and settings.OPENAI_AUTHOR_MODEL:
            return "openai"
        if settings.ANTHROPIC_API_KEY and settings.ANTHROPIC_AUTHOR_MODEL:
            return "anthropic"
        return "sample"
    if provider == "openai" and settings.OPENAI_API_KEY and settings.OPENAI_AUTHOR_MODEL:
        return "openai"
    if provider == "anthropic" and settings.ANTHROPIC_API_KEY and settings.ANTHROPIC_AUTHOR_MODEL:
        return "anthropic"
    return "sample"


def _user_prompt(prompt: str, source_text: str) -> dict:
    return {
        "request": prompt,
        "source_text": source_text,
        "requirements": [
            "Create a static quiz with at least one playable round. Respect the requested format; list_race-only quizzes are allowed when requested.",
            "Set category to one of science, tv, sports, geography, history, general. New generated quizzes should remain status=draft until the user marks them ready.",
            "Use prompt_blocks and answer_widget on every question.",
            "Support non-text play when requested: image prompts, table prompts, math blocks, source excerpts, list_race rounds, image_choice, ordering, matching, and hotspot widgets.",
            "For flag/image sprint quizzes, prefer image prompt blocks and text_input answers. If reliable image URLs are not provided, make the image asset requirement explicit in alt/caption/metadata rather than pretending the quiz is pure text.",
            "For fuzzy text_input questions, include non-empty canonical_answer and acceptable_answers.",
            "If a text_input answer cannot be enumerated, set judge_mode to llm and provide a concise canonical_answer/rubric.",
            "For multiple_choice widgets, use choices as an array of strings and set canonical_answer to the exact correct choice text.",
            "Every non-list-race question must include a playable answer key.",
            "For list_race rounds, config.prompt and config.items must be non-empty; every item needs canonical and acceptable variants.",
            "Use LaTeX strings for math blocks, without Markdown fences.",
            "Return JSON only.",
        ],
    }


def _chat_context(
    mode: str,
    current_quiz: dict | None,
    recent_quizzes: list[dict],
    source_text: str,
) -> str:
    return json.dumps(
        {
            "selected_mode": mode,
            "current_draft": current_quiz,
            "recent_quizzes": recent_quizzes[:12],
            "source_text_present": bool(source_text.strip()),
            "source_text_excerpt": source_text[:4000],
            "instructions": [
                "Reply in natural language, not JSON.",
                "Do not create the full quiz unless the user says to draft/generate/update now.",
                "If the user asks broadly, ask for format, difficulty, length, and audience.",
                "Keep replies under 140 words unless the user asks for detail.",
            ],
        },
        default=str,
    )


def _repair_prompt(prompt: str, source_text: str, document: dict, errors: list[str]) -> dict:
    return {
        "request": prompt,
        "source_text": source_text,
        "invalid_document": document,
        "validation_errors": errors,
        "repair_instructions": [
            "Return a complete corrected quiz JSON document, not a patch.",
            "Do not remove good questions unless necessary.",
            "Fill all missing canonical_answer and acceptable_answers fields.",
            "For multiple_choice, canonical_answer must exactly equal one item in answer_widget.choices.",
            "For conceptual text_input questions, judge_mode may be llm but canonical_answer must still describe the expected answer/rubric.",
            "Return JSON only.",
        ],
    }


async def _repair_if_needed(provider: str, prompt: str, source_text: str, document: dict) -> dict:
    errors = validate_quiz_document(document)
    if not errors:
        return document

    if provider == "openai":
        repaired = await _repair_with_openai(prompt, source_text, document, errors)
    elif provider == "anthropic":
        repaired = await _repair_with_anthropic(prompt, source_text, document, errors)
    else:
        repaired = document

    repaired_errors = validate_quiz_document(repaired)
    if repaired_errors:
        raise LLMGenerationError(
            "Generated quiz failed playability validation: "
            + "; ".join(repaired_errors[:8])
        )

    return repaired


async def _generate_with_anthropic(prompt: str, source_text: str) -> dict:
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        return sample_quiz_document(prompt, source_text)

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    try:
        response = await client.messages.create(
            model=settings.ANTHROPIC_AUTHOR_MODEL,
            max_tokens=5000,
            temperature=0.4,
            system=AUTHORING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(_user_prompt(prompt, source_text))}],
        )
    except Exception as exc:
        raise LLMGenerationError(str(exc)) from exc

    text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMGenerationError("Anthropic returned non-JSON content") from exc


async def _generate_with_openai(prompt: str, source_text: str) -> dict:
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return sample_quiz_document(prompt, source_text)

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    try:
        response = await client.chat.completions.create(
            model=settings.OPENAI_AUTHOR_MODEL,
            response_format=OPENAI_QUIZ_RESPONSE_FORMAT,
            messages=[
                {"role": "system", "content": AUTHORING_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(_user_prompt(prompt, source_text))},
            ],
        )
    except Exception as exc:
        raise LLMGenerationError(str(exc)) from exc

    text = response.choices[0].message.content or "{}"
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMGenerationError("OpenAI returned non-JSON content") from exc


async def _chat_with_openai(
    messages: list[dict],
    mode: str,
    current_quiz: dict | None,
    recent_quizzes: list[dict],
    source_text: str,
) -> str:
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return _sample_chat_response(messages, mode, current_quiz)

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    chat_messages = [
        {"role": "system", "content": AUTHORING_CHAT_SYSTEM_PROMPT},
        {"role": "system", "content": _chat_context(mode, current_quiz, recent_quizzes, source_text)},
    ]
    chat_messages.extend(_normalize_chat_messages(messages))

    try:
        response = await client.chat.completions.create(
            model=settings.OPENAI_AUTHOR_MODEL,
            messages=chat_messages,
            max_completion_tokens=500,
        )
    except Exception as exc:
        raise LLMGenerationError(str(exc)) from exc

    return (response.choices[0].message.content or "").strip()


async def _chat_with_anthropic(
    messages: list[dict],
    mode: str,
    current_quiz: dict | None,
    recent_quizzes: list[dict],
    source_text: str,
) -> str:
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        return _sample_chat_response(messages, mode, current_quiz)

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    system = AUTHORING_CHAT_SYSTEM_PROMPT + "\n\n" + _chat_context(
        mode, current_quiz, recent_quizzes, source_text
    )

    try:
        response = await client.messages.create(
            model=settings.ANTHROPIC_AUTHOR_MODEL,
            max_tokens=500,
            temperature=0.4,
            system=system,
            messages=_normalize_chat_messages(messages),
        )
    except Exception as exc:
        raise LLMGenerationError(str(exc)) from exc

    return "".join(block.text for block in response.content if getattr(block, "type", "") == "text").strip()


def _normalize_chat_messages(messages: list[dict]) -> list[dict]:
    normalized = []
    for message in messages[-16:]:
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = str(message.get("content", "")).strip()
        if content:
            normalized.append({"role": role, "content": content})
    return normalized or [{"role": "user", "content": "Help me design a quiz."}]


def _sample_chat_response(messages: list[dict], mode: str, current_quiz: dict | None) -> str:
    last_user = next(
        (
            str(message.get("content", ""))
            for message in reversed(messages)
            if message.get("role") == "user"
        ),
        "",
    ).lower()
    if "geography" in last_user or "flag" in last_user or "country" in last_user:
        return (
            "Yes. Geography can work as a flag sprint, capitals race, map-clue quiz, "
            "landmarks round, or a mixed geography set. What format, difficulty, and length do you want?"
        )
    if current_quiz:
        return "I can revise the current draft. Tell me what should change, then use Update draft when ready."
    if mode != "auto":
        return f"I have {mode.replace('_', ' ')} selected. Give me topic, difficulty, and length, then use Draft now."
    return "Yes. What format, difficulty, length, and audience should I target?"


async def _repair_with_openai(
    prompt: str, source_text: str, document: dict, errors: list[str]
) -> dict:
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return document

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    try:
        response = await client.chat.completions.create(
            model=settings.OPENAI_AUTHOR_MODEL,
            response_format=OPENAI_QUIZ_RESPONSE_FORMAT,
            messages=[
                {"role": "system", "content": AUTHORING_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(_repair_prompt(prompt, source_text, document, errors))},
            ],
        )
    except Exception as exc:
        raise LLMGenerationError(str(exc)) from exc

    text = response.choices[0].message.content or "{}"
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMGenerationError("OpenAI repair returned non-JSON content") from exc


async def _repair_with_anthropic(
    prompt: str, source_text: str, document: dict, errors: list[str]
) -> dict:
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        return document

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        response = await client.messages.create(
            model=settings.ANTHROPIC_AUTHOR_MODEL,
            max_tokens=5000,
            temperature=0.4,
            system=AUTHORING_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(_repair_prompt(prompt, source_text, document, errors)),
                }
            ],
        )
    except Exception as exc:
        raise LLMGenerationError(str(exc)) from exc

    text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMGenerationError("Anthropic repair returned non-JSON content") from exc
