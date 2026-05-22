"""
E5.T2–T4 — Extracción estructurada de README usando LLM.
"""
from __future__ import annotations

import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
sys.path = [p for p in sys.path if os.path.abspath(p) != _this_dir]
sys.path.insert(0, _project_root)

import argparse
import json
import logging
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from enrichment.llm_client import DEFAULT_MODEL, call_llm
from enrichment.types import ProductType, ReadmeIntel

logger = logging.getLogger("enrichment.readme_extractor")

README_MODEL = "claude-haiku-4-5-20251001"
MIN_README_WORDS = 150

SYSTEM_PROMPT = """You extract product intelligence from README text.
Return strict JSON only. Do not wrap the JSON in markdown.

Schema:
{
  "product_type": {"value": "web_app|library|cli|agent|api|framework|plugin|unknown|null", "evidence": "string|null"},
  "target_user": {"value": "string|null", "evidence": "string|null"},
  "pain_solved": {"value": "string|null", "evidence": "string|null"},
  "limitations": [{"value": "string", "evidence": "string"}],
  "roadmap_items": [{"value": "string", "evidence": "string"}],
  "has_demo": {"value": true|false|null, "evidence": "string|null"},
  "readme_quality_score": {"value": 0-10|null, "evidence": "string|null"}
}

If you cannot find clear evidence for a field in the provided README text, return null. Do not use your general knowledge. Only use the text provided. The evidence field must contain a direct quote or paraphrase from the README."""


def _extract_value_and_evidence(field: Any) -> tuple[Any, str | None]:
    if not isinstance(field, dict):
        return None, None
    return field.get("value"), field.get("evidence")


def validate_readme_output(output_dict: dict[str, Any]) -> dict[str, Any] | None:
    """
    Verifica enum, rangos y evidence obligatorio para claims no-null.
    """
    try:
        valid_product_types = {item.value for item in ProductType}

        product_type_value, product_type_evidence = _extract_value_and_evidence(
            output_dict.get("product_type")
        )
        if product_type_value is not None and product_type_value not in valid_product_types:
            raise ValueError(f"product_type inválido: {product_type_value}")
        if product_type_value is not None and not product_type_evidence:
            raise ValueError("product_type sin evidence")

        for field_name in ("target_user", "pain_solved", "has_demo", "readme_quality_score"):
            value, evidence = _extract_value_and_evidence(output_dict.get(field_name))
            if value is not None and not evidence:
                raise ValueError(f"{field_name} sin evidence")

        score_value, _ = _extract_value_and_evidence(output_dict.get("readme_quality_score"))
        if score_value is not None and not (0 <= int(score_value) <= 10):
            raise ValueError(f"readme_quality_score fuera de rango: {score_value}")

        for field_name in ("limitations", "roadmap_items"):
            items = output_dict.get(field_name) or []
            if not isinstance(items, list):
                raise ValueError(f"{field_name} debe ser lista")
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError(f"{field_name} contiene item inválido")
                value = item.get("value")
                evidence = item.get("evidence")
                if value and not evidence:
                    raise ValueError(f"{field_name} item sin evidence")

        return output_dict
    except Exception as exc:
        logger.warning("README output inválido: %s", exc)
        return None


def _build_readme_intel(validated: dict[str, Any]) -> ReadmeIntel:
    evidence: dict[str, str] = {}

    product_type_value, product_type_evidence = _extract_value_and_evidence(validated.get("product_type"))
    if product_type_evidence:
        evidence["product_type"] = product_type_evidence

    target_user, target_user_evidence = _extract_value_and_evidence(validated.get("target_user"))
    if target_user_evidence:
        evidence["target_user"] = target_user_evidence

    pain_solved, pain_solved_evidence = _extract_value_and_evidence(validated.get("pain_solved"))
    if pain_solved_evidence:
        evidence["pain_solved"] = pain_solved_evidence

    has_demo, has_demo_evidence = _extract_value_and_evidence(validated.get("has_demo"))
    if has_demo_evidence:
        evidence["has_demo"] = has_demo_evidence

    readme_quality_score, score_evidence = _extract_value_and_evidence(validated.get("readme_quality_score"))
    if score_evidence:
        evidence["readme_quality_score"] = score_evidence

    limitations_items = validated.get("limitations") or []
    roadmap_items = validated.get("roadmap_items") or []
    limitations = [item["value"] for item in limitations_items if item.get("value")]
    roadmap = [item["value"] for item in roadmap_items if item.get("value")]
    limitation_evidence = [item.get("evidence") for item in limitations_items if item.get("evidence")]
    roadmap_evidence = [item.get("evidence") for item in roadmap_items if item.get("evidence")]
    if limitation_evidence:
        evidence["limitations"] = " | ".join(limitation_evidence)
    if roadmap_evidence:
        evidence["roadmap_items"] = " | ".join(roadmap_evidence)

    product_type = None
    if product_type_value is not None:
        product_type = ProductType(product_type_value)

    return ReadmeIntel(
        product_type=product_type,
        target_user=target_user,
        pain_solved=pain_solved,
        limitations=limitations,
        roadmap_items=roadmap,
        has_demo=bool(has_demo) if has_demo is not None else False,
        readme_quality_score=int(readme_quality_score or 0),
        evidence=evidence,
    )


def extract_readme_intel(
    readme_content: str | None,
    repo_full_name: str,
    *,
    include_metadata: bool = False,
) -> ReadmeIntel | tuple[ReadmeIntel | None, dict[str, int]]:
    """
    Extrae ReadmeIntel desde texto ya fetched.
    """
    empty_meta = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
    if not readme_content or len(readme_content.split()) < MIN_README_WORDS:
        return (None, empty_meta) if include_metadata else None

    prompt = (
        f"Repository: {repo_full_name}\n"
        "Analyze only the README text below and return strict JSON.\n\n"
        f"{readme_content}"
    )

    try:
        llm_result = call_llm(
            prompt,
            SYSTEM_PROMPT,
            model=README_MODEL,
            max_tokens=1200,
            entity_id=repo_full_name,
            enrichment_type="readme_extraction",
        )
        parsed = json.loads(llm_result["text"])
    except json.JSONDecodeError as exc:
        logger.warning("README extractor JSON inválido para %s: %s", repo_full_name, exc)
        meta = {
            "llm_calls": 1,
            "input_tokens": int(llm_result.get("input_tokens", 0)),
            "output_tokens": int(llm_result.get("output_tokens", 0)),
        } if "llm_result" in locals() else empty_meta
        return (None, meta) if include_metadata else None
    except Exception as exc:
        logger.warning("README extractor falló para %s: %s", repo_full_name, exc)
        return (None, empty_meta) if include_metadata else None

    validated = validate_readme_output(parsed)
    if validated is None:
        meta = {
            "llm_calls": 1,
            "input_tokens": int(llm_result.get("input_tokens", 0)),
            "output_tokens": int(llm_result.get("output_tokens", 0)),
        }
        return (None, meta) if include_metadata else None

    intel = _build_readme_intel(validated)
    meta = {
        "llm_calls": 1,
        "input_tokens": int(llm_result.get("input_tokens", 0)),
        "output_tokens": int(llm_result.get("output_tokens", 0)),
    }
    return (intel, meta) if include_metadata else intel


def enrich_readme(repo_full_name: str) -> ReadmeIntel | None:
    """
    Helper para dispatcher/CLI: fetch de README vía github_profile y extracción LLM.
    """
    sys.path.insert(0, os.path.join(_project_root, "collectors"))
    from github_client import GitHubClient
    from enrichment.github_profile import fetch_repo_profile

    client = GitHubClient()
    profile = fetch_repo_profile(
        repo_full_name,
        client,
        fetch_issues=False,
        fetch_readme=True,
    )
    if profile is None:
        logger.warning("No se pudo obtener perfil para %s", repo_full_name)
        return None
    return extract_readme_intel(profile.readme_content, repo_full_name)


def _to_jsonable(intel: ReadmeIntel | None) -> dict[str, Any] | None:
    if intel is None:
        return None
    return {
        "product_type": intel.product_type.value if intel.product_type else None,
        "target_user": intel.target_user,
        "pain_solved": intel.pain_solved,
        "limitations": intel.limitations,
        "roadmap_items": intel.roadmap_items,
        "has_demo": intel.has_demo,
        "readme_quality_score": intel.readme_quality_score,
        "evidence": intel.evidence,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser(description="Extract README intelligence for a repo")
    parser.add_argument("--repo", required=True, help="owner/repo")
    args = parser.parse_args()

    intel = enrich_readme(args.repo)
    print(json.dumps(_to_jsonable(intel), indent=2, ensure_ascii=True))
