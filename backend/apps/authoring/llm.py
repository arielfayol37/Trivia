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
Use the format_examples in the user payload as composable patterns, not rigid quiz
templates. Rounds can mix questions with images, text, math, tables, and source excerpts.
When the request asks for image identification, create ordinary sync_open questions with
image prompt blocks and the requested answer widget. Do not turn image-identification
requests into list_race unless the user explicitly asks players to name many items from
memory from a single prompt.
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

FORMAT_EXAMPLES = {
    "image_identification": {
        "round": {
            "type": "sync_open",
            "config": {
                "answer_timeout_s": 20,
                "points_per_question": 10,
                "runner": "sequential_image_identification",
            },
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
                    "answer_widget": {"type": "text_input", "placeholder": "Country name"},
                    "canonical_answer": "Cameroon",
                    "acceptable_answers": ["Cameroon", "Republic of Cameroon", "Cameroun"],
                    "judge_mode": "fuzzy",
                    "metadata": {"source_kind": "country_flag", "image_question_kind": "flag"},
                }
            ],
        },
        "notes": [
            "Use one question per image when the game asks players to identify displayed images.",
            "This pattern also applies to flags, paintings, maps, diagrams, screenshots, logos, landmarks, or specimens.",
            "Preserve source image URLs exactly in prompt_blocks[].url when provided.",
            "Do not reveal the answer in visible prompt text or captions.",
        ],
    },
    "mixed_media_round": {
        "round": {
            "type": "sync_open",
            "config": {"answer_timeout_s": 25, "points_per_question": 10},
            "questions": [
                {
                    "prompt_blocks": [
                        {
                            "type": "image",
                            "url": "https://example.com/maps/cameroon.png",
                            "alt": "Map highlighting Cameroon",
                        },
                        {"type": "text", "text": "Which country is highlighted?"},
                    ],
                    "answer_widget": {"type": "text_input", "placeholder": "Country"},
                    "canonical_answer": "Cameroon",
                    "acceptable_answers": ["Cameroon", "Republic of Cameroon"],
                    "judge_mode": "fuzzy",
                },
                {
                    "prompt_blocks": [
                        {"type": "text", "text": "What city is Cameroon's political capital?"}
                    ],
                    "answer_widget": {"type": "text_input", "placeholder": "City"},
                    "canonical_answer": "Yaounde",
                    "acceptable_answers": ["Yaounde"],
                    "judge_mode": "fuzzy",
                },
                {
                    "prompt_blocks": [
                        {
                            "type": "table",
                            "columns": ["Clue", "Value"],
                            "rows": [["Largest city", "Douala"], ["Highest mountain", "Mount Cameroon"]],
                        }
                    ],
                    "answer_widget": {
                        "type": "multiple_choice",
                        "choices": ["Cameroon", "Gabon", "Chad", "Nigeria"],
                    },
                    "canonical_answer": "Cameroon",
                    "acceptable_answers": ["Cameroon"],
                    "judge_mode": "fuzzy",
                },
            ],
        },
        "notes": [
            "A single round may mix image questions and non-image questions.",
            "Choose prompt blocks per question; do not create a new round solely because the prompt block type changes.",
        ],
    },
    "classic_text_input": {
        "question": {
            "prompt_blocks": [{"type": "text", "text": "What city is Cameroon's political capital?"}],
            "answer_widget": {"type": "text_input", "placeholder": "City name"},
            "canonical_answer": "Yaounde",
            "acceptable_answers": ["Yaounde", "Yaounde, Cameroon"],
            "judge_mode": "fuzzy",
        }
    },
    "multiple_choice": {
        "question": {
            "prompt_blocks": [{"type": "text", "text": "Which country uses this currency: CFA franc?"}],
            "answer_widget": {
                "type": "multiple_choice",
                "choices": ["Cameroon", "Japan", "Brazil", "Canada"],
            },
            "canonical_answer": "Cameroon",
            "acceptable_answers": ["Cameroon"],
            "judge_mode": "fuzzy",
        }
    },
    "math_prompt": {
        "question": {
            "prompt_blocks": [
                {"type": "text", "text": "Identify the equation."},
                {"type": "math", "latex": "i\\hbar\\frac{\\partial}{\\partial t}\\Psi=\\hat{H}\\Psi"},
            ],
            "answer_widget": {"type": "text_input"},
            "canonical_answer": "time-dependent Schrodinger equation",
            "acceptable_answers": ["time-dependent Schrodinger equation", "TDSE"],
            "judge_mode": "fuzzy",
        }
    },
    "table_prompt": {
        "question": {
            "prompt_blocks": [
                {
                    "type": "table",
                    "columns": ["Clue", "Value"],
                    "rows": [["Largest city", "Douala"], ["Official languages", "French and English"]],
                }
            ],
            "answer_widget": {"type": "text_input"},
            "canonical_answer": "Cameroon",
            "acceptable_answers": ["Cameroon"],
            "judge_mode": "fuzzy",
        }
    },
    "source_excerpt": {
        "question": {
            "prompt_blocks": [
                {
                    "type": "source_excerpt",
                    "text": "The lecture describes a behavioral observation, then tests competing hypotheses.",
                    "citation": "User source material",
                }
            ],
            "answer_widget": {"type": "text_input"},
            "canonical_answer": "hypothesis testing",
            "acceptable_answers": ["hypothesis testing", "experimental design"],
            "judge_mode": "llm",
        }
    },
    "list_race": {
        "round": {
            "type": "list_race",
            "config": {
                "prompt": "Name the countries that border Cameroon.",
                "time_limit_s": 90,
                "items": [
                    {"canonical": "Nigeria", "acceptable": ["Nigeria"]},
                    {"canonical": "Chad", "acceptable": ["Chad"]},
                ],
            },
            "questions": [],
        },
        "notes": ["Use list_race only when players should recall many answers from one prompt."],
    },
    "meta_strategy": {
        "round": {
            "type": "meta_strategy",
            "config": {
                "min_bet": 1,
                "max_bet": 10,
                "default_bet": 1,
                "bet_window_s": 10,
                "answer_timeout_s": 25,
            },
            "questions": [
                {
                    "prompt_blocks": [
                        {
                            "type": "text",
                            "text": "Which operator generates time evolution in the Schrodinger equation?",
                        }
                    ],
                    "answer_widget": {"type": "text_input", "placeholder": "Operator"},
                    "canonical_answer": "Hamiltonian",
                    "acceptable_answers": ["Hamiltonian", "Hamiltonian operator"],
                    "judge_mode": "fuzzy",
                    "metadata": {"category_hint": "Foundations of quantum mechanics"},
                }
            ],
        },
        "notes": [
            "Players see metadata.category_hint before they see prompt_blocks.",
            "After players wager, the normal question prompt is revealed.",
            "The server turns min_bet/max_bet into one reusable wager deck card per question, spread across the range. Use wager_values only for an explicit custom deck.",
            "Use this for risk/reward strategy, not for every ordinary question.",
        ],
    },
    "ordering": {
        "question": {
            "prompt_blocks": [{"type": "text", "text": "Order these countries by population, largest first."}],
            "answer_widget": {"type": "ordering", "items": ["Cameroon", "Gabon", "Chad"]},
            "canonical_answer": "Cameroon > Chad > Gabon",
            "acceptable_answers": ["Cameroon > Chad > Gabon"],
            "judge_mode": "fuzzy",
            "metadata": {"correct_payload": ["Cameroon", "Chad", "Gabon"]},
        }
    },
    "matching": {
        "question": {
            "prompt_blocks": [{"type": "text", "text": "Match each country to its capital."}],
            "answer_widget": {
                "type": "matching",
                "left": ["Cameroon", "Japan"],
                "right": ["Yaounde", "Tokyo"],
            },
            "canonical_answer": "Cameroon-Yaounde; Japan-Tokyo",
            "acceptable_answers": ["Cameroon-Yaounde; Japan-Tokyo"],
            "judge_mode": "fuzzy",
            "metadata": {"correct_payload": {"Cameroon": "Yaounde", "Japan": "Tokyo"}},
        }
    },
    "image_choice": {
        "question": {
            "prompt_blocks": [{"type": "text", "text": "Choose the flag of Cameroon."}],
            "answer_widget": {
                "type": "image_choice",
                "images": [
                    {"url": "https://example.com/flags/cm.png", "alt": "Cameroon", "label": "A"},
                    {"url": "https://example.com/flags/jp.png", "alt": "Japan", "label": "B"},
                ],
            },
            "canonical_answer": "A",
            "acceptable_answers": ["A", "Cameroon"],
            "judge_mode": "fuzzy",
            "metadata": {"correct_payload": "A"},
        }
    },
    "hotspot": {
        "question": {
            "prompt_blocks": [{"type": "text", "text": "Click Cameroon on the map."}],
            "answer_widget": {
                "type": "hotspot",
                "image_url": "https://example.com/maps/africa.png",
                "regions": [{"id": "cm", "label": "Cameroon"}],
            },
            "canonical_answer": "cm",
            "acceptable_answers": ["cm", "Cameroon"],
            "judge_mode": "fuzzy",
            "metadata": {"correct_payload": "cm"},
        }
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
        "format_examples": FORMAT_EXAMPLES,
        "requirements": [
            "Create a static quiz with at least one playable round. Respect the requested format; list_race-only quizzes are allowed when requested.",
            "Set category to one of science, tv, sports, geography, history, general. New generated quizzes should remain status=draft until the user marks them ready.",
            "Use prompt_blocks and answer_widget on every question.",
            "Treat prompt blocks as composable. A quiz may contain multiple round types, and a single sync_open round may mix text-only, image, math, table, and source-excerpt questions.",
            "Support non-text play when requested: image prompts, table prompts, math blocks, source excerpts, list_race rounds, image_choice, ordering, matching, and hotspot widgets.",
            "Prefer currently playable answer flows unless the user explicitly requests an experimental format: text_input, multiple_choice, image prompt plus text_input, list_race, image_choice, ordering, and matching.",
            "For image-identification questions, create sync_open questions with image prompt blocks and the requested answer widget. Do not use list_race unless the user asks for a name-all/list-race format.",
            "When source_text contains HTML, rows, or snippets with country names and flag image URLs, extract country-image pairs and preserve those image URLs exactly in prompt_blocks[].url.",
            "For flag/image identification questions, do not reveal the answer in visible prompt text or captions. Use alt text for accessibility only.",
            "If reliable image URLs are not provided, make the image asset requirement explicit in alt/caption/metadata rather than pretending the quiz is pure text.",
            "For fuzzy text_input questions, include non-empty canonical_answer and acceptable_answers.",
            "If a text_input answer cannot be enumerated, set judge_mode to llm and provide a concise canonical_answer/rubric.",
            "For multiple_choice widgets, use choices as an array of strings and set canonical_answer to the exact correct choice text.",
            "For meta_strategy rounds, set round config min_bet, max_bet, default_bet, bet_window_s, answer_timeout_s, and put a concise pre-question hint in each question's metadata.category_hint. The server will expose one wager card per question, spread across min_bet/max_bet, unless wager_values is explicitly set.",
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
