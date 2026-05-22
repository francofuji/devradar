"""
E5.T5–T7 — Detección de pain signals heurística + LLM.
"""
from __future__ import annotations

import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
sys.path = [p for p in sys.path if os.path.abspath(p) != _this_dir]
sys.path.insert(0, _project_root)

import json
import logging
from pathlib import Path
from typing import Any

from enrichment.llm_client import call_llm
from enrichment.readme_extractor import extract_readme_intel
from enrichment.types import PainCategory, PainSignal, ReadmeIntel, StackSnapshot

logger = logging.getLogger("enrichment.pain_detector")

_TAXONOMY_PATH = Path(_project_root) / "taxonomy" / "dependencies.json"
_TAXONOMY: dict[str, Any] | None = None
PAIN_MODEL = "claude-haiku-4-5-20251001"


def _get_taxonomy() -> dict[str, Any]:
    global _TAXONOMY
    if _TAXONOMY is None:
        _TAXONOMY = json.loads(_TAXONOMY_PATH.read_text()).get("packages", {})
    return _TAXONOMY


def _all_runtime_packages(stack_snapshot: StackSnapshot) -> list[str]:
    packages: list[str] = []
    for values in stack_snapshot.runtime_deps.values():
        packages.extend(values)
    return packages


def _taxonomy_pain_hints(stack_snapshot: StackSnapshot) -> dict[PainCategory, list[str]]:
    taxonomy = _get_taxonomy()
    hints: dict[PainCategory, list[str]] = {}
    for pkg in _all_runtime_packages(stack_snapshot):
        entry = taxonomy.get(pkg) or taxonomy.get(pkg.lstrip("@").replace("/", "-"))
        if not entry:
            continue
        category = entry.get("pain_category")
        if not category:
            continue
        try:
            pain_category = PainCategory(category)
        except ValueError:
            continue
        hints.setdefault(pain_category, []).append(pkg)
    return hints


def _add_signal(
    signals: list[PainSignal],
    *,
    category: PainCategory,
    description: str,
    evidence: str,
    evidence_source: str,
    confidence: float,
    corroborating: list[str] | None = None,
    signal_age_days: int | None = None,
) -> None:
    try:
        signals.append(PainSignal(
            category=category,
            description=description,
            evidence=evidence,
            evidence_source=evidence_source,
            confidence=confidence,
            corroborating_signals=corroborating or [],
            signal_age_days=signal_age_days,
        ))
    except Exception as exc:
        logger.warning("PainSignal descartada: %s", exc)


def detect_pains_heuristic(issues, stack_snapshot: StackSnapshot) -> list[PainSignal]:
    """
    Heurístico primero, usando taxonomía como primera fuente auxiliar.
    """
    signals: list[PainSignal] = []
    taxonomy_hints = _taxonomy_pain_hints(stack_snapshot)
    queue_deps = stack_snapshot.runtime_deps.get("queues", [])
    auth_deps = stack_snapshot.runtime_deps.get("auth", [])
    llm_deps = stack_snapshot.runtime_deps.get("ai_llm", []) + stack_snapshot.runtime_deps.get("ai_framework", [])
    automation_deps = stack_snapshot.runtime_deps.get("browser_automation", [])
    logging_deps = stack_snapshot.runtime_deps.get("logging", [])
    monitoring_deps = stack_snapshot.runtime_deps.get("monitoring", [])

    for issue in issues:
        title = (issue.title or "").strip()
        title_lower = title.lower()
        labels_lower = [label.lower() for label in issue.labels]

        if queue_deps and (
            "performance" in labels_lower
            or any(term in title_lower for term in ("slow", "timeout", "latency", "oom"))
        ):
            _add_signal(
                signals,
                category=PainCategory.SCALING,
                description="Open issues suggest queue-backed performance or throughput pain.",
                evidence=f"Issue #{issue.number}: {title}",
                evidence_source="github_issue",
                confidence=0.84,
                corroborating=[f"Queue deps: {', '.join(queue_deps[:3])}"],
                signal_age_days=issue.age_days,
            )

        if llm_deps and any(term in title_lower for term in ("rate limit", "429", "quota", "cost", "billing")):
            corroborating = [f"LLM deps: {', '.join(llm_deps[:3])}"]
            if taxonomy_hints.get(PainCategory.API_COST):
                corroborating.append(
                    "Taxonomy pain hints: "
                    + ", ".join(taxonomy_hints[PainCategory.API_COST][:3])
                )
            _add_signal(
                signals,
                category=PainCategory.API_COST,
                description="Issue titles point to provider cost, quota, or rate limit pressure.",
                evidence=f"Issue #{issue.number}: {title}",
                evidence_source="github_issue",
                confidence=0.86,
                corroborating=corroborating,
                signal_age_days=issue.age_days,
            )

        if automation_deps and any(term in title_lower for term in ("flaky", "timeout", "selector")):
            _add_signal(
                signals,
                category=PainCategory.RELIABILITY,
                description="Browser automation issues indicate flaky execution or brittle selectors.",
                evidence=f"Issue #{issue.number}: {title}",
                evidence_source="github_issue",
                confidence=0.82,
                corroborating=[f"Automation deps: {', '.join(automation_deps[:3])}"],
                signal_age_days=issue.age_days,
            )

    if len(auth_deps) >= 2:
        corroborating = []
        if taxonomy_hints.get(PainCategory.AUTH):
            corroborating.append(
                "Taxonomy pain hints: " + ", ".join(taxonomy_hints[PainCategory.AUTH][:3])
            )
        _add_signal(
            signals,
            category=PainCategory.AUTH,
            description="Multiple auth libraries suggest auth complexity or integration overhead.",
            evidence=f"Auth deps detected together: {', '.join(auth_deps[:4])}",
            evidence_source="dependency_combination",
            confidence=0.78,
            corroborating=corroborating,
        )

    if not logging_deps and not monitoring_deps:
        _add_signal(
            signals,
            category=PainCategory.OBSERVABILITY,
            description="Project appears to lack explicit logging or monitoring dependencies.",
            evidence="No logging or monitoring libraries detected in runtime dependencies.",
            evidence_source="dependency_combination",
            confidence=0.72,
            corroborating=["Stack runtime_deps.logging and runtime_deps.monitoring are empty"],
        )

    return merge_pain_signals(signals, [])


def _condense_readme(readme_intel: ReadmeIntel | None) -> dict[str, Any]:
    if readme_intel is None:
        return {}
    return {
        "product_type": readme_intel.product_type.value if readme_intel.product_type else None,
        "target_user": readme_intel.target_user,
        "pain_solved": readme_intel.pain_solved,
        "limitations": readme_intel.limitations[:3],
        "roadmap_items": readme_intel.roadmap_items[:3],
        "evidence": readme_intel.evidence,
    }


def detect_pains_llm(
    issues,
    readme_intel: ReadmeIntel | None,
    *,
    entity_id: str = "system",
    include_metadata: bool = False,
) -> list[PainSignal] | tuple[list[PainSignal], dict[str, int]]:
    """
    Solo usa títulos de issues + README condensado. Devuelve pains con evidence explícita.
    """
    empty_meta = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
    issue_payload = [
        {"number": issue.number, "title": issue.title, "labels": issue.labels}
        for issue in issues[:10]
    ]
    if not issue_payload and readme_intel is None:
        return ([], empty_meta) if include_metadata else []

    system_prompt = """You detect technical pain signals from issue titles and README-derived notes.
Return strict JSON only as an array of objects:
[{"category":"api_cost|scaling|auth|observability|reliability","description":"string","evidence":"string","confidence":0.0,"source":"github_issue|readme"}]

Rules:
- Return only pains with explicit evidence from the provided issue titles or README notes.
- Evidence must quote or tightly paraphrase the provided text.
- If evidence is weak or missing, omit the pain entirely.
- Do not use outside knowledge."""

    prompt = json.dumps(
        {
            "issues": issue_payload,
            "readme_intel": _condense_readme(readme_intel),
        },
        ensure_ascii=True,
    )

    try:
        llm_result = call_llm(
            prompt,
            system_prompt,
            model=PAIN_MODEL,
            max_tokens=1000,
            entity_id=entity_id,
            enrichment_type="pain_detection",
        )
        parsed = json.loads(llm_result["text"])
    except json.JSONDecodeError as exc:
        logger.warning("Pain detector JSON inválido para %s: %s", entity_id, exc)
        meta = {
            "llm_calls": 1,
            "input_tokens": int(llm_result.get("input_tokens", 0)),
            "output_tokens": int(llm_result.get("output_tokens", 0)),
        } if "llm_result" in locals() else empty_meta
        return ([], meta) if include_metadata else []
    except Exception as exc:
        logger.warning("Pain detector LLM falló para %s: %s", entity_id, exc)
        return ([], empty_meta) if include_metadata else []

    signals: list[PainSignal] = []
    if isinstance(parsed, list):
        for item in parsed:
            if not isinstance(item, dict):
                continue
            category = item.get("category")
            evidence = (item.get("evidence") or "").strip()
            if not category or not evidence:
                continue
            try:
                pain_category = PainCategory(category)
                _add_signal(
                    signals,
                    category=pain_category,
                    description=(item.get("description") or "").strip() or f"{pain_category.value} pain detected.",
                    evidence=evidence,
                    evidence_source=(item.get("source") or "github_issue").strip(),
                    confidence=float(item.get("confidence", 0.0) or 0.0),
                )
            except Exception:
                continue

    meta = {
        "llm_calls": 1,
        "input_tokens": int(llm_result.get("input_tokens", 0)),
        "output_tokens": int(llm_result.get("output_tokens", 0)),
    }
    merged = merge_pain_signals([], signals)
    return (merged, meta) if include_metadata else merged


def merge_pain_signals(heuristic: list[PainSignal], llm: list[PainSignal]) -> list[PainSignal]:
    """
    Dedup por categoría. Mantiene mayor confianza y agrega evidencia complementaria.
    """
    merged: dict[PainCategory, PainSignal] = {}

    for signal in heuristic + llm:
        existing = merged.get(signal.category)
        if existing is None:
            merged[signal.category] = signal
            continue

        winner = existing if existing.confidence >= signal.confidence else signal
        loser = signal if winner is existing else existing
        extras = list(winner.corroborating_signals)
        if loser.evidence not in extras:
            extras.append(loser.evidence)
        for extra in loser.corroborating_signals:
            if extra not in extras:
                extras.append(extra)

        merged[signal.category] = PainSignal(
            category=winner.category,
            description=winner.description,
            evidence=winner.evidence,
            evidence_source=winner.evidence_source,
            confidence=winner.confidence,
            corroborating_signals=extras,
            signal_age_days=winner.signal_age_days or loser.signal_age_days,
        )

    return sorted(merged.values(), key=lambda item: item.confidence, reverse=True)


def analyze_pains(
    issues,
    stack_snapshot: StackSnapshot,
    readme_intel: ReadmeIntel | None,
    *,
    entity_id: str,
    include_metadata: bool = False,
) -> list[PainSignal] | tuple[list[PainSignal], dict[str, int]]:
    heuristic = detect_pains_heuristic(issues, stack_snapshot)
    usable_heuristics = [signal for signal in heuristic if signal.confidence >= 0.7]
    meta = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}

    if len(usable_heuristics) >= 2:
        return (heuristic, meta) if include_metadata else heuristic

    llm_signals, llm_meta = detect_pains_llm(
        issues,
        readme_intel,
        entity_id=entity_id,
        include_metadata=True,
    )
    merged = merge_pain_signals(heuristic, llm_signals)
    meta = {
        "llm_calls": llm_meta["llm_calls"],
        "input_tokens": llm_meta["input_tokens"],
        "output_tokens": llm_meta["output_tokens"],
    }
    return (merged, meta) if include_metadata else merged


def run_pain_check(repo_full_name: str) -> list[PainSignal]:
    """
    Runner operativo para jobs pain_check sin depender del cooldown de full_enrichment.
    """
    sys.path.insert(0, os.path.join(_project_root, "collectors"))
    from github_client import GitHubClient
    from enrichment.dependency_parser import parse_dependency_file
    from enrichment.github_profile import fetch_repo_profile

    client = GitHubClient()
    stack = parse_dependency_file(repo_full_name, client)
    profile = fetch_repo_profile(
        repo_full_name,
        client,
        fetch_issues=True,
        fetch_readme=True,
    )
    if profile is None:
        logger.warning("Pain check sin perfil para %s", repo_full_name)
        return []

    readme_intel = None
    if profile.readme_word_count >= 150:
        readme_intel = extract_readme_intel(profile.readme_content, repo_full_name)

    pains = analyze_pains(
        profile.open_issues,
        stack,
        readme_intel,
        entity_id=repo_full_name,
    )
    return pains
