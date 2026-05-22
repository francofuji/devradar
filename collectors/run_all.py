"""
Entry point de los colectores de señales.
Uso: python collectors/run_all.py --collector {github,hn,monitor,all}

Escribe log en logs/collector_YYYY-MM-DD.log con:
  - timestamp de inicio
  - cantidad de eventos emitidos
  - rate limit restante al terminar (colectores GitHub)
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Project root en path para imports de db.*
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()


def _setup_logging(collector_name: str) -> None:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = log_dir / f"collector_{today}.log"

    fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )
    logging.info(f"=== Collector run: {collector_name} — {datetime.now(timezone.utc).isoformat()} ===")


def run_github(client=None) -> int:
    from github_client import GitHubClient
    from github_trending import scan_ecosystem

    logger = logging.getLogger("run_all.github")

    if client is None:
        client = GitHubClient()

    start = datetime.now(timezone.utc)
    events = scan_ecosystem(client)
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    remaining = client.get_rate_limit_remaining()

    logger.info(
        f"GitHub scan: {events} eventos emitidos en {elapsed:.1f}s. "
        f"Rate limit restante: {remaining}"
    )
    return events


def run_hn() -> int:
    from hn_digest import scan_hn

    logger = logging.getLogger("run_all.hn")
    start = datetime.now(timezone.utc)
    events = scan_hn()
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()

    logger.info(f"HN scan: {events} eventos emitidos en {elapsed:.1f}s")
    return events


def run_monitor(client=None) -> int:
    from github_client import GitHubClient
    from github_repo_monitor import monitor_known_repos

    logger = logging.getLogger("run_all.monitor")

    if client is None:
        client = GitHubClient()

    start = datetime.now(timezone.utc)
    events = monitor_known_repos(client)
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    remaining = client.get_rate_limit_remaining()

    logger.info(
        f"Monitor: {events} eventos emitidos en {elapsed:.1f}s. "
        f"Rate limit restante: {remaining}"
    )
    return events


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dev Intelligence — Collector runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  python collectors/run_all.py --collector github\n"
            "  python collectors/run_all.py --collector hn\n"
            "  python collectors/run_all.py --collector monitor\n"
            "  python collectors/run_all.py --collector all\n"
        ),
    )
    parser.add_argument(
        "--collector",
        choices=["github", "hn", "monitor", "all"],
        required=True,
        help="Colector a ejecutar",
    )
    args = parser.parse_args()

    _setup_logging(args.collector)
    logger = logging.getLogger("run_all")

    total_events = 0
    start_total = datetime.now(timezone.utc)

    try:
        if args.collector in ("github", "all"):
            total_events += run_github()

        if args.collector in ("hn", "all"):
            total_events += run_hn()

        if args.collector in ("monitor", "all"):
            total_events += run_monitor()

    except KeyboardInterrupt:
        logger.info("Interrumpido por el usuario.")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Collector '{args.collector}' falló: {e}", exc_info=True)
        sys.exit(1)

    elapsed_total = (datetime.now(timezone.utc) - start_total).total_seconds()
    logger.info(
        f"=== Run completo: {total_events} eventos totales en {elapsed_total:.1f}s ==="
    )
    print(f"\n✅ Collector '{args.collector}' completo. Eventos emitidos: {total_events}")

    # Mostrar stats de DB
    try:
        from db.queries import get_total_cost
        from db import get_connection
        with get_connection() as conn:
            n_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            n_devs = conn.execute("SELECT COUNT(*) FROM developers").fetchone()[0]
            n_repos = conn.execute("SELECT COUNT(*) FROM repositories").fetchone()[0]
        print(f"   DB: {n_events} eventos | {n_devs} developers | {n_repos} repos")
    except Exception:
        pass


if __name__ == "__main__":
    main()
