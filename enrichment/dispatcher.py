"""
E4.T8 — Dispatcher: consume la enrichment_queue y ejecuta los jobs.

Uso:
  python enrichment/dispatcher.py --once       # procesa batch y sale
  python enrichment/dispatcher.py              # loop continuo (cada 60s)
"""
from __future__ import annotations

import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
sys.path = [p for p in sys.path if os.path.abspath(p) != _this_dir]
sys.path.insert(0, _project_root)

import logging
import time
import traceback
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from db.queries import get_pending_queue, update_queue_status

logger = logging.getLogger("enrichment.dispatcher")

# Redis para reportar heartbeat al health check
_redis_client = None

def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis as redis_lib
        _redis_client = redis_lib.from_url(
            os.getenv("REDIS_URL", "redis://redis:6379/0"),
            decode_responses=True,
            socket_connect_timeout=2,
        )
        _redis_client.ping()
    except Exception as exc:
        logger.warning(f"dispatcher.redis_unavailable: {exc}")
        _redis_client = None
    return _redis_client


def _ping_worker_heartbeat(job_type: str) -> None:
    """Escribe worker:last_job_at y worker:last_job_type en Redis (TTL 2h)."""
    try:
        r = _get_redis()
        if r is None:
            return
        now = datetime.now(timezone.utc).isoformat()
        r.set("worker:last_job_at", now, ex=7200)
        r.set("worker:last_job_type", job_type, ex=7200)
    except Exception as exc:
        logger.warning(f"dispatcher.heartbeat_failed: {exc}")

_BATCH_SIZE = 20
_LOOP_INTERVAL_SECONDS = 60
_INTER_JOB_SLEEP_SECONDS = 3  # pausa entre jobs para no agotar el rate limit de GitHub


def _get_source_event_type(source_event_id: Optional[str]) -> Optional[str]:
    """Fetch the event_type of the source event from the DB."""
    if not source_event_id:
        return None
    try:
        from db import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT event_type FROM events WHERE id = ?",
                (source_event_id,)
            ).fetchone()
        return row["event_type"] if row else None
    except Exception:
        return None


def _run_job(job) -> None:
    """Execute a single enrichment job. Raises on failure."""
    entity_id = job["entity_id"]
    enrichment_type = job["enrichment_type"]
    source_event_id = job["source_event_id"]

    logger.info(f"Running job: {entity_id} — {enrichment_type}")

    if enrichment_type == "full":
        from enrichment.full_enrichment import run_full_enrichment
        run_full_enrichment(entity_id)

    elif enrichment_type == "partial":
        from enrichment.partial_enrichment import run_partial_enrichment
        trigger = _get_source_event_type(source_event_id) or "unknown"
        run_partial_enrichment(entity_id, trigger_event_type=trigger)

    elif enrichment_type == "pain_check":
        from enrichment.pain_detector import run_pain_check
        run_pain_check(entity_id)

    elif enrichment_type == "readme_only":
        from enrichment.readme_extractor import enrich_readme
        enrich_readme(entity_id)

    else:
        logger.warning(f"Unknown enrichment_type: {enrichment_type} for {entity_id}")


def run_dispatcher(once: bool = False) -> int:
    """
    Main dispatcher loop.
    once=True: process one batch and return.
    once=False: loop every _LOOP_INTERVAL_SECONDS until interrupted.

    Returns total jobs processed.
    """
    total = 0

    while True:
        jobs = get_pending_queue(limit=_BATCH_SIZE)

        if not jobs:
            if once:
                logger.info("No pending jobs — dispatcher done")
                break
            logger.debug("No pending jobs, sleeping...")
            time.sleep(_LOOP_INTERVAL_SECONDS)
            continue

        logger.info(f"Dispatching {len(jobs)} jobs")

        for job in jobs:
            job_id = job["id"]
            entity_id = job["entity_id"]
            enrichment_type = job["enrichment_type"]

            # Mark running
            update_queue_status(job_id, "running")

            try:
                _run_job(job)
                update_queue_status(job_id, "completed")
                total += 1
                _ping_worker_heartbeat(enrichment_type)
                logger.info(f"Job completed: {entity_id} ({enrichment_type})")

            except Exception as e:
                tb = traceback.format_exc()
                logger.error(
                    f"Job failed: {entity_id} ({enrichment_type}): {e}\n{tb}"
                )
                update_queue_status(job_id, "failed", error=str(e)[:500])

            finally:
                # Pausa entre jobs para no agotar el rate limit de GitHub en ráfaga
                time.sleep(_INTER_JOB_SLEEP_SECONDS)

        if once:
            break
        time.sleep(_LOOP_INTERVAL_SECONDS)

    return total


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    parser = argparse.ArgumentParser(description="Dev Intelligence — Enrichment dispatcher")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one batch of pending jobs and exit",
    )
    args = parser.parse_args()

    start = datetime.now(timezone.utc)
    total = run_dispatcher(once=args.once)
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()

    print(f"\n✅ Dispatcher {'(once)' if args.once else '(loop)'} completo:")
    print(f"   Jobs procesados: {total} en {elapsed:.1f}s")

    # Queue stats
    try:
        from db import get_connection
        with get_connection() as conn:
            stats = conn.execute(
                """
                SELECT status, COUNT(*) as n
                FROM enrichment_queue
                GROUP BY status
                """
            ).fetchall()
        for row in stats:
            print(f"   Queue {row['status']}: {row['n']}")
    except Exception:
        pass
