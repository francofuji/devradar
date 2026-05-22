from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db import db_cursor
from db.events import emit_event
from db.memory_queries import get_latest_memory
from db.queries import get_developer, update_developer_profile_fields
from enrichment.memory_writer import update_memory_on_event
from intelligence.draft_generator import generate_outreach_draft

log = structlog.get_logger().bind(module="api.routers.outreach")
router = APIRouter(prefix="/api/outreach", tags=["outreach"])
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output" / "drafts"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _edit_distance(model_output: str, approved_output: str) -> float:
    from difflib import SequenceMatcher

    similarity = SequenceMatcher(None, _normalize_text(model_output), _normalize_text(approved_output)).ratio()
    return round(1.0 - similarity, 4)


def _quality_score(model_output: str, approved_output: str) -> float:
    from difflib import SequenceMatcher

    normalized_approved = _normalize_text(approved_output)
    if len(normalized_approved) < 8:
        return 0.0
    similarity = SequenceMatcher(None, _normalize_text(model_output), normalized_approved).ratio()
    return round(similarity, 4)


def _draft_path(handle: str) -> Path | None:
    if not OUTPUT_DIR.exists():
        return None
    candidates = sorted(OUTPUT_DIR.glob(f"{handle}_*.md"), reverse=True)
    return candidates[0] if candidates else None


def _parse_draft(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    sections = []
    current_title = "Intro"
    current_lines: list[str] = []

    for line in content.splitlines():
        if line.startswith("## "):
            sections.append({"title": current_title, "content": "\n".join(current_lines).strip()})
            current_title = line[3:].strip()
            current_lines = []
            continue
        current_lines.append(line)
    sections.append({"title": current_title, "content": "\n".join(current_lines).strip()})
    return {"path": str(path), "content": content, "sections": [s for s in sections if s["content"]]}


class DraftApprovalRequest(BaseModel):
    approved_output: str = Field(min_length=1)
    example_id: str | None = None


class ReplyRequest(BaseModel):
    outcome: str = Field(pattern="^(positive|negative|neutral)$")
    notes: str = Field(min_length=1)


@router.get("/queue")
def outreach_queue(limit: int = 25) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT d.id, d.name, d.status, d.intent_score, d.maturity_score,
                   d.archetype, d.outreach_status, d.last_enriched, d.last_active,
                   m.summary AS narrative,
                   m.memory->'specific_hooks' AS specific_hooks,
                   m.memory->'pain_signals' AS pain_signals
            FROM developers d
            LEFT JOIN LATERAL (
                SELECT summary, memory
                FROM entity_memory
                WHERE entity_id = d.id AND status = 'active'
                ORDER BY version DESC
                LIMIT 1
            ) m ON TRUE
            WHERE d.status = 'QUALIFIED'
              AND d.outreach_status = 'none'
            ORDER BY d.intent_score DESC, d.last_enriched DESC NULLS LAST
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    return {
        "items": [
            {
                "id": row["id"],
                "name": row.get("name"),
                "status": row["status"],
                "intent_score": float(row["intent_score"] or 0.0),
                "maturity_score": float(row["maturity_score"] or 0.0),
                "archetype": row.get("archetype"),
                "outreach_status": row["outreach_status"],
                "last_enriched": row["last_enriched"].isoformat() if row.get("last_enriched") else None,
                "last_active": row["last_active"].isoformat() if row.get("last_active") else None,
                "narrative": row.get("narrative"),
                "specific_hooks": row.get("specific_hooks") or [],
                "pain_signals": row.get("pain_signals") or [],
            }
            for row in rows
        ]
    }


@router.get("/{handle}/draft")
def get_or_generate_draft(handle: str) -> dict[str, Any]:
    if get_developer(handle) is None:
        raise HTTPException(status_code=404, detail=f"Developer no encontrado: {handle}")

    path = _draft_path(handle)
    generated = False
    if path is None:
        try:
            path = Path(generate_outreach_draft(handle))
            generated = True
            update_developer_profile_fields(handle, outreach_status="drafted", last_active=_now_iso())
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    payload = _parse_draft(path)
    payload["generated"] = generated
    return payload


@router.post("/{handle}/draft/approve")
def approve_draft(handle: str, payload: DraftApprovalRequest) -> dict[str, Any]:
    if get_developer(handle) is None:
        raise HTTPException(status_code=404, detail=f"Developer no encontrado: {handle}")

    with db_cursor() as cur:
        if payload.example_id:
            cur.execute(
                """
                SELECT id, model_output
                FROM fine_tuning_examples
                WHERE id = %s AND entity_id = %s AND task_type = 'draft'
                """,
                (payload.example_id, handle),
            )
        else:
            cur.execute(
                """
                SELECT id, model_output
                FROM fine_tuning_examples
                WHERE entity_id = %s AND task_type = 'draft'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (handle,),
            )
        row = cur.fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail=f"No hay ejemplo draft para {handle}")

        approved_output = _normalize_text(payload.approved_output)
        model_output = _normalize_text(row["model_output"])
        cur.execute(
            """
            UPDATE fine_tuning_examples
            SET approved_output = %s,
                was_edited = %s,
                edit_distance = %s,
                quality_score = %s,
                approved_at = NOW(),
                outcome = 'approved'
            WHERE id = %s
            """,
            (
                approved_output,
                model_output != approved_output,
                _edit_distance(model_output, approved_output),
                _quality_score(model_output, approved_output),
                row["id"],
            ),
        )

    update_developer_profile_fields(handle, outreach_status="drafted", last_active=_now_iso())
    return {"ok": True, "example_id": row["id"], "entity_id": handle}


@router.post("/{handle}/reply")
def register_reply(handle: str, payload: ReplyRequest) -> dict[str, Any]:
    if get_developer(handle) is None:
        raise HTTPException(status_code=404, detail=f"Developer no encontrado: {handle}")

    new_status = "ENGAGED" if payload.outcome == "positive" else None
    update_developer_profile_fields(
        handle,
        outreach_status="replied",
        status=new_status,
        last_active=_now_iso(),
    )
    event_id = emit_event(
        "outreach.reply_received",
        handle,
        "developer",
        {"outcome": payload.outcome, "notes": payload.notes},
        source="api",
        source_url=f"api://outreach/{handle}/reply/{_now_iso()}",
    )
    memory_version = update_memory_on_event(
        handle,
        "outreach.reply_received",
        {"outcome": payload.outcome, "notes": payload.notes},
    )

    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE fine_tuning_examples
            SET outcome = %s
            WHERE id = (
                SELECT id
                FROM fine_tuning_examples
                WHERE entity_id = %s AND task_type = 'draft'
                ORDER BY created_at DESC
                LIMIT 1
            )
            """,
            (payload.outcome, handle),
        )

    return {
        "ok": True,
        "event_id": event_id,
        "memory_version": memory_version,
        "entity_id": handle,
        "outcome": payload.outcome,
    }

