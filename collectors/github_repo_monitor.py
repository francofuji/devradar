"""
Monitor de repos conocidos. Detecta deltas de actividad en entidades ya
registradas en la DB. Rota por last_monitored ASC para distribución equitativa.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from github_client import GitHubClient
from github_trending import check_activity_delta
from db.queries import get_repos_to_monitor, update_repo_monitored

logger = logging.getLogger("collectors.github_repo_monitor")


def monitor_known_repos(
    client: GitHubClient | None = None,
    limit: int = 100,
) -> int:
    """
    Monitorea repos conocidos. Detecta y emite deltas de actividad.
    Rotación por last_monitored ASC (NULL primero).
    Retorna cantidad de eventos emitidos.
    """
    if client is None:
        client = GitHubClient()

    repos = get_repos_to_monitor(limit=limit)
    logger.info(f"Monitoreando {len(repos)} repos")

    emitted = 0

    for repo_row in repos:
        repo_id = repo_row["id"]

        try:
            current = client.get_repo(repo_id)

            if current is None:
                # Repo eliminado o privado — actualizar timestamp igual para no re-intentar siempre
                logger.warning(f"Repo no accesible: {repo_id}")
                update_repo_monitored(repo_id)
                continue

            delta = check_activity_delta(repo_id, current)
            emitted += delta

            # update_repo_monitored ya es llamado por check_activity_delta,
            # pero si delta=0 (no hubo eventos) igual actualizar el timestamp
            if delta == 0:
                update_repo_monitored(repo_id)

        except Exception as e:
            logger.error(f"Error monitoreando {repo_id}: {e}")
            # Actualizar timestamp para evitar re-intentos continuos en repos rotos
            try:
                update_repo_monitored(repo_id)
            except Exception:
                pass
            continue

    logger.info(f"Monitor completo: {emitted} eventos emitidos de {len(repos)} repos")
    return emitted
