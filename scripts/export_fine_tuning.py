"""
Export fine_tuning_examples to JSONL for Ollama / llama.cpp fine-tuning.

Usage (inside container):
    docker compose exec api python scripts/export_fine_tuning.py
    docker compose exec api python scripts/export_fine_tuning.py --task draft --min-quality 0.0 --only-edited
    docker compose exec api python scripts/export_fine_tuning.py --out /app/output/ft_export.jsonl

Output format (OpenAI chat / Ollama compatible):
    {"messages": [
        {"role": "system", "content": "..."},
        {"role": "user",   "content": "..."},
        {"role": "assistant", "content": "...approved_output..."}
    ]}

One line per example. Only includes examples where approved_output was
actually provided (was_edited=true OR source != 'ollama'), ensuring the
dataset contains human-curated or externally generated outputs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
sys.path.insert(0, _project_root)

from db import db_cursor


def export(
    task_type: str = "draft",
    min_quality: float = 0.0,
    only_edited: bool = False,
    out_path: str | None = None,
) -> Path:
    conditions = ["task_type = %s", "approved_output IS NOT NULL", "LENGTH(approved_output) >= 10"]
    params: list = [task_type]

    if only_edited:
        conditions.append("(was_edited = TRUE OR source NOT IN ('ollama'))")

    if min_quality > 0.0:
        conditions.append("quality_score >= %s")
        params.append(min_quality)

    query = f"""
        SELECT system_prompt, user_input, approved_output,
               entity_id, variant_label, source, quality_score, was_edited
        FROM fine_tuning_examples
        WHERE {' AND '.join(conditions)}
        ORDER BY approved_at DESC NULLS LAST, created_at DESC
    """

    with db_cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    if not rows:
        print("No examples found matching criteria.")
        return None

    output_dir = Path(_project_root) / "output" / "fine_tuning"
    output_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    default_name = f"{task_type}_examples_{date_str}.jsonl"
    out_file = Path(out_path) if out_path else output_dir / default_name

    written = 0
    skipped = 0
    with open(out_file, "w", encoding="utf-8") as f:
        for row in rows:
            system_prompt = (row["system_prompt"] or "").strip()
            user_input = (row["user_input"] or "").strip()
            approved_output = (row["approved_output"] or "").strip()

            if not system_prompt or not user_input or not approved_output:
                skipped += 1
                continue

            record = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input},
                    {"role": "assistant", "content": approved_output},
                ]
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1

    print(f"Exported {written} examples → {out_file}")
    if skipped:
        print(f"Skipped {skipped} incomplete rows")

    # Summary stats
    sources = {}
    edited_count = 0
    for row in rows:
        src = row["source"] or "unknown"
        sources[src] = sources.get(src, 0) + 1
        if row["was_edited"]:
            edited_count += 1

    print(f"\nBreakdown by source: {sources}")
    print(f"Edited by operator: {edited_count}/{len(rows)}")
    print(f"\nTo fine-tune with Ollama:")
    print(f"  ollama create {task_type}-ft -f Modelfile  # create Modelfile first")
    print(f"  # See: https://github.com/ollama/ollama/blob/main/docs/fine-tune.md")

    return out_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Export fine-tuning examples to JSONL")
    parser.add_argument("--task", default="draft", choices=["draft", "narrative", "extraction"])
    parser.add_argument("--min-quality", type=float, default=0.0, help="Min quality_score (0.0–1.0)")
    parser.add_argument("--only-edited", action="store_true", help="Only include human-edited or externally sourced examples")
    parser.add_argument("--out", default=None, help="Output file path (default: output/fine_tuning/)")
    args = parser.parse_args()

    export(
        task_type=args.task,
        min_quality=args.min_quality,
        only_edited=args.only_edited,
        out_path=args.out,
    )


if __name__ == "__main__":
    main()
