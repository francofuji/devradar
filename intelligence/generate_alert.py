"""
E8 — Intent alert generator.
"""
from __future__ import annotations

import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
sys.path.insert(0, _project_root)

from datetime import datetime, timezone
from pathlib import Path

from db import get_connection
from db.memory_queries import get_latest_memory
from db.queries import get_developer, get_events_by_entity


def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_outreach_context(memory: dict) -> dict:
    meta_context = memory.get("meta", {}).get("outreach_context")
    if isinstance(meta_context, dict):
        return meta_context
    return {
        "recommended_angle": memory.get("recommended_angle"),
        "specific_hooks": memory.get("specific_hooks", []),
        "vocabulary_to_use": [],
        "vocabulary_to_avoid": [],
        "tone": "peer_technical",
    }


def _latest_transition_reason(entity_id: str) -> tuple[str | None, dict]:
    events = get_events_by_entity(entity_id, limit=20)
    for event in events:
        if event["event_type"] == "enrichment.state_transition":
            payload = event["payload"] if isinstance(event["payload"], dict) else {}
            return event["occurred_at"], payload
    return None, {}


def generate_intent_alert(entity_id: str) -> str:
    developer = get_developer(entity_id)
    memory = get_latest_memory(entity_id)
    if not developer or not memory:
        raise ValueError(f"No developer or active memory found for {entity_id}")

    occurred_at, transition_payload = _latest_transition_reason(entity_id)
    outreach_context = _load_outreach_context(memory)
    pain_signals = memory.get("confirmed_pain_signals", [])
    hooks = outreach_context.get("specific_hooks") or memory.get("specific_hooks") or []

    output_dir = Path(_project_root) / "output" / "alerts"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{entity_id}_{_utc_today()}.md"

    why_lines = []
    if transition_payload:
        why_lines.append(
            f"- Latest transition: `{transition_payload.get('from_status')}` → `{transition_payload.get('to_status')}`"
        )
        why_lines.append(f"- Reason: {transition_payload.get('reason')}")
    else:
        why_lines.append("- No recent state transition found; alert generated from latest memory snapshot.")

    why_lines.append(f"- Current status: `{developer['status']}`")
    why_lines.append(f"- Intent score: `{developer['intent_score']}`")
    why_lines.append(f"- Maturity score: `{developer['maturity_score']}`")
    if occurred_at:
        why_lines.append(f"- Transition detected at: `{occurred_at}`")

    pain_lines = [
        f"- `{item.get('category')}` — {item.get('description')} | evidence: {item.get('evidence')}"
        for item in pain_signals[:5]
    ]

    context_lines = [
        f"- Recommended angle: `{outreach_context.get('recommended_angle') or memory.get('recommended_angle')}`",
        f"- Tone: `{outreach_context.get('tone', 'peer_technical')}`",
    ]
    for hook in hooks[:5]:
        context_lines.append(f"- Hook: {hook}")

    vocab_use = outreach_context.get("vocabulary_to_use") or []
    vocab_avoid = outreach_context.get("vocabulary_to_avoid") or []
    if vocab_use:
        context_lines.append(f"- Vocabulary to use: {', '.join(vocab_use[:8])}")
    if vocab_avoid:
        context_lines.append(f"- Vocabulary to avoid: {', '.join(vocab_avoid[:8])}")

    content = "\n".join([
        f"# Intent Alert — {entity_id}",
        "",
        "## Por qué triggerió",
        *(why_lines or ["Sin novedades"]),
        "",
        "## Qué sabemos",
        f"- Narrative: {memory.get('narrative') or memory.get('_summary') or 'Sin narrativa'}",
        *(pain_lines or ["- Sin pain signals confirmadas"]),
        "",
        "## Outreach context",
        *(context_lines or ["Sin contexto de outreach"]),
        "",
        "## Decisión del operador",
        "- [ ] Aprobar draft",
        "- [ ] Editar y enviar",
        "- [ ] Hold",
        "- [ ] Disqualify",
        "",
    ])

    path.write_text(content, encoding="utf-8")
    return str(path)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python intelligence/generate_alert.py <entity_id>")
    print(generate_intent_alert(sys.argv[1]))


if __name__ == "__main__":
    main()
