"""
E18.T3 — Prepara el dataset de fine-tuning desde PostgreSQL.

Uso:
    python fine_tuning/prepare_dataset.py --task narrative [--min-quality 0.7]

Escribe:
    fine_tuning/data/{task}_train.jsonl
    fine_tuning/data/{task}_eval.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from db import db_cursor

DATA_DIR = _project_root / "fine_tuning" / "data"


def _to_chat_messages(row: dict) -> list[dict]:
    return [
        {"role": "system", "content": row["system_prompt"] or ""},
        {"role": "user",   "content": row["user_input"]},
        {"role": "assistant", "content": row["approved_output"]},
    ]


def prepare(
    task: str,
    min_quality: float = 0.7,
    seed: int = 42,
) -> dict:
    """
    Retorna stats: {"train": int, "eval": int, "total": int, "train_path": str, "eval_path": str}
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with db_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (entity_id)
                id, task_type, system_prompt, user_input, approved_output,
                quality_score, provider, model_used, entity_id, created_at
            FROM fine_tuning_examples
            WHERE task_type = %s
              AND COALESCE(quality_score, 0) >= %s
              AND approved_output IS NOT NULL
              AND TRIM(approved_output) != ''
            ORDER BY entity_id, quality_score DESC, created_at DESC
            """,
            (task, min_quality),
        )
        rows = [dict(r) for r in cur.fetchall()]

    if not rows:
        print(f"[prepare_dataset] Sin ejemplos para task={task!r} min_quality={min_quality}")
        return {"train": 0, "eval": 0, "total": 0}

    random.seed(seed)
    random.shuffle(rows)

    split = max(1, int(len(rows) * 0.8))
    train_rows = rows[:split]
    eval_rows  = rows[split:]

    train_path = DATA_DIR / f"{task}_train.jsonl"
    eval_path  = DATA_DIR / f"{task}_eval.jsonl"

    for path, subset in [(train_path, train_rows), (eval_path, eval_rows)]:
        with path.open("w", encoding="utf-8") as fh:
            for row in subset:
                record = {
                    "messages": _to_chat_messages(row),
                    "metadata": {
                        "entity_id":     row.get("entity_id"),
                        "quality_score": row.get("quality_score"),
                        "provider":      row.get("provider"),
                        "model_used":    row.get("model_used"),
                    },
                }
                fh.write(json.dumps(record, ensure_ascii=True) + "\n")

    stats = {
        "train": len(train_rows),
        "eval":  len(eval_rows),
        "total": len(rows),
        "train_path": str(train_path),
        "eval_path":  str(eval_path),
    }

    print(
        f"[prepare_dataset] task={task!r}  total={stats['total']}"
        f"  train={stats['train']}  eval={stats['eval']}"
        f"  → {train_path.name} / {eval_path.name}"
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepara dataset JSONL para fine-tuning")
    parser.add_argument("--task", required=True, choices=["narrative", "draft", "extraction"])
    parser.add_argument("--min-quality", type=float, default=0.7)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    stats = prepare(task=args.task, min_quality=args.min_quality, seed=args.seed)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
