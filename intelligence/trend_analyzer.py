"""
E8 — Weekly trend analyzer.
"""
from __future__ import annotations

import os
import re
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
sys.path.insert(0, _project_root)

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from db import get_connection

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "your", "repo",
    "issue", "latest", "current", "their", "there", "into", "have", "has",
    "are", "was", "were", "using", "detected", "runtime", "dependencies",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _current_week_number() -> int:
    return int(_utc_now().strftime("%V"))


def _fetch_signal_trends(days: int = 7) -> tuple[list[dict], list[dict]]:
    end = _utc_now()
    start = end - timedelta(days=days)
    baseline_start = start - timedelta(days=28)

    with get_connection() as conn:
        current = conn.execute(
            """
            SELECT signal_type, COUNT(*) AS count
            FROM signals
            WHERE detected_at >= ?
            GROUP BY signal_type
            ORDER BY count DESC
            """,
            (start.isoformat(),),
        ).fetchall()
        baseline = conn.execute(
            """
            SELECT signal_type, COUNT(*) AS count
            FROM signals
            WHERE detected_at >= ? AND detected_at < ?
            GROUP BY signal_type
            ORDER BY count DESC
            """,
            (baseline_start.isoformat(), start.isoformat()),
        ).fetchall()
    return [dict(r) for r in current], [dict(r) for r in baseline]


def _fetch_approaching_qualified() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, status, intent_score, trajectory_7d, trajectory_direction, maturity_score
            FROM developers
            WHERE intent_score BETWEEN 50 AND 74
              AND trajectory_7d >= 0
            ORDER BY intent_score DESC, trajectory_7d DESC
            LIMIT 20
            """
        ).fetchall()
    return [dict(r) for r in rows]


def _extract_issue_terms() -> list[tuple[str, int]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT memory
            FROM entity_memory
            WHERE status = 'active'
            ORDER BY created_at DESC
            LIMIT 50
            """
        ).fetchall()

    counter: Counter[str] = Counter()
    for row in rows:
        memory = row["memory"] if isinstance(row["memory"], dict) else {}
        for signal in memory.get("confirmed_pain_signals", []):
            evidence = str(signal.get("evidence", ""))
            for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", evidence.lower()):
                if token in STOPWORDS:
                    continue
                counter[token] += 1
    return counter.most_common(10)


def _fetch_watchlist() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, intent_score, trajectory_7d, trajectory_direction, status
            FROM developers
            WHERE status = 'WARM'
              AND trajectory_7d > 0
            ORDER BY trajectory_7d DESC, intent_score DESC
            LIMIT 20
            """
        ).fetchall()
    return [dict(r) for r in rows]


def generate_weekly_report(week_number: int | None = None) -> str:
    week = week_number or _current_week_number()
    current_signals, baseline_signals = _fetch_signal_trends()
    approaching = _fetch_approaching_qualified()
    terms = _extract_issue_terms()
    watchlist = _fetch_watchlist()

    output_dir = Path(_project_root) / "output" / "weekly"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"week_{week}.md"

    current_map = {row["signal_type"]: row["count"] for row in current_signals}
    baseline_map = {row["signal_type"]: row["count"] for row in baseline_signals}
    signal_lines = []
    for signal_type, count in sorted(current_map.items(), key=lambda item: item[1], reverse=True)[:10]:
        previous = baseline_map.get(signal_type, 0)
        signal_lines.append(f"- `{signal_type}` — this week={count}, previous_4_weeks={previous}")

    approaching_lines = [
        f"- `{row['id']}` — intent={row['intent_score']} trajectory_7d={row['trajectory_7d']} status={row['status']}"
        for row in approaching
    ]
    term_lines = [f"- `{term}` — {count}" for term, count in terms]
    watch_lines = [
        f"- `{row['id']}` — trajectory_7d={row['trajectory_7d']} intent={row['intent_score']} | ETA to QUALIFIED: needs WARM + intent>=75"
        for row in watchlist
    ]

    content = "\n".join([
        f"# Weekly Report — Week {week}",
        "",
        "## Stack signals observed",
        *(signal_lines or ["Sin novedades"]),
        "",
        "## Entities approaching QUALIFIED",
        *(approaching_lines or ["Sin novedades"]),
        "",
        "## Frequent issue terms",
        *(term_lines or ["Sin novedades"]),
        "",
        "## Entidades en vigilancia",
        *(watch_lines or ["Sin novedades"]),
        "",
    ])

    path.write_text(content, encoding="utf-8")
    return str(path)


def main() -> None:
    print(generate_weekly_report())


if __name__ == "__main__":
    main()
