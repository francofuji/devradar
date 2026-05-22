"""
Colector de repositorios del ecosistema desde GitHub.
Descubre nuevas entidades y detecta deltas de actividad en entidades conocidas.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

from github_client import GitHubClient
from db.events import emit_event
from db.queries import (
    upsert_developer,
    upsert_repository,
    repository_exists,
    get_repository,
    developer_exists,
    update_repo_monitored,
)

logger = logging.getLogger("collectors.github_trending")


def scan_ecosystem(client: GitHubClient | None = None) -> int:
    """
    Escanea GitHub con los parámetros de config.toml[ecosystem].
    Retorna cantidad de eventos emitidos.
    """
    with open("config.toml", "rb") as f:
        config = tomllib.load(f)

    eco = config["ecosystem"]

    if client is None:
        client = GitHubClient()

    events_emitted = 0

    for repo in client.search_repos(
        topics=eco["github_topics"],
        languages=eco["primary_languages"],
        min_stars=eco["min_stars"],
        max_stars=eco["max_stars"],
        created_after=eco["created_after"],
    ):
        try:
            if repository_exists(repo.full_name):
                events_emitted += check_activity_delta(repo.full_name, repo)
            else:
                events_emitted += _discover_repo(repo)
        except Exception as e:
            logger.error(f"Error procesando {repo.full_name}: {e}")
            continue

    logger.info(f"scan_ecosystem completo: {events_emitted} eventos emitidos")
    return events_emitted


def _discover_repo(repo) -> int:
    """
    Emite eventos de discovery para un repo nuevo.
    Retorna cantidad de eventos emitidos.
    """
    emitted = 0
    owner = repo.owner

    # Extraer topics de forma segura (puede requerir API call en PyGitHub)
    topics: list[str] = []
    try:
        t = repo.topics
        if t:
            topics = list(t)
    except Exception:
        topics = []

    pushed_at = repo.pushed_at.isoformat() if repo.pushed_at else None
    created_at = repo.created_at.isoformat() if repo.created_at else None

    # Upsert developer si no existe
    if not developer_exists(owner.login):
        upsert_developer({
            "id": owner.login,
            "github_url": owner.html_url,
        })

    # Upsert repository
    upsert_repository({
        "id": repo.full_name,
        "owner_id": owner.login,
        "primary_language": repo.language,
        "topics": topics,
        "description": repo.description,
        "homepage": repo.homepage,
        "stars": repo.stargazers_count,
        "forks": repo.forks_count,
        "open_issues": repo.open_issues_count,
        "last_push": pushed_at,
    })

    # Emit repository.discovered
    eid = emit_event(
        "repository.discovered",
        repo.full_name,
        "repository",
        {
            "full_name": repo.full_name,
            "owner_login": owner.login,
            "language": repo.language,
            "topics": topics,
            "stars": repo.stargazers_count,
            "created_at": created_at,
        },
        source="github",
        source_url=repo.html_url,
    )
    if eid:
        emitted += 1

    # Emit developer.discovered
    did = emit_event(
        "developer.discovered",
        owner.login,
        "developer",
        {
            "github_url": owner.html_url,
            "name": owner.login,
        },
        source="github",
        source_url=owner.html_url,
    )
    if did:
        emitted += 1

    return emitted


def check_activity_delta(repo_full_name: str, current_data) -> int:
    """
    Compara datos actuales del repo con los almacenados en DB.
    Emite eventos de delta cuando hay cambios relevantes.
    Retorna cantidad de eventos emitidos.
    """
    db_repo = get_repository(repo_full_name)
    if not db_repo:
        return 0

    emitted = 0
    owner_login = current_data.owner.login
    current_stars = current_data.stargazers_count
    current_issues = current_data.open_issues_count
    current_push_dt = current_data.pushed_at
    current_push = current_push_dt.isoformat() if current_push_dt else None

    # Stars spike: delta > 20%
    db_stars = db_repo["stars"] or 0
    if db_stars > 0 and current_stars > db_stars:
        delta_pct = (current_stars - db_stars) / db_stars
        if delta_pct > 0.20:
            eid = emit_event(
                "repo.stars_spiked",
                repo_full_name,
                "repository",
                {
                    "previous_stars": db_stars,
                    "current_stars": current_stars,
                    "delta_pct": round(delta_pct * 100, 1),
                },
                source="github",
                source_url=current_data.html_url,
            )
            if eid:
                emitted += 1
                logger.info(f"stars_spiked: {repo_full_name} {db_stars}→{current_stars} (+{delta_pct*100:.0f}%)")

    # Issue count changed
    db_issues = db_repo["open_issues"] or 0
    if current_issues != db_issues:
        eid = emit_event(
            "repo.issue_count_changed",
            repo_full_name,
            "repository",
            {
                "previous_count": db_issues,
                "current_count": current_issues,
                "delta": current_issues - db_issues,
            },
            source="github",
            source_url=current_data.html_url,
        )
        if eid:
            emitted += 1

    # Commit detected (push más reciente)
    db_last_push = db_repo["last_push"]
    db_last_push_value = db_last_push.isoformat() if hasattr(db_last_push, "isoformat") else db_last_push
    if current_push_dt and (not db_last_push or current_push_dt > db_last_push):
        eid = emit_event(
            "repo.commit_detected",
            repo_full_name,
            "repository",
            {
                "previous_push": db_last_push_value,
                "current_push": current_push,
            },
            source="github",
            source_url=current_data.html_url,
        )
        if eid:
            emitted += 1

    # Actualizar repo en DB con valores actuales
    topics: list[str] = []
    try:
        t = current_data.topics
        if t:
            topics = list(t)
    except Exception:
        topics = []

    upsert_repository({
        "id": repo_full_name,
        "owner_id": owner_login,
        "primary_language": current_data.language,
        "topics": topics,
        "description": current_data.description,
        "homepage": current_data.homepage,
        "stars": current_stars,
        "forks": current_data.forks_count,
        "open_issues": current_issues,
        "last_push": current_push,
    })
    update_repo_monitored(repo_full_name)

    return emitted
