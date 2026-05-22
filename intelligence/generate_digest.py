"""
E8 — Daily digest generator.
"""
from __future__ import annotations

import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
sys.path.insert(0, _project_root)

from datetime import datetime, timedelta, timezone
from pathlib import Path

from db import get_connection


def _as_dict(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    return {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _hours_ago(dt_value: str | None) -> float | None:
    parsed = _parse_iso(dt_value)
    if not parsed:
        return None
    return (_utc_now() - parsed).total_seconds() / 3600.0


def _fetch_recent_developers(hours: int = 24) -> list[dict]:
    cutoff = (_utc_now() - timedelta(hours=hours)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, status, intent_score, maturity_score, trajectory_direction, first_seen
            FROM developers
            WHERE first_seen >= ?
            ORDER BY first_seen DESC
            LIMIT 20
            """,
            (cutoff,),
        ).fetchall()
    return [dict(row) for row in rows]


def _fetch_recent_transitions(hours: int = 24) -> list[dict]:
    cutoff = (_utc_now() - timedelta(hours=hours)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT entity_id, occurred_at, payload
            FROM events
            WHERE event_type = 'enrichment.state_transition'
              AND occurred_at >= ?
            ORDER BY occurred_at DESC
            LIMIT 20
            """,
            (cutoff,),
        ).fetchall()
    result: list[dict] = []
    for row in rows:
        payload = _as_dict(row["payload"])
        result.append({
            "entity_id": row["entity_id"],
            "occurred_at": row["occurred_at"],
            "from_status": payload.get("from_status"),
            "to_status": payload.get("to_status"),
            "reason": payload.get("reason"),
            "intent_score": payload.get("intent_score"),
            "maturity_tier": payload.get("maturity_tier"),
        })
    return result


def _fetch_intent_alert_candidates() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, status, intent_score, maturity_score, trajectory_7d, trajectory_direction
            FROM developers
            WHERE status IN ('WARM', 'QUALIFIED')
            ORDER BY intent_score DESC, trajectory_7d DESC
            LIMIT 15
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _fetch_recent_stack_activity(hours: int = 24) -> list[dict]:
    cutoff = (_utc_now() - timedelta(hours=hours)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT r.id, r.owner_id, r.last_enriched, r.stack_snapshot, d.status
            FROM repositories r
            JOIN developers d ON d.id = r.owner_id
            WHERE r.last_enriched >= ?
            ORDER BY r.last_enriched DESC
            LIMIT 20
            """,
            (cutoff,),
        ).fetchall()
    result: list[dict] = []
    for row in rows:
        snapshot = _as_dict(row["stack_snapshot"])
        runtime_deps = snapshot.get("runtime_deps", {})
        signals = []
        for label in ("ai_llm", "browser_automation", "payments", "queues"):
            packages = runtime_deps.get(label) or []
            if packages:
                signals.append(f"{label}: {', '.join(packages[:3])}")
        result.append({
            "repo_id": row["id"],
            "owner_id": row["owner_id"],
            "status": row["status"],
            "last_enriched": row["last_enriched"],
            "signals": signals,
        })
    return result


def _fetch_recent_reconfigurations(hours: int = 48) -> list[dict]:
    cutoff = (_utc_now() - timedelta(hours=hours)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT entity_id, occurred_at, payload
            FROM events
            WHERE event_type = 'developer.architectural_reconfiguration'
              AND occurred_at >= ?
            ORDER BY occurred_at DESC
            LIMIT 20
            """,
            (cutoff,),
        ).fetchall()
    result = []
    for row in rows:
        payload = _as_dict(row["payload"])
        result.append({
            "entity_id": row["entity_id"],
            "occurred_at": row["occurred_at"],
            "distinct_count": payload.get("distinct_count"),
            "distinct_event_types": payload.get("distinct_event_types", []),
        })
    return result


def _fetch_total_stats() -> dict:
    with get_connection() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM developers WHERE status NOT IN ('CLOSED')"
        ).fetchone()["c"]
        warm = conn.execute(
            "SELECT COUNT(*) AS c FROM developers WHERE status = 'WARM'"
        ).fetchone()["c"]
        qualified = conn.execute(
            "SELECT COUNT(*) AS c FROM developers WHERE status = 'QUALIFIED'"
        ).fetchone()["c"]
        llm_cost = conn.execute(
            """
            SELECT COALESCE(SUM(estimated_cost), 0) AS total
            FROM enrichment_costs
            WHERE created_at >= ?
            """,
            (_utc_now().date().isoformat(),),
        ).fetchone()["total"]
    return {
        "total": total,
        "warm": warm,
        "qualified": qualified,
        "llm_cost": float(llm_cost or 0.0),
    }


def _find_triggering_source_url(entity_id: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT source_url
            FROM events
            WHERE entity_id = ?
              AND source_url IS NOT NULL
              AND source_url NOT LIKE 'memory://%'
              AND source_url NOT LIKE 'transition://%'
              AND source_url NOT LIKE 'intent-threshold://%'
              AND source_url NOT LIKE 'reconfiguration://%'
            ORDER BY occurred_at DESC
            LIMIT 1
            """,
            (entity_id,),
        ).fetchone()
    return row["source_url"] if row else None


def _render_section(title: str, lines: list[str]) -> str:
    content = lines if lines else ["Sin novedades"]
    return "\n".join([f"## {title}", *content, ""])


def generate_daily_digest(date: str | None = None) -> str:
    digest_date = date or _utc_now().strftime("%Y-%m-%d")
    recent_developers = _fetch_recent_developers(24)
    transitions = _fetch_recent_transitions(24)
    alert_candidates = _fetch_intent_alert_candidates()
    stack_activity = _fetch_recent_stack_activity(24)
    reconfigs = _fetch_recent_reconfigurations(48)
    stats = _fetch_total_stats()

    output_dir = Path(_project_root) / "output" / "daily"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{digest_date}.md"

    new_entities_lines = [
        f"- `{row['id']}` — status={row['status']} maturity={row['maturity_score']} intent={row['intent_score']}"
        for row in recent_developers
    ]

    transition_lines = [
        f"- `{row['entity_id']}` — {row['from_status']} → {row['to_status']} ({row['reason']})"
        for row in transitions
    ]

    alert_lines: list[str] = []
    for row in alert_candidates:
        source_url = _find_triggering_source_url(row["id"])
        line = (
            f"- `{row['id']}` — status={row['status']} intent={row['intent_score']} "
            f"trajectory={row['trajectory_direction']}"
        )
        if source_url:
            line += f" | source: {source_url}"
        alert_lines.append(line)

    stack_lines = []
    for row in stack_activity:
        signal_text = "; ".join(row["signals"]) if row["signals"] else "stack snapshot refreshed"
        stack_lines.append(
            f"- `{row['repo_id']}` (owner `{row['owner_id']}`) — {signal_text}"
        )

    notable_lines = [
        f"- `{row['entity_id']}` — {row['distinct_count']} event types in 48h ({', '.join(row['distinct_event_types'][:4])})"
        for row in reconfigs
    ]

    if not notable_lines and transitions:
        top = transitions[0]
        source_url = _find_triggering_source_url(top["entity_id"])
        fallback = f"- `{top['entity_id']}` — latest transition {top['from_status']} → {top['to_status']}"
        if source_url:
            fallback += f" | trigger source: {source_url}"
        notable_lines.append(fallback)

    content = "\n".join([
        f"# Daily Digest — {digest_date}",
        "",
        _render_section("Nuevas entidades detectadas", new_entities_lines),
        _render_section("Transiciones de estado", transition_lines),
        _render_section("Alertas de intención", alert_lines),
        _render_section("Cambios de stack observados", stack_lines),
        _render_section("Actividad notable", notable_lines),
        "## Stats",
        f"- Total entities monitoreadas: {stats['total']}",
        f"- WARM: {stats['warm']}",
        f"- QUALIFIED: {stats['qualified']}",
        f"- Costo LLM del día: ${stats['llm_cost']:.6f}",
        "",
    ])

    path.write_text(content, encoding="utf-8")
    return str(path)


def main() -> None:
    path = generate_daily_digest()
    print(path)


if __name__ == "__main__":
    main()
