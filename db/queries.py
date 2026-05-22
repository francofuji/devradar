"""
Todas las queries SQL del sistema.
Sin ORM, con psycopg2 + PostgreSQL JSONB nativo.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from psycopg2.extras import Json

from db import db_cursor


def _json_param(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return Json(json.loads(value))
        except json.JSONDecodeError:
            return Json(value)
    return Json(value)


def upsert_developer(data: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO developers (
                id, name, email, github_url, twitter, personal_site,
                first_seen, last_active, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = COALESCE(EXCLUDED.name, developers.name),
                email = COALESCE(EXCLUDED.email, developers.email),
                github_url = COALESCE(EXCLUDED.github_url, developers.github_url),
                twitter = COALESCE(EXCLUDED.twitter, developers.twitter),
                personal_site = COALESCE(EXCLUDED.personal_site, developers.personal_site),
                last_active = EXCLUDED.last_active,
                updated_at = EXCLUDED.updated_at
            """,
            (
                data["id"],
                data.get("name"),
                data.get("email"),
                data.get("github_url"),
                data.get("twitter"),
                data.get("personal_site"),
                data.get("first_seen", now),
                data.get("last_active", now),
                now,
            ),
        )


def get_developer(github_handle: str):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM developers WHERE id = %s", (github_handle.lower(),))
        return cur.fetchone()


def developer_exists(github_handle: str) -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT 1 AS found FROM developers WHERE id = %s", (github_handle.lower(),))
        return cur.fetchone() is not None


def update_developer_profile_fields(
    entity_id: str,
    *,
    linkedin_manual: dict | None = None,
    outreach_status: str | None = None,
    status: str | None = None,
    last_active: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    assignments: list[str] = ["updated_at = %s"]
    params: list = [now]

    if linkedin_manual is not None:
        assignments.append("linkedin_manual = %s")
        params.append(Json(linkedin_manual))
    if outreach_status is not None:
        assignments.append("outreach_status = %s")
        params.append(outreach_status)
    if status is not None:
        assignments.append("status = %s")
        params.append(status)
    if last_active is not None:
        assignments.append("last_active = %s")
        params.append(last_active)

    params.append(entity_id)

    with db_cursor() as cur:
        cur.execute(f"UPDATE developers SET {', '.join(assignments)} WHERE id = %s", params)


def update_developer_status(entity_id: str, status: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with db_cursor() as cur:
        cur.execute(
            "UPDATE developers SET status = %s, updated_at = %s WHERE id = %s",
            (status, now, entity_id),
        )


def update_developer_scores(
    entity_id: str,
    intent_score: float,
    maturity_score: float,
    trajectory_7d: float = 0.0,
    trajectory_30d: float = 0.0,
    trajectory_direction: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE developers SET
                intent_score = %s,
                maturity_score = %s,
                trajectory_7d = %s,
                trajectory_30d = %s,
                trajectory_direction = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (intent_score, maturity_score, trajectory_7d, trajectory_30d, trajectory_direction, now, entity_id),
        )


def get_developers_by_status(status: str) -> list:
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM developers WHERE status = %s ORDER BY intent_score DESC",
            (status,),
        )
        return cur.fetchall()


def get_active_developers(min_score: float = 0.0) -> list:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM developers
            WHERE status NOT IN ('CLOSED')
              AND intent_score >= %s
            ORDER BY intent_score DESC
            """,
            (min_score,),
        )
        return cur.fetchall()


def upsert_repository(data: dict) -> None:
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO repositories (
                id, owner_id, primary_language, topics, description,
                homepage, stars, forks, open_issues, last_push,
                dependency_hash, is_primary
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s
            )
            ON CONFLICT (id) DO UPDATE SET
                primary_language = COALESCE(EXCLUDED.primary_language, repositories.primary_language),
                topics = COALESCE(EXCLUDED.topics, repositories.topics),
                description = COALESCE(EXCLUDED.description, repositories.description),
                homepage = COALESCE(EXCLUDED.homepage, repositories.homepage),
                stars = EXCLUDED.stars,
                forks = EXCLUDED.forks,
                open_issues = EXCLUDED.open_issues,
                last_push = COALESCE(EXCLUDED.last_push, repositories.last_push),
                dependency_hash = COALESCE(EXCLUDED.dependency_hash, repositories.dependency_hash),
                is_primary = EXCLUDED.is_primary
            """,
            (
                data["id"],
                data["owner_id"],
                data.get("primary_language"),
                Json(data.get("topics", [])),
                data.get("description"),
                data.get("homepage"),
                data.get("stars", 0),
                data.get("forks", 0),
                data.get("open_issues", 0),
                data.get("last_push"),
                data.get("dependency_hash"),
                bool(data.get("is_primary")),
            ),
        )


def get_repository(repo_full_name: str):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM repositories WHERE id = %s", (repo_full_name,))
        return cur.fetchone()


def repository_exists(repo_full_name: str) -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT 1 AS found FROM repositories WHERE id = %s", (repo_full_name,))
        return cur.fetchone() is not None


def get_repos_to_monitor(limit: int = 100) -> list:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT r.*, d.status AS owner_status
            FROM repositories r
            JOIN developers d ON r.owner_id = d.id
            WHERE d.status NOT IN ('CLOSED')
            ORDER BY r.last_monitored ASC NULLS FIRST
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


def update_repo_monitored(repo_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with db_cursor() as cur:
        cur.execute(
            "UPDATE repositories SET last_monitored = %s WHERE id = %s",
            (now, repo_id),
        )


def get_pending_enrichment(limit: int = 20) -> list:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM events
            WHERE enrichment_status = 'pending'
            ORDER BY occurred_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


def mark_enrichment_queued(event_id: str) -> None:
    with db_cursor() as cur:
        cur.execute("UPDATE events SET enrichment_status = 'queued' WHERE id = %s", (event_id,))


def mark_enrichment_completed(event_id: str) -> None:
    with db_cursor() as cur:
        cur.execute("UPDATE events SET enrichment_status = 'completed' WHERE id = %s", (event_id,))


def get_events_by_entity(entity_id: str, limit: int = 50) -> list:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM events
            WHERE entity_id = %s
            ORDER BY occurred_at DESC
            LIMIT %s
            """,
            (entity_id, limit),
        )
        return cur.fetchall()


def get_recent_events(event_type: str, hours_back: int = 24) -> list:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM events
            WHERE event_type = %s
              AND occurred_at >= NOW() - (%s || ' hours')::interval
            ORDER BY occurred_at DESC
            """,
            (event_type, str(hours_back)),
        )
        return cur.fetchall()


def enqueue_enrichment(
    entity_id: str,
    enrichment_type: str,
    source_event_id: str | None = None,
    priority: int = 2,
) -> str:
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO enrichment_queue
                (id, entity_id, enrichment_type, priority, source_event_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (job_id, entity_id, enrichment_type, priority, source_event_id, now),
        )
    return job_id


def get_pending_queue(limit: int = 5) -> list:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM enrichment_queue
            WHERE status = 'pending'
            ORDER BY priority ASC, created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


def update_queue_status(job_id: str, status: str, error: str | None = None) -> None:
    import json as _json
    now = datetime.now(timezone.utc).isoformat()
    field = "started_at" if status == "running" else "completed_at"
    with db_cursor() as cur:
        cur.execute(
            f"UPDATE enrichment_queue SET status = %s, {field} = %s, error = %s WHERE id = %s",
            (status, now, error, job_id),
        )
        payload = _json.dumps({
            "type": "queue_status",
            "job_id": job_id,
            "status": status,
            "ts": now,
        })
        cur.execute("SELECT pg_notify('system_logs', %s)", (payload,))


def emit_signal(
    entity_id: str,
    category: str,
    signal_type: str,
    base_score: float,
    half_life_days: float,
    evidence: str | None = None,
    source_event_id: str | None = None,
) -> str:
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    expires_at = (now_dt + timedelta(days=4 * half_life_days)).isoformat()
    signal_id = str(uuid.uuid4())

    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id FROM signals
            WHERE entity_id = %s AND category = %s AND signal_type = %s
              AND status IN ('ACTIVE', 'DECAYING')
            LIMIT 1
            """,
            (entity_id, category, signal_type),
        )
        existing = cur.fetchone()

        if existing:
            cur.execute(
                """
                UPDATE signals SET
                    base_score = %s,
                    current_score = %s,
                    half_life_days = %s,
                    detected_at = %s,
                    expires_at = %s,
                    status = 'ACTIVE',
                    evidence = COALESCE(%s, evidence),
                    source_event_id = COALESCE(%s, source_event_id)
                WHERE id = %s
                """,
                (base_score, base_score, half_life_days, now, expires_at, evidence, source_event_id, existing["id"]),
            )
            return existing["id"]

        cur.execute(
            """
            INSERT INTO signals (
                id, entity_id, category, signal_type, base_score, current_score,
                half_life_days, detected_at, expires_at, status, evidence, source_event_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'ACTIVE', %s, %s)
            """,
            (signal_id, entity_id, category, signal_type, base_score, base_score, half_life_days, now, expires_at, evidence, source_event_id),
        )
    return signal_id


def get_active_signals(entity_id: str) -> list:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM signals
            WHERE entity_id = %s AND status IN ('ACTIVE', 'DECAYING')
            ORDER BY current_score DESC
            """,
            (entity_id,),
        )
        return cur.fetchall()


def record_score_snapshot(entity_id: str, intent_score: float, maturity_score: float, status: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO score_history (entity_id, intent_score, maturity_score, status, recorded_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (entity_id, recorded_at) DO UPDATE SET
                intent_score = EXCLUDED.intent_score,
                maturity_score = EXCLUDED.maturity_score,
                status = EXCLUDED.status
            """,
            (entity_id, intent_score, maturity_score, status, now),
        )


def get_score_history(entity_id: str, days_back: int = 90) -> list:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM score_history
            WHERE entity_id = %s
              AND recorded_at >= NOW() - (%s || ' days')::interval
            ORDER BY recorded_at ASC
            """,
            (entity_id, str(days_back)),
        )
        return cur.fetchall()


_PREVIEW_MAX = 3000  # chars stored per prompt/response


def log_enrichment_cost(
    entity_id: str,
    enrichment_type: str,
    llm_calls: int,
    input_tokens: int,
    output_tokens: int,
    provider: str = "anthropic",
    prompt: str | None = None,
    response: str | None = None,
) -> None:
    import json as _json
    cost = 0.0 if provider == "ollama" else (
        (input_tokens / 1000 * 0.00025) + (output_tokens / 1000 * 0.00125)
    )
    now = datetime.now(timezone.utc).isoformat()
    prompt_preview = (prompt or "")[:_PREVIEW_MAX] or None
    response_preview = (response or "")[:_PREVIEW_MAX] or None
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO enrichment_costs (
                entity_id, enrichment_type, llm_calls, input_tokens, output_tokens,
                estimated_cost, provider, prompt_preview, response_preview
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (entity_id, enrichment_type, llm_calls, input_tokens, output_tokens,
             cost, provider, prompt_preview, response_preview),
        )
        payload = _json.dumps({
            "type": "llm_cost",
            "entity_id": entity_id,
            "enrichment_type": enrichment_type,
            "llm_calls": llm_calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost": cost,
            "provider": provider,
            "ts": now,
        })
        cur.execute("SELECT pg_notify('system_logs', %s)", (payload,))


def get_total_cost() -> float:
    with db_cursor() as cur:
        cur.execute("SELECT COALESCE(SUM(estimated_cost), 0) AS total FROM enrichment_costs")
        row = cur.fetchone()
        return float(row["total"]) if row else 0.0


def get_repos_by_owner(owner_id: str) -> list:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM repositories
            WHERE LOWER(owner_id) = LOWER(%s)
            ORDER BY stars DESC, last_push DESC
            """,
            (owner_id,),
        )
        return cur.fetchall()


def get_primary_repo_by_owner(owner_id: str):
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM repositories
            WHERE LOWER(owner_id) = LOWER(%s)
            ORDER BY is_primary DESC, stars DESC, last_push DESC
            LIMIT 1
            """,
            (owner_id,),
        )
        return cur.fetchone()


def update_repo_enriched(
    repo_id: str,
    stack_snapshot,
    has_ci: bool,
    has_docker: bool,
    has_tests: bool,
    has_payments: bool,
    has_auth: bool,
    has_monitoring: bool,
    maturity_score: float,
    is_primary: bool = False,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE repositories SET
                stack_snapshot = %s,
                has_ci = %s,
                has_docker = %s,
                has_tests = %s,
                has_payments = %s,
                has_auth = %s,
                has_monitoring = %s,
                maturity_score = %s,
                is_primary = %s,
                last_enriched = %s
            WHERE id = %s
            """,
            (
                _json_param(stack_snapshot),
                has_ci,
                has_docker,
                has_tests,
                has_payments,
                has_auth,
                has_monitoring,
                maturity_score,
                is_primary,
                now,
                repo_id,
            ),
        )


def update_developer_enriched(
    developer_id: str,
    archetype: str | None,
    arch_confidence: float | None,
    maturity_score: float,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE developers SET
                archetype = COALESCE(%s, archetype),
                arch_confidence = COALESCE(%s, arch_confidence),
                maturity_score = %s,
                last_enriched = %s,
                enrichment_ver = enrichment_ver + 1,
                updated_at = %s
            WHERE id = %s
            """,
            (archetype, arch_confidence, maturity_score, now, now, developer_id),
        )
