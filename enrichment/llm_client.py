"""
E10 — LLMClient: multi-provider (Ollama + Anthropic) con Redis cache.
Backward-compat: call_llm() module function sigue disponible para E5 callers.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

import redis as redis_lib
import requests
import structlog

from db.queries import log_enrichment_cost

log = structlog.get_logger().bind(module="enrichment.llm_client")

_RETRY_DELAYS = (1, 2, 4)

# Mapeo enrichment_type → task_type para backward compat
_ENRICHMENT_TYPE_TO_TASK = {
    "readme_extraction": "extraction",
    "pain_detection": "extraction",
    "archetype_classification": "extraction",
    "archetype_disambiguation": "extraction",
    "narrative_generation": "narrative",
    "memory_narrative": "narrative",       # ← fix: ruteaba a extraction → llama3.2:3b
    "draft_generation": "draft",
    "llm": "extraction",
}

# Singleton para backward compat
_DEFAULT_CLIENT: LLMClient | None = None


def _load_config() -> dict:
    import tomllib
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.toml")
    with open(config_path, "rb") as f:
        return tomllib.load(f)


class LLMClient:
    def __init__(self, config: dict | None = None):
        if config is None:
            config = _load_config()
        self._cfg = config.get("llm", {})
        self.provider: str = self._cfg.get("provider", "ollama")

        # Redis cache — degradación elegante si no disponible
        try:
            self._cache = redis_lib.from_url(
                os.getenv("REDIS_URL", "redis://redis:6379/0"),
                decode_responses=False,
                socket_connect_timeout=2,
            )
            self._cache.ping()
            self._cache_enabled = True
            log.info("llm_client.cache_ready", provider=self.provider)
        except Exception as exc:
            self._cache = None
            self._cache_enabled = False
            log.warning("llm_client.cache_unavailable", error=str(exc))

        # Cliente Anthropic lazy-init
        self._anthropic_client = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def call_llm(
        self,
        prompt: str,
        system_prompt: str,
        task_type: str = "extraction",
        max_tokens: int = 1024,
        *,
        entity_id: str = "system",
        enrichment_type: str = "llm",
    ) -> dict[str, Any]:
        if self._cache_enabled:
            return self._call_with_cache(
                prompt, system_prompt, task_type, max_tokens,
                entity_id=entity_id, enrichment_type=enrichment_type,
            )
        return self._call_provider(
            prompt, system_prompt, task_type, max_tokens,
            entity_id=entity_id, enrichment_type=enrichment_type,
        )

    # ------------------------------------------------------------------
    # Cache layer
    # ------------------------------------------------------------------

    def _call_with_cache(
        self,
        prompt: str,
        system_prompt: str,
        task_type: str,
        max_tokens: int,
        *,
        entity_id: str,
        enrichment_type: str,
    ) -> dict[str, Any]:
        raw = f"{task_type}:{self.provider}:{system_prompt}:{prompt}"
        cache_key = f"llm:{hashlib.sha256(raw.encode()).hexdigest()[:24]}"

        try:
            cached = self._cache.get(cache_key)
            if cached:
                log.info(
                    "llm_client.cache_hit",
                    task=task_type,
                    key=cache_key[:12],
                )
                return json.loads(cached)
        except Exception as exc:
            log.warning("llm_client.cache_read_error", error=str(exc))

        result = self._call_provider(
            prompt, system_prompt, task_type, max_tokens,
            entity_id=entity_id, enrichment_type=enrichment_type,
        )

        if result is not None:
            ttl_map = {
                "extraction": self._cfg.get("cache_ttl_extraction", 86400),
                "narrative": self._cfg.get("cache_ttl_narrative", 43200),
                "draft": self._cfg.get("cache_ttl_draft", 21600),
            }
            ttl = ttl_map.get(task_type, 86400)
            try:
                self._cache.setex(cache_key, ttl, json.dumps(result))
                log.info(
                    "llm_client.cache_set",
                    task=task_type,
                    key=cache_key[:12],
                    ttl=ttl,
                )
            except Exception as exc:
                log.warning("llm_client.cache_write_error", error=str(exc))

        return result

    # ------------------------------------------------------------------
    # Provider dispatch
    # ------------------------------------------------------------------

    def _call_provider(
        self,
        prompt: str,
        system_prompt: str,
        task_type: str,
        max_tokens: int,
        *,
        entity_id: str,
        enrichment_type: str,
    ) -> dict[str, Any]:
        if self.provider == "ollama":
            return self._call_ollama(
                prompt, system_prompt, task_type, max_tokens,
                entity_id=entity_id, enrichment_type=enrichment_type,
            )
        return self._call_anthropic(
            prompt, system_prompt, task_type, max_tokens,
            entity_id=entity_id, enrichment_type=enrichment_type,
        )

    # ------------------------------------------------------------------
    # Ollama
    # ------------------------------------------------------------------

    def _call_ollama(
        self,
        prompt: str,
        system_prompt: str,
        task_type: str,
        max_tokens: int,
        *,
        entity_id: str,
        enrichment_type: str,
    ) -> dict[str, Any]:
        model_map = {
            "extraction": self._cfg.get("ollama_model_extraction", "llama3.1:8b"),
            "narrative": self._cfg.get("ollama_model_narrative", "qwen2.5:7b"),
            "draft": self._cfg.get("ollama_model_draft", "qwen2.5:7b"),
        }
        model = model_map.get(task_type, self._cfg.get("ollama_model_extraction", "llama3.1:8b"))
        base_url = self._cfg.get("ollama_base_url", "http://ollama:11434")
        timeout = self._cfg.get("ollama_timeout_seconds", 180)
        temperature = self._cfg.get("ollama_temperature", 0.3)

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }

        last_exc: Exception | None = None
        for attempt, delay in enumerate([0] + list(_RETRY_DELAYS)):
            if delay:
                time.sleep(delay)
            try:
                resp = requests.post(
                    f"{base_url}/api/chat",
                    json=payload,
                    timeout=timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                text = data.get("message", {}).get("content", "").strip()

                log.info(
                    "llm_client.ollama_ok",
                    model=model,
                    entity=entity_id,
                    task=task_type,
                    chars=len(text),
                )
                log_enrichment_cost(
                    entity_id=entity_id,
                    enrichment_type=enrichment_type,
                    llm_calls=1,
                    input_tokens=0,
                    output_tokens=0,
                    provider="ollama",
                    prompt=prompt,
                    response=text,
                )
                return {"text": text, "model": model, "input_tokens": 0, "output_tokens": 0}

            except requests.exceptions.ConnectionError as exc:
                last_exc = exc
                if attempt < len(_RETRY_DELAYS):
                    log.warning(
                        "llm_client.ollama_retry",
                        attempt=attempt + 1,
                        delay=_RETRY_DELAYS[attempt] if attempt < len(_RETRY_DELAYS) else 0,
                        error=str(exc),
                    )
                continue
            except Exception as exc:
                log.error("llm_client.ollama_failed", model=model, entity=entity_id, error=str(exc))
                raise

        assert last_exc is not None
        raise last_exc

    # ------------------------------------------------------------------
    # Anthropic
    # ------------------------------------------------------------------

    def _get_anthropic_client(self):
        if self._anthropic_client is not None:
            return self._anthropic_client
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key or api_key == "your_anthropic_api_key_here":
            raise RuntimeError(
                "ANTHROPIC_API_KEY no configurada. "
                "Configúrala en .env o usa provider=ollama."
            )
        from anthropic import Anthropic
        self._anthropic_client = Anthropic(api_key=api_key)
        return self._anthropic_client

    def _call_anthropic(
        self,
        prompt: str,
        system_prompt: str,
        task_type: str,
        max_tokens: int,
        *,
        entity_id: str,
        enrichment_type: str,
    ) -> dict[str, Any]:
        model_map = {
            "extraction": self._cfg.get("anthropic_model_extraction", "claude-haiku-4-5-20251001"),
            "narrative": self._cfg.get("anthropic_model_narrative", "claude-sonnet-4-6"),
            "draft": self._cfg.get("anthropic_model_draft", "claude-sonnet-4-6"),
        }
        model = model_map.get(task_type, self._cfg.get("anthropic_model_extraction", "claude-haiku-4-5-20251001"))

        client = self._get_anthropic_client()
        last_exc: Exception | None = None

        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=0,
                    system=system_prompt,
                    messages=[{"role": "user", "content": prompt}],
                )
                usage = getattr(response, "usage", None)
                input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
                parts = [
                    getattr(b, "text", None)
                    for b in (getattr(response, "content", []) or [])
                ]
                text = "\n".join(p for p in parts if p).strip()

                log.info(
                    "llm_client.anthropic_ok",
                    model=model,
                    entity=entity_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                log_enrichment_cost(
                    entity_id=entity_id,
                    enrichment_type=enrichment_type,
                    llm_calls=1,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    provider="anthropic",
                    prompt=prompt,
                    response=text,
                )
                return {"text": text, "model": model, "input_tokens": input_tokens, "output_tokens": output_tokens}

            except Exception as exc:
                last_exc = exc
                status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
                if status == 529 and attempt < len(_RETRY_DELAYS):
                    delay = _RETRY_DELAYS[attempt]
                    log.warning("llm_client.anthropic_529", delay=delay, attempt=attempt + 1)
                    time.sleep(delay)
                    continue
                log.error("llm_client.anthropic_failed", model=model, entity=entity_id, error=str(exc))
                raise

        assert last_exc is not None
        raise last_exc


# ------------------------------------------------------------------
# Ollama health check
# ------------------------------------------------------------------

def check_ollama_health(base_url: str | None = None) -> dict[str, Any]:
    if base_url is None:
        try:
            cfg = _load_config()
            base_url = cfg.get("llm", {}).get("ollama_base_url", "http://ollama:11434")
        except Exception:
            base_url = "http://ollama:11434"
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        return {"available": True, "models": models, "error": None}
    except Exception as exc:
        return {"available": False, "models": [], "error": str(exc)}


# ------------------------------------------------------------------
# Backward-compat shim (para E5 callers: readme_extractor, pain_detector, etc.)
# ------------------------------------------------------------------

# Modelo legacy usado como default
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def _get_default_client() -> LLMClient:
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        _DEFAULT_CLIENT = LLMClient()
    return _DEFAULT_CLIENT


def call_llm(
    prompt: str,
    system_prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1200,
    *,
    entity_id: str = "system",
    enrichment_type: str = "llm",
) -> dict[str, Any]:
    """Backward-compat wrapper. Mapea enrichment_type → task_type."""
    task_type = _ENRICHMENT_TYPE_TO_TASK.get(enrichment_type, "extraction")
    return _get_default_client().call_llm(
        prompt=prompt,
        system_prompt=system_prompt,
        task_type=task_type,
        max_tokens=max_tokens,
        entity_id=entity_id,
        enrichment_type=enrichment_type,
    )
