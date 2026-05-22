"""
E4.T3+T4 — Fetch de perfil completo de repo desde GitHub API.
Optimizado para minimizar API calls: 1 root listing + fetch selectivo.
"""
from __future__ import annotations

import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
sys.path = [p for p in sys.path if os.path.abspath(p) != _this_dir]
sys.path.insert(0, _project_root)

import logging
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from enrichment.types import IssueData, RepoProfile

logger = logging.getLogger("enrichment.github_profile")


# ── Root content helpers ─────────────────────────────────────────

def _list_root(repo) -> dict[str, str]:
    """One API call: returns {name: type} for items at repo root."""
    try:
        items = repo.get_contents("")
        if not isinstance(items, list):
            items = [items]
        return {item.name: item.type for item in items}
    except Exception as e:
        logger.debug(f"Could not list root for {repo.full_name}: {e}")
        return {}


def _fetch_content(repo, path: str) -> Optional[str]:
    """Fetch decoded content of a single file. Returns None on error."""
    try:
        item = repo.get_contents(path)
        if isinstance(item, list):
            item = item[0]
        return item.decoded_content.decode("utf-8", errors="replace")
    except Exception:
        return None


def _list_dir(repo, path: str) -> set[str]:
    """Returns set of names inside a directory path."""
    try:
        items = repo.get_contents(path)
        if not isinstance(items, list):
            items = [items]
        return {item.name for item in items}
    except Exception:
        return set()


# ── Service detection from .env.example ─────────────────────────

_SERVICE_PATTERNS: dict[str, list[str]] = {
    "stripe":    ["STRIPE_"],
    "openai":    ["OPENAI_"],
    "anthropic": ["ANTHROPIC_"],
    "sendgrid":  ["SENDGRID_"],
    "mailgun":   ["MAILGUN_"],
    "twilio":    ["TWILIO_"],
    "sentry":    ["SENTRY_"],
    "datadog":   ["DATADOG_", "DD_AGENT"],
    "postmark":  ["POSTMARK_"],
    "resend":    ["RESEND_"],
    "clerk":     ["CLERK_"],
    "auth0":     ["AUTH0_"],
    "supabase":  ["SUPABASE_"],
    "upstash":   ["UPSTASH_"],
    "redis":     ["REDIS_", "REDIS_URL"],
    "mongodb":   ["MONGO_", "MONGODB_"],
    "postgres":  ["POSTGRES_", "DATABASE_URL", "PG_"],
    "firebase":  ["FIREBASE_"],
    "aws":       ["AWS_"],
    "gcp":       ["GCP_", "GOOGLE_CLOUD_"],
    "azure":     ["AZURE_"],
    "vercel":    ["VERCEL_"],
    "planetscale": ["DATABASE_URL"],
}


def _parse_env_services(content: str) -> list[str]:
    services: list[str] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key = line.split("=")[0].strip().upper()
        for service, patterns in _SERVICE_PATTERNS.items():
            if service not in services and any(key.startswith(p) for p in patterns):
                services.append(service)
    return services


# ── Issue fetch (E4.T4) ─────────────────────────────────────────

def fetch_open_issues(repo, limit: int = 20) -> list[IssueData]:
    """
    Fetch oldest open issues (no body — metadata only).
    Skips pull requests.
    """
    issues: list[IssueData] = []
    try:
        for issue in repo.get_issues(state="open", sort="created", direction="asc"):
            if len(issues) >= limit:
                break
            if issue.pull_request:
                continue
            labels = [lbl.name for lbl in (issue.labels or [])]
            issues.append(IssueData(
                number=issue.number,
                title=issue.title,
                labels=labels,
                created_at=issue.created_at.isoformat() if issue.created_at else "",
                updated_at=issue.updated_at.isoformat() if issue.updated_at else "",
                comments_count=issue.comments or 0,
                has_linked_pr=False,  # skip timeline call to save API quota
                url=issue.html_url,
            ))
    except Exception as e:
        logger.warning(f"Error fetching issues for {repo.full_name}: {e}")
    return issues


# ── Main profile fetch (E4.T3) ──────────────────────────────────

def fetch_repo_profile(
    repo_full_name: str,
    github_client,
    fetch_issues: bool = True,
    fetch_readme: bool = True,
) -> Optional[RepoProfile]:
    """
    Fetch complete RepoProfile. Minimizes API calls via root listing.
    Returns None if repo is inaccessible.
    """
    repo = github_client.get_repo(repo_full_name)
    if repo is None:
        logger.warning(f"Repo no accesible: {repo_full_name}")
        return None

    logger.info(f"Fetching profile: {repo_full_name}")

    root = _list_root(repo)  # 1 API call

    # ── CI detection ─────────────────────────────────────────────
    has_github_dir = ".github" in root
    has_ci = (
        ".travis.yml" in root
        or "Jenkinsfile" in root
        or ".gitlab-ci.yml" in root
        or ".circleci" in root
    )
    if not has_ci and has_github_dir:
        github_children = _list_dir(repo, ".github")  # 1 API call if .github exists
        has_ci = "workflows" in github_children

    # ── Dockerfile ───────────────────────────────────────────────
    has_docker = (
        "Dockerfile" in root
        or "docker-compose.yml" in root
        or "docker-compose.yaml" in root
    )

    # ── .env.example ─────────────────────────────────────────────
    env_candidates = [".env.example", ".env.sample", ".env.template"]
    env_file = next((f for f in env_candidates if f in root), None)
    has_env_example = env_file is not None
    env_services: list[str] = []
    if env_file:
        env_content = _fetch_content(repo, env_file)  # 1 API call
        if env_content:
            env_services = _parse_env_services(env_content)

    # ── CHANGELOG ────────────────────────────────────────────────
    changelog_candidates = ["CHANGELOG.md", "CHANGELOG", "CHANGES.md", "HISTORY.md"]
    has_changelog = any(f in root for f in changelog_candidates)

    # ── docs/ folder ─────────────────────────────────────────────
    has_docs_folder = "docs" in root or "documentation" in root or "doc" in root

    # ── CONTRIBUTING ─────────────────────────────────────────────
    has_contributing = "CONTRIBUTING.md" in root or "CONTRIBUTING" in root

    # ── README ───────────────────────────────────────────────────
    readme_candidates = ["README.md", "README.rst", "README"]
    readme_file = next((f for f in readme_candidates if f in root), None)
    has_readme = readme_file is not None
    readme_content: Optional[str] = None
    readme_word_count = 0
    if fetch_readme and readme_file:
        readme_content = _fetch_content(repo, readme_file)  # 1 API call
        if readme_content:
            readme_word_count = len(readme_content.split())

    # ── Topics ───────────────────────────────────────────────────
    topics: list[str] = []
    try:
        t = repo.topics
        if t:
            topics = list(t)
    except Exception:
        try:
            topics = list(repo.get_topics())
        except Exception:
            topics = []

    # ── Open issues ──────────────────────────────────────────────
    open_issues: list[IssueData] = []
    if fetch_issues and repo.open_issues_count > 0:
        open_issues = fetch_open_issues(repo, limit=20)

    pushed_at = repo.pushed_at.isoformat() if repo.pushed_at else None
    created_at = repo.created_at.isoformat() if repo.created_at else ""

    return RepoProfile(
        full_name=repo.full_name,
        owner=repo.owner.login,
        primary_language=repo.language,
        topics=topics,
        description=repo.description,
        homepage=repo.homepage,
        stars=repo.stargazers_count,
        forks=repo.forks_count,
        open_issues_count=repo.open_issues_count,
        last_push=pushed_at,
        created_at=created_at,
        has_ci=has_ci,
        has_docker=has_docker,
        has_env_example=has_env_example,
        has_changelog=has_changelog,
        has_docs_folder=has_docs_folder,
        has_contributing=has_contributing,
        has_readme=has_readme,
        env_example_services=env_services,
        open_issues=open_issues,
        readme_content=readme_content,
        readme_word_count=readme_word_count,
    )
