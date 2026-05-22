"""api/routers/logs.py — Observability endpoints for LLM calls, enrichment jobs, and events."""
from __future__ import annotations

import asyncio
import json
import select
from typing import Optional

import structlog
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from db import db_cursor, get_pool, release_connection

log = structlog.get_logger().bind(module="api.routers.logs")
router = APIRouter(prefix="/api/logs", tags=["logs"])


# ── Helpers ────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    """Convert a psycopg2 RealDictRow to a plain dict, serialising datetimes."""
    out = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


# ── GET /api/logs/llm ──────────────────────────────────────────────────────

@router.get("/llm")
def get_llm_logs(
    limit: int = Query(50, ge=1, le=500),
    enrichment_type: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
) -> dict:
    clauses = []
    params: list = []

    if enrichment_type:
        clauses.append("enrichment_type = %s")
        params.append(enrichment_type)
    if provider:
        clauses.append("provider = %s")
        params.append(provider)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, entity_id, enrichment_type, provider,
                   llm_calls, input_tokens, output_tokens, estimated_cost, created_at
            FROM enrichment_costs
            {where}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()

        cur.execute(
            f"""
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(llm_calls), 0)      AS total_calls,
                   COALESCE(SUM(input_tokens), 0)   AS total_input_tokens,
                   COALESCE(SUM(output_tokens), 0)  AS total_output_tokens,
                   COALESCE(SUM(estimated_cost), 0) AS total_cost
            FROM enrichment_costs
            {where}
            """,
            params[:-1],  # exclude limit
        )
        totals = cur.fetchone()

    return {
        "rows": [_row_to_dict(r) for r in rows],
        "totals": _row_to_dict(totals) if totals else {},
    }


# ── GET /api/logs/llm/{id} ────────────────────────────────────────────────

@router.get("/llm/{log_id}")
def get_llm_log_detail(log_id: int) -> dict:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, entity_id, enrichment_type, provider,
                   llm_calls, input_tokens, output_tokens, estimated_cost,
                   prompt_preview, response_preview, created_at
            FROM enrichment_costs
            WHERE id = %s
            """,
            (log_id,),
        )
        row = cur.fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Log not found")
    return _row_to_dict(row)


# ── GET /api/logs/enrichment ───────────────────────────────────────────────

@router.get("/enrichment")
def get_enrichment_logs(
    limit: int = Query(50, ge=1, le=500),
    status: Optional[str] = Query(None),
) -> dict:
    valid_statuses = {"pending", "running", "completed", "failed"}
    clauses = []
    params: list = []

    if status and status in valid_statuses:
        clauses.append("status = %s")
        params.append(status)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, entity_id, enrichment_type, priority, status, error,
                   created_at, started_at, completed_at
            FROM enrichment_queue
            {where}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()

    result = []
    for row in rows:
        d = _row_to_dict(row)
        if d.get("completed_at") and d.get("started_at"):
            from datetime import datetime, timezone
            try:
                completed = datetime.fromisoformat(d["completed_at"])
                started = datetime.fromisoformat(d["started_at"])
                d["duration_seconds"] = round((completed - started).total_seconds(), 2)
            except Exception:
                d["duration_seconds"] = None
        else:
            d["duration_seconds"] = None
        result.append(d)

    return {"rows": result}


# ── GET /api/logs/events ───────────────────────────────────────────────────

@router.get("/events")
def get_event_logs(
    limit: int = Query(100, ge=1, le=1000),
    event_type: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
) -> dict:
    clauses = []
    params: list = []

    if event_type:
        clauses.append("event_type ILIKE %s")
        params.append(f"%{event_type}%")
    if entity_id:
        clauses.append("entity_id = %s")
        params.append(entity_id)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, event_type, event_category, occurred_at, source,
                   entity_id, entity_type, confidence,
                   payload->>'title' AS payload_title
            FROM events
            {where}
            ORDER BY occurred_at DESC
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()

    return {"rows": [_row_to_dict(r) for r in rows]}


# ── GET /api/logs/stream (SSE) ─────────────────────────────────────────────

def _blocking_wait(conn, timeout: float) -> bool:
    ready, _, _ = select.select([conn], [], [], timeout)
    return bool(ready)


async def _log_stream():
    loop = asyncio.get_event_loop()
    raw_conn = get_pool().getconn()
    raw_conn.set_isolation_level(0)  # autocommit for LISTEN
    cur = raw_conn.cursor()
    cur.execute("LISTEN system_logs;")
    log.info("logs.sse.started", channel="system_logs")

    try:
        while True:
            ready = await loop.run_in_executor(None, _blocking_wait, raw_conn, 15.0)
            if not ready:
                yield ": keepalive\n\n"
                continue

            raw_conn.poll()
            while raw_conn.notifies:
                notify = raw_conn.notifies.pop(0)
                try:
                    body = json.loads(notify.payload)
                except json.JSONDecodeError:
                    body = {"type": "raw", "payload": notify.payload}
                yield f"data: {json.dumps(body, ensure_ascii=True)}\n\n"
    finally:
        cur.close()
        release_connection(raw_conn)
        log.info("logs.sse.stopped", channel="system_logs")


@router.get("/stream")
async def stream_logs() -> StreamingResponse:
    return StreamingResponse(_log_stream(), media_type="text/event-stream")
