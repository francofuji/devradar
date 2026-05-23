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

def _load_config() -> dict:
    """Load and cache full config.toml."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore
    config_path = Path(_project_root) / "config.toml"
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def _load_draft_model() -> tuple[str, str]:
    """Return (model_name, provider) from config.toml."""
    cfg = _load_config()
    llm = cfg.get("llm", {})
    provider = llm.get("provider", "ollama")
    if provider == "anthropic":
        model = llm.get("anthropic_model_draft", "claude-sonnet-4-6")
    else:
        model = llm.get("ollama_model_draft", "llama3.2:3b")
    return model, provider


def _load_product_context() -> dict:
    """Return product section from config.toml, with safe defaults."""
    cfg = _load_config()
    p = cfg.get("product", {})
    return {
        "name": p.get("name", ""),
        "one_liner": p.get("one_liner", ""),
        "what_it_does": p.get("what_it_does", ""),
        "relevant_when": p.get("relevant_when", ""),
        "avoid_mentioning": p.get("avoid_mentioning", []),
    }


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
                f"Looked through {entity_id}'s work — {narrative[:120].rstrip()}. "
                f"Working on something adjacent and had a question about your approach. "
                f"Would it be useful to compare notes?"
            ),
            "evidence_used": [narrative[:120]],
        },
        {
            "label": "Fallback B",
            "message": (
                f"Came across {entity_id}'s repo while exploring the {angle.replace('_', ' ')} space. "
                f"The direction looks interesting — are you running into any friction with the current setup?"
            ),
            "evidence_used": [f"Project angle: {angle}"],
        },
    ]
    return variants


_META_PATTERNS = re.compile(
    r"(dependencies detected|push recorded|enrichment ran|last push|"
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}|signal_type|category:|intent_score)",
    re.IGNORECASE,
)
_META_SENTENCE_PATTERNS = re.compile(
    r"[^.!?]*("
    r"enrichment ran|dependencies detected|push recorded|last push|"
    r"signal_type|intent_score|outreach_status|entity_id|"
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"
    r")[^.!?]*[.!?]?",
    re.IGNORECASE,
)
# Absence-based hooks are weak outreach angles ("No X detected", "lacks Y", etc.)
_ABSENCE_PATTERNS = re.compile(
    r"\b(no |not detected|absent|missing|lacks?|without|none detected|appear to lack)\b",
    re.IGNORECASE,
)


def _is_absence_signal(text: str) -> bool:
    return bool(_ABSENCE_PATTERNS.search(str(text)))


def _filter_hooks(hooks: list, narrative: str) -> list:
    """Return positive hooks only. If none exist, extract from narrative as fallback."""
    positive = [h for h in hooks if not _is_absence_signal(str(h))]
    if positive:
        return positive
    # Fallback: pull sentences from narrative that mention libraries/tools/decisions
    sentences = re.split(r"[.!?]", narrative)
    stack_sentences = []
    for s in sentences:
        s = s.strip()
        if (
            len(s) > 25
            and any(kw in s.lower() for kw in ["librar", "framework", "using", "built", "depend", "tool"])
        ):
            stack_sentences.append(s)
    return stack_sentences[:2] or hooks  # absolute last resort: original hooks


def build_draft_prompt(entity_id: str, memory: dict, outreach_context: dict) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the outreach draft LLM call.

    Extracted so the same prompt can be returned to the operator via API
    (to copy-paste into ChatGPT / Claude.ai / etc.) without calling the LLM.
    """
    raw_hooks = outreach_context.get("specific_hooks") or memory.get("specific_hooks") or []
    hooks_no_meta = [h for h in raw_hooks if not _META_PATTERNS.search(str(h))]

    # Filter absence-based hooks ("No X detected") — bad outreach angles
    raw_narrative = memory.get("narrative") or memory.get("_summary") or ""
    clean_narrative = _META_SENTENCE_PATTERNS.sub("", raw_narrative).strip()
    hooks = _filter_hooks(hooks_no_meta, clean_narrative)

    # Prefer pain signals with positive evidence; fall back to all if none positive
    all_pain = memory.get("confirmed_pain_signals", [])
    positive_pain = [p for p in all_pain if not _is_absence_signal(str(p.get("evidence", "")))]
    pain_signals = positive_pain if positive_pain else all_pain

    vocabulary_to_avoid = outreach_context.get("vocabulary_to_avoid") or []

    product = _load_product_context()
    vocab_avoid_all = list(set(vocabulary_to_avoid + product.get("avoid_mentioning", [])))

    product_block = ""
    if product.get("name"):
        product_block = f"""
Your product context (you are the founder of this):
- Product: {product['name']}
- What it does: {product['what_it_does'].strip()}
- One-liner: {product['one_liner']}
- Relevant when: {product['relevant_when'].strip()}

Important: weave the product naturally into ONE of the two variants only if there is a clear, honest connection to the developer's actual stack or pain. If there is no clear connection, do not mention it — write a pure curiosity/observation message instead. Never pitch — frame it as a tool you built that might be relevant.
"""

    system_prompt = f"""You are writing a cold outreach message from one technical founder to another.
Use the provided context to write two message variants.
{product_block}
Rules:
(1) Reference ONE specific, verifiable thing they ARE doing — a library they chose, a design decision, an architectural pattern, a problem they're visibly solving. NEVER mention what is absent, missing, or not present in their stack. Absence is not a hook.
(2) Maximum 3 sentences per variant. Under 50 words total.
(3) Do not use these words: {", ".join(vocab_avoid_all) or "none"}.
(4) Write as a technical peer who genuinely read the repo, not a salesperson.
(5) No links, no pitching, no attachments. End with a single open question or concrete offer.
(6) The evidence_used field must contain a human-readable sentence explaining what you observed, not raw metadata.

Return strict JSON only:
{{"variants":[{{"label":"A","message":"string","evidence_used":["string"]}},{{"label":"B","message":"string","evidence_used":["string"]}}]}}"""

    user_prompt = json.dumps(
        {
            "entity_id": entity_id,
            "narrative": clean_narrative or None,
            "recommended_angle": outreach_context.get("recommended_angle"),
            "specific_hooks": hooks[:4],
            "pain_signals": pain_signals[:4],
            "vocabulary_to_avoid": vocab_avoid_all,
        },
        ensure_ascii=True,
        indent=2,
    )

    return system_prompt, user_prompt


def _generate_llm_variants(entity_id: str, memory: dict, outreach_context: dict) -> tuple[list[dict], str | None]:
    system_prompt, prompt = build_draft_prompt(entity_id, memory, outreach_context)
    vocab_avoid_all = json.loads(prompt).get("vocabulary_to_avoid", [])

    draft_model, _ = _load_draft_model()
    try:
        llm_result = call_llm(
            prompt,
            system_prompt,
            model=draft_model,
            max_tokens=700,
            entity_id=entity_id,
            enrichment_type="outreach_draft",
        )
        raw = llm_result["text"].strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw.strip())
        # Extract first JSON object if surrounded by prose
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        raw = match.group(0) if match else raw
        parsed = json.loads(raw)
        variants = parsed.get("variants") or []
        clean = []
        for item in variants[:2]:
            message = _sanitize_variant(str(item.get("message", "")), vocab_avoid_all)
            if not message:
                continue
            # evidence_used may be a string or a list depending on the model
            raw_evidence = item.get("evidence_used") or []
            if isinstance(raw_evidence, str):
                raw_evidence = [raw_evidence]
            clean.append({
                "label": str(item.get("label", "Variant")).strip(),
                "message": message,
                "evidence_used": [str(x) for x in raw_evidence if str(x).strip()],
            })
        if len(clean) >= 2:
            for item in clean[:2]:
                try:
                    capture_example(
                        task_type="draft",
                        system_prompt=system_prompt,
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

    # Evidencia separada — no contamina el texto editable de cada variante
    evidence_notes = []
    for idx, item in enumerate(variants, start=1):
        body.extend([
            f"## Variante {idx} — {item['label']}",
            item["message"],
            "",
        ])
        evidence_notes.append((idx, item["label"], item.get("evidence_used", [])))

    body.extend([
        "## Acciones del operador",
        "- [ ] Usar Variante 1",
        "- [ ] Usar Variante 2",
        "- [ ] Editar antes de enviar",
        "",
        "## Notas del operador",
    ])
    for idx, label, evidence in evidence_notes:
        body.append(f"**Variante {idx} — {label}** · evidencia usada:")
        body.extend([f"- {e}" for e in evidence] or ["- Sin evidencia explícita"])
    body.append("")

    path.write_text("\n".join(body), encoding="utf-8")
    return str(path)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python intelligence/draft_generator.py <entity_id>")
    print(generate_outreach_draft(sys.argv[1]))


if __name__ == "__main__":
    main()
