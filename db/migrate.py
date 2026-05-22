from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://devint:changeme_in_production@postgres:5432/dev_intelligence")

VISIBLE_TABLES = [
    "developers",
    "enrichment_costs",
    "enrichment_queue",
    "entity_memory",
    "events",
    "fine_tuning_examples",
    "model_registry",
    "repositories",
    "score_history",
]

REQUIRED_TABLES = VISIBLE_TABLES + ["signals"]


def wait_for_postgres(max_retries: int = 30) -> bool:
    for attempt in range(1, max_retries + 1):
        try:
            conn = psycopg2.connect(DATABASE_URL)
            conn.close()
            print(f"PostgreSQL listo ({attempt} intentos)")
            return True
        except psycopg2.OperationalError:
            print(f"Esperando PostgreSQL... ({attempt}/{max_retries})")
            time.sleep(2)
    return False


def migrate():
    if not wait_for_postgres():
        print("ERROR: PostgreSQL no disponible")
        sys.exit(1)

    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")

    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql)
    finally:
        conn.close()

    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
                """
            )
            tables = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()

    missing = [name for name in REQUIRED_TABLES if name not in tables]
    if missing:
        print(f"ERROR: Tablas faltantes: {missing}")
        sys.exit(1)

    print(f"✅ Migración exitosa. Tablas: {', '.join(VISIBLE_TABLES)}")
    return tables


if __name__ == "__main__":
    migrate()
