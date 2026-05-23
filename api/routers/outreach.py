from __future__ import annotations

import re
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
from fine_tuning.capture import capture_example
from intelligence.draft_generator import (
    _load_draft_model,
    _load_outreach_context,
    build_draft_prompt,
    generate_outreach_draft,
)

log = structlog.get_logger().bind(module="api.routers.outreach")
router = APIRouter(prefix="/api/outreach", tags=["outreach"])
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output" / "drafts"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _draft_path(handle: str) -> Path | None:
    if not OUTPUT_DIR.exists():
        return None
    candidates = sorted(OUTPUT_DIR.glob(f"{handle}_*.md"), reverse=True)
    return candidates[0] if candidates else None


_OPERATOR_SECTIONS = {"Acciones del operador", "Notas del operador", "Intro"}


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

    editable = [
        s for s in sections
        if s["content"] and s["title"] not in _OPERATOR_SECTIONS
    ]
    return {"path": str(path), "content": content, "sections": editable}


class DraftApprovalRequest(BaseModel):
    approved_output: str = Field(min_length=1)
    example_id: str | None = None
    variant_label: str | None = None  # "A", "B", etc.
    source: str = Field(default="operator_edit", pattern="^(ollama|operator_edit|chatgpt|claude|other)$")


class ReplyRequest(BaseModel):
    outcome: str = Field(pattern="^(positive|negative|neutral)$")
    channel: str = Field(default="unknown", pattern="^(LinkedIn|Twitter|Email|GitHub|unknown)$")
    notes: str = Field(min_length=1)


@router.get("/contacted")
def outreach_contacted(limit: int = 50) -> dict[str, Any]:
    """Developers que ya recibieron outreach (outreach_status != 'none')."""
    limit = max(1, min(limit, 200))
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT d.id, d.name, d.status, d.intent_score, d.maturity_score,
                   d.archetype, d.outreach_status, d.last_enriched, d.last_active,
                   d.email, d.twitter, d.github_url, d.avatar_url, d.location,
                   m.summary AS narrative
            FROM developers d
            LEFT JOIN LATERAL (
                SELECT summary
                FROM entity_memory
                WHERE entity_id = d.id AND status = 'active'
                ORDER BY version DESC
                LIMIT 1
            ) m ON TRUE
            WHERE d.outreach_status IN ('drafted', 'replied', 'sent')
               OR d.status IN ('OUTREACHED', 'ENGAGED', 'CLOSED')
            ORDER BY d.last_active DESC NULLS LAST
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
                "archetype": row.get("archetype"),
                "outreach_status": row["outreach_status"],
                "last_active": row["last_active"].isoformat() if row.get("last_active") else None,
                "narrative": row.get("narrative"),
                "email": row.get("email"),
                "twitter": row.get("twitter"),
                "github_url": row.get("github_url"),
                "avatar_url": row.get("avatar_url"),
                "location": row.get("location"),
            }
            for row in rows
        ]
    }


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
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    payload = _parse_draft(path)
    payload["generated"] = generated
    return payload


@router.get("/{handle}/draft/prompt")
def get_draft_prompt(handle: str) -> dict[str, Any]:
    """Return the system + user prompt used to generate this developer's draft.
    Useful for pasting into ChatGPT, Claude.ai, or any other LLM manually.
    """
    developer = get_developer(handle)
    if developer is None:
        raise HTTPException(status_code=404, detail=f"Developer no encontrado: {handle}")

    memory = get_latest_memory(handle)
    if not memory:
        raise HTTPException(status_code=404, detail=f"Sin memoria activa para {handle}")

    outreach_context = _load_outreach_context(memory)

    try:
        system_prompt, user_prompt = build_draft_prompt(handle, memory, outreach_context)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    combined = (
        f"SYSTEM PROMPT\n{'=' * 60}\n{system_prompt}\n\n"
        f"{'=' * 60}\nUSER INPUT\n{'=' * 60}\n{user_prompt}"
    )
    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "combined": combined,
    }


@router.post("/{handle}/draft/regenerate")
def regenerate_draft(handle: str) -> dict[str, Any]:
    if get_developer(handle) is None:
        raise HTTPException(status_code=404, detail=f"Developer no encontrado: {handle}")
    # Delete existing draft files so generator creates a fresh one
    if OUTPUT_DIR.exists():
        for old in OUTPUT_DIR.glob(f"{handle}_*.md"):
            old.unlink()
    try:
        path = Path(generate_outreach_draft(handle))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    payload = _parse_draft(path)
    payload["generated"] = True
    return payload


def _variant_label_from_title(title: str) -> str | None:
    """Extract label letter ('A', 'B'…) from section title like 'Variante 1 — A'."""
    m = re.search(r"—\s*([A-Z])$", title)
    return m.group(1) if m else None


@router.post("/{handle}/draft/approve")
def approve_draft(handle: str, payload: DraftApprovalRequest) -> dict[str, Any]:
    if get_developer(handle) is None:
        raise HTTPException(status_code=404, detail=f"Developer no encontrado: {handle}")

    # ── 1. Extract model_output from the draft file ──────────────────────────
    path = _draft_path(handle)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail=f"No hay draft para {handle}. Genera o regenera el draft primero.",
        )
    draft_data = _parse_draft(path)

    model_output: str | None = None
    for section in draft_data["sections"]:
        label = _variant_label_from_title(section["title"])
        if payload.variant_label:
            if label == payload.variant_label:
                model_output = section["content"]
                break
        elif re.search(r"Variante\s+\d", section["title"]):
            # No variant_label specified — use the first variant section found
            model_output = section["content"]
            break

    if not model_output:
        raise HTTPException(
            status_code=404,
            detail=f"Variante '{payload.variant_label}' no encontrada en el draft de {handle}.",
        )

    # ── 2. Reconstruct the prompt for fine-tuning ────────────────────────────
    memory = get_latest_memory(handle)
    system_prompt = ""
    user_input = ""
    if memory:
        try:
            outreach_context = _load_outreach_context(memory)
            system_prompt, user_input = build_draft_prompt(handle, memory, outreach_context)
        except Exception:
            pass  # Missing prompt is recoverable — the example is still useful

    draft_model, _ = _load_draft_model()

    # ── 3. INSERT the approved example ───────────────────────────────────────
    try:
        example_id = capture_example(
            task_type="draft",
            system_prompt=system_prompt,
            user_input=user_input,
            model_output=model_output,
            approved_output=payload.approved_output,
            entity_id=handle,
            provider="ollama",
            model_used=draft_model,
            variant_label=payload.variant_label,
            source=payload.source,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error guardando ejemplo: {exc}") from exc

    update_developer_profile_fields(handle, outreach_status="drafted", last_active=_now_iso())
    return {"ok": True, "example_id": example_id, "entity_id": handle, "variant_label": payload.variant_label}


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
        {"outcome": payload.outcome, "channel": payload.channel, "notes": payload.notes},
        source="api",
        source_url=f"api://outreach/{handle}/reply/{_now_iso()}",
    )
    memory_version = update_memory_on_event(
        handle,
        "outreach.reply_received",
        {"outcome": payload.outcome, "channel": payload.channel, "notes": payload.notes},
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


@router.get("/{handle}/thread")
def get_thread(handle: str) -> dict[str, Any]:
    """Timeline de mensajes enviados y respuestas para un developer."""
    if get_developer(handle) is None:
        raise HTTPException(status_code=404, detail=f"Developer no encontrado: {handle}")

    thread: list[dict] = []

    # Approved drafts = messages sent
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT approved_output, approved_at, variant_label, source, model_output
            FROM fine_tuning_examples
            WHERE entity_id = %s AND task_type = 'draft'
              AND approved_at IS NOT NULL
              AND approved_output IS NOT NULL
              AND LENGTH(approved_output) > 5
            ORDER BY approved_at ASC
            """,
            (handle,),
        )
        for row in cur.fetchall():
            thread.append({
                "type": "sent",
                "direction": "out",
                "content": row["approved_output"],
                "occurred_at": row["approved_at"].isoformat() if row["approved_at"] else None,
                "meta": {
                    "variant_label": row.get("variant_label"),
                    "source": row.get("source"),
                    "was_edited": row["model_output"] != row["approved_output"],
                },
            })

    # Manually registered sends (operator sent message via external channel)
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT payload, occurred_at
            FROM events
            WHERE entity_id = %s
              AND event_type = 'outreach.reply_received'
            ORDER BY occurred_at ASC
            """,
            (handle,),
        )
        for row in cur.fetchall():
            p = row["payload"] or {}
            thread.append({
                "type": "sent_manual",
                "direction": "out",
                "content": p.get("notes", ""),
                "occurred_at": row["occurred_at"].isoformat() if row["occurred_at"] else None,
                "meta": {
                    "outcome": p.get("outcome"),
                    "channel": p.get("channel"),
                },
            })

    # Sort by occurred_at
    thread.sort(key=lambda x: x["occurred_at"] or "")

    return {"entity_id": handle, "thread": thread}

