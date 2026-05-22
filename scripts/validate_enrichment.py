"""
E5.T10 — Validación end-to-end de enriquecimiento LLM.

Corre E5 sobre repos del ecosistema y reporta:
- archetype accuracy
- pain precision / recall
- claims sin evidence
- costo total LLM
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from collectors.github_client import GitHubClient
from db.queries import get_total_cost
from enrichment.archetype_classifier import classify_archetype_heuristic
from enrichment.dependency_parser import parse_dependency_file
from enrichment.github_profile import fetch_repo_profile
from enrichment.pain_detector import analyze_pains
from enrichment.readme_extractor import extract_readme_intel

FIXTURES = [
    {
        "repo": "MinishLab/semble",
        "expected_archetypes": ["mcp_platform_builder", "solo_agent_builder"],
        "expected_pains": ["api_cost", "observability"],
    },
    {
        "repo": "ascending-llc/jarvis-registry",
        "expected_archetypes": ["mcp_platform_builder", "technical_founder"],
        "expected_pains": ["auth", "observability"],
    },
    {
        "repo": "drt-hub/drt",
        "expected_archetypes": ["mcp_platform_builder", "technical_founder"],
        "expected_pains": ["observability"],
    },
    {
        "repo": "browser-use/workflow-use",
        "expected_archetypes": ["automation_builder"],
        "expected_pains": ["reliability"],
    },
    {
        "repo": "IBM/mcp-context-forge",
        "expected_archetypes": ["mcp_platform_builder", "technical_founder"],
        "expected_pains": ["auth", "observability"],
    },
]


def _readme_claims_without_evidence(readme_intel) -> list[str]:
    if readme_intel is None:
        return []

    missing: list[str] = []
    evidence = readme_intel.evidence or {}
    if readme_intel.product_type is not None and not evidence.get("product_type"):
        missing.append("product_type")
    if readme_intel.target_user is not None and not evidence.get("target_user"):
        missing.append("target_user")
    if readme_intel.pain_solved is not None and not evidence.get("pain_solved"):
        missing.append("pain_solved")
    if readme_intel.limitations and not evidence.get("limitations"):
        missing.append("limitations")
    if readme_intel.roadmap_items and not evidence.get("roadmap_items"):
        missing.append("roadmap_items")
    if not evidence.get("has_demo"):
        missing.append("has_demo")
    if not evidence.get("readme_quality_score"):
        missing.append("readme_quality_score")
    return missing


def _pain_claims_without_evidence(pain_signals) -> list[str]:
    missing: list[str] = []
    for signal in pain_signals:
        if not signal.evidence or not signal.evidence.strip():
            missing.append(signal.category.value)
    return missing


def evaluate_repo(repo_full_name: str, github_client: GitHubClient) -> dict:
    print(f"\n=== {repo_full_name} ===")
    stack = parse_dependency_file(repo_full_name, github_client)
    profile = fetch_repo_profile(repo_full_name, github_client, fetch_issues=True, fetch_readme=True)

    if profile is None:
        raise RuntimeError(f"No se pudo obtener perfil de {repo_full_name}")

    readme_intel, readme_meta = extract_readme_intel(
        profile.readme_content,
        repo_full_name,
        include_metadata=True,
    )
    pain_signals, pain_meta = analyze_pains(
        profile.open_issues,
        stack,
        readme_intel,
        entity_id=repo_full_name,
        include_metadata=True,
    )
    archetype, arch_meta = classify_archetype_heuristic(
        stack,
        profile,
        readme_intel=readme_intel,
        entity_id=repo_full_name,
        include_metadata=True,
    )

    print("stack.file_found:", stack.file_found)
    print("readme_words:", profile.readme_word_count)
    print("issues_fetched:", len(profile.open_issues))
    print("readme_intel:", json.dumps({
        "product_type": readme_intel.product_type.value if readme_intel and readme_intel.product_type else None,
        "target_user": readme_intel.target_user if readme_intel else None,
        "pain_solved": readme_intel.pain_solved if readme_intel else None,
        "limitations": readme_intel.limitations if readme_intel else [],
        "roadmap_items": readme_intel.roadmap_items if readme_intel else [],
        "has_demo": readme_intel.has_demo if readme_intel else False,
        "readme_quality_score": readme_intel.readme_quality_score if readme_intel else 0,
        "evidence": readme_intel.evidence if readme_intel else {},
    }, ensure_ascii=True))
    print("pain_signals:", json.dumps([
        {
            "category": signal.category.value,
            "description": signal.description,
            "evidence": signal.evidence,
            "source": signal.evidence_source,
            "confidence": signal.confidence,
            "corroborating_signals": signal.corroborating_signals,
        }
        for signal in pain_signals
    ], ensure_ascii=True))
    print("archetype:", json.dumps({
        "primary": archetype.primary.value,
        "confidence": archetype.confidence,
        "secondary": archetype.secondary.value if archetype.secondary else None,
        "classification_method": archetype.classification_method,
        "signals_used": archetype.signals_used,
        "reasoning": archetype.reasoning,
    }, ensure_ascii=True))
    print(
        "llm_usage:",
        json.dumps({
            "readme": readme_meta,
            "pain": pain_meta,
            "archetype": arch_meta,
        }, ensure_ascii=True),
    )

    return {
        "stack": stack,
        "profile": profile,
        "readme_intel": readme_intel,
        "pain_signals": pain_signals,
        "archetype": archetype,
    }


def run() -> int:
    if os.getenv("ANTHROPIC_API_KEY", "").strip() in ("", "your_anthropic_api_key_here"):
        print("❌ ANTHROPIC_API_KEY no configurada en .env")
        return 1

    github_client = GitHubClient()
    archetype_correct = 0
    archetype_total = 0
    pain_tp = 0
    pain_fp = 0
    pain_fn = 0
    claims_without_evidence = 0

    for fixture in FIXTURES:
        repo = fixture["repo"]
        result = evaluate_repo(repo, github_client)

        predicted_arch = result["archetype"].primary.value
        expected_archetypes = set(fixture["expected_archetypes"])
        archetype_total += 1
        if predicted_arch in expected_archetypes:
            archetype_correct += 1
            print(f"archetype_check: OK ({predicted_arch})")
        else:
            print(f"archetype_check: FAIL predicted={predicted_arch} expected={sorted(expected_archetypes)}")

        expected_pains = set(fixture["expected_pains"])
        predicted_pains = {signal.category.value for signal in result["pain_signals"] if signal.is_usable}
        pain_tp += len(predicted_pains & expected_pains)
        pain_fp += len(predicted_pains - expected_pains)
        pain_fn += len(expected_pains - predicted_pains)
        print(f"pain_check: predicted={sorted(predicted_pains)} expected={sorted(expected_pains)}")

        missing_readme = _readme_claims_without_evidence(result["readme_intel"])
        missing_pains = _pain_claims_without_evidence(result["pain_signals"])
        claims_without_evidence += len(missing_readme) + len(missing_pains)
        print(f"claims_without_evidence: readme={missing_readme} pains={missing_pains}")

    archetype_accuracy = archetype_correct / archetype_total if archetype_total else 0.0
    pain_precision = pain_tp / (pain_tp + pain_fp) if (pain_tp + pain_fp) else 0.0
    pain_recall = pain_tp / (pain_tp + pain_fn) if (pain_tp + pain_fn) else 0.0
    total_cost = get_total_cost()

    print("\n=== SUMMARY ===")
    print(f"archetype_accuracy: {archetype_correct}/{archetype_total} = {archetype_accuracy:.1%}")
    print(f"pain_precision: {pain_precision:.1%}")
    print(f"pain_recall: {pain_recall:.1%}")
    print(f"claims_without_evidence: {claims_without_evidence}")
    print(f"total_llm_cost_usd: {total_cost:.6f}")

    if archetype_correct >= 4 and claims_without_evidence == 0:
        print("✅ E5 validation threshold met")
        return 0

    print("❌ E5 validation threshold not met")
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
