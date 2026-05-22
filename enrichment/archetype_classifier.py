"""
E5.T8–T9 — Clasificación de arquetipo con heurística y LLM para desempate.
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
from collections import Counter
from typing import Any

from enrichment.llm_client import call_llm
from enrichment.types import Archetype, ArchetypeResult, ReadmeIntel, RepoProfile, StackSnapshot

logger = logging.getLogger("enrichment.archetype_classifier")

ARCHETYPE_MODEL = "claude-haiku-4-5-20251001"


def _normalize_archetype(value: str) -> Archetype:
    try:
        return Archetype(value)
    except Exception:
        return Archetype.UNKNOWN


def _score_candidates(stack_snapshot: StackSnapshot, repo_profile: RepoProfile | None) -> dict[Archetype, dict[str, Any]]:
    score_map: dict[Archetype, dict[str, Any]] = {
        archetype: {"score": 0.0, "signals": []}
        for archetype in Archetype
        if archetype is not Archetype.UNKNOWN
    }

    signal_counts = Counter(stack_snapshot.archetype_signals)
    for raw_name, count in signal_counts.items():
        archetype = _normalize_archetype(raw_name)
        if archetype is Archetype.UNKNOWN:
            continue
        score_map[archetype]["score"] += count * 2.0
        score_map[archetype]["signals"].append(f"taxonomy signal x{count}: {raw_name}")

    topics = [topic.lower() for topic in (repo_profile.topics if repo_profile else [])]
    description = ((repo_profile.description or "") + " " + (repo_profile.homepage or "")).lower() if repo_profile else ""
    services = [service.lower() for service in (repo_profile.env_example_services if repo_profile else [])]

    if "mcp" in description or any("mcp" in topic for topic in topics):
        score_map[Archetype.MCP_PLATFORM_BUILDER]["score"] += 4.0
        score_map[Archetype.MCP_PLATFORM_BUILDER]["signals"].append("repo metadata mentions MCP")

    if stack_snapshot.runtime_deps.get("browser_automation"):
        score_map[Archetype.AUTOMATION_BUILDER]["score"] += 3.0
        score_map[Archetype.AUTOMATION_BUILDER]["signals"].append(
            "browser automation runtime dependencies present"
        )

    if stack_snapshot.has_payments():
        score_map[Archetype.TECHNICAL_FOUNDER]["score"] += 3.0
        score_map[Archetype.TECHNICAL_FOUNDER]["signals"].append("payments integration present")

    if any(term in description for term in ("agency", "client work", "lead gen", "outreach")):
        score_map[Archetype.AI_AGENCY_BUILDER]["score"] += 3.0
        score_map[Archetype.AI_AGENCY_BUILDER]["signals"].append("repo description suggests agency workflow")

    if any(term in description for term in ("growth", "acquisition", "marketing", "seo")):
        score_map[Archetype.GROWTH_ENGINEER]["score"] += 3.0
        score_map[Archetype.GROWTH_ENGINEER]["signals"].append("repo description suggests growth tooling")

    if stack_snapshot.has_ai() and not stack_snapshot.has_payments():
        score_map[Archetype.SOLO_AGENT_BUILDER]["score"] += 2.0
        score_map[Archetype.SOLO_AGENT_BUILDER]["signals"].append("AI stack present without payment layer")

    if services and any(service in services for service in ("stripe", "auth0", "clerk", "supabase")):
        score_map[Archetype.TECHNICAL_FOUNDER]["score"] += 2.0
        score_map[Archetype.TECHNICAL_FOUNDER]["signals"].append(
            "env services suggest SaaS/product infrastructure"
        )

    if stack_snapshot.runtime_deps.get("mcp"):
        score_map[Archetype.MCP_PLATFORM_BUILDER]["score"] += 4.0
        score_map[Archetype.MCP_PLATFORM_BUILDER]["signals"].append("MCP runtime dependencies present")

    return score_map


def classify_archetype_llm(
    stack_snapshot: StackSnapshot,
    readme_intel: ReadmeIntel | None,
    candidates: list[dict[str, Any]],
    *,
    entity_id: str = "system",
    include_metadata: bool = False,
) -> ArchetypeResult | tuple[ArchetypeResult, dict[str, int]]:
    empty_meta = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
    if len(candidates) < 2:
        result = ArchetypeResult(primary=Archetype.UNKNOWN, confidence=0.0)
        return (result, empty_meta) if include_metadata else result

    system_prompt = """You classify a developer-builder archetype from structured evidence.
Return strict JSON only:
{"primary":"solo_agent_builder|automation_builder|mcp_platform_builder|technical_founder|ai_agency_builder|growth_engineer|unknown","confidence":0.0,"reasoning":"string","signals_used":["string"]}

Rules:
- Choose only between the provided candidates unless the evidence clearly supports unknown.
- Base reasoning only on the supplied signals and README intel.
- Do not invent evidence."""

    prompt = json.dumps(
        {
            "stack_summary": {
                "runtime_deps": {k: v for k, v in stack_snapshot.runtime_deps.items() if v},
                "budget_signals": stack_snapshot.budget_signals,
                "archetype_signals": stack_snapshot.archetype_signals,
            },
            "readme_intel": {
                "product_type": readme_intel.product_type.value if readme_intel and readme_intel.product_type else None,
                "target_user": readme_intel.target_user if readme_intel else None,
                "pain_solved": readme_intel.pain_solved if readme_intel else None,
                "evidence": readme_intel.evidence if readme_intel else {},
            },
            "candidates": candidates[:2],
        },
        ensure_ascii=True,
    )

    try:
        llm_result = call_llm(
            prompt,
            system_prompt,
            model=ARCHETYPE_MODEL,
            max_tokens=800,
            entity_id=entity_id,
            enrichment_type="archetype_disambiguation",
        )
        parsed = json.loads(llm_result["text"])
        primary = _normalize_archetype(parsed.get("primary", "unknown"))
        confidence = float(parsed.get("confidence", 0.0) or 0.0)
        signals_used = [
            str(item).strip()
            for item in (parsed.get("signals_used") or [])
            if str(item).strip()
        ]
        result = ArchetypeResult(
            primary=primary,
            confidence=max(0.0, min(1.0, confidence)),
            secondary=_normalize_archetype(candidates[1]["archetype"]),
            classification_method="llm_disambiguated",
            signals_used=signals_used,
            reasoning=(parsed.get("reasoning") or "").strip() or None,
        )
        meta = {
            "llm_calls": 1,
            "input_tokens": int(llm_result.get("input_tokens", 0)),
            "output_tokens": int(llm_result.get("output_tokens", 0)),
        }
        return (result, meta) if include_metadata else result
    except Exception as exc:
        logger.warning("Archetype LLM fallback falló para %s: %s", entity_id, exc)
        fallback = ArchetypeResult(
            primary=_normalize_archetype(candidates[0]["archetype"]),
            confidence=max(0.0, min(0.74, float(candidates[0]["confidence"]))),
            secondary=_normalize_archetype(candidates[1]["archetype"]),
            classification_method="heuristic",
            signals_used=list(candidates[0]["signals"]),
        )
        return (fallback, empty_meta) if include_metadata else fallback


def classify_archetype_heuristic(
    stack_snapshot: StackSnapshot,
    repo_profile: RepoProfile | None,
    *,
    readme_intel: ReadmeIntel | None = None,
    entity_id: str = "system",
    include_metadata: bool = False,
) -> ArchetypeResult | tuple[ArchetypeResult, dict[str, int]]:
    """
    Heurística primero; si confidence < 0.75, usa LLM para desempatar top-2.
    """
    score_map = _score_candidates(stack_snapshot, repo_profile)
    ranked = sorted(
        (
            {
                "archetype": archetype.value,
                "score": payload["score"],
                "signals": payload["signals"],
            }
            for archetype, payload in score_map.items()
            if payload["score"] > 0
        ),
        key=lambda item: item["score"],
        reverse=True,
    )

    if not ranked:
        result = ArchetypeResult(primary=Archetype.UNKNOWN, confidence=0.0)
        meta = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
        return (result, meta) if include_metadata else result

    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    total = sum(item["score"] for item in ranked)
    margin = top["score"] - (second["score"] if second else 0.0)
    confidence = min(0.92, 0.45 + (top["score"] / max(total, 1.0)) * 0.35 + min(margin, 4.0) * 0.05)
    heuristic_result = ArchetypeResult(
        primary=_normalize_archetype(top["archetype"]),
        confidence=confidence,
        secondary=_normalize_archetype(second["archetype"]) if second else None,
        classification_method="heuristic",
        signals_used=list(top["signals"]),
    )

    if heuristic_result.confidence >= 0.75 or second is None:
        meta = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
        return (heuristic_result, meta) if include_metadata else heuristic_result

    candidates = [
        {
            "archetype": top["archetype"],
            "confidence": round(confidence, 3),
            "signals": top["signals"],
        },
        {
            "archetype": second["archetype"],
            "confidence": round(max(0.35, confidence - 0.1), 3),
            "signals": second["signals"],
        },
    ]
    return classify_archetype_llm(
        stack_snapshot,
        readme_intel,
        candidates,
        entity_id=entity_id,
        include_metadata=include_metadata,
    )
