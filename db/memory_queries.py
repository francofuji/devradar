"""
Queries específicas para entity_memory sobre PostgreSQL JSONB.
"""
from __future__ import annotations

from psycopg2 import IntegrityError
from psycopg2.extras import Json

from db import db_cursor


def get_latest_memory(entity_id: str) -> dict | None:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT memory, summary, version, created_at
            FROM entity_memory
            WHERE entity_id = %s AND status = 'active'
            ORDER BY version DESC
            LIMIT 1
            """,
            (entity_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    memory = dict(row["memory"] or {})
    memory["_version"] = row["version"]
    memory["_created_at"] = row["created_at"]
    memory["_summary"] = row["summary"]
    return memory


def get_memory_at_date(entity_id: str, before_date: str) -> dict | None:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT memory, summary, version, created_at
            FROM entity_memory
            WHERE entity_id = %s AND created_at <= %s
            ORDER BY version DESC
            LIMIT 1
            """,
            (entity_id, before_date),
        )
        row = cur.fetchone()

    if not row:
        return None

    memory = dict(row["memory"] or {})
    memory["_version"] = row["version"]
    memory["_created_at"] = row["created_at"]
    return memory


def get_memory_versions(entity_id: str) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT version, status, summary, created_at
            FROM entity_memory
            WHERE entity_id = %s
            ORDER BY version DESC
            """,
            (entity_id,),
        )
        return cur.fetchall()


def write_memory(
    entity_id: str,
    memory_dict: dict,
    summary: str | None = None,
    entity_type: str = "developer",
) -> int:
    last_error: Exception | None = None
    for _attempt in range(3):
        try:
            with db_cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(version), 0) AS max_v FROM entity_memory WHERE entity_id = %s",
                    (entity_id,),
                )
                row = cur.fetchone()
                next_version = int(row["max_v"]) + 1

                cur.execute(
                    """
                    INSERT INTO entity_memory (entity_id, entity_type, version, status, memory, summary)
                    VALUES (%s, %s, %s, 'active', %s, %s)
                    """,
                    (entity_id, entity_type, next_version, Json(memory_dict), summary),
                )

                cur.execute(
                    """
                    SELECT id FROM entity_memory
                    WHERE entity_id = %s AND status = 'active'
                    ORDER BY version DESC
                    OFFSET 10
                    """,
                    (entity_id,),
                )
                old_versions = cur.fetchall()

                if old_versions:
                    ids = [row["id"] for row in old_versions]
                    placeholders = ", ".join(["%s"] * len(ids))
                    cur.execute(
                        f"UPDATE entity_memory SET status = 'archived' WHERE id IN ({placeholders})",
                        ids,
                    )

            return next_version
        except IntegrityError as exc:
            last_error = exc
            continue

    assert last_error is not None
    raise last_error


def get_narrative(entity_id: str) -> str | None:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT summary FROM entity_memory
            WHERE entity_id = %s AND status = 'active'
            ORDER BY version DESC
            LIMIT 1
            """,
            (entity_id,),
        )
        row = cur.fetchone()
    return row["summary"] if row else None
