from __future__ import annotations

import os
import sys
import json
from datetime import datetime, timezone

from app_logging import configure_logging
from db import db_cursor

try:
    import redis as redis_lib
except Exception:  # pragma: no cover
    redis_lib = None  # type: ignore

log = configure_logging("worker")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECTORS_DIR = os.path.join(PROJECT_ROOT, "collectors")


def _ensure_collectors_path() -> None:
    if COLLECTORS_DIR not in sys.path:
        sys.path.insert(0, COLLECTORS_DIR)

JOB_DEFINITIONS = [
    {"id": "github_scan", "type": "interval", "hours": 6},
    {"id": "hn_scan", "type": "interval", "hours": 4},
    {"id": "monitor_repos", "type": "interval", "hours": 12},
    {"id": "enrichment_dispatch", "type": "interval", "minutes": 15},
    {"id": "nightly_scoring", "type": "cron", "hour": 2, "minute": 0},
    {"id": "daily_digest", "type": "cron", "hour": 7, "minute": 0},
    {"id": "weekly_report", "type": "cron", "day_of_week": "sun", "hour": 18},
]


def _publish_worker_event(job_id: str, payload) -> None:
    now = datetime.now(timezone.utc).isoformat()
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT pg_notify(%s, %s)",
                (
                    "dev_intel_events",
                    json.dumps(
                        {
                            "type": "worker_job_completed",
                            "job_id": job_id,
                            "completed_at": now,
                            "payload": payload,
                        },
                        ensure_ascii=True,
                    ),
                ),
            )
    except Exception as exc:
        log.warning("worker.notify_failed", job_id=job_id, error=str(exc))

    if redis_lib is None:
        return

    try:
        client = redis_lib.from_url(
            os.getenv("REDIS_URL", "redis://redis:6379/0"),
            decode_responses=True,
            socket_connect_timeout=2,
        )
        client.set("worker:last_job_at", now, ex=86400)
        client.set("worker:last_job_type", job_id, ex=86400)
    except Exception as exc:
        log.warning("worker.redis_state_failed", job_id=job_id, error=str(exc))


def github_scan() -> int:
    _ensure_collectors_path()
    from collectors.run_all import run_github

    count = run_github()
    _publish_worker_event("github_scan", {"events": count})
    log.info("worker.job_completed", job_id="github_scan", events=count)
    return count


def hn_scan() -> int:
    _ensure_collectors_path()
    from collectors.run_all import run_hn

    count = run_hn()
    _publish_worker_event("hn_scan", {"events": count})
    log.info("worker.job_completed", job_id="hn_scan", events=count)
    return count


def monitor_repos() -> int:
    _ensure_collectors_path()
    from collectors.run_all import run_monitor

    count = run_monitor()
    _publish_worker_event("monitor_repos", {"events": count})
    log.info("worker.job_completed", job_id="monitor_repos", events=count)
    return count


def enrichment_dispatch() -> dict:
    from enrichment.dispatcher import run_dispatcher
    from enrichment.trigger import process_pending_events

    # Heartbeat al inicio para que el health check vea actividad mientras los jobs corren
    _publish_worker_event("enrichment_dispatch", {"status": "started"})

    queued = process_pending_events(batch_size=20)
    processed = run_dispatcher(once=True)
    _publish_worker_event("enrichment_dispatch", {"queued": queued, "processed": processed})
    log.info("worker.job_completed", job_id="enrichment_dispatch", queued=queued, processed=processed)
    return {"queued": queued, "processed": processed}


def nightly_scoring() -> dict:
    from intelligence.detect_transitions import evaluate_all_entities
    from intelligence.score_entities import run_nightly_scoring

    scoring = run_nightly_scoring()
    transitions = evaluate_all_entities()
    _publish_worker_event(
        "nightly_scoring",
        {"scoring": scoring, "transitions": len(transitions["transitions"])},
    )
    log.info(
        "worker.job_completed",
        job_id="nightly_scoring",
        scoring=scoring,
        transitions=len(transitions["transitions"]),
        clusters=len(transitions["clusters"]),
    )
    return {"scoring": scoring, "transitions": transitions}


def daily_digest() -> str:
    from intelligence.generate_digest import generate_daily_digest

    path = generate_daily_digest()
    _publish_worker_event("daily_digest", {"output": path})
    log.info("worker.job_completed", job_id="daily_digest", output=path)
    return path


def weekly_report() -> str:
    from intelligence.trend_analyzer import generate_weekly_report

    path = generate_weekly_report()
    _publish_worker_event("weekly_report", {"output": path})
    log.info("worker.job_completed", job_id="weekly_report", output=path)
    return path


JOB_HANDLERS = {
    "github_scan": github_scan,
    "hn_scan": hn_scan,
    "monitor_repos": monitor_repos,
    "enrichment_dispatch": enrichment_dispatch,
    "nightly_scoring": nightly_scoring,
    "daily_digest": daily_digest,
    "weekly_report": weekly_report,
}
