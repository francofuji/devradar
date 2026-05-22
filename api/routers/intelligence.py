from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException

from db import db_cursor
from intelligence.generate_digest import generate_daily_digest
from intelligence.trend_analyzer import generate_weekly_report

log = structlog.get_logger().bind(module="api.routers.intelligence")
router = APIRouter(tags=["intelligence"])
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DAILY_DIR = PROJECT_ROOT / "output" / "daily"
ALERTS_DIR = PROJECT_ROOT / "output" / "alerts"
WEEKLY_DIR = PROJECT_ROOT / "output" / "weekly"


def _read_markdown(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    sections: list[dict[str, str]] = []
    current_title = "Intro"
    current_lines: list[str] = []

    for line in content.splitlines():
        if line.startswith("## "):
            sections.append({"title": current_title, "content": "\n".join(current_lines).strip()})
            current_title = line[3:].strip()
            current_lines = []
            continue
        current_lines.append(line)
    sections.append({"title": current_title, "content": "\n".join(current_lines).strip()})

    return {
        "path": str(path),
        "content": content,
        "sections": [section for section in sections if section["content"]],
    }


def _require_file(path: Path) -> Path:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Archivo no encontrado: {path.name}")
    return path


@router.get("/api/digest/latest")
def get_latest_digest() -> dict[str, Any]:
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    candidates = sorted(DAILY_DIR.glob("*.md"))
    path = Path(generate_daily_digest()) if not candidates else candidates[-1]
    payload = _read_markdown(path)
    payload["date"] = path.stem
    return payload


@router.get("/api/digest/{date}")
def get_digest_by_date(date: str) -> dict[str, Any]:
    path = _require_file(DAILY_DIR / f"{date}.md")
    payload = _read_markdown(path)
    payload["date"] = date
    return payload


@router.get("/api/alerts")
def list_alerts(limit: int = 20) -> dict[str, Any]:
    ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(ALERTS_DIR.glob("*.md"), reverse=True)[: max(1, min(limit, 100))]:
        parsed = _read_markdown(path)
        items.append(
            {
                "id": path.stem,
                "path": str(path),
                "preview": parsed["content"][:320],
                "sections": parsed["sections"][:3],
            }
        )
    return {"items": items}


@router.get("/api/trends/latest")
def get_latest_trends() -> dict[str, Any]:
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    candidates = sorted(WEEKLY_DIR.glob("week_*.md"))
    path = Path(generate_weekly_report()) if not candidates else candidates[-1]
    payload = _read_markdown(path)
    payload["week"] = path.stem
    return payload


@router.get("/api/ecosystem/stats")
def ecosystem_stats() -> dict[str, Any]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT status, COUNT(*) AS total
            FROM developers
            GROUP BY status
            ORDER BY total DESC
            """
        )
        status_rows = cur.fetchall()

        cur.execute(
            """
            SELECT COALESCE(archetype, 'unknown') AS archetype, COUNT(*) AS total
            FROM developers
            GROUP BY COALESCE(archetype, 'unknown')
            ORDER BY total DESC
            """
        )
        archetype_rows = cur.fetchall()

        cur.execute(
            """
            SELECT primary_language, COUNT(*) AS total
            FROM repositories
            GROUP BY primary_language
            ORDER BY total DESC
            LIMIT 15
            """
        )
        language_rows = cur.fetchall()

        cur.execute("SELECT stack_snapshot FROM repositories WHERE stack_snapshot IS NOT NULL")
        stack_rows = cur.fetchall()

    tech_counter: dict[str, int] = {}
    for row in stack_rows:
        snapshot = row.get("stack_snapshot") or {}
        runtime_deps = snapshot.get("runtime_deps") or {}
        for category, packages in runtime_deps.items():
            if packages:
                tech_counter[category] = tech_counter.get(category, 0) + len(packages)

    return {
        "statuses": [dict(row) for row in status_rows],
        "archetypes": [dict(row) for row in archetype_rows],
        "languages": [dict(row) for row in language_rows],
        "technologies": [
            {"category": category, "mentions": mentions}
            for category, mentions in sorted(tech_counter.items(), key=lambda item: item[1], reverse=True)
        ],
    }

