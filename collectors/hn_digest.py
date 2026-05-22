"""
Colector de Show HN stories relacionadas con el ecosistema.
Usa Algolia HN API para filtrar por tags=show_hn y keywords del ecosistema.
"""
from __future__ import annotations

import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from db.events import emit_event
from db.queries import developer_exists, upsert_developer

logger = logging.getLogger("collectors.hn_digest")

HN_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"

# Regex para extraer owner/repo de URLs de GitHub
GITHUB_REPO_RE = re.compile(
    r'github\.com/([a-zA-Z0-9][a-zA-Z0-9_-]{0,38})/([a-zA-Z0-9][a-zA-Z0-9_.-]{0,99})',
    re.IGNORECASE,
)

# Handles de GitHub que no son repos
_GITHUB_NON_REPO_PATHS = frozenset({
    "topics", "trending", "explore", "organizations", "search",
    "features", "pricing", "about", "contact", "security",
    "marketplace", "sponsors", "login", "join",
})

ECOSYSTEM_KEYWORDS = [
    "mcp", "langchain", "browser automation", "ai agent",
    "playwright automation", "llm agent", "claude", "openai",
    "anthropic", "crewai", "fastmcp", "pydantic-ai",
]

# Construimos la query de Algolia combinando algunos keywords representativos
_ALGOLIA_QUERY = " OR ".join(ECOSYSTEM_KEYWORDS[:8])


def scan_hn(hours_back: int = 4) -> int:
    """
    Escanea HN Show HN stories de las últimas `hours_back` horas.
    Retorna cantidad de eventos emitidos.
    """
    since_ts = int(
        (datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp()
    )

    params = {
        "tags": "show_hn",
        "query": _ALGOLIA_QUERY,
        "hitsPerPage": 50,
        "numericFilters": f"created_at_i>{since_ts}",
    }

    try:
        resp = requests.get(HN_ALGOLIA_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f"HN Algolia API error: {e}")
        return 0

    hits = data.get("hits", [])
    logger.info(f"HN scan: {len(hits)} Show HN stories encontradas")

    emitted = 0
    for hit in hits:
        try:
            emitted += _process_hit(hit)
        except Exception as e:
            logger.error(f"Error procesando hit {hit.get('objectID')}: {e}")
            continue

    return emitted


def _process_hit(hit: dict) -> int:
    """
    Procesa un hit de HN. Emite developer.product_launched si hay GitHub URL.
    Retorna 1 si se emitió evento, 0 si no.
    """
    title = hit.get("title", "")
    url = hit.get("url") or ""
    story_text = hit.get("story_text") or ""
    hn_id = hit.get("objectID", "")

    # Filtro adicional: título o URL deben mencionar keywords del ecosistema
    searchable = (title + " " + url + " " + story_text).lower()
    if not any(kw.lower() in searchable for kw in ECOSYSTEM_KEYWORDS):
        return 0

    # Extraer GitHub URL del campo url primero, luego del texto
    github_match = _extract_github_repo(url) or _extract_github_repo(story_text)
    if not github_match:
        return 0

    owner_login, repo_name = github_match
    repo_full_name = f"{owner_login}/{repo_name}"
    hn_url = f"https://news.ycombinator.com/item?id={hn_id}"

    # Upsert developer si no existe
    if not developer_exists(owner_login):
        upsert_developer({
            "id": owner_login,
            "github_url": f"https://github.com/{owner_login}",
        })

    eid = emit_event(
        "developer.product_launched",
        owner_login,
        "developer",
        {
            "hn_url": hn_url,
            "github_url": f"https://github.com/{repo_full_name}",
            "repo_full_name": repo_full_name,
            "title": title,
            "points": hit.get("points", 0) or 0,
            "num_comments": hit.get("num_comments", 0) or 0,
        },
        source="hn",
        source_url=hn_url,
    )

    if eid:
        logger.info(f"product_launched: {owner_login} — '{title}' ({hn_url})")
        return 1
    return 0


def _extract_github_repo(text: str) -> tuple[str, str] | None:
    """
    Extrae (owner, repo) del primer match de GitHub URL en el texto.
    Retorna None si no encuentra o el path no es owner/repo válido.
    """
    if not text:
        return None

    match = GITHUB_REPO_RE.search(text)
    if not match:
        return None

    owner = match.group(1).lower()
    repo = match.group(2).lower()

    # Remover sufijo .git
    if repo.endswith(".git"):
        repo = repo[:-4]

    # Filtrar paths que no son repos
    if owner in _GITHUB_NON_REPO_PATHS:
        return None

    # Evitar paths demasiado cortos o que parecen rutas de archivos
    if len(owner) < 2 or len(repo) < 2:
        return None
    if "." in owner:
        return None

    return (owner, repo)
