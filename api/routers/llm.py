"""
E10.T7b — Endpoints de estado LLM y cache Redis.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

from enrichment.llm_client import LLMClient, check_ollama_health
from api.deps import get_config

log = structlog.get_logger().bind(module="api.routers.llm")
router = APIRouter(prefix="/api/llm", tags=["llm"])

_client: LLMClient | None = None


def _get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


@router.get("/status")
def llm_status() -> dict:
    client = _get_client()
    health = check_ollama_health()
    config = get_config()
    llm_cfg = config.get("llm", {})
    return {
        "provider": client.provider,
        "cache_enabled": client._cache_enabled,
        "ollama": health,
        "models": {
            "extraction": llm_cfg.get(f"{client.provider}_model_extraction"),
            "narrative": llm_cfg.get(f"{client.provider}_model_narrative"),
            "draft": llm_cfg.get(f"{client.provider}_model_draft"),
        },
    }


@router.get("/cache-stats")
def cache_stats() -> dict:
    client = _get_client()
    if not client._cache_enabled:
        return {"enabled": False, "total_keys": 0, "memory_used_mb": 0.0, "memory_limit_mb": 256.0, "keys_by_task": {}}

    try:
        all_keys = client._cache.keys("llm:*")
        info = client._cache.info("memory")
        used_bytes = info.get("used_memory", 0)

        # Contar keys por task_type es difícil sin TTL metadata — usamos prefijos guardados opcionalmente.
        # Como el hash no codifica task_type, reportamos total. E17 puede refinar esto.
        return {
            "enabled": True,
            "total_keys": len(all_keys),
            "memory_used_mb": round(used_bytes / 1024 / 1024, 2),
            "memory_limit_mb": 256.0,
            "keys_by_task": {},
        }
    except Exception as exc:
        log.error("cache_stats.error", error=str(exc))
        return {"enabled": True, "error": str(exc)}


@router.get("/models")
def llm_models() -> dict:
    health = check_ollama_health()
    config = get_config()
    llm_cfg = config.get("llm", {})
    return {
        "provider": llm_cfg.get("provider", "ollama"),
        "available_models": health.get("models", []),
        "configured_models": {
            "ollama": {
                "extraction": llm_cfg.get("ollama_model_extraction"),
                "narrative": llm_cfg.get("ollama_model_narrative"),
                "draft": llm_cfg.get("ollama_model_draft"),
            },
            "anthropic": {
                "extraction": llm_cfg.get("anthropic_model_extraction"),
                "narrative": llm_cfg.get("anthropic_model_narrative"),
                "draft": llm_cfg.get("anthropic_model_draft"),
            },
        },
    }


class LlmTestRequest(BaseModel):
    prompt: str
    task_type: str = "narrative"
    system_prompt: str | None = None


@router.post("/test")
def test_llm(payload: LlmTestRequest) -> dict:
    client = _get_client()
    cache_key_before = None
    cache_key_after = None
    try:
        if client._cache_enabled:
            import hashlib
            raw = f"{payload.task_type}:{payload.system_prompt or ''}:{payload.prompt}"
            cache_key_before = "llm:" + hashlib.sha256(raw.encode()).hexdigest()[:32]
            cache_hit = bool(client._cache.exists(cache_key_before))
        else:
            cache_hit = False

        system = payload.system_prompt or "You are a helpful assistant."

        cache_hit = False
        if client._cache_enabled:
            import hashlib as _hashlib
            raw = f"{payload.task_type}:{client.provider}:{system}:{payload.prompt}"
            cache_key = "llm:" + _hashlib.sha256(raw.encode()).hexdigest()[:24]
            cache_hit = bool(client._cache.exists(cache_key))

        result = client.call_llm(
            prompt=payload.prompt,
            system_prompt=system,
            task_type=payload.task_type,
            entity_id="system-test",
            enrichment_type=payload.task_type,
        )

        cached_now = False
        if client._cache_enabled and not cache_hit:
            cached_now = bool(client._cache.exists(cache_key))

        return {
            "output": result,
            "cache_hit": cache_hit,
            "cached_now": cached_now,
            "task_type": payload.task_type,
        }
    except Exception as exc:
        log.error("llm.test.error", error=str(exc))
        return {"error": str(exc), "cache_hit": False, "cached_now": False}
