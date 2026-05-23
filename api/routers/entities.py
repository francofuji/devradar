from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db.events import emit_event
from db.memory_queries import get_latest_memory
from db.queries import (
    enqueue_enrichment,
    get_active_signals,
    get_developer,
    get_events_by_entity,
    get_primary_repo_by_owner,
    get_repos_by_owner,
    get_score_history,
    update_developer_profile_fields,
)
from enrichment.memory_writer import update_memory_on_event

log = structlog.get_logger().bind(module="api.routers.entities")
router = APIRouter(prefix="/api/entities", tags=["entities"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _developer_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row.get("name"),
        "status": row.get("status"),
        "intent_score": float(row.get("intent_score") or 0.0),
        "maturity_score": float(row.get("maturity_score") or 0.0),
        "trajectory_7d": float(row.get("trajectory_7d") or 0.0),
        "trajectory_30d": float(row.get("trajectory_30d") or 0.0),
        "trajectory_direction": row.get("trajectory_direction"),
        "archetype": row.get("archetype"),
        "arch_confidence": row.get("arch_confidence"),
        "outreach_status": row.get("outreach_status"),
        "github_url": row.get("github_url"),
        "twitter": row.get("twitter"),
        "personal_site": row.get("personal_site"),
        "linkedin_manual": row.get("linkedin_manual"),
        "email": row.get("email"),
        "avatar_url": row.get("avatar_url"),
        "location": row.get("location"),
        "bio": row.get("bio"),
        "first_seen": row.get("first_seen"),
        "last_active": row.get("last_active"),
        "last_enriched": row.get("last_enriched"),
        "updated_at": row.get("updated_at"),
    }


class NoteRequest(BaseModel):
    text: str = Field(min_length=1)


class LinkedInRequest(BaseModel):
    title: str
    company: str
    team_size: str | None = None
    notes: str | None = ""


class DisqualifyRequest(BaseModel):
    reason: str = Field(min_length=1)


class EnrichRequest(BaseModel):
    enrichment_type: str = "full"
    source_event_id: str | None = None


@router.get("")
def list_entities(
    status: str | None = None,
    archetype: str | None = None,
    min_score: float = 0.0,
    trajectory: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    from db import db_cursor

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    where_clauses = ["intent_score >= %s"]
    params: list[Any] = [min_score]

    if status:
        where_clauses.append("status = %s")
        params.append(status)
    if archetype:
        where_clauses.append("archetype = %s")
        params.append(archetype)
    if trajectory == "up":
        where_clauses.append("COALESCE(trajectory_7d, 0) > 0")
    elif trajectory == "down":
        where_clauses.append("COALESCE(trajectory_7d, 0) < 0")
    elif trajectory == "flat":
        where_clauses.append("COALESCE(trajectory_7d, 0) = 0")

    params.extend([limit, offset])

    sql = f"""
        SELECT d.*,
               m.summary AS narrative,
               m.memory->'specific_hooks' AS specific_hooks
        FROM developers d
        LEFT JOIN LATERAL (
            SELECT summary, memory
            FROM entity_memory
            WHERE entity_id = d.id AND status = 'active'
            ORDER BY version DESC
            LIMIT 1
        ) m ON TRUE
        WHERE {' AND '.join(where_clauses)}
        ORDER BY d.intent_score DESC, d.last_enriched DESC NULLS LAST, d.id ASC
        LIMIT %s OFFSET %s
    """

    with db_cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    items = []
    for row in rows:
        payload = _developer_payload(row)
        payload["narrative"] = row.get("narrative")
        payload["specific_hooks"] = row.get("specific_hooks") or []
        items.append(payload)

    return {"items": items, "limit": limit, "offset": offset, "count": len(items)}


@router.get("/{handle}")
def get_entity_profile(handle: str) -> dict[str, Any]:
    developer = get_developer(handle)
    if developer is None:
        raise HTTPException(status_code=404, detail=f"Developer no encontrado: {handle}")

    return {
        "developer": _developer_payload(developer),
        "memory": get_latest_memory(handle),
        "repositories": [dict(row) for row in get_repos_by_owner(handle)],
        "primary_repository": (
            dict(primary_repo) if (primary_repo := get_primary_repo_by_owner(handle)) else None
        ),
        "signals": [dict(row) for row in get_active_signals(handle)],
        "score_history": [dict(row) for row in get_score_history(handle)],
        "recent_events": [dict(row) for row in get_events_by_entity(handle, limit=25)],
    }


@router.post("/{handle}/note")
def add_note(handle: str, payload: NoteRequest) -> dict[str, Any]:
    if get_developer(handle) is None:
        raise HTTPException(status_code=404, detail=f"Developer no encontrado: {handle}")

    event_id = emit_event(
        "developer.note_added",
        handle,
        "developer",
        {"text": payload.text},
        source="api",
        source_url=f"api://entities/{handle}/note/{_now_iso()}",
    )
    version = update_memory_on_event(handle, "developer.note_added", {"text": payload.text})
    return {"ok": True, "event_id": event_id, "memory_version": version}


@router.post("/{handle}/linkedin")
def update_linkedin(handle: str, payload: LinkedInRequest) -> dict[str, Any]:
    if get_developer(handle) is None:
        raise HTTPException(status_code=404, detail=f"Developer no encontrado: {handle}")

    data = payload.model_dump()
    data["updated_at"] = _now_iso()
    update_developer_profile_fields(handle, linkedin_manual=data, last_active=data["updated_at"])
    return {"ok": True, "entity_id": handle, "linkedin_manual": data}


@router.post("/{handle}/disqualify")
def disqualify_entity(handle: str, payload: DisqualifyRequest) -> dict[str, Any]:
    if get_developer(handle) is None:
        raise HTTPException(status_code=404, detail=f"Developer no encontrado: {handle}")

    update_developer_profile_fields(
        handle,
        outreach_status="disqualified",
        status="CLOSED",
        last_active=_now_iso(),
    )
    event_id = emit_event(
        "developer.disqualified",
        handle,
        "developer",
        {"reason": payload.reason},
        source="api",
        source_url=f"api://entities/{handle}/disqualify/{_now_iso()}",
    )
    version = update_memory_on_event(handle, "developer.disqualified", {"reason": payload.reason})
    return {"ok": True, "event_id": event_id, "memory_version": version}


@router.post("/{handle}/enrich")
def enqueue_entity_enrichment(handle: str, payload: EnrichRequest) -> dict[str, Any]:
    if get_developer(handle) is None:
        raise HTTPException(status_code=404, detail=f"Developer no encontrado: {handle}")

    job_id = enqueue_enrichment(
        entity_id=handle,
        enrichment_type=payload.enrichment_type,
        source_event_id=payload.source_event_id,
        priority=1,
    )
    log.info("entities.enrichment_enqueued", entity_id=handle, job_id=job_id, enrichment_type=payload.enrichment_type)
    return {"ok": True, "job_id": job_id, "entity_id": handle, "enrichment_type": payload.enrichment_type}

