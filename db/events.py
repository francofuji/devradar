"""
Función canónica emit_event() y lógica de deduplicación.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from psycopg2.extras import Json

from db import db_cursor
from db.catalog import get_category, validate_event_type


def emit_event(
    event_type: str,
    entity_id: str,
    entity_type: str,
    payload: dict,
    source: str = "internal",
    confidence: float = 1.0,
    source_url: str | None = None,
    occurred_at: str | None = None,
) -> str | None:
    validate_event_type(event_type)

    now = datetime.now(timezone.utc).isoformat()
    occurred = occurred_at or now
    event_id = str(uuid.uuid4())
    category = get_category(event_type)

    if _is_duplicate(entity_id, event_type, source_url, occurred):
        return None

    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO events (
                id, event_type, event_category, occurred_at, detected_at,
                source, source_url, entity_id, entity_type,
                payload, confidence, enrichment_status, processing_ver
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', '0.1.0')
            """,
            (
                event_id,
                event_type,
                category,
                occurred,
                now,
                source,
                source_url,
                entity_id,
                entity_type,
                Json(payload),
                confidence,
            ),
        )

    return event_id


def _is_duplicate(
    entity_id: str,
    event_type: str,
    source_url: str | None,
    occurred_at: str,
    window_hours: int = 24,
) -> bool:
    with db_cursor() as cur:
        if source_url:
            cur.execute(
                """
                SELECT id FROM events
                WHERE entity_id = %s
                  AND event_type = %s
                  AND source_url = %s
                  AND occurred_at >= (%s::timestamptz - (%s || ' hours')::interval)
                LIMIT 1
                """,
                (entity_id, event_type, source_url, occurred_at, str(window_hours)),
            )
        else:
            cur.execute(
                """
                SELECT id FROM events
                WHERE entity_id = %s
                  AND event_type = %s
                  AND source_url IS NULL
                  AND occurred_at >= (%s::timestamptz - (%s || ' hours')::interval)
                LIMIT 1
                """,
                (entity_id, event_type, occurred_at, str(window_hours)),
            )
        return cur.fetchone() is not None
