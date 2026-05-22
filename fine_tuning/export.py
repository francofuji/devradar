from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import structlog

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from db import db_cursor

log = structlog.get_logger().bind(module="fine_tuning.export")


def export_examples(
    task: str,
    min_quality: float = 0.7,
    output: str | None = None,
) -> str:
    output_dir = Path(_project_root) / "fine_tuning" / "data"
    output_dir.mkdir(parents=True, exist_ok=True)

    if output is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"{task}_examples_{stamp}.jsonl"
    else:
        output_path = Path(output)
        if not output_path.is_absolute():
            output_path = Path(_project_root) / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

    with db_cursor() as cur:
        cur.execute(
            """
            SELECT task_type, system_prompt, user_input, approved_output,
                   quality_score, provider, model_used, entity_id, created_at
            FROM fine_tuning_examples
            WHERE task_type = %s
              AND COALESCE(quality_score, 0) >= %s
            ORDER BY quality_score DESC, created_at ASC
            """,
            (task, min_quality),
        )
        rows = cur.fetchall()

    with output_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            record = {
                "messages": [
                    {"role": "system", "content": row["system_prompt"]},
                    {"role": "user", "content": row["user_input"]},
                    {"role": "assistant", "content": row["approved_output"]},
                ],
                "metadata": {
                    "task_type": row["task_type"],
                    "quality_score": row["quality_score"],
                    "provider": row["provider"],
                    "model_used": row["model_used"],
                    "entity_id": row["entity_id"],
                    "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"],
                },
            }
            fh.write(json.dumps(record, ensure_ascii=True) + "\n")

    log.info(
        "fine_tuning.export_complete",
        task=task,
        min_quality=min_quality,
        count=len(rows),
        output=str(output_path),
    )
    return str(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Exporta ejemplos de fine-tuning a JSONL")
    parser.add_argument("--task", required=True, choices=["narrative", "draft", "extraction"])
    parser.add_argument("--min-quality", type=float, default=0.7)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    output_path = export_examples(
        task=args.task,
        min_quality=args.min_quality,
        output=args.output,
    )
    print(output_path)


if __name__ == "__main__":
    main()
