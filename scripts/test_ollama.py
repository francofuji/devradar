"""
E10.T7 — Verifica Ollama + Redis cache.
Uso: docker compose exec api python scripts/test_ollama.py
"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, ".")

from enrichment.llm_client import LLMClient, check_ollama_health

PROMPT = "List three Python web frameworks in one sentence."
SYSTEM = "You are a concise technical assistant."


def main() -> None:
    print("=" * 50)
    print("Test E10 — Ollama + Redis cache")
    print("=" * 50)

    # 1. Health check
    health = check_ollama_health()
    print(f"\n[1] Ollama health: available={health['available']}")
    if health["error"]:
        print(f"    ERROR: {health['error']}")
        sys.exit(1)
    print(f"    Models: {health['models'] or '(ninguno descargado)'}")
    if not health["models"]:
        print("    ⚠  Sin modelos. Correr: make pull-model")
        sys.exit(1)

    # 2. Primera llamada (cache MISS esperado)
    client = LLMClient()
    print(f"\n[2] Primera llamada (provider={client.provider}) ...")
    t0 = time.perf_counter()
    try:
        result = client.call_llm(
            prompt=PROMPT,
            system_prompt=SYSTEM,
            task_type="extraction",
            max_tokens=100,
            entity_id="test_ollama",
            enrichment_type="llm",
        )
        elapsed1 = time.perf_counter() - t0
        print(f"    Latencia: {elapsed1:.2f}s")
        print(f"    Modelo: {result['model']}")
        words = result["text"].split()
        print(f"    Respuesta ({len(words)} palabras): {' '.join(words[:20])}...")
    except Exception as exc:
        print(f"    ERROR en primera llamada: {exc}")
        sys.exit(1)

    # 3. Segunda llamada (cache HIT esperado)
    print("\n[3] Segunda llamada (mismo prompt — debe ser cache HIT) ...")
    t1 = time.perf_counter()
    result2 = client.call_llm(
        prompt=PROMPT,
        system_prompt=SYSTEM,
        task_type="extraction",
        max_tokens=100,
        entity_id="test_ollama",
        enrichment_type="llm",
    )
    elapsed2 = time.perf_counter() - t1
    print(f"    Latencia: {elapsed2:.4f}s")

    if elapsed2 < 0.5 and elapsed1 > 1.0:
        print("    ✅ Cache HIT confirmado (segunda llamada instantánea)")
    elif not client._cache_enabled:
        print("    ⚠  Redis no disponible — cache deshabilitado")
    else:
        print(f"    ⚠  Cache status incierto (1a={elapsed1:.2f}s 2a={elapsed2:.4f}s)")

    # 4. Stats de cache
    if client._cache_enabled:
        keys = client._cache.keys("llm:*")
        info = client._cache.info("memory")
        print(f"\n[4] Cache Redis: {len(keys)} keys LLM | {info['used_memory_human']} usados")
    else:
        print("\n[4] Redis no disponible — stats omitidos")

    print("\n✅ test_ollama.py completado")


if __name__ == "__main__":
    main()
