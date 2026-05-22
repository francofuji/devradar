"""
E8 — Outreach draft generator with graceful LLM fallback.
"""
from __future__ import annotations

import json
import os
import re
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
sys.path.insert(0, _project_root)

from datetime import datetime, timezone
from pathlib import Path

from db.memory_queries import get_latest_memory
from db.queries import get_developer
from enrichment.llm_client import call_llm
from fine_tuning.capture import capture_example

DRAFT_MODEL = "claude-sonnet-4-6"


def _provider_from_model(model_name: str | None) -> str | None:
    if not model_name:
        return None
    if "claude" in model_name.lower():
        return "anthropic"
    return "ollama"


def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_outreach_context(memory: dict) -> dict:
    meta_context = memory.get("meta", {}).get("outreach_context")
    if isinstance(meta_context, dict):
        return meta_context
    return {
        "recommended_angle": memory.get("recommended_angle"),
        "specific_hooks": memory.get("specific_hooks", []),
        "vocabulary_to_use": [],
        "vocabulary_to_avoid": [],
        "tone": "peer_technical",
    }


def _sanitize_variant(text: str, vocabulary_to_avoid: list[str]) -> str:
    result = " ".join(text.strip().split())
    for word in vocabulary_to_avoid:
        result = re.sub(rf"\b{re.escape(word)}\b", "avoid", result, flags=re.IGNORECASE)
    return result


def _build_fallback_variants(entity_id: str, memory: dict, outreach_context: dict) -> list[dict]:
    hooks = outreach_context.get("specific_hooks") or memory.get("specific_hooks") or []
    first_hook = hooks[0] if hooks else "the current implementation details in your repo"
    second_hook = hooks[1] if len(hooks) > 1 else first_hook
    angle = outreach_context.get("recommended_angle") or memory.get("recommended_angle") or "monitor"
    narrative = memory.get("narrative") or memory.get("_summary") or f"I looked at {entity_id}'s work."

    variants = [
        {
            "label": "Fallback A",
            "message": (
                f"Spent a bit of time on your repo and noticed {first_hook}. "
                f"I work on infra around {angle}, and I think there may be a useful shortcut here. "
                f"If helpful, I can send a concrete idea after reading the same evidence you already surfaced."
            ),
            "evidence_used": [first_hook],
        },
        {
            "label": "Fallback B",
            "message": (
                f"Read through your latest context and the part that stood out was {second_hook}. "
                f"I build for teams hitting this kind of {angle} issue and can share one concrete approach. "
                f"Happy to send it if you're actively revisiting that area."
            ),
            "evidence_used": [second_hook, narrative],
        },
    ]
    return variants


def _generate_llm_variants(entity_id: str, memory: dict, outreach_context: dict) -> tuple[list[dict], str | None]:
    hooks = outreach_context.get("specific_hooks") or memory.get("specific_hooks") or []
    pain_signals = memory.get("confirmed_pain_signals", [])
    vocabulary_to_avoid = outreach_context.get("vocabulary_to_avoid") or []

    system_prompt = """You are writing a cold outreach message from one technical founder to another.
Use the provided context to write two message variants.
Rules:
(1) Each variant must reference ONE specific, verifiable observation — not a generic claim.
(2) Maximum 3 sentences per variant.
(3) Do not use these words: {vocabulary_to_avoid}.
(4) Write as a technical peer, not a salesperson.
(5) The recipient should feel you actually looked at their work.
Return strict JSON only:
{"variants":[{"label":"A","message":"string","evidence_used":["string"]},{"label":"B","message":"string","evidence_used":["string"]}]}"""

    prompt = json.dumps(
        {
            "entity_id": entity_id,
            "narrative": memory.get("narrative") or memory.get("_summary"),
            "recommended_angle": outreach_context.get("recommended_angle"),
            "specific_hooks": hooks[:4],
            "pain_signals": pain_signals[:4],
            "vocabulary_to_avoid": vocabulary_to_avoid,
        },
        ensure_ascii=True,
    )

    try:
        llm_result = call_llm(
            prompt,
            system_prompt.replace("{vocabulary_to_avoid}", ", ".join(vocabulary_to_avoid)),
            model=DRAFT_MODEL,
            max_tokens=700,
            entity_id=entity_id,
            enrichment_type="outreach_draft",
        )
        parsed = json.loads(llm_result["text"])
        variants = parsed.get("variants") or []
        clean = []
        for item in variants[:2]:
            message = _sanitize_variant(str(item.get("message", "")), vocabulary_to_avoid)
            if not message:
                continue
            clean.append({
                "label": str(item.get("label", "Variant")).strip(),
                "message": message,
                "evidence_used": [str(x) for x in (item.get("evidence_used") or []) if str(x).strip()],
            })
        if len(clean) >= 2:
            for item in clean[:2]:
                try:
                    capture_example(
                        task_type="draft",
                        system_prompt=system_prompt.replace("{vocabulary_to_avoid}", ", ".join(vocabulary_to_avoid)),
                        user_input=prompt,
                        model_output=item["message"],
                        approved_output=item["message"],
                        entity_id=entity_id,
                        provider=_provider_from_model(llm_result.get("model")),
                        model_used=llm_result.get("model"),
                    )
                except Exception:
                    pass
            return clean[:2], None
        return [], "LLM returned insufficient variants"
    except Exception as exc:
        return [], str(exc)


def generate_outreach_draft(entity_id: str) -> str:
    developer = get_developer(entity_id)
    memory = get_latest_memory(entity_id)
    if not developer or not memory:
        raise ValueError(f"No developer or active memory found for {entity_id}")

    outreach_context = _load_outreach_context(memory)
    variants, llm_error = _generate_llm_variants(entity_id, memory, outreach_context)
    if not variants:
        variants = _build_fallback_variants(entity_id, memory, outreach_context)

    output_dir = Path(_project_root) / "output" / "drafts"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{entity_id}_{_utc_today()}.md"

    body = [
        f"# Outreach Drafts — {entity_id}",
        "",
        f"- Status: `{developer['status']}`",
        f"- Intent score: `{developer['intent_score']}`",
        f"- Angle: `{outreach_context.get('recommended_angle') or memory.get('recommended_angle')}`",
    ]
    if llm_error:
        body.append(f"- Draft generation mode: fallback (`{llm_error}`)")
    else:
        body.append("- Draft generation mode: LLM")
    body.append("")

    for idx, item in enumerate(variants, start=1):
        body.extend([
            f"## Variante {idx} — {item['label']}",
            item["message"],
            "",
            "Evidence used:",
            *([f"- {e}" for e in item.get("evidence_used", [])] or ["- Sin evidencia explícita"]),
            "",
            "Qué editar antes de enviar:",
            "- Ajustar el canal si no será email.",
            "- Reemplazar la última frase por un CTA más concreto si ya hubo contacto previo.",
            "",
        ])

    body.extend([
        "## Acciones del operador",
        "- [ ] Usar Variante 1",
        "- [ ] Usar Variante 2",
        "- [ ] Editar antes de enviar",
        "",
    ])

    path.write_text("\n".join(body), encoding="utf-8")
    return str(path)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python intelligence/draft_generator.py <entity_id>")
    print(generate_outreach_draft(sys.argv[1]))


if __name__ == "__main__":
    main()
