"""
E4.T5+T6+T9+T10 — Pipeline completo de enriquecimiento heurístico.

Secuencia de 7 pasos:
  1. Fetch repos del developer (DB primero, GitHub API como fallback)
  2. Seleccionar primary repo
  3. Fetch dependency file + classify_stack
  4. Fetch repo profile (CI, Docker, issues, README)
  5. Compute maturity score
  6. Encolar README LLM enrichment si readme_word_count > 150 (E5)
  7. Escribir resultados a DB — developers + repositories

Emite enrichment.completed al finalizar, después de persistir memory.
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
import math
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from enrichment.types import (
    ArchetypeResult,
    EnrichmentResult,
    MaturityResult,
    PainSignal,
    StackSnapshot,
)
from enrichment.archetype_classifier import classify_archetype_heuristic
from enrichment.dependency_parser import classify_stack, compute_maturity_score, parse_dependency_file
from enrichment.github_profile import fetch_repo_profile
from enrichment.memory_writer import write_entity_memory
from enrichment.pain_detector import analyze_pains
from enrichment.readme_extractor import extract_readme_intel
from db.queries import (
    get_repos_by_owner,
    log_enrichment_cost,
    update_developer_enriched,
    update_developer_status,
    update_repo_enriched,
    upsert_developer,
    upsert_repository,
)

logger = logging.getLogger("enrichment.full_enrichment")

# Skip re-enrichment if last_enriched is more recent than this (hours)
_ENRICHMENT_COOLDOWN_HOURS = 6


# ── Primary repo selection (E4.T6) ──────────────────────────────

def select_primary_repo(repo_rows: list) -> Optional[str]:
    """
    Select the most relevant repo from DB rows.
    Score = stars × 1/log(days_since_push + 2). Tie → higher stars.
    Returns repo id (owner/repo) or None.
    """
    if not repo_rows:
        return None

    def score(row) -> float:
        stars = row["stars"] or 0
        last_push = row["last_push"]
        if last_push:
            try:
                pushed = datetime.fromisoformat(last_push.replace("Z", "+00:00"))
                days = max(0, (datetime.now(timezone.utc) - pushed).days)
            except Exception:
                days = 365
        else:
            days = 365
        return stars / math.log(days + 2)

    best = max(repo_rows, key=score)
    return best["id"]


# ── Signal emission helpers ──────────────────────────────────────

def _emit_stack_signals(developer_id: str, stack: StackSnapshot) -> None:
    """E4.T9 / E7.T6 — Emit signals derived from classified stack."""
    from db.queries import emit_signal

    if stack.has_payments():
        emit_signal(
            entity_id=developer_id,
            category="budget",
            signal_type="payments_detected",
            base_score=25.0,
            half_life_days=21.0,
            evidence=f"Payment library in deps: {stack.runtime_deps.get('payments', [])[:3]}",
        )

    if stack.has_ai():
        emit_signal(
            entity_id=developer_id,
            category="budget",
            signal_type="ai_provider_present",
            base_score=20.0,
            half_life_days=7.0,
            evidence=f"AI libs: {(stack.runtime_deps.get('ai_llm', []) + stack.runtime_deps.get('ai_framework', []))[:3]}",
        )

    if stack.has_queues():
        emit_signal(
            entity_id=developer_id,
            category="scaling",
            signal_type="queue_library_added",
            base_score=12.0,
            half_life_days=7.0,
            evidence=f"Queue lib: {stack.runtime_deps.get('queues', [])[:2]}",
        )

    if stack.has_automation():
        emit_signal(
            entity_id=developer_id,
            category="evaluation",
            signal_type="browser_automation_runtime",
            base_score=18.0,
            half_life_days=14.0,
            evidence=f"Automation libs: {stack.runtime_deps.get('browser_automation', [])[:3]}",
        )

    email_libs = stack.runtime_deps.get("email", [])
    if email_libs:
        emit_signal(
            entity_id=developer_id,
            category="budget",
            signal_type="email_provider_detected",
            base_score=15.0,
            half_life_days=14.0,
            evidence=f"Email library in deps: {email_libs[:3]}",
        )

    email_testing_libs = [
        lib for lib in email_libs
        if any(t in lib.lower() for t in ["mailtrap", "mailhog", "mock", "ethereal"])
    ]
    if email_testing_libs:
        emit_signal(
            entity_id=developer_id,
            category="evaluation",
            signal_type="email_testing_detected",
            base_score=20.0,
            half_life_days=30.0,
            evidence=f"Email testing tool detected: {email_testing_libs}",
        )

    if stack.has_automation() and email_libs:
        emit_signal(
            entity_id=developer_id,
            category="evaluation",
            signal_type="browser_plus_email",
            base_score=25.0,
            half_life_days=14.0,
            evidence="Browser automation + email library — likely testing full verification flows",
        )


def _emit_pain_signals(developer_id: str, pain_signals: list[PainSignal]) -> None:
    from db.queries import emit_signal

    for signal in pain_signals:
        if not signal.is_usable:
            continue
        emit_signal(
            entity_id=developer_id,
            category=signal.category.value,
            signal_type=f"pain_{signal.category.value}",
            base_score=12.0,
            half_life_days=30.0,
            evidence=signal.evidence,
        )


# ── Main enrichment function (E4.T5) ────────────────────────────

def run_full_enrichment(entity_id: str, github_client=None) -> EnrichmentResult:
    """
    Run full heuristic enrichment for a developer or repo entity.

    If entity_id is 'owner/repo': treats owner as the developer.
    If entity_id is a handle: enriches that developer directly.
    """
    # Resolve developer_id and optional preferred_repo
    if "/" in entity_id:
        developer_id = entity_id.split("/")[0].lower()
        preferred_repo = entity_id
    else:
        developer_id = entity_id.lower()
        preferred_repo = None

    logger.info(f"Starting full enrichment for: {developer_id}")
    result = EnrichmentResult(developer_id=developer_id, enrichment_type="full")

    # ── Cooldown check ────────────────────────────────────────────
    from db.queries import get_developer
    dev = get_developer(developer_id)
    if dev and dev["last_enriched"]:
        try:
            last = datetime.fromisoformat(dev["last_enriched"])
            elapsed_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600
            if elapsed_h < _ENRICHMENT_COOLDOWN_HOURS:
                logger.info(
                    f"Skipping {developer_id} — enriched {elapsed_h:.1f}h ago "
                    f"(cooldown={_ENRICHMENT_COOLDOWN_HOURS}h)"
                )
                return result
        except Exception:
            pass

    # ── GitHub client ─────────────────────────────────────────────
    if github_client is None:
        sys.path.insert(0, os.path.join(_project_root, "collectors"))
        from github_client import GitHubClient
        github_client = GitHubClient()

    # ── Step 1: Get developer repos (DB first, GitHub fallback) ──
    db_repos = get_repos_by_owner(developer_id)

    if not db_repos and preferred_repo:
        # At least upsert the known repo so we have something to work with
        repo_obj = github_client.get_repo(preferred_repo)
        if repo_obj:
            pushed = repo_obj.pushed_at.isoformat() if repo_obj.pushed_at else None
            upsert_repository({
                "id": repo_obj.full_name,
                "owner_id": developer_id,
                "primary_language": repo_obj.language,
                "stars": repo_obj.stargazers_count,
                "forks": repo_obj.forks_count,
                "open_issues": repo_obj.open_issues_count,
                "last_push": pushed,
            })
            db_repos = get_repos_by_owner(developer_id)
            result.sources_fetched.append("github_api_repo")

    if not db_repos:
        logger.warning(f"No repos found for {developer_id} — enrichment aborted")
        result.sources_failed.append("repos")
        return result

    # ── Step 2: Select primary repo ────────────────────────────────
    if preferred_repo and any(r["id"] == preferred_repo for r in db_repos):
        primary_repo_id = preferred_repo
    else:
        primary_repo_id = select_primary_repo(db_repos)

    if not primary_repo_id:
        logger.warning(f"No primary repo selected for {developer_id}")
        return result

    logger.info(f"Primary repo: {primary_repo_id}")

    # ── Step 3: Fetch dependency file + classify stack ─────────────
    stack: Optional[StackSnapshot] = None
    try:
        stack = parse_dependency_file(primary_repo_id, github_client)
        result.sources_fetched.append(f"deps:{stack.file_found or 'none'}")
        if stack.file_found:
            logger.info(
                f"Stack classified from {stack.file_found}: "
                f"{stack.raw_count} deps, coverage={stack.taxonomy_coverage():.0%}"
            )
    except Exception as e:
        logger.error(f"Error parsing deps for {primary_repo_id}: {e}")
        result.sources_failed.append("dependency_file")
        stack = StackSnapshot()

    result.stack = stack

    # ── Step 4: Fetch repo profile ──────────────────────────────────
    profile = None
    try:
        profile = fetch_repo_profile(
            primary_repo_id,
            github_client,
            fetch_issues=True,
            fetch_readme=True,
        )
        if profile:
            result.sources_fetched.append("github_profile")
            result.repo_profile = profile
            logger.info(
                f"Profile: ci={profile.has_ci} docker={profile.has_docker} "
                f"issues={len(profile.open_issues)} readme={profile.readme_word_count}w"
            )
    except Exception as e:
        logger.error(f"Error fetching profile for {primary_repo_id}: {e}")
        result.sources_failed.append("github_profile")

    # ── Step 5: Compute maturity score ─────────────────────────────
    maturity: Optional[MaturityResult] = None
    try:
        maturity = compute_maturity_score(stack, profile)
        result.maturity = maturity
        logger.info(f"Maturity: {maturity.score} ({maturity.tier.value})")
    except Exception as e:
        logger.error(f"Error computing maturity for {developer_id}: {e}")
        result.sources_failed.append("maturity_score")

    # ── Step 6: README intel + pain detection + archetype (E5) ───
    readme_meta = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
    if profile and profile.readme_word_count > 150:
        readme_intel, readme_meta = extract_readme_intel(
            profile.readme_content,
            primary_repo_id,
            include_metadata=True,
        )
        result.readme_intel = readme_intel
        if readme_intel:
            logger.info(
                "README intel: product_type=%s score=%s",
                readme_intel.product_type.value if readme_intel.product_type else None,
                readme_intel.readme_quality_score,
            )

    pain_meta = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
    if stack and profile:
        pains, pain_meta = analyze_pains(
            profile.open_issues,
            stack,
            result.readme_intel,
            entity_id=primary_repo_id,
            include_metadata=True,
        )
        result.pain_signals = pains
        if pains:
            logger.info(
                "Pain signals: %s",
                ", ".join(f"{signal.category.value}:{signal.confidence:.2f}" for signal in pains),
            )

    # ── Infer archetype from stack/profile/readme ─────────────────
    archetype: Optional[ArchetypeResult] = None
    if stack:
        archetype, archetype_meta = classify_archetype_heuristic(
            stack,
            profile,
            readme_intel=result.readme_intel,
            entity_id=primary_repo_id,
            include_metadata=True,
        )
        result.archetype = archetype
        logger.info(
            "Archetype: %s (confidence=%.2f, method=%s)",
            archetype.primary.value,
            archetype.confidence,
            archetype.classification_method,
        )
    else:
        archetype_meta = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}

    result.llm_calls_made = (
        readme_meta["llm_calls"] + pain_meta["llm_calls"] + archetype_meta["llm_calls"]
    )
    result.input_tokens_used = (
        readme_meta["input_tokens"] + pain_meta["input_tokens"] + archetype_meta["input_tokens"]
    )
    result.output_tokens_used = (
        readme_meta["output_tokens"] + pain_meta["output_tokens"] + archetype_meta["output_tokens"]
    )

    # ── Step 7: Write results to DB ────────────────────────────────

    # Update repositories table
    if stack:
        try:
            stack_json = json.dumps({
                "file_found": stack.file_found,
                "raw_count": stack.raw_count,
                "taxonomy_coverage": round(stack.taxonomy_coverage(), 3),
                "runtime_deps": {k: v for k, v in stack.runtime_deps.items() if v},
                "dev_deps": {k: v for k, v in stack.dev_deps.items() if v},
                "budget_signals": stack.budget_signals,
                "archetype_signals": stack.archetype_signals,
                "scaling_signals": stack.scaling_signals,
                "pain_signals": stack.pain_signals,
                "maturity_modifier": stack.maturity_modifier,
                "readme_intel": {
                    "product_type": (
                        result.readme_intel.product_type.value
                        if result.readme_intel and result.readme_intel.product_type
                        else None
                    ),
                    "target_user": result.readme_intel.target_user if result.readme_intel else None,
                    "pain_solved": result.readme_intel.pain_solved if result.readme_intel else None,
                    "limitations": result.readme_intel.limitations if result.readme_intel else [],
                    "roadmap_items": result.readme_intel.roadmap_items if result.readme_intel else [],
                    "has_demo": result.readme_intel.has_demo if result.readme_intel else False,
                    "readme_quality_score": (
                        result.readme_intel.readme_quality_score if result.readme_intel else 0
                    ),
                    "evidence": result.readme_intel.evidence if result.readme_intel else {},
                },
                "detected_pains": [
                    {
                        "category": signal.category.value,
                        "description": signal.description,
                        "evidence": signal.evidence,
                        "evidence_source": signal.evidence_source,
                        "confidence": signal.confidence,
                        "corroborating_signals": signal.corroborating_signals,
                    }
                    for signal in result.pain_signals
                ],
            })
            update_repo_enriched(
                repo_id=primary_repo_id,
                stack_snapshot=stack_json,
                has_ci=profile.has_ci if profile else False,
                has_docker=(profile.has_docker if profile else False) or stack.has_monitoring(),
                has_tests=stack.has_tests(),
                has_payments=stack.has_payments(),
                has_auth=stack.has_auth(),
                has_monitoring=stack.has_monitoring(),
                maturity_score=maturity.score if maturity else 0.0,
                is_primary=True,
            )
        except Exception as e:
            logger.error(f"Error updating repo {primary_repo_id}: {e}")

    # Update developers table
    try:
        update_developer_enriched(
            developer_id=developer_id,
            archetype=archetype.primary.value if archetype else None,
            arch_confidence=archetype.confidence if archetype else None,
            maturity_score=maturity.score if maturity else 0.0,
        )
        # Advance status from DISCOVERED → PROFILED
        if dev and dev["status"] == "DISCOVERED":
            update_developer_status(developer_id, "PROFILED")
            logger.info(f"Status: {developer_id} DISCOVERED → PROFILED")
    except Exception as e:
        logger.error(f"Error updating developer {developer_id}: {e}")

    # Emit stack signals for scoring (E7.T6)
    if stack:
        try:
            _emit_stack_signals(developer_id, stack)
        except Exception as e:
            logger.warning(f"Error emitting stack signals for {developer_id}: {e}")

    if result.pain_signals:
        try:
            _emit_pain_signals(developer_id, result.pain_signals)
        except Exception as e:
            logger.warning(f"Error emitting pain signals for {developer_id}: {e}")

    # ── E4.T10: Log enrichment cost (llm_calls=0 in E4) ───────────
    try:
        log_enrichment_cost(
            entity_id=developer_id,
            enrichment_type="full",
            llm_calls=0,
            input_tokens=0,
            output_tokens=0,
        )
    except Exception as e:
        logger.warning(f"Could not log enrichment cost: {e}")

    result.overall_confidence = max(
        archetype.confidence if archetype else 0.0,
        max((signal.confidence for signal in result.pain_signals), default=0.0),
    )
    try:
        memory_version = write_entity_memory(developer_id, result)
        logger.info("Entity memory written: v%s for %s", memory_version, developer_id)
    except Exception as e:
        logger.warning("Could not write entity memory for %s: %s", developer_id, e)
    logger.info(f"Full enrichment complete: {developer_id}")
    return result
