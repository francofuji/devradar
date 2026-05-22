"""
Heuristic dependency parser — E3.

Parse dependency files from GitHub repos and classify the tech stack
using taxonomy/dependencies.json. No LLM calls; pure heuristics.

Entry points:
  parse_dependency_file(repo_full_name, github_client) -> StackSnapshot
  classify_stack(runtime_deps, dev_deps, primary_language) -> StackSnapshot
  compute_maturity_score(stack_snapshot, repo_profile) -> MaturityResult
"""
from __future__ import annotations

import os
import sys

# enrichment/ is added to sys.path[0] by Python when running this file directly.
# enrichment/types.py shadows stdlib's `types` module, breaking all imports.
# Fix: remove enrichment/ from sys.path and add project root.
# Must use `os` (already loaded by interpreter) — cannot use pathlib yet.
_this_file = os.path.abspath(__file__)
_enrichment_dir = os.path.dirname(_this_file)
_project_root = os.path.dirname(_enrichment_dir)
sys.path = [p for p in sys.path if os.path.abspath(p) != _enrichment_dir]
sys.path.insert(0, _project_root)

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

from enrichment.types import MaturityResult, MaturityTier, StackSnapshot

logger = logging.getLogger("enrichment.dependency_parser")

# ── Taxonomy loading ─────────────────────────────────────────────

_TAXONOMY: dict | None = None
_TAXONOMY_PATH = Path(__file__).parent.parent / "taxonomy" / "dependencies.json"


def _get_taxonomy() -> dict:
    global _TAXONOMY
    if _TAXONOMY is None:
        _TAXONOMY = json.loads(_TAXONOMY_PATH.read_text())["packages"]
    return _TAXONOMY


# ── File parsing ─────────────────────────────────────────────────

def _parse_package_json(content: str) -> tuple[list[str], list[str]]:
    """Returns (runtime_deps, dev_deps) package name lists."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return [], []
    runtime = list(data.get("dependencies", {}).keys())
    dev = list(data.get("devDependencies", {}).keys())
    return runtime, dev


def _parse_requirements_txt(content: str) -> tuple[list[str], list[str]]:
    """Returns (runtime_deps, dev_deps=[]) from requirements.txt."""
    packages = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Strip version specifier: pkg>=1.0 → pkg
        for sep in (">=", "<=", "==", "!=", "~=", ">", "<", "[", ";"):
            if sep in line:
                line = line[: line.index(sep)]
        packages.append(line.strip().lower())
    return packages, []


def _parse_pyproject_toml(content: str) -> tuple[list[str], list[str]]:
    """Returns (runtime_deps, dev_deps) from pyproject.toml."""
    try:
        data = tomllib.loads(content)
    except Exception:
        return [], []

    runtime: list[str] = []
    dev: list[str] = []

    # [project] dependencies
    project = data.get("project", {})
    for dep in project.get("dependencies", []):
        name = dep.split()[0].split(">=")[0].split("==")[0].split("[")[0]
        runtime.append(name.strip().lower())

    # [project.optional-dependencies] dev/test groups
    opt_deps = project.get("optional-dependencies", {})
    for group_name, deps in opt_deps.items():
        target = dev if any(g in group_name for g in ("dev", "test", "lint")) else runtime
        for dep in deps:
            name = dep.split()[0].split(">=")[0].split("==")[0].split("[")[0]
            target.append(name.strip().lower())

    # poetry: [tool.poetry.dependencies] / [tool.poetry.dev-dependencies]
    poetry = data.get("tool", {}).get("poetry", {})
    for dep in poetry.get("dependencies", {}):
        if dep.lower() != "python":
            runtime.append(dep.lower())
    for dep in poetry.get("dev-dependencies", {}):
        dev.append(dep.lower())

    return runtime, dev


# ── GitHub file fetcher ──────────────────────────────────────────

def _fetch_file(repo_full_name: str, path: str, client) -> Optional[str]:
    """Fetch raw file content via GitHub API. Returns None on 404/error."""
    try:
        repo = client.get_repo(repo_full_name)
        if repo is None:
            return None
        contents = repo.get_contents(path)
        if contents is None:
            return None
        return contents.decoded_content.decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug(f"Could not fetch {repo_full_name}/{path}: {e}")
        return None


# ── Main entry point ─────────────────────────────────────────────

def parse_dependency_file(
    repo_full_name: str,
    github_client,
) -> StackSnapshot:
    """
    Fetch dependency file from GitHub and return classified StackSnapshot.
    Tries: package.json → requirements.txt → pyproject.toml.
    """
    files_to_try = [
        ("package.json", _parse_package_json),
        ("requirements.txt", _parse_requirements_txt),
        ("pyproject.toml", _parse_pyproject_toml),
    ]

    for filename, parser in files_to_try:
        content = _fetch_file(repo_full_name, filename, github_client)
        if content is not None:
            logger.info(f"{repo_full_name}: found {filename}")
            runtime_raw, dev_raw = parser(content)
            snapshot = classify_stack(runtime_raw, dev_raw, primary_language=None)
            snapshot.file_found = filename
            return snapshot

    logger.warning(f"{repo_full_name}: no dependency file found")
    return StackSnapshot(file_found=None, raw_count=0)


# ── Stack classifier ─────────────────────────────────────────────

# Categories that live in dev_deps rather than runtime_deps
_DEV_CATEGORIES = {"testing", "linting", "bundler"}

# Taxonomy categories → StackSnapshot.runtime_deps keys
_RUNTIME_CATEGORY_MAP = {
    "ai_llm":             "ai_llm",
    "ai_framework":       "ai_framework",
    "ai_observability":   "monitoring",
    "browser_automation": "browser_automation",
    "testing":            None,          # routed to dev_deps
    "payments":           "payments",
    "auth":               "auth",
    "database":           "database",
    "queues":             "queues",
    "caching":            "caching",
    "monitoring":         "monitoring",
    "logging":            "logging",
    "analytics":          "analytics",
    "email":              "email",
    "validation":         "validation",
    "infra":              "infra",
    "mcp":                "mcp",
}

# Dev dependency pattern matching
_DEV_INDICATORS = {
    # testing
    "pytest", "jest", "mocha", "vitest", "jasmine", "karma", "ava",
    "unittest", "nose2", "hypothesis", "factory-boy", "nock", "chai",
    "cypress", "robotframework", "k6", "artillery", "autocannon",
    # linting
    "eslint", "prettier", "pylint", "flake8", "ruff", "mypy", "black",
    "isort", "bandit", "tslint", "stylelint",
    # bundler
    "webpack", "vite", "esbuild", "rollup", "parcel", "turbopack",
    "bun", "swc",
}

_LINTING_INDICATORS = {"eslint", "prettier", "pylint", "flake8", "ruff", "mypy", "black", "isort", "bandit"}
_BUNDLER_INDICATORS = {"webpack", "vite", "esbuild", "rollup", "parcel", "swc", "turbopack"}
_TEST_INDICATORS = _DEV_INDICATORS - _LINTING_INDICATORS - _BUNDLER_INDICATORS


def classify_stack(
    runtime_raw: list[str],
    dev_raw: list[str],
    primary_language: Optional[str],
) -> StackSnapshot:
    """
    Classify package lists into StackSnapshot using taxonomy + heuristics.
    Logs unclassified packages to logs/unclassified_YYYY-MM-DD.log.
    """
    taxonomy = _get_taxonomy()
    snapshot = StackSnapshot(primary_language=primary_language)

    all_raw = runtime_raw + dev_raw
    snapshot.raw_count = len(all_raw)

    budget_set: set[str] = set()
    archetype_set: set[str] = set()
    scaling_set: set[str] = set()
    pain_set: set[str] = set()
    maturity_mod = 0
    unclassified: list[str] = []

    def classify_pkg(pkg_name: str, is_dev: bool) -> None:
        nonlocal maturity_mod
        norm = pkg_name.lower().strip()
        entry = taxonomy.get(norm)

        if entry is None:
            # Fallback: try with common name normalizations
            # e.g. "@anthropic-ai/sdk" might also be stored without @scope
            fallback = norm.lstrip("@").replace("/", "-")
            entry = taxonomy.get(fallback)

        if entry is None:
            # Heuristic classification for dev deps by name pattern
            if is_dev or norm in _DEV_INDICATORS:
                if norm in _LINTING_INDICATORS:
                    snapshot.dev_deps["linting"].append(norm)
                elif norm in _BUNDLER_INDICATORS:
                    snapshot.dev_deps["bundler"].append(norm)
                elif norm in _TEST_INDICATORS:
                    snapshot.dev_deps["testing"].append(norm)
                else:
                    unclassified.append(norm)
            else:
                unclassified.append(norm)
            return

        cat = entry["category"]
        runtime_key = _RUNTIME_CATEGORY_MAP.get(cat)

        # Route to dev_deps or runtime_deps
        if cat == "testing" or (is_dev and norm in _DEV_INDICATORS):
            # further sub-classify dev entries
            if norm in _LINTING_INDICATORS:
                snapshot.dev_deps["linting"].append(norm)
            elif norm in _BUNDLER_INDICATORS:
                snapshot.dev_deps["bundler"].append(norm)
            else:
                snapshot.dev_deps["testing"].append(norm)
        elif runtime_key:
            if runtime_key not in snapshot.runtime_deps:
                snapshot.runtime_deps[runtime_key] = []
            snapshot.runtime_deps[runtime_key].append(norm)
        else:
            unclassified.append(norm)

        # Accumulate signals
        if entry.get("budget_signal") in ("possible", "confirmed"):
            budget_set.add(norm)
        for a in entry.get("archetype_signals", []):
            archetype_set.add(a)
        if entry.get("scaling_signal"):
            scaling_set.add(norm)
        if entry.get("pain_category"):
            pain_set.add(entry["pain_category"])

        maturity_mod += entry.get("maturity_modifier", 0)

    for pkg in runtime_raw:
        classify_pkg(pkg, is_dev=False)
    for pkg in dev_raw:
        classify_pkg(pkg, is_dev=True)

    snapshot.unclassified = unclassified
    snapshot.budget_signals = sorted(budget_set)
    snapshot.archetype_signals = sorted(archetype_set)
    snapshot.scaling_signals = sorted(scaling_set)
    snapshot.pain_signals = sorted(pain_set)
    snapshot.maturity_modifier = maturity_mod

    # Log unclassified packages
    if unclassified:
        _log_unclassified(unclassified)

    return snapshot


def _log_unclassified(packages: list[str]) -> None:
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_path = log_dir / f"unclassified_{today}.log"
    ts = datetime.now(timezone.utc).isoformat()
    with log_path.open("a", encoding="utf-8") as f:
        for pkg in packages:
            f.write(f"{ts}\t{pkg}\n")


# ── Maturity scorer ──────────────────────────────────────────────

def compute_maturity_score(
    stack: StackSnapshot,
    repo_profile=None,
) -> MaturityResult:
    """
    Compute maturity score using CLAUDE.md point table.
    repo_profile is an optional RepoProfile dataclass instance.
    """
    score = 0
    breakdown: dict[str, int] = {}

    # ── Language / type safety ───────────────────────────────────
    lang = (stack.primary_language or "").lower()
    if lang == "typescript":
        score += 10
        breakdown["typescript"] = 10
    if stack.dev_deps.get("testing"):
        score += 10
        breakdown["test_framework"] = 10
    has_e2e = any(
        p in stack.dev_deps.get("testing", [])
        for p in ("cypress", "playwright", "puppeteer", "robotframework", "e2e")
    )
    if has_e2e:
        score += 8
        breakdown["e2e_tests"] = 8
    has_type_safety = bool(
        lang == "typescript"
        or any(p in (stack.dev_deps.get("linting", []) + stack.runtime_deps.get("validation", []))
               for p in ("mypy", "pydantic", "zod", "typebox"))
    )
    if lang != "typescript" and any(
        p in stack.runtime_deps.get("validation", []) for p in ("pydantic", "zod")
    ):
        score += 8
        breakdown["type_validation"] = 8

    if any(p in stack.dev_deps.get("linting", []) for p in ("eslint", "prettier")):
        score += 5
        breakdown["linting"] = 5

    # ── Infrastructure signals from repo_profile ─────────────────
    has_ci_cd = False
    has_deploy_step = False
    has_multi_env = False
    has_docker = False
    has_changelog = False
    has_docs = False
    last_commit_days: Optional[int] = None
    release_freq: Optional[int] = None
    contributors = 1
    is_actively_maintained = False

    if repo_profile is not None:
        has_docker = getattr(repo_profile, "has_docker", False)
        has_changelog = getattr(repo_profile, "has_changelog", False)
        has_docs = getattr(repo_profile, "has_docs_folder", False)
        has_ci_cd = getattr(repo_profile, "has_ci", False)

        if has_ci_cd and has_deploy_step:
            score += 15
            breakdown["ci_cd_with_deploy"] = 15
        elif has_ci_cd:
            score += 8
            breakdown["ci_cd"] = 8

        if has_docker:
            score += 8
            breakdown["docker"] = 8

        if has_multi_env:
            score += 10
            breakdown["multi_env_ci"] = 10

        if has_changelog:
            score += 5
            breakdown["changelog"] = 5

        if has_docs:
            score += 5
            breakdown["docs_folder"] = 5

        # Maintenance activity
        last_push = getattr(repo_profile, "last_push", None)
        if last_push:
            try:
                pushed = datetime.fromisoformat(last_push.replace("Z", "+00:00"))
                last_commit_days = (datetime.now(timezone.utc) - pushed).days
                if last_commit_days <= 7:
                    score += 10
                    breakdown["recent_commit"] = 10
                    is_actively_maintained = True
            except Exception:
                pass

    # ── Stack-based signals ───────────────────────────────────────
    has_observability = stack.has_monitoring()
    if has_observability:
        score += 8
        breakdown["observability"] = 8

    has_payments_flag = stack.has_payments()
    if has_payments_flag:
        score += 12
        breakdown["payments"] = 12

    has_auth_flag = stack.has_auth()
    if has_auth_flag:
        score += 8
        breakdown["auth_library"] = 8

    has_analytics = len(stack.runtime_deps.get("analytics", [])) > 0
    if has_analytics:
        score += 6
        breakdown["analytics"] = 6

    # Add taxonomy-derived modifier (capped to avoid runaway scores)
    taxonomy_bonus = min(stack.maturity_modifier, 20)
    if taxonomy_bonus > 0:
        score += taxonomy_bonus
        breakdown["taxonomy_bonus"] = taxonomy_bonus

    # Clamp to 0–100
    score = max(0, min(100, score))

    return MaturityResult(
        score=score,
        tier=MaturityTier.from_score(score),
        has_tests=bool(stack.dev_deps.get("testing")),
        has_e2e_tests=has_e2e,
        has_type_safety=has_type_safety,
        has_observability=has_observability,
        has_ci_cd=has_ci_cd,
        has_deploy_step=has_deploy_step,
        has_multi_env=has_multi_env,
        has_docker=has_docker,
        has_payments=has_payments_flag,
        has_auth=has_auth_flag,
        has_analytics=has_analytics,
        is_actively_maintained=is_actively_maintained,
        last_commit_days_ago=last_commit_days,
        release_frequency_days=release_freq,
        contributors_count=contributors,
        breakdown=breakdown,
    )


# ── CLI entry point ──────────────────────────────────────────────

def _cli() -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Parse and classify repo dependencies")
    parser.add_argument("--repo", required=True, help="owner/repo on GitHub")
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN"),
        help="GitHub token (defaults to GITHUB_TOKEN env var)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    sys.path.insert(0, str(Path(__file__).parent.parent / "collectors"))
    from github_client import GitHubClient

    client = GitHubClient(token=args.token)
    snapshot = parse_dependency_file(args.repo, client)
    maturity = compute_maturity_score(snapshot)

    result = {
        "repo": args.repo,
        "file_found": snapshot.file_found,
        "raw_count": snapshot.raw_count,
        "taxonomy_coverage": round(snapshot.taxonomy_coverage(), 3),
        "primary_language": snapshot.primary_language,
        "runtime_deps": {k: v for k, v in snapshot.runtime_deps.items() if v},
        "dev_deps": {k: v for k, v in snapshot.dev_deps.items() if v},
        "unclassified_count": len(snapshot.unclassified),
        "unclassified": snapshot.unclassified[:20],
        "budget_signals": snapshot.budget_signals,
        "archetype_signals": snapshot.archetype_signals,
        "scaling_signals": snapshot.scaling_signals,
        "pain_signals": snapshot.pain_signals,
        "maturity": {
            "score": maturity.score,
            "tier": maturity.tier.value,
            "is_targetable": maturity.is_targetable,
            "breakdown": maturity.breakdown,
        },
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _cli()
