"""
E7 — Nightly scoring, decay e historial de trayectoria.
"""
from __future__ import annotations

import math
import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
sys.path.insert(0, _project_root)

import logging
from datetime import datetime, timezone
from typing import Iterable

from db import get_connection
from db.events import emit_event
from db.queries import (
    get_active_developers,
    get_active_signals,
    get_developer,
    get_events_by_entity,
    get_score_history,
    record_score_snapshot,
    update_developer_scores,
)
from enrichment.types import IntentTier, TrajectoryDirection

logger = logging.getLogger("intelligence.score_entities")

SIGNAL_DECAYING_THRESHOLD = 0.5
SIGNAL_EXPIRED_THRESHOLD = 0.05
RECENT_EVENT_LOOKBACK_DAYS = 30
TEMPORAL_MULTIPLIERS = (
    (2, 2.0),
    (7, 1.5),
    (21, 1.0),
    (10_000, 0.5),
)
IGNORED_TEMPORAL_EVENT_TYPES = {
    "enrichment.completed",
    "developer.note_added",
    "outreach.message_sent",
    "outreach.reply_received",
    "developer.disqualified",
}


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _days_elapsed_since(iso_value: str | None) -> float:
    parsed = _parse_iso(iso_value)
    if not parsed:
        return 0.0
    now = datetime.now(timezone.utc)
    return max(0.0, (now - parsed).total_seconds() / 86400.0)


def _compute_decayed_score(base_score: float, half_life_days: float, days_elapsed: float) -> float:
    if base_score <= 0:
        return 0.0
    if half_life_days <= 0:
        return base_score
    return base_score * math.exp((-math.log(2) / half_life_days) * days_elapsed)


def _signal_status(base_score: float, current_score: float) -> str:
    if base_score <= 0:
        return "EXPIRED"
    ratio = current_score / base_score
    if ratio < SIGNAL_EXPIRED_THRESHOLD:
        return "EXPIRED"
    if ratio < SIGNAL_DECAYING_THRESHOLD:
        return "DECAYING"
    return "ACTIVE"


def _update_signal_decay(signal_id: str, current_score: float, status: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE signals
            SET current_score = ?, status = ?
            WHERE id = ?
            """,
            (current_score, status, signal_id),
        )
        conn.commit()


def get_temporal_multiplier(entity_id: str, days_back: int = RECENT_EVENT_LOOKBACK_DAYS) -> float:
    """
    Multiplicador temporal basado en el evento externo/semántico más reciente.
    Ignora eventos puramente operacionales para no inflar score artificialmente.
    """
    events = get_events_by_entity(entity_id, limit=100)
    for event in events:
        event_type = event["event_type"]
        if event_type in IGNORED_TEMPORAL_EVENT_TYPES:
            continue
        days_elapsed = _days_elapsed_since(event["occurred_at"])
        if days_elapsed > days_back:
            continue
        for max_days, multiplier in TEMPORAL_MULTIPLIERS:
            if days_elapsed < max_days:
                return multiplier
    return 1.0


def _emit_intent_threshold_event_if_needed(entity_id: str, previous_score: float, current_score: float) -> None:
    previous_tier = IntentTier.from_score(previous_score)
    current_tier = IntentTier.from_score(current_score)
    if previous_tier == current_tier:
        return
    try:
        emit_event(
            "developer.intent_threshold_crossed",
            entity_id,
            "developer",
            {
                "previous_score": round(previous_score, 2),
                "current_score": round(current_score, 2),
                "previous_tier": previous_tier.value,
                "current_tier": current_tier.value,
            },
            source="internal",
            source_url=f"intent-threshold://{entity_id}/{current_tier.value}/{datetime.now(timezone.utc).isoformat()}",
        )
    except Exception as exc:
        logger.warning("Could not emit intent threshold event for %s: %s", entity_id, exc)


def compute_intent_score(entity_id: str) -> float:
    """
    Agrega señales activas por capa y aplica multiplicador temporal del evento más reciente.
    """
    developer = get_developer(entity_id)
    previous_score = float(developer["intent_score"]) if developer else 0.0

    signals = get_active_signals(entity_id)
    layer_score = 0.0
    for signal in signals:
        if signal["status"] not in {"ACTIVE", "DECAYING"}:
            continue
        if signal["category"] in {"budget", "evaluation", "scaling"}:
            layer_score += float(signal["current_score"] or 0.0)

    temporal_multiplier = get_temporal_multiplier(entity_id)
    final_score = round(layer_score * temporal_multiplier, 2)

    if developer:
        _emit_intent_threshold_event_if_needed(entity_id, previous_score, final_score)
        update_developer_scores(
            entity_id=entity_id,
            intent_score=final_score,
            maturity_score=float(developer["maturity_score"] or 0.0),
            trajectory_7d=float(developer["trajectory_7d"] or 0.0),
            trajectory_30d=float(developer["trajectory_30d"] or 0.0),
            trajectory_direction=developer["trajectory_direction"],
        )

    return final_score


def _velocity_from_history(history: Iterable, days_window: int) -> float:
    rows = list(history)
    if not rows:
        return 0.0

    cutoff = datetime.now(timezone.utc).timestamp() - (days_window * 86400)
    scoped = []
    for row in rows:
        parsed = _parse_iso(row["recorded_at"])
        if parsed and parsed.timestamp() >= cutoff:
            scoped.append(row)

    if len(scoped) < 2:
        return 0.0

    first = scoped[0]
    last = scoped[-1]
    first_time = _parse_iso(first["recorded_at"])
    last_time = _parse_iso(last["recorded_at"])
    if not first_time or not last_time:
        return 0.0

    elapsed_days = max(1e-6, (last_time - first_time).total_seconds() / 86400.0)
    return round((float(last["intent_score"]) - float(first["intent_score"])) / elapsed_days, 4)


def compute_trajectory(entity_id: str) -> tuple[float, float, str]:
    """
    Calcula velocidades 7d y 30d y clasifica dirección.
    """
    history = get_score_history(entity_id, days_back=90)
    developer = get_developer(entity_id)
    if len(history) < 3:
        trajectory = (0.0, 0.0, TrajectoryDirection.INSUFFICIENT_DATA.value)
        if developer:
            update_developer_scores(
                entity_id=entity_id,
                intent_score=float(developer["intent_score"] or 0.0),
                maturity_score=float(developer["maturity_score"] or 0.0),
                trajectory_7d=trajectory[0],
                trajectory_30d=trajectory[1],
                trajectory_direction=trajectory[2],
            )
        return trajectory

    trajectory_7d = _velocity_from_history(history, 7)
    trajectory_30d = _velocity_from_history(history, 30)

    if trajectory_7d > trajectory_30d > 0:
        direction = TrajectoryDirection.ACCELERATING.value
    elif trajectory_30d > 0:
        direction = TrajectoryDirection.STEADY_RISING.value
    elif abs(trajectory_30d) < 0.5:
        direction = TrajectoryDirection.PLATEAU.value
    elif trajectory_7d < trajectory_30d and trajectory_30d < 0:
        direction = TrajectoryDirection.SPIKE_AND_FALL.value
    elif trajectory_30d < 0:
        direction = TrajectoryDirection.DECLINING.value
    else:
        direction = TrajectoryDirection.INSUFFICIENT_DATA.value

    if developer:
        update_developer_scores(
            entity_id=entity_id,
            intent_score=float(developer["intent_score"] or 0.0),
            maturity_score=float(developer["maturity_score"] or 0.0),
            trajectory_7d=trajectory_7d,
            trajectory_30d=trajectory_30d,
            trajectory_direction=direction,
        )

    return trajectory_7d, trajectory_30d, direction


def _apply_decay_for_entity(entity_id: str) -> dict[str, int]:
    signals = get_active_signals(entity_id)
    summary = {"updated": 0, "expired": 0, "decaying": 0}

    for signal in signals:
        base_score = float(signal["base_score"] or 0.0)
        days_elapsed = _days_elapsed_since(signal["detected_at"])
        current_score = round(
            _compute_decayed_score(
                base_score=base_score,
                half_life_days=float(signal["half_life_days"] or 0.0),
                days_elapsed=days_elapsed,
            ),
            4,
        )
        status = _signal_status(base_score, current_score)
        _update_signal_decay(signal["id"], current_score, status)
        summary["updated"] += 1
        if status == "EXPIRED":
            summary["expired"] += 1
        elif status == "DECAYING":
            summary["decaying"] += 1

    return summary


def run_nightly_scoring() -> dict[str, int]:
    """
    Aplica decay, recalcula intent score, trayectoria y registra snapshots.
    """
    developers = get_active_developers(min_score=0.0)
    summary = {
        "developers_processed": 0,
        "signals_updated": 0,
        "signals_expired": 0,
        "signals_decaying": 0,
        "snapshots_recorded": 0,
    }

    for developer in developers:
        entity_id = developer["id"]
        decay_summary = _apply_decay_for_entity(entity_id)
        summary["signals_updated"] += decay_summary["updated"]
        summary["signals_expired"] += decay_summary["expired"]
        summary["signals_decaying"] += decay_summary["decaying"]

        intent_score = compute_intent_score(entity_id)
        trajectory_7d, trajectory_30d, trajectory_direction = compute_trajectory(entity_id)

        refreshed = get_developer(entity_id)
        record_score_snapshot(
            entity_id=entity_id,
            intent_score=float(refreshed["intent_score"] if refreshed else intent_score),
            maturity_score=float(refreshed["maturity_score"] if refreshed else developer["maturity_score"] or 0.0),
            status=refreshed["status"] if refreshed else developer["status"],
        )

        summary["developers_processed"] += 1
        summary["snapshots_recorded"] += 1

    return summary


def main() -> None:
    summary = run_nightly_scoring()
    print(
        "Nightly scoring complete | "
        f"developers={summary['developers_processed']} "
        f"signals_updated={summary['signals_updated']} "
        f"signals_decaying={summary['signals_decaying']} "
        f"signals_expired={summary['signals_expired']} "
        f"snapshots={summary['snapshots_recorded']}"
    )


if __name__ == "__main__":
    main()
