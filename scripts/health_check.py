"""
Health check operacional para PostgreSQL + Redis.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import redis

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import get_connection


def check_db_accessible() -> tuple[bool, str]:
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1 AS ok").fetchone()
        return True, "DB accesible"
    except Exception as exc:
        return False, f"DB inaccesible: {exc}"


def check_redis_accessible() -> tuple[bool, str]:
    try:
        client = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
        return bool(client.ping()), "Redis accesible"
    except Exception as exc:
        return False, f"Redis inaccesible: {exc}"


def check_tables_exist() -> tuple[bool, str]:
    expected = {
        "developers",
        "enrichment_costs",
        "enrichment_queue",
        "entity_memory",
        "events",
        "fine_tuning_examples",
        "model_registry",
        "repositories",
        "score_history",
        "signals",
    }
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            ).fetchall()
        found = {row["table_name"] for row in rows}
        missing = expected - found
        if missing:
            return False, f"Tablas faltantes: {sorted(missing)}"
        return True, f"{len(found)} tablas presentes"
    except Exception as exc:
        return False, f"Error verificando tablas: {exc}"


def check_recent_events(hours: int = 6) -> tuple[bool, str]:
    try:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM events
                WHERE occurred_at >= NOW() - (%s || ' hours')::interval
                """,
                (str(hours),),
            ).fetchone()
        count = row["cnt"]
        if count == 0:
            return False, f"Sin eventos en las últimas {hours}h"
        return True, f"{count} eventos en las últimas {hours}h"
    except Exception as exc:
        return False, f"Error verificando eventos: {exc}"


def check_recent_enrichment(hours: int = 24) -> tuple[bool, str]:
    try:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM events
                WHERE event_type = 'enrichment.completed'
                  AND occurred_at >= NOW() - (%s || ' hours')::interval
                """,
                (str(hours),),
            ).fetchone()
        count = row["cnt"]
        if count == 0:
            return False, f"Sin enrichments completados en {hours}h"
        return True, f"{count} enrichments en las últimas {hours}h"
    except Exception as exc:
        return False, f"Error verificando enrichment: {exc}"


def check_daily_digest_exists() -> tuple[bool, str]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    digest_path = Path(f"output/daily/{today}.md")
    if digest_path.exists():
        return True, f"Digest del día existe: {digest_path}"
    return False, f"Digest del día no existe: {digest_path}"


def check_pending_queue() -> tuple[bool, str]:
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM enrichment_queue WHERE status = 'pending'"
            ).fetchone()
            activity = conn.execute(
                """
                SELECT
                    MAX(started_at) AS last_started,
                    MAX(completed_at) AS last_completed
                FROM enrichment_queue
                WHERE status IN ('running', 'completed')
                """
            ).fetchone()
        count = row["cnt"]
        last_started = activity["last_started"]
        last_completed = activity["last_completed"]

        if count > 50:
            now = datetime.now(timezone.utc)
            recent_activity = False
            for ts_value in (last_started, last_completed):
                if ts_value and ts_value >= now - timedelta(minutes=30):
                    recent_activity = True
            if recent_activity:
                return True, f"Cola acumulada pero drenando: {count} jobs pendientes"
            return False, f"Cola acumulada: {count} jobs pendientes"
        return True, f"{count} jobs pendientes"
    except Exception as exc:
        return False, f"Error verificando cola: {exc}"


def run_health_check(skip_operational: bool = False) -> bool:
    print(f"🔍 Health check — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    checks = [
        ("DB accesible", check_db_accessible),
        ("Redis accesible", check_redis_accessible),
        ("Tablas presentes", check_tables_exist),
        ("Cola de enrichment", check_pending_queue),
    ]

    if not skip_operational:
        checks.extend(
            [
                ("Eventos recientes (6h)", check_recent_events),
                ("Enrichments recientes (24h)", check_recent_enrichment),
                ("Digest del día", check_daily_digest_exists),
            ]
        )

    all_ok = True
    for name, check_fn in checks:
        status_ok, message = check_fn()
        icon = "✅" if status_ok else "❌"
        print(f"  {icon} {name:35s} {message}")
        if not status_ok:
            all_ok = False

    print()
    if all_ok:
        print("✅ Sistema operacional")
    else:
        print("⚠️  Sistema con problemas")
        if not skip_operational:
            sys.exit(1)

    return all_ok


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-operational", action="store_true")
    args = parser.parse_args()
    run_health_check(skip_operational=args.skip_operational)
