"""
E4.T7 — Partial enrichment: updates ligeros sin LLM, disparados por
         actividad en repos conocidos.

Tipos de trigger:
  stars_spiked         → actualiza stars, emite señal de actividad
  issue_count_changed  → re-fetch issues, encola pain_check si E5 disponible
  commit_detected      → actualiza last_push, emite señal commit_velocity
  (default)            → actualiza last_monitored sin re-enrichment
"""
from __future__ import annotations

import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
sys.path = [p for p in sys.path if os.path.abspath(p) != _this_dir]
sys.path.insert(0, _project_root)

import logging
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from db.queries import (
    emit_signal,
    enqueue_enrichment,
    get_repository,
    log_enrichment_cost,
    update_repo_monitored,
)

logger = logging.getLogger("enrichment.partial_enrichment")


def run_partial_enrichment(
    entity_id: str,
    trigger_event_type: str,
    github_client=None,
) -> bool:
    """
    Lightweight update based on trigger event type.
    entity_id is typically 'owner/repo' for repo-triggered events.
    Returns True on success.
    """
    logger.info(f"Partial enrichment: {entity_id} (trigger={trigger_event_type})")

    # Resolve developer_id (owner) for signals
    if "/" in entity_id:
        developer_id = entity_id.split("/")[0].lower()
        repo_id = entity_id
    else:
        developer_id = entity_id.lower()
        repo_id = None

    if github_client is None:
        sys.path.insert(0, os.path.join(_project_root, "collectors"))
        from github_client import GitHubClient
        github_client = GitHubClient()

    try:
        if trigger_event_type == "repo.stars_spiked":
            return _handle_stars_spiked(repo_id or entity_id, developer_id, github_client)

        elif trigger_event_type == "repo.issue_count_changed":
            return _handle_issue_count_changed(repo_id or entity_id, developer_id, github_client)

        elif trigger_event_type == "repo.commit_detected":
            return _handle_commit_detected(repo_id or entity_id, developer_id, github_client)

        else:
            # Generic partial: just update last_monitored timestamp
            if repo_id:
                update_repo_monitored(repo_id)
            logger.info(f"Generic partial update for {entity_id} ({trigger_event_type})")
            return True

    except Exception as e:
        logger.error(f"Partial enrichment failed for {entity_id}: {e}", exc_info=True)
        return False
    finally:
        # Always log cost (0 for partial — no LLM)
        try:
            log_enrichment_cost(
                entity_id=developer_id,
                enrichment_type="partial",
                llm_calls=0,
                input_tokens=0,
                output_tokens=0,
            )
        except Exception:
            pass


def _handle_stars_spiked(
    repo_id: str,
    developer_id: str,
    github_client,
) -> bool:
    """Update stars in DB and emit stars activity signal."""
    from db import get_connection

    repo = github_client.get_repo(repo_id)
    if repo is None:
        return False

    current_stars = repo.stargazers_count
    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.execute(
            "UPDATE repositories SET stars = ? WHERE id = ?",
            (current_stars, repo_id),
        )
        conn.commit()

    emit_signal(
        entity_id=developer_id,
        category="activity",
        signal_type="stars_spike",
        base_score=15.0,
        half_life_days=5.0,
        evidence=f"{repo_id} now has {current_stars} stars",
    )

    logger.info(f"stars_spiked: updated {repo_id} to {current_stars} stars")
    update_repo_monitored(repo_id)
    return True


def _handle_issue_count_changed(
    repo_id: str,
    developer_id: str,
    github_client,
) -> bool:
    """Re-fetch issues and enqueue pain_check if E5 is available."""
    from enrichment.github_profile import fetch_open_issues

    repo = github_client.get_repo(repo_id)
    if repo is None:
        return False

    issues = fetch_open_issues(repo, limit=10)

    # Look for pain signals in issue titles (heuristic — no LLM in E4)
    pain_keywords = {
        "api_cost": ["rate limit", "429", "quota", "billing", "cost", "expensive"],
        "scaling":  ["slow", "timeout", "latency", "oom", "memory", "performance"],
        "reliability": ["flaky", "broken", "crash", "fail", "error"],
        "auth":     ["auth", "token", "permission", "unauthorized", "403"],
    }

    for issue in issues:
        title_lower = issue.title.lower()
        for category, keywords in pain_keywords.items():
            if any(kw in title_lower for kw in keywords):
                emit_signal(
                    entity_id=developer_id,
                    category=category,
                    signal_type=f"issue_pain_{category}",
                    base_score=10.0,
                    half_life_days=30.0,
                    evidence=f"Issue #{issue.number}: {issue.title[:120]}",
                )
                break

    # Enqueue pain_check (E5 will process it when available)
    try:
        enqueue_enrichment(
            entity_id=repo_id,
            enrichment_type="pain_check",
            priority=3,
        )
    except Exception:
        pass

    logger.info(f"issue_count_changed: processed {len(issues)} issues for {repo_id}")
    update_repo_monitored(repo_id)
    return True


def _handle_commit_detected(
    repo_id: str,
    developer_id: str,
    github_client,
) -> bool:
    """Update last_push and emit commit_velocity signal."""
    from db import get_connection

    repo = github_client.get_repo(repo_id)
    if repo is None:
        return False

    pushed_at = repo.pushed_at.isoformat() if repo.pushed_at else None

    with get_connection() as conn:
        conn.execute(
            "UPDATE repositories SET last_push = ? WHERE id = ?",
            (pushed_at, repo_id),
        )
        conn.commit()

    emit_signal(
        entity_id=developer_id,
        category="activity",
        signal_type="commit_velocity",
        base_score=8.0,
        half_life_days=10.0,
        evidence=f"Commit detected in {repo_id} at {pushed_at}",
    )

    logger.info(f"commit_detected: updated {repo_id} last_push to {pushed_at}")
    update_repo_monitored(repo_id)
    return True
