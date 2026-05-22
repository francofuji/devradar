"""
E6 — Sistema de memoria vivo para developers enriquecidos.
"""
from __future__ import annotations

import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
sys.path = [p for p in sys.path if os.path.abspath(p) != _this_dir]
sys.path.insert(0, _project_root)

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

import structlog

from db.events import emit_event
from db.memory_queries import get_latest_memory, write_memory
from db.queries import get_developer
from enrichment.llm_client import call_llm
from fine_tuning.capture import capture_example
from enrichment.types import (
    EntityMemory,
    EnrichmentResult,
    OutreachContext,
)

logger = structlog.get_logger().bind(module="enrichment.memory_writer")

NARRATIVE_MODEL = "claude-sonnet-4-6"
VOCABULARY_TO_AVOID = ["synergies", "leverage", "streamline", "revolutionize"]
SIGNIFICANT_MEMORY_TRIGGERS = {
    "outreach.message_sent",
    "outreach.reply_received",
    "developer.disqualified",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_value(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {str(k): _safe_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    return value


def _stack_summary(stack) -> dict[str, Any]:
    if stack is None:
        return {}
    return {
        "primary_language": stack.primary_language,
        "secondary_languages": stack.secondary_languages,
        "runtime_deps": {k: v for k, v in stack.runtime_deps.items() if v},
        "dev_deps": {k: v for k, v in stack.dev_deps.items() if v},
        "budget_signals": stack.budget_signals,
        "archetype_signals": stack.archetype_signals,
        "scaling_signals": stack.scaling_signals,
        "pain_signals": stack.pain_signals,
        "file_found": stack.file_found,
        "raw_count": stack.raw_count,
    }


def _pain_to_memory_dict(signal) -> dict[str, Any]:
    return {
        "category": signal.category.value,
        "description": signal.description,
        "evidence": signal.evidence,
        "evidence_source": signal.evidence_source,
        "confidence": signal.confidence,
        "corroborating_signals": signal.corroborating_signals,
        "signal_age_days": signal.signal_age_days,
    }


def _extract_vocabulary(result: EnrichmentResult) -> list[str]:
    terms: list[str] = []
    if result.readme_intel:
        for value in [
            result.readme_intel.pain_solved,
            result.readme_intel.target_user,
        ]:
            if not value:
                continue
            for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", value):
                normalized = token.lower()
                if normalized not in terms:
                    terms.append(normalized)
    for signal in result.usable_pain_signals:
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", signal.description):
            normalized = token.lower()
            if normalized not in terms:
                terms.append(normalized)
        if len(terms) >= 8:
            break
    return terms[:8]


def _extract_hook_candidates(result: EnrichmentResult) -> list[str]:
    hooks: list[str] = []

    for signal in result.usable_pain_signals:
        evidence = signal.evidence.strip()
        if evidence and evidence not in hooks:
            hooks.append(evidence)

    if result.stack:
        runtime_groups = [
            ("payments", result.stack.runtime_deps.get("payments", [])),
            ("ai_llm", result.stack.runtime_deps.get("ai_llm", [])),
            ("browser_automation", result.stack.runtime_deps.get("browser_automation", [])),
            ("queues", result.stack.runtime_deps.get("queues", [])),
        ]
        for label, packages in runtime_groups:
            if packages:
                hooks.append(f"{label} dependencies detected: {', '.join(packages[:3])}")

    profile = result.repo_profile
    if profile and profile.last_push:
        hooks.append(f"Latest repo push recorded at {profile.last_push}")

    unique_hooks: list[str] = []
    for hook in hooks:
        cleaned = hook.strip()
        if cleaned and cleaned not in unique_hooks:
            unique_hooks.append(cleaned)
    return unique_hooks[:3]


def compute_outreach_context(enrichment_result: EnrichmentResult) -> OutreachContext:
    """
    Determina ángulo recomendado y hooks verificables para outreach.
    """
    usable_pains = sorted(
        enrichment_result.usable_pain_signals,
        key=lambda item: item.confidence,
        reverse=True,
    )
    top_pain = usable_pains[0].category.value if usable_pains else "monitor"
    hooks = _extract_hook_candidates(enrichment_result)
    vocabulary = _extract_vocabulary(enrichment_result)

    return OutreachContext(
        recommended_angle=top_pain,
        specific_hooks=hooks,
        vocabulary_to_use=vocabulary,
        vocabulary_to_avoid=list(VOCABULARY_TO_AVOID),
        channel_priority=["email", "linkedin"],
        tone="peer_technical",
    )


def build_fallback_narrative(entity_id: str, enrichment_result: EnrichmentResult) -> str:
    """
    Narrativa útil sin depender del LLM.
    """
    developer = get_developer(entity_id)
    handle = entity_id
    archetype = (
        enrichment_result.archetype.primary.value
        if enrichment_result.archetype and enrichment_result.archetype.primary
        else "unknown builder"
    )

    ai_stack = []
    if enrichment_result.stack:
        ai_stack = (
            enrichment_result.stack.runtime_deps.get("ai_llm", [])
            + enrichment_result.stack.runtime_deps.get("ai_framework", [])
        )[:3]
    top_ai_stack = ", ".join(ai_stack) if ai_stack else "an unclassified stack"

    sentences = [
        f"{handle} is a {archetype} building with {top_ai_stack}.",
    ]

    if enrichment_result.usable_pain_signals:
        top_signal = enrichment_result.usable_pain_signals[0]
        sentences.append(
            f"Active pain signal: {top_signal.category.value} backed by {top_signal.evidence}."
        )

    if enrichment_result.maturity:
        sentences.append(
            f"Product maturity is {enrichment_result.maturity.tier.value} ({enrichment_result.maturity.score}/100)."
        )

    if enrichment_result.stack and enrichment_result.stack.has_payments():
        payments = enrichment_result.stack.runtime_deps.get("payments", [])[:2]
        if payments:
            sentences.append(
                f"Payment integration is present via {', '.join(payments)}."
            )

    if not enrichment_result.usable_pain_signals and enrichment_result.repo_profile and enrichment_result.repo_profile.last_push:
        sentences.append(
            f"The primary repo shows recent activity with last push at {enrichment_result.repo_profile.last_push}."
        )

    if developer and developer["last_enriched"]:
        sentences.append(
            f"Last enrichment ran at {developer['last_enriched']}."
        )

    return " ".join(sentences[:4])


def _has_specific_reference(text: str) -> bool:
    patterns = [
        r"#\d+",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b(openai|anthropic|langchain|stripe|playwright|redis|celery|bullmq|supabase|clerk)\b",
    ]
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in patterns)


def _provider_from_model(model_name: str | None) -> str | None:
    if not model_name:
        return None
    if "claude" in model_name.lower():
        return "anthropic"
    return "ollama"


def generate_narrative(entity_id: str, enrichment_result: EnrichmentResult) -> str:
    """
    Genera 3–4 oraciones con Sonnet. Si falla o no cumple validación, usa fallback.
    """
    fallback = build_fallback_narrative(entity_id, enrichment_result)

    prompt = json.dumps(
        {
            "developer_id": entity_id,
            "archetype": (
                enrichment_result.archetype.primary.value
                if enrichment_result.archetype and enrichment_result.archetype.primary
                else None
            ),
            "maturity": {
                "score": enrichment_result.maturity.score if enrichment_result.maturity else None,
                "tier": enrichment_result.maturity.tier.value if enrichment_result.maturity else None,
            },
            "stack": _stack_summary(enrichment_result.stack),
            "pain_signals": [_pain_to_memory_dict(signal) for signal in enrichment_result.usable_pain_signals[:3]],
            "readme_intel": {
                "product_type": (
                    enrichment_result.readme_intel.product_type.value
                    if enrichment_result.readme_intel and enrichment_result.readme_intel.product_type
                    else None
                ),
                "target_user": (
                    enrichment_result.readme_intel.target_user
                    if enrichment_result.readme_intel
                    else None
                ),
                "pain_solved": (
                    enrichment_result.readme_intel.pain_solved
                    if enrichment_result.readme_intel
                    else None
                ),
                "evidence": (
                    enrichment_result.readme_intel.evidence
                    if enrichment_result.readme_intel
                    else {}
                ),
            },
            "repo_profile": {
                "full_name": (
                    enrichment_result.repo_profile.full_name
                    if enrichment_result.repo_profile
                    else None
                ),
                "last_push": (
                    enrichment_result.repo_profile.last_push
                    if enrichment_result.repo_profile
                    else None
                ),
            },
            "fallback": fallback,
        },
        ensure_ascii=True,
    )

    system_prompt = """You write a concise technical memory narrative in English.
Return strict JSON only:
{"narrative":"string"}

Rules:
- Write 3 or 4 sentences.
- Describe who the builder is, what they are building, where technical pain is visible, and where they are in their journey.
- Mention at least one specific verifiable detail from the provided evidence such as a package name, issue number, or date.
- Do not invent facts.
- Keep the tone factual and operator-friendly."""

    try:
        llm_result = call_llm(
            prompt,
            system_prompt,
            model=NARRATIVE_MODEL,
            max_tokens=500,
            entity_id=entity_id,
            enrichment_type="memory_narrative",
        )
        parsed = json.loads(llm_result["text"])
        narrative = str(parsed.get("narrative", "")).strip()
        sentence_count = len([s for s in re.split(r"[.!?]+", narrative) if s.strip()])
        if sentence_count < 2 or not _has_specific_reference(narrative):
            logger.warning(
                "narrative.validation_failed",
                entity_id=entity_id,
                sentences=sentence_count,
                has_specific_reference=_has_specific_reference(narrative),
            )
            return fallback
        try:
            capture_example(
                task_type="narrative",
                system_prompt=system_prompt,
                user_input=prompt,
                model_output=narrative,
                approved_output=narrative,
                entity_id=entity_id,
                provider=_provider_from_model(llm_result.get("model")),
                model_used=llm_result.get("model"),
            )
        except Exception as exc:
            logger.warning("narrative.capture_failed", entity_id=entity_id, error=str(exc))
        return narrative
    except Exception as exc:
        logger.warning("narrative.llm_fallback", entity_id=entity_id, error=str(exc))
        return fallback


def build_memory_object(entity_id: str, enrichment_result: EnrichmentResult) -> dict[str, Any]:
    """
    Construye el objeto EntityMemory serializable.
    """
    previous_memory = get_latest_memory(entity_id) or {}
    previous_stack_history = list(previous_memory.get("stack_history", []))
    previous_contact_history = list(previous_memory.get("contact_history", []))
    previous_operator_notes = list(previous_memory.get("operator_notes", []))
    previous_transitions = list(previous_memory.get("transitions_observed", []))
    developer = get_developer(entity_id)

    outreach_context = compute_outreach_context(enrichment_result)
    enrichment_result.outreach_context = outreach_context
    narrative = generate_narrative(entity_id, enrichment_result)

    stack_snapshot = {
        "captured_at": _now_iso(),
        "repo": enrichment_result.repo_profile.full_name if enrichment_result.repo_profile else None,
        "snapshot": _stack_summary(enrichment_result.stack),
    }

    stack_history = list(previous_stack_history)
    if stack_snapshot["snapshot"]:
        stack_history.append(stack_snapshot)
        stack_history = stack_history[-10:]

    memory = EntityMemory(
        narrative=narrative,
        stack_history=stack_history,
        confirmed_pain_signals=[
            _pain_to_memory_dict(signal)
            for signal in enrichment_result.usable_pain_signals
        ],
        transitions_observed=previous_transitions,
        scores={
            "intent_score": float(developer["intent_score"]) if developer else 0.0,
            "maturity_score": (
                enrichment_result.maturity.score if enrichment_result.maturity else 0.0
            ),
            "maturity_tier": (
                enrichment_result.maturity.tier.value if enrichment_result.maturity else None
            ),
        },
        contact_history=previous_contact_history,
        recommended_angle=outreach_context.recommended_angle,
        specific_hooks=list(outreach_context.specific_hooks),
        operator_notes=previous_operator_notes,
        meta={
            "enriched_at": _now_iso(),
            "sources_fetched": list(enrichment_result.sources_fetched),
            "sources_failed": list(enrichment_result.sources_failed),
            "overall_confidence": enrichment_result.overall_confidence,
            "archetype": (
                enrichment_result.archetype.primary.value
                if enrichment_result.archetype and enrichment_result.archetype.primary
                else None
            ),
            "repo": (
                enrichment_result.repo_profile.full_name
                if enrichment_result.repo_profile
                else None
            ),
            "readme_product_type": (
                enrichment_result.readme_intel.product_type.value
                if enrichment_result.readme_intel and enrichment_result.readme_intel.product_type
                else None
            ),
            "outreach_context": asdict(outreach_context),
        },
    )
    return _safe_value(asdict(memory))


def write_entity_memory(entity_id: str, enrichment_result: EnrichmentResult) -> int:
    """
    Escribe una nueva versión de memoria y emite enrichment.completed al terminar.
    """
    memory_dict = build_memory_object(entity_id, enrichment_result)
    summary = memory_dict.get("narrative") or ""
    version = write_memory(entity_id, memory_dict, summary=summary, entity_type="developer")

    try:
        emit_event(
            "enrichment.completed",
            entity_id,
            "developer",
            {
                "enrichment_type": enrichment_result.enrichment_type,
                "memory_version": version,
                "primary_repo": (
                    enrichment_result.repo_profile.full_name
                    if enrichment_result.repo_profile
                    else None
                ),
                "archetype": (
                    enrichment_result.archetype.primary.value
                    if enrichment_result.archetype and enrichment_result.archetype.primary
                    else None
                ),
                "archetype_method": (
                    enrichment_result.archetype.classification_method
                    if enrichment_result.archetype
                    else None
                ),
                "maturity_score": (
                    enrichment_result.maturity.score if enrichment_result.maturity else 0
                ),
                "maturity_tier": (
                    enrichment_result.maturity.tier.value if enrichment_result.maturity else None
                ),
                "pain_categories": [
                    signal.category.value for signal in enrichment_result.usable_pain_signals
                ],
                "readme_product_type": (
                    enrichment_result.readme_intel.product_type.value
                    if enrichment_result.readme_intel and enrichment_result.readme_intel.product_type
                    else None
                ),
                "recommended_angle": memory_dict.get("recommended_angle"),
                "specific_hooks": memory_dict.get("specific_hooks", []),
                "sources_fetched": enrichment_result.sources_fetched,
                "sources_failed": enrichment_result.sources_failed,
            },
            source="internal",
            source_url=f"memory://{entity_id}/v{version}",
        )
    except Exception as exc:
        logger.warning("memory.enrichment_event_emit_failed", entity_id=entity_id, error=str(exc))

    return version


def _merge_memory_patch(base_memory: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base_memory)
    for key, value in patch.items():
        merged[key] = value
    return merged


def update_memory_on_event(entity_id: str, trigger: str, payload: dict[str, Any]) -> int | None:
    """
    Actualiza solo los campos relevantes de memoria para eventos operacionales.
    """
    current = get_latest_memory(entity_id)
    if not current:
        logger.warning("memory.update_skipped_no_active", entity_id=entity_id)
        return None

    base_memory = {
        key: value
        for key, value in current.items()
        if not key.startswith("_")
    }

    operator_notes = list(base_memory.get("operator_notes", []))
    contact_history = list(base_memory.get("contact_history", []))
    transitions = list(base_memory.get("transitions_observed", []))
    now = _now_iso()

    if trigger == "developer.note_added":
        operator_notes.append(
            {
                "timestamp": now,
                "text": payload.get("text", "").strip(),
            }
        )
    elif trigger == "developer.disqualified":
        operator_notes.append(
            {
                "timestamp": now,
                "text": payload.get("reason", "").strip() or "Entity disqualified",
            }
        )
    elif trigger in {"outreach.message_sent", "outreach.reply_received"}:
        contact_history.append(
            {
                "timestamp": now,
                "trigger": trigger,
                "channel": payload.get("channel"),
                "outcome": payload.get("outcome"),
                "notes": payload.get("notes"),
                "draft_id": payload.get("draft_id"),
            }
        )
    elif trigger == "enrichment.state_transition":
        transitions.append(
            {
                "timestamp": now,
                "from": payload.get("from_status"),
                "to": payload.get("to_status"),
                "reason": payload.get("reason"),
            }
        )
    else:
        logger.info("memory.trigger_noop", trigger=trigger, entity_id=entity_id)

    patch = {
        "operator_notes": operator_notes,
        "contact_history": contact_history,
        "transitions_observed": transitions,
    }
    merged = _merge_memory_patch(base_memory, patch)

    if trigger in SIGNIFICANT_MEMORY_TRIGGERS:
        existing_narrative = str(merged.get("narrative", "")).strip()
        extra_sentence = None
        if trigger == "outreach.message_sent":
            extra_sentence = (
                f"Operator sent outreach on {now}"
                + (f" via {payload.get('channel')}." if payload.get("channel") else ".")
            )
        elif trigger == "outreach.reply_received":
            extra_sentence = (
                f"Reply received on {now}"
                + (f" with outcome {payload.get('outcome')}." if payload.get("outcome") else ".")
            )
        elif trigger == "developer.disqualified":
            extra_sentence = (
                f"Entity was disqualified on {now}"
                + (f" because {payload.get('reason')}." if payload.get("reason") else ".")
            )
        if extra_sentence:
            merged["narrative"] = f"{existing_narrative} {extra_sentence}".strip()

    merged_meta = dict(merged.get("meta", {}))
    merged_meta["updated_at"] = now
    merged_meta["last_memory_trigger"] = trigger
    merged["meta"] = merged_meta

    return write_memory(
        entity_id,
        _safe_value(merged),
        summary=merged.get("narrative"),
        entity_type="developer",
    )
