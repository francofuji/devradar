from __future__ import annotations

import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher

import structlog

from db import db_cursor

log = structlog.get_logger().bind(module="fine_tuning.capture")

MIN_TEXT_LEN = 8


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _compute_edit_distance(model_output: str, approved_output: str) -> float:
    left = _normalize_text(model_output)
    right = _normalize_text(approved_output)
    if not left and not right:
        return 0.0
    similarity = SequenceMatcher(None, left, right).ratio()
    return round(1.0 - similarity, 4)


def _compute_quality_score(model_output: str, approved_output: str) -> float:
    left = _normalize_text(model_output)
    right = _normalize_text(approved_output)
    if len(right) < MIN_TEXT_LEN:
        return 0.0
    similarity = SequenceMatcher(None, left, right).ratio()
    return round(similarity, 4)


def capture_example(
    task_type: str,
    system_prompt: str,
    user_input: str,
    model_output: str,
    approved_output: str,
    entity_id: str | None,
    provider: str | None,
    model_used: str | None,
    variant_label: str | None = None,
    source: str | None = "ollama",
) -> str:
    normalized_model_output = _normalize_text(model_output)
    normalized_approved_output = _normalize_text(approved_output)

    if not normalized_model_output:
        raise ValueError("model_output vacío")
    if not normalized_approved_output:
        raise ValueError("approved_output vacío")

    row_id = str(uuid.uuid4())
    was_edited = normalized_model_output != normalized_approved_output
    edit_distance = _compute_edit_distance(normalized_model_output, normalized_approved_output)
    quality_score = _compute_quality_score(normalized_model_output, normalized_approved_output)
    approved_at = datetime.now(timezone.utc).isoformat()

    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO fine_tuning_examples (
                id, task_type, system_prompt, user_input, model_output,
                approved_output, was_edited, edit_distance, entity_id,
                outcome, provider, model_used, approved_at, quality_score,
                variant_label, source
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                row_id,
                task_type,
                system_prompt,
                user_input,
                normalized_model_output,
                normalized_approved_output,
                was_edited,
                edit_distance,
                entity_id,
                "approved",
                provider,
                model_used,
                approved_at,
                quality_score,
                variant_label,
                source,
            ),
        )

    log.info(
        "fine_tuning.example_captured",
        row_id=row_id,
        task_type=task_type,
        entity_id=entity_id,
        provider=provider,
        model_used=model_used,
        was_edited=was_edited,
        quality_score=quality_score,
    )
    return row_id
