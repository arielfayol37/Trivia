from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction

from apps.quizzes.models import (
    AntiCheatStrictness,
    Difficulty,
    JudgeMode,
    Question,
    Quiz,
    QuizCategory,
    QuizStatus,
    QuizVisibility,
    Round,
    RoundType,
    SourceKind,
    SourceMaterial,
)


class AuthoringError(ValueError):
    pass


@dataclass(frozen=True)
class AuthoringContext:
    user: Any | None = None


def validate_quiz_document(document: dict) -> list[str]:
    errors: list[str] = []

    if not isinstance(document, dict):
        return ["quiz document must be an object"]

    if not str(document.get("title", "")).strip():
        errors.append("quiz.title is required")

    rounds = document.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        errors.append("quiz.rounds must contain at least one round")
        return errors

    for round_index, round_payload in enumerate(rounds, start=1):
        if not isinstance(round_payload, dict):
            errors.append(f"round {round_index} must be an object")
            continue

        round_type = round_payload.get("type", RoundType.SYNC_OPEN)
        if round_type not in RoundType.values:
            errors.append(f"round {round_index} has unsupported type: {round_type}")
            continue

        if round_type == RoundType.LIST_RACE:
            errors.extend(_validate_list_race_round(round_payload, round_index))
        else:
            errors.extend(_validate_question_round(round_payload, round_index))

    return errors


def _validate_list_race_round(round_payload: dict, round_index: int) -> list[str]:
    errors: list[str] = []
    config = round_payload.get("config") or {}
    if not str(config.get("prompt", "")).strip():
        errors.append(f"round {round_index} list_race config.prompt is required")

    items = config.get("items")
    if not isinstance(items, list) or not items:
        errors.append(f"round {round_index} list_race config.items must be non-empty")
        return errors

    for item_index, item in enumerate(items, start=1):
        if not isinstance(item, dict) or not str(item.get("canonical", "")).strip():
            errors.append(f"round {round_index} list_race item {item_index} needs canonical")
            continue
        acceptable = item.get("acceptable") or item.get("acceptable_answers") or []
        if acceptable and not isinstance(acceptable, list):
            errors.append(f"round {round_index} list_race item {item_index} acceptable must be a list")

    return errors


def _validate_question_round(round_payload: dict, round_index: int) -> list[str]:
    errors: list[str] = []
    questions = round_payload.get("questions")
    if not isinstance(questions, list) or not questions:
        errors.append(f"round {round_index} must contain at least one question")
        return errors

    for question_index, question_payload in enumerate(questions, start=1):
        prefix = f"round {round_index} question {question_index}"
        if not isinstance(question_payload, dict):
            errors.append(f"{prefix} must be an object")
            continue

        try:
            normalized = _normalize_question_payload(question_payload)
        except AuthoringError as exc:
            errors.append(f"{prefix}: {exc}")
            continue

        widget = normalized["answer_widget"]
        canonical = str(normalized["canonical_answer"]).strip()
        acceptable = normalized["acceptable_answers"]

        if widget["type"] == "multiple_choice":
            choices = widget.get("choices") or []
            if len(choices) < 2:
                errors.append(f"{prefix} multiple_choice needs at least two choices")
            if not canonical:
                errors.append(f"{prefix} multiple_choice needs canonical_answer")
            elif canonical not in choices:
                errors.append(
                    f"{prefix} multiple_choice canonical_answer must exactly match one choice"
                )
        elif widget["type"] in {"text_input", "list_input"}:
            if not canonical:
                errors.append(f"{prefix} {widget['type']} needs canonical_answer")
            if normalized["judge_mode"] == JudgeMode.FUZZY and not acceptable:
                errors.append(f"{prefix} fuzzy {widget['type']} needs acceptable_answers")
        else:
            has_structured_key = bool(normalized["metadata"].get("correct_payload"))
            if not canonical and not has_structured_key:
                errors.append(f"{prefix} {widget['type']} needs canonical_answer or correct_payload")

    return errors


def _validate_prompt_blocks(blocks: list[dict]) -> None:
    allowed = {"text", "image", "table", "math", "source_excerpt", "diagram_spec"}
    if not isinstance(blocks, list) or not blocks:
        raise AuthoringError("question.prompt_blocks must be a non-empty list")
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") not in allowed:
            raise AuthoringError(f"unsupported prompt block type: {block!r}")


def _normalize_answer_widget(widget: dict) -> dict:
    allowed = {
        "text_input",
        "list_input",
        "multiple_choice",
        "ordering",
        "matching",
        "image_choice",
        "hotspot",
    }
    if not isinstance(widget, dict) or widget.get("type") not in allowed:
        raise AuthoringError(f"unsupported answer widget: {widget!r}")

    if widget["type"] == "multiple_choice":
        if "choices" in widget and isinstance(widget["choices"], list):
            choices = [str(choice) for choice in widget["choices"]]
        elif "options" in widget and isinstance(widget["options"], list):
            choices = []
            for option in widget["options"]:
                if isinstance(option, dict):
                    choices.append(str(option.get("text") or option.get("label") or option.get("id")))
                else:
                    choices.append(str(option))
        else:
            raise AuthoringError("multiple_choice widgets require choices/options")
        return {"type": "multiple_choice", "choices": choices, "multi": bool(widget.get("multi", False))}

    return widget


def _extract_canonical_answer(payload: dict, answer_widget: dict) -> str:
    canonical = _first_non_empty_string(
        payload,
        [
            "canonical_answer",
            "correct_answer",
            "expected_answer",
            "answer",
            "answer_key",
            "rubric",
        ],
    )

    if answer_widget["type"] != "multiple_choice":
        return canonical

    raw_widget = payload.get("answer_widget") or {}
    choices = answer_widget.get("choices") or []
    options = raw_widget.get("options") if isinstance(raw_widget, dict) else None

    if canonical and canonical in choices:
        return canonical

    if canonical and isinstance(options, list):
        for option in options:
            if not isinstance(option, dict):
                continue
            option_text = str(option.get("text") or option.get("label") or option.get("id") or "")
            option_id = str(option.get("id") or "")
            if canonical in {option_id, option_text}:
                return option_text

    if isinstance(options, list):
        for option in options:
            if isinstance(option, dict) and option.get("correct"):
                return str(option.get("text") or option.get("label") or option.get("id") or "")

    correct_choice = _first_non_empty_string(
        raw_widget if isinstance(raw_widget, dict) else {},
        ["correct_choice", "correct_choice_id", "correct_answer", "answer_key"],
    )
    if correct_choice and correct_choice in choices:
        return correct_choice
    if correct_choice and isinstance(options, list):
        for option in options:
            if not isinstance(option, dict):
                continue
            option_text = str(option.get("text") or option.get("label") or option.get("id") or "")
            option_id = str(option.get("id") or "")
            if correct_choice in {option_id, option_text}:
                return option_text

    return canonical


def _first_non_empty_string(payload: dict, keys: list[str]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_acceptable_answers(payload: dict) -> list[str]:
    for key in ["acceptable_answers", "accepted_answers", "acceptable", "aliases", "synonyms"]:
        value = payload.get(key)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
    return []


def _normalize_question_payload(payload: dict) -> dict:
    prompt_blocks = payload.get("prompt_blocks")
    if prompt_blocks is None and payload.get("prompt"):
        prompt_blocks = [{"type": "text", "text": payload["prompt"]}]
    answer_widget = payload.get("answer_widget") or {"type": "text_input"}

    _validate_prompt_blocks(prompt_blocks)
    answer_widget = _normalize_answer_widget(answer_widget)

    canonical_answer = _extract_canonical_answer(payload, answer_widget)
    acceptable_answers = _extract_acceptable_answers(payload)
    if canonical_answer and canonical_answer not in acceptable_answers:
        acceptable_answers = [canonical_answer, *acceptable_answers]

    judge_mode = payload.get("judge_mode", JudgeMode.FUZZY)
    if judge_mode not in JudgeMode.values:
        raise AuthoringError(f"unsupported judge_mode: {judge_mode}")

    return {
        "prompt_blocks": prompt_blocks,
        "answer_widget": answer_widget,
        "canonical_answer": canonical_answer,
        "acceptable_answers": acceptable_answers,
        "judge_mode": judge_mode,
        "judge_config": payload.get("judge_config") or {},
        "metadata": payload.get("metadata") or {},
    }


def create_quiz_from_document(document: dict, context: AuthoringContext | None = None) -> Quiz:
    context = context or AuthoringContext()
    source_payload = document.get("source_material")
    validation_errors = validate_quiz_document(document)
    if validation_errors:
        raise AuthoringError("; ".join(validation_errors[:8]))

    with transaction.atomic():
        source_material = None
        if source_payload and source_payload.get("content"):
            source_material = SourceMaterial.objects.create(
                kind=source_payload.get("kind", SourceKind.TEXT),
                content=source_payload["content"],
                original_url=source_payload.get("original_url", ""),
                uploaded_by=getattr(context.user, "is_authenticated", False) and context.user or None,
            )

        quiz = Quiz.objects.create(
            title=document.get("title", "Untitled Quiz"),
            description=document.get("description", ""),
            category=_quiz_category(document),
            topic=document.get("topic", ""),
            difficulty=document.get("difficulty", Difficulty.MEDIUM),
            status=_quiz_status(document),
            visibility=document.get("visibility", QuizVisibility.PRIVATE),
            author=getattr(context.user, "is_authenticated", False) and context.user or None,
            source_material=source_material,
            anticheat_strictness=document.get("anticheat_strictness", AntiCheatStrictness.FRIENDLY),
            metadata=document.get("metadata") or {},
        )

        for round_index, round_payload in enumerate(document.get("rounds", []), start=1):
            round_type = round_payload.get("type", RoundType.SYNC_OPEN)
            if round_type not in RoundType.values:
                raise AuthoringError(f"unsupported round type: {round_type}")

            round_obj = Round.objects.create(
                quiz=quiz,
                order=round_payload.get("order", round_index),
                type=round_type,
                config=_normalize_round_config(round_type, round_payload.get("config") or {}),
            )

            for question_index, question_payload in enumerate(
                round_payload.get("questions", []), start=1
            ):
                normalized = _normalize_question_payload(question_payload)
                Question.objects.create(
                    round=round_obj,
                    order=question_payload.get("order", question_index),
                    **normalized,
                )

        if not quiz.rounds.exists():
            raise AuthoringError("quiz must contain at least one round")

        return quiz


def _quiz_category(document: dict) -> str:
    category = str(document.get("category", QuizCategory.GENERAL))
    if category not in QuizCategory.values:
        raise AuthoringError(f"unsupported category: {category}")
    return category


def _quiz_status(document: dict) -> str:
    status = str(document.get("status", QuizStatus.DRAFT))
    if status not in QuizStatus.values:
        raise AuthoringError(f"unsupported status: {status}")
    return status


def apply_quiz_op(quiz: Quiz, op_payload: dict) -> Quiz:
    if not isinstance(op_payload, dict):
        raise AuthoringError("operation payload must be an object")

    op_name = op_payload.get("op")
    if not isinstance(op_name, str) or not op_name.strip():
        raise AuthoringError("operation op is required")

    with transaction.atomic():
        locked_quiz = Quiz.objects.select_for_update().get(pk=quiz.pk)

        if op_name == "quiz.update_metadata":
            _apply_quiz_metadata_update(locked_quiz, _require_patch(op_payload))
        elif op_name == "question.update":
            _apply_question_update(locked_quiz, op_payload)
        elif op_name == "round.update_config":
            _apply_round_config_update(locked_quiz, op_payload)
        elif op_name == "items.bulk_set":
            _apply_items_bulk_set(locked_quiz, op_payload)
        else:
            raise AuthoringError(f"unsupported operation: {op_name}")

    return (
        Quiz.objects.prefetch_related("rounds__questions")
        .select_related("source_material")
        .get(pk=quiz.pk)
    )


def _require_patch(op_payload: dict) -> dict:
    patch = op_payload.get("patch")
    if not isinstance(patch, dict):
        raise AuthoringError("operation patch must be an object")
    return patch


def _reject_unknown_fields(patch: dict, allowed: set[str], label: str) -> None:
    unknown = sorted(set(patch) - allowed)
    if unknown:
        raise AuthoringError(f"{label} patch has unsupported fields: {', '.join(unknown)}")


def _apply_quiz_metadata_update(quiz: Quiz, patch: dict) -> None:
    allowed = {
        "title",
        "description",
        "category",
        "topic",
        "difficulty",
        "status",
        "visibility",
        "anticheat_strictness",
        "metadata",
    }
    _reject_unknown_fields(patch, allowed, "quiz.update_metadata")

    update_fields: list[str] = []
    if "title" in patch:
        title = str(patch["title"]).strip()
        if not title:
            raise AuthoringError("quiz title cannot be blank")
        quiz.title = title
        update_fields.append("title")
    if "description" in patch:
        quiz.description = str(patch["description"])
        update_fields.append("description")
    if "category" in patch:
        category = str(patch["category"])
        if category not in QuizCategory.values:
            raise AuthoringError(f"unsupported category: {category}")
        quiz.category = category
        update_fields.append("category")
    if "topic" in patch:
        quiz.topic = str(patch["topic"]).strip()
        update_fields.append("topic")
    if "difficulty" in patch:
        difficulty = str(patch["difficulty"])
        if difficulty not in Difficulty.values:
            raise AuthoringError(f"unsupported difficulty: {difficulty}")
        quiz.difficulty = difficulty
        update_fields.append("difficulty")
    if "status" in patch:
        status = str(patch["status"])
        if status not in QuizStatus.values:
            raise AuthoringError(f"unsupported status: {status}")
        quiz.status = status
        update_fields.append("status")
    if "visibility" in patch:
        visibility = str(patch["visibility"])
        if visibility not in QuizVisibility.values:
            raise AuthoringError(f"unsupported visibility: {visibility}")
        quiz.visibility = visibility
        update_fields.append("visibility")
    if "anticheat_strictness" in patch:
        strictness = str(patch["anticheat_strictness"])
        if strictness not in AntiCheatStrictness.values:
            raise AuthoringError(f"unsupported anticheat_strictness: {strictness}")
        quiz.anticheat_strictness = strictness
        update_fields.append("anticheat_strictness")
    if "metadata" in patch:
        if not isinstance(patch["metadata"], dict):
            raise AuthoringError("quiz metadata must be an object")
        quiz.metadata = patch["metadata"]
        update_fields.append("metadata")

    if update_fields:
        quiz.save(update_fields=[*update_fields, "updated_at"])


def _apply_question_update(quiz: Quiz, op_payload: dict) -> None:
    question_id = op_payload.get("question_id")
    if not isinstance(question_id, str) or not question_id:
        raise AuthoringError("question.update requires question_id")

    patch = _require_patch(op_payload)
    allowed = {
        "prompt_blocks",
        "answer_widget",
        "canonical_answer",
        "acceptable_answers",
        "judge_mode",
        "judge_config",
        "metadata",
    }
    _reject_unknown_fields(patch, allowed, "question.update")

    try:
        question = Question.objects.select_for_update().select_related("round").get(
            id=question_id,
            round__quiz=quiz,
        )
    except Question.DoesNotExist as exc:
        raise AuthoringError("question not found for quiz") from exc

    payload = {
        "prompt_blocks": question.prompt_blocks,
        "answer_widget": question.answer_widget,
        "canonical_answer": question.canonical_answer,
        "acceptable_answers": question.acceptable_answers,
        "judge_mode": question.judge_mode,
        "judge_config": question.judge_config,
        "metadata": question.metadata,
        **patch,
    }
    normalized = _normalize_question_payload(payload)
    errors = _validate_question_round(
        {"type": question.round.type, "questions": [normalized]},
        question.round.order,
    )
    if errors:
        raise AuthoringError("; ".join(errors[:4]))

    for field, value in normalized.items():
        setattr(question, field, value)
    question.save(
        update_fields=[
            "prompt_blocks",
            "answer_widget",
            "canonical_answer",
            "acceptable_answers",
            "judge_mode",
            "judge_config",
            "metadata",
        ]
    )


def _apply_round_config_update(quiz: Quiz, op_payload: dict) -> None:
    round_obj = _get_round_for_op(quiz, op_payload, "round.update_config")
    patch = _require_patch(op_payload)
    config = {**round_obj.config, **patch}
    _save_round_config(round_obj, config)


def _apply_items_bulk_set(quiz: Quiz, op_payload: dict) -> None:
    round_obj = _get_round_for_op(quiz, op_payload, "items.bulk_set")
    items = op_payload.get("items")
    if not isinstance(items, list):
        raise AuthoringError("items.bulk_set requires items list")
    config = {**round_obj.config, "items": items}
    _save_round_config(round_obj, config)


def _get_round_for_op(quiz: Quiz, op_payload: dict, op_name: str) -> Round:
    round_id = op_payload.get("round_id")
    if not isinstance(round_id, str) or not round_id:
        raise AuthoringError(f"{op_name} requires round_id")

    try:
        return Round.objects.select_for_update().get(id=round_id, quiz=quiz)
    except Round.DoesNotExist as exc:
        raise AuthoringError("round not found for quiz") from exc


def _save_round_config(round_obj: Round, config: dict) -> None:
    if not isinstance(config, dict):
        raise AuthoringError("round config must be an object")

    if round_obj.type == RoundType.LIST_RACE:
        errors = _validate_list_race_round({"config": config}, round_obj.order)
        if errors:
            raise AuthoringError("; ".join(errors[:4]))

    round_obj.config = _normalize_round_config(round_obj.type, config)
    round_obj.save(update_fields=["config"])


def _normalize_round_config(round_type: str, config: dict) -> dict:
    if round_type != RoundType.LIST_RACE:
        return config

    normalized_items = []
    for item in config.get("items", []):
        canonical = str(item.get("canonical", "")).strip()
        acceptable = item.get("acceptable") or item.get("acceptable_answers") or []
        if canonical and canonical not in acceptable:
            acceptable = [canonical, *acceptable]
        normalized_items.append({"canonical": canonical, "acceptable": acceptable})

    return {**config, "items": normalized_items}
