from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.deps import clear_dependency_caches
from db import db_cursor
from fine_tuning.export import export_examples

log = structlog.get_logger().bind(module="api.routers.training")
router = APIRouter(prefix="/api/training", tags=["training"])
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.toml"


def _load_config() -> dict[str, Any]:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore[no-redef]

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


class ExportRequest(BaseModel):
    task: str
    min_quality: float = 0.7
    output: str | None = None


@router.get("/stats")
def training_stats() -> dict[str, Any]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
                task_type,
                COUNT(*) AS total_examples,
                COUNT(*) FILTER (WHERE COALESCE(quality_score, 0) >= 0.7) AS high_quality_examples,
                AVG(CASE WHEN was_edited THEN 1.0 ELSE 0.0 END) AS avg_edit_rate
            FROM fine_tuning_examples
            GROUP BY task_type
            ORDER BY task_type
            """
        )
        rows = cur.fetchall()

        cur.execute(
            """
            SELECT COUNT(*) AS total_examples
            FROM fine_tuning_examples
            WHERE COALESCE(quality_score, 0) >= 0.7
            """
        )
        total_high_quality = int(cur.fetchone()["total_examples"])

    return {
        "by_task": [
            {
                "task_type": row["task_type"],
                "total_examples": int(row["total_examples"]),
                "high_quality_examples": int(row["high_quality_examples"]),
                "avg_edit_rate": float(row["avg_edit_rate"] or 0.0),
            }
            for row in rows
        ],
        "high_quality_total": total_high_quality,
        "eta_to_150": max(0, 150 - total_high_quality),
    }


@router.get("/examples")
def list_training_examples(
    task: str | None = None,
    outcome: str | None = None,
    min_quality: float = 0.0,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    where = ["COALESCE(quality_score, 0) >= %s"]
    params: list[Any] = [min_quality]
    if task:
        where.append("task_type = %s")
        params.append(task)
    if outcome:
        where.append("outcome = %s")
        params.append(outcome)
    params.extend([limit, offset])

    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, task_type, entity_id, provider, model_used, outcome, was_edited,
                   edit_distance, quality_score, created_at, approved_at
            FROM fine_tuning_examples
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        rows = cur.fetchall()

    return {"items": [dict(row) for row in rows], "limit": limit, "offset": offset, "count": len(rows)}


@router.post("/export")
def export_training_examples(payload: ExportRequest) -> dict[str, Any]:
    output_path = export_examples(payload.task, min_quality=payload.min_quality, output=payload.output)
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS total
            FROM fine_tuning_examples
            WHERE task_type = %s
              AND COALESCE(quality_score, 0) >= %s
            """,
            (payload.task, payload.min_quality),
        )
        row = cur.fetchone()
    return {"ok": True, "path": output_path, "task": payload.task, "count": int(row["total"])}


@router.get("/models")
def list_registered_models() -> dict[str, Any]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, task_type, model_name, base_model, training_examples,
                   eval_rouge_l, is_active, deployed_at, notes
            FROM model_registry
            ORDER BY deployed_at DESC
            """
        )
        rows = cur.fetchall()
    return {"items": [dict(row) for row in rows]}


class LaunchRequest(BaseModel):
    task: str = "narrative"
    base_model: str = "llama3.1:8b"
    epochs: int = 3
    min_quality: float = 0.7


@router.post("/launch")
def launch_training(payload: LaunchRequest) -> dict[str, Any]:
    """
    Valida que haya suficientes ejemplos y lanza train.py como proceso background.
    El progreso llega via SSE (PostgreSQL NOTIFY dev_intel_events type=training_progress).
    """
    valid_tasks = ("narrative", "draft", "extraction")
    if payload.task not in valid_tasks:
        raise HTTPException(status_code=400, detail=f"task debe ser uno de: {valid_tasks}")
    if not 1 <= payload.epochs <= 20:
        raise HTTPException(status_code=400, detail="epochs debe estar entre 1 y 20")

    # Verificar ejemplos disponibles
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(DISTINCT entity_id) AS total
            FROM fine_tuning_examples
            WHERE task_type = %s
              AND COALESCE(quality_score, 0) >= %s
              AND approved_output IS NOT NULL
              AND TRIM(approved_output) != ''
            """,
            (payload.task, payload.min_quality),
        )
        row = cur.fetchone()
        available = int(row["total"]) if row else 0

    MIN_EXAMPLES = 10  # Umbral mínimo para lanzar (100 para producción, 10 para desarrollo)
    if available < MIN_EXAMPLES:
        raise HTTPException(
            status_code=422,
            detail=f"Ejemplos insuficientes: {available} disponibles, mínimo {MIN_EXAMPLES} requeridos para task={payload.task!r}",
        )

    # Lanzar train.py como subproceso background
    train_script = Path(__file__).resolve().parent.parent.parent / "fine_tuning" / "train.py"
    cmd = [
        sys.executable, str(train_script),
        "--task",        payload.task,
        "--base-model",  payload.base_model,
        "--epochs",      str(payload.epochs),
        "--min-quality", str(payload.min_quality),
    ]

    log.info("training.launch", task=payload.task, base_model=payload.base_model,
             epochs=payload.epochs, available_examples=available)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # desacopla del proceso padre — sobrevive al request
        )
    except Exception as exc:
        log.error("training.launch_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Error lanzando train.py: {exc}") from exc

    return {
        "ok": True,
        "pid": proc.pid,
        "task": payload.task,
        "base_model": payload.base_model,
        "epochs": payload.epochs,
        "available_examples": available,
        "message": f"Fine-tuning iniciado (PID {proc.pid}). Sigue el progreso via SSE.",
    }


@router.post("/models/{model_id}/activate")
def activate_model(model_id: str) -> dict[str, Any]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, task_type, model_name, base_model
            FROM model_registry
            WHERE id = %s
            """,
            (model_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Modelo no encontrado: {model_id}")

        cur.execute("UPDATE model_registry SET is_active = FALSE WHERE task_type = %s", (row["task_type"],))
        cur.execute("UPDATE model_registry SET is_active = TRUE WHERE id = %s", (model_id,))

    config = _load_config()
    llm_cfg = dict(config.get("llm", {}))
    provider_key = "anthropic" if "claude" in row["model_name"].lower() else "ollama"
    llm_cfg[f"{provider_key}_model_{row['task_type']}"] = row["model_name"]
    config["llm"] = llm_cfg
    CONFIG_PATH.write_text(_dump_toml(config), encoding="utf-8")
    clear_dependency_caches()

    return {
        "ok": True,
        "model_id": model_id,
        "task_type": row["task_type"],
        "model_name": row["model_name"],
    }
