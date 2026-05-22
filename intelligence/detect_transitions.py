"""
E7 — State machine y detección de transiciones / reconfiguraciones.
"""
from __future__ import annotations

import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
sys.path.insert(0, _project_root)

import json
import logging
from datetime import datetime, timezone

from db.events import emit_event
from db.queries import (
    enqueue_enrichment,
    get_active_developers,
    get_active_signals,
    get_developer,
    get_events_by_entity,
    update_developer_status,
)
from enrichment.memory_writer import update_memory_on_event
from enrichment.types import DeveloperStatus, MaturityTier
from intelligence.score_entities import get_temporal_multiplier

logger = logging.getLogger("intelligence.detect_transitions")


def _emit_transition_event(entity_id: str, from_status: str, to_status: str, payload: dict) -> str | None:
    event_payload = {
        "from_status": from_status,
        "to_status": to_status,
        **payload,
    }
    return emit_event(
        "enrichment.state_transition",
        entity_id,
        "developer",
        event_payload,
        source="internal",
        source_url=f"transition://{entity_id}/{from_status}-{to_status}/{datetime.now(timezone.utc).isoformat()}",
    )


def _maybe_generate_alert(entity_id: str) -> None:
    try:
        from intelligence.generate_alert import generate_intent_alert  # type: ignore
    except Exception:
        logger.info("generate_alert.py not available yet; skipping alert for %s", entity_id)
        return

    try:
        generate_intent_alert(entity_id)
    except Exception as exc:
        logger.warning("Could not generate alert for %s: %s", entity_id, exc)


def _total_active_signal_score(entity_id: str) -> float:
    return round(
        sum(float(signal["current_score"] or 0.0) for signal in get_active_signals(entity_id)),
        2,
    )


def evaluate_state_machine(entity_id: str) -> dict | None:
    developer = get_developer(entity_id)
    if not developer:
        return None

    current_status = developer["status"]
    intent_score = float(developer["intent_score"] or 0.0)
    maturity_score = float(developer["maturity_score"] or 0.0)
    maturity_tier = MaturityTier.from_score(maturity_score)
    temporal_multiplier = get_temporal_multiplier(entity_id)
    total_signal_score = _total_active_signal_score(entity_id)

    target_status = None
    reason = None

    if (
        current_status == DeveloperStatus.DISCOVERED.value
        and developer["last_enriched"]
        and (developer["archetype"] or maturity_score > 0)
    ):
        target_status = DeveloperStatus.PROFILED.value
        reason = "enrichment complete"
    elif current_status == DeveloperStatus.PROFILED.value and total_signal_score > 0:
        target_status = DeveloperStatus.MONITORED.value
        reason = f"active signal score > 0 ({total_signal_score})"
    elif current_status == DeveloperStatus.MONITORED.value and intent_score >= 50:
        target_status = DeveloperStatus.WARM.value
        reason = f"intent_score >= 50 ({intent_score})"
    elif (
        current_status == DeveloperStatus.WARM.value
        and intent_score >= 75
        and maturity_tier in {MaturityTier.INTERMEDIATE, MaturityTier.PRODUCTION, MaturityTier.SCALE_READY}
        and temporal_multiplier >= 1.5
    ):
        target_status = DeveloperStatus.QUALIFIED.value
        reason = (
            f"intent_score={intent_score}, maturity={maturity_tier.value}, "
            f"temporal_multiplier={temporal_multiplier}"
        )

    if not target_status:
        return None

    payload = {
        "reason": reason,
        "intent_score": intent_score,
        "maturity_score": maturity_score,
        "maturity_tier": maturity_tier.value,
        "temporal_multiplier": temporal_multiplier,
        "active_signal_score": total_signal_score,
    }

    event_id = _emit_transition_event(entity_id, current_status, target_status, payload)
    update_developer_status(entity_id, target_status)
    update_memory_on_event(
        entity_id,
        "enrichment.state_transition",
        {
            "from_status": current_status,
            "to_status": target_status,
            "reason": reason,
        },
    )

    if target_status == DeveloperStatus.QUALIFIED.value:
        _maybe_generate_alert(entity_id)

    return {
        "entity_id": entity_id,
        "from_status": current_status,
        "to_status": target_status,
        "reason": reason,
        "event_id": event_id,
    }


def detect_transition_cluster(entity_id: str, window_days: int = 14) -> dict | None:
    events = get_events_by_entity(entity_id, limit=200)
    now = datetime.now(timezone.utc)
    distinct_types: set[str] = set()

    for event in events:
        occurred_at = event["occurred_at"]
        try:
            event_time = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
        except Exception:
            continue
        if (now - event_time).days > window_days:
            continue

        event_type = event["event_type"]
        if event_type == "repo.commit_detected":
            continue
        if event_type.startswith("enrichment.") or event_type.startswith("repo."):
            distinct_types.add(event_type)

    if len(distinct_types) < 3:
        return None

    payload = {
        "window_days": window_days,
        "distinct_event_types": sorted(distinct_types),
        "distinct_count": len(distinct_types),
    }
    event_id = emit_event(
        "developer.architectural_reconfiguration",
        entity_id,
        "developer",
        payload,
        source="internal",
        source_url=f"reconfiguration://{entity_id}/{window_days}",
    )
    if event_id:
        enqueue_enrichment(entity_id, "partial", source_event_id=event_id, priority=1)

    return {
        "entity_id": entity_id,
        "event_id": event_id,
        "distinct_count": len(distinct_types),
        "distinct_event_types": sorted(distinct_types),
    }


def evaluate_all_entities() -> dict[str, list]:
    transitions: list[dict] = []
    clusters: list[dict] = []

    for developer in get_active_developers(min_score=0.0):
        entity_id = developer["id"]
        transition = evaluate_state_machine(entity_id)
        if transition:
            transitions.append(transition)

        cluster = detect_transition_cluster(entity_id)
        if cluster:
            clusters.append(cluster)

    return {"transitions": transitions, "clusters": clusters}


def main() -> None:
    result = evaluate_all_entities()
    print(
        "Transition evaluation complete | "
        f"transitions={len(result['transitions'])} "
        f"clusters={len(result['clusters'])}"
    )
    if result["transitions"]:
        print(json.dumps(result["transitions"][:10], ensure_ascii=True))
    if result["clusters"]:
        print(json.dumps(result["clusters"][:10], ensure_ascii=True))


if __name__ == "__main__":
    main()
