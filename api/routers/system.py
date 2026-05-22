from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import redis as redis_lib
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import clear_dependency_caches, verify_token
from db import db_cursor
from enrichment.llm_client import check_ollama_health

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

log = structlog.get_logger().bind(module="api.routers.system")
router = APIRouter(tags=["system"])
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.toml"
TAXONOMY_PATH = PROJECT_ROOT / "taxonomy" / "dependencies.json"
DAILY_DIR = PROJECT_ROOT / "output" / "daily"


def _get_redis():
    return redis_lib.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=3,
    )


def _load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("rb") as fh:
        return tomllib.load(fh)


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return '""'
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    raise TypeError(f"Tipo TOML no soportado: {type(value)!r}")


def _dump_toml(data: dict[str, Any], prefix: list[str] | None = None) -> str:
    prefix = prefix or []
    scalar_lines: list[str] = []
    table_lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, dict):
            header = ".".join(prefix + [key])
            table_lines.append(f"[{header}]")
            table_lines.append(_dump_toml(value, prefix + [key]).strip())
            table_lines.append("")
        else:
            scalar_lines.append(f"{key} = {_toml_scalar(value)}")
    return "\n".join([*scalar_lines, *table_lines]).strip() + "\n"


def _latest_digest_exists() -> bool:
    return any(DAILY_DIR.glob("*.md"))


def _worker_health_snapshot() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM enrichment_queue WHERE status = 'pending'")
        pending_in_queue = int(cur.fetchone()["total"])

        cur.execute(
            """
            SELECT enrichment_type, created_at
            FROM enrichment_queue
            WHERE status IN ('running', 'completed')
              AND (started_at > NOW() - INTERVAL '60 minutes'
                   OR completed_at > NOW() - INTERVAL '60 minutes')
            ORDER BY COALESCE(completed_at, started_at) DESC
            LIMIT 1
            """
        )
        recent_queue = cur.fetchone()

    last_job_at = None
    last_job_type = None
    redis_ok = False
    try:
        r = _get_redis()
        last_job_at = r.get("worker:last_job_at")
        last_job_type = r.get("worker:last_job_type")
        redis_ok = True
    except Exception as exc:
        log.warning("worker_health.redis_unavailable", error=str(exc))

    recent_completed = False
    if last_job_at:
        try:
            last_dt = datetime.fromisoformat(last_job_at.replace("Z", "+00:00"))
            recent_completed = last_dt >= now - timedelta(minutes=60)
        except Exception:
            recent_completed = False

    alive = recent_queue is not None or recent_completed
    return {
        "alive": alive,
        "last_job_at": last_job_at or (recent_queue["created_at"].isoformat() if recent_queue else None),
        "last_job_type": last_job_type or (recent_queue["enrichment_type"] if recent_queue else None),
        "pending_in_queue": pending_in_queue,
        "source": "redis+postgres" if redis_ok else "postgres",
    }


class ConfigUpdateRequest(BaseModel):
    config: dict[str, Any]


class TaxonomyUpdateRequest(BaseModel):
    category: str
    subcategory: str | None = None
    budget_signal: str | None = None
    archetype_signals: list[str] = []
    maturity_modifier: int = 0
    intent_weight: int = 0
    scaling_signal: bool = False
    pain_category: str | None = None
    runtime_only: bool = False
    note: str | None = ""


@router.get("/api/health")
def api_health() -> dict[str, Any]:
    db_ok = False
    redis_ok = False
    db_error = None
    redis_error = None

    try:
        with db_cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            db_ok = bool(cur.fetchone()["ok"] == 1)
    except Exception as exc:
        db_error = str(exc)
        log.error("api.health.db_failed", error=db_error)

    try:
        redis_ok = bool(_get_redis().ping())
    except Exception as exc:
        redis_error = str(exc)
        log.error("api.health.redis_failed", error=redis_error)

    worker = _worker_health_snapshot()
    ollama = check_ollama_health()
    status = "ok" if db_ok and redis_ok and ollama.get("available") else "degraded"
    return {
        "service": "api",
        "status": status,
        "db": {"ok": db_ok, "error": db_error},
        "redis": {"ok": redis_ok, "error": redis_error},
        "ollama": ollama,
        "worker": worker,
        "daily_digest_ready": _latest_digest_exists(),
    }


@router.get("/api/config", dependencies=[Depends(verify_token)])
def get_config() -> dict[str, Any]:
    return _load_config()


@router.put("/api/config", dependencies=[Depends(verify_token)])
def update_config(payload: ConfigUpdateRequest) -> dict[str, Any]:
    CONFIG_PATH.write_text(_dump_toml(payload.config), encoding="utf-8")
    clear_dependency_caches()
    return {"ok": True, "path": str(CONFIG_PATH)}


@router.get("/api/taxonomy/{package}", dependencies=[Depends(verify_token)])
def get_taxonomy_package(package: str) -> dict[str, Any]:
    data = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    packages = data.get("packages", {})
    if package not in packages:
        raise HTTPException(status_code=404, detail=f"Package no encontrado: {package}")
    return {"package": package, "definition": packages[package]}


@router.post("/api/taxonomy/{package}", dependencies=[Depends(verify_token)])
def create_taxonomy_package(package: str, payload: TaxonomyUpdateRequest) -> dict[str, Any]:
    data = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    packages = data.setdefault("packages", {})
    if package in packages:
        raise HTTPException(status_code=409, detail=f"Package ya existe: {package}")
    if payload.category not in data.get("_meta", {}).get("categories", []):
        raise HTTPException(status_code=400, detail=f"Categoría inválida: {payload.category}")
    packages[package] = payload.model_dump()
    TAXONOMY_PATH.write_text(json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "package": package}


@router.put("/api/taxonomy/{package}", dependencies=[Depends(verify_token)])
def update_taxonomy_package(package: str, payload: TaxonomyUpdateRequest) -> dict[str, Any]:
    data = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    packages = data.setdefault("packages", {})
    if package not in packages:
        raise HTTPException(status_code=404, detail=f"Package no encontrado: {package}")
    if payload.category not in data.get("_meta", {}).get("categories", []):
        raise HTTPException(status_code=400, detail=f"Categoría inválida: {payload.category}")
    packages[package] = payload.model_dump()
    TAXONOMY_PATH.write_text(json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "package": package}


@router.get("/api/costs", dependencies=[Depends(verify_token)])
def costs_summary() -> dict[str, Any]:
    with db_cursor() as cur:
        cur.execute("SELECT COALESCE(SUM(estimated_cost), 0) AS total FROM enrichment_costs")
        total = float(cur.fetchone()["total"])

        cur.execute(
            """
            SELECT COALESCE(provider, 'unknown') AS provider, COUNT(*) AS calls, COALESCE(SUM(estimated_cost), 0) AS total
            FROM enrichment_costs
            GROUP BY COALESCE(provider, 'unknown')
            ORDER BY total DESC
            """
        )
        providers = cur.fetchall()

        cur.execute(
            """
            SELECT COALESCE(enrichment_type, 'unknown') AS enrichment_type, COUNT(*) AS calls, COALESCE(SUM(estimated_cost), 0) AS total
            FROM enrichment_costs
            GROUP BY COALESCE(enrichment_type, 'unknown')
            ORDER BY total DESC
            """
        )
        task_types = cur.fetchall()

    return {
        "total": total,
        "by_provider": [dict(row) for row in providers],
        "by_task_type": [dict(row) for row in task_types],
    }


@router.get("/api/system/github-rate-limit", dependencies=[Depends(verify_token)])
def github_rate_limit() -> dict[str, Any]:
    try:
        r = _get_redis()
        remaining_raw = r.get("github:rate_limit:remaining")
        reset_raw = r.get("github:rate_limit:reset")
        return {
            "remaining": int(remaining_raw) if remaining_raw else None,
            "reset_at": int(reset_raw) if reset_raw else None,
            "source": "redis",
        }
    except Exception as exc:
        log.error("github_rate_limit.error", error=str(exc))
        return {"remaining": None, "reset_at": None, "source": "unavailable", "error": str(exc)}


@router.get("/api/system/worker-health", dependencies=[Depends(verify_token)])
def worker_health() -> dict[str, Any]:
    return _worker_health_snapshot()


@router.get("/api/system/metrics", dependencies=[Depends(verify_token)])
def system_metrics() -> dict[str, Any]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT status, COUNT(*) AS total
            FROM developers
            GROUP BY status
            ORDER BY status
            """
        )
        statuses = [{"status": r["status"], "total": int(r["total"])} for r in cur.fetchall()]

        cur.execute(
            """
            SELECT COUNT(*) AS total
            FROM events
            WHERE created_at >= NOW() - INTERVAL '24 hours'
            """
        )
        events_today = int(cur.fetchone()["total"])

        cur.execute(
            """
            SELECT COUNT(*) AS total
            FROM enrichment_queue
            WHERE created_at >= NOW() - INTERVAL '24 hours'
              AND status = 'completed'
            """
        )
        enrichments_today = int(cur.fetchone()["total"])

    cache_hits = 0
    try:
        r = _get_redis()
        raw = r.get("stats:cache_hits")
        cache_hits = int(raw) if raw else 0
    except Exception:
        pass

    return {
        "statuses": statuses,
        "events_today": events_today,
        "enrichments_today": enrichments_today,
        "cache_hits": cache_hits,
    }


@router.get("/api/taxonomy", dependencies=[Depends(verify_token)])
def list_taxonomy(search: str = "", offset: int = 0, limit: int = 50) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    data = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    packages = data.get("packages", {})
    categories = data.get("_meta", {}).get("categories", [])

    items = [
        {"package": pkg, **definition}
        for pkg, definition in packages.items()
        if not search or search.lower() in pkg.lower() or search.lower() in definition.get("category", "").lower()
    ]
    items.sort(key=lambda x: x["package"])
    total = len(items)
    page = items[offset : offset + limit]

    return {"items": page, "total": total, "offset": offset, "limit": limit, "categories": categories}
