"""
E4.T1+T2 — Trigger: lee eventos pending y los encola para enrichment.

Uso: python enrichment/trigger.py [--batch N]
"""
from __future__ import annotations

import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
sys.path = [p for p in sys.path if os.path.abspath(p) != _this_dir]
sys.path.insert(0, _project_root)

import logging

from dotenv import load_dotenv
load_dotenv()

from db.queries import (
    enqueue_enrichment,
    get_pending_enrichment,
    mark_enrichment_queued,
)

logger = logging.getLogger("enrichment.trigger")

# Mapeo event_type → [(enrichment_type, priority)]
# priority: 1=urgente, 2=normal, 3=background
ENRICHMENT_TRIGGERS: dict[str, list[tuple[str, int]]] = {
    # Discovery → full enrichment
    "developer.discovered":       [("full", 2)],
    "repository.discovered":      [("full", 2)],
    # High-intent signals → full enrichment urgente
    "developer.product_launched": [("full", 1)],
    "developer.job_changed":      [("full", 1)],
    "developer.funding_announced":[("full", 1)],
    # Activity signals → partial
    "repo.stars_spiked":          [("partial", 2)],
    "repo.dependency_changed":    [("partial", 2)],
    "repo.release_published":     [("partial", 2)],
    "developer.article_published":[("partial", 2)],
    # Low-signal activity → background
    "repo.issue_count_changed":   [("pain_check", 3)],
    "repo.commit_detected":       [("partial", 3)],
}


def process_pending_events(batch_size: int = 20) -> int:
    """
    Procesa eventos con enrichment_status='pending'.
    Encola el trabajo apropiado en enrichment_queue.
    Marca el evento como 'queued'.
    Retorna cantidad de eventos procesados.
    """
    events = get_pending_enrichment(limit=batch_size)
    if not events:
        logger.info("No hay eventos pending")
        return 0

    logger.info(f"Procesando {len(events)} eventos pending")

    queued = 0
    skipped = 0

    for event in events:
        event_type = event["event_type"]
        entity_id = event["entity_id"]
        event_id = event["id"]

        if not entity_id:
            logger.warning(f"Evento {event_id} sin entity_id — skipping")
            mark_enrichment_queued(event_id)
            skipped += 1
            continue

        triggers = ENRICHMENT_TRIGGERS.get(event_type)
        if not triggers:
            # No enrichment para este tipo — marcar como queued para no re-procesar
            mark_enrichment_queued(event_id)
            skipped += 1
            continue

        jobs_enqueued = 0
        for enrich_type, priority in triggers:
            try:
                job_id = enqueue_enrichment(
                    entity_id=entity_id,
                    enrichment_type=enrich_type,
                    source_event_id=event_id,
                    priority=priority,
                )
                logger.debug(
                    f"Job encolado {job_id}: {entity_id} → "
                    f"{enrich_type} (priority={priority})"
                )
                jobs_enqueued += 1
            except Exception as e:
                logger.error(f"Error encolando {entity_id} ({enrich_type}): {e}")

        mark_enrichment_queued(event_id)
        if jobs_enqueued > 0:
            queued += 1
        else:
            skipped += 1

    logger.info(f"Trigger: {queued} eventos encolados, {skipped} sin acción")
    return queued


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser(description="Dev Intelligence — Enrichment trigger")
    parser.add_argument("--batch", type=int, default=20, help="Eventos por batch")
    args = parser.parse_args()

    n = process_pending_events(batch_size=args.batch)
    print(f"\n✅ Trigger completo: {n} eventos procesados y encolados")

    # Mostrar estadísticas de queue
    try:
        from db import get_connection
        with get_connection() as conn:
            pending = conn.execute(
                "SELECT COUNT(*) as n FROM enrichment_queue WHERE status='pending'"
            ).fetchone()["n"]
            print(f"   Queue: {pending} jobs pending")
    except Exception:
        pass
