"""
Smoke test de foundation sobre PostgreSQL + Redis.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import redis

sys.path.insert(0, str(Path(__file__).parent.parent))


def section(title: str):
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print("─" * 50)


def ok(msg: str):
    print(f"  ✅ {msg}")


def fail(msg: str):
    print(f"  ❌ {msg}")
    sys.exit(1)


def warn(msg: str):
    print(f"  ⚠️  {msg}")


def _cleanup_test_data():
    from db import get_connection

    with get_connection() as conn:
        conn.execute("DELETE FROM events WHERE entity_id LIKE %s", ("__test_%",))
        conn.execute("DELETE FROM events WHERE entity_id = %s", ("__health__",))
        conn.execute("DELETE FROM developers WHERE id LIKE %s", ("__test_%",))
        conn.execute("DELETE FROM repositories WHERE id LIKE %s", ("__test_%",))
        conn.execute("DELETE FROM enrichment_queue WHERE entity_id LIKE %s", ("__test_%",))
        conn.execute("DELETE FROM signals WHERE entity_id LIKE %s", ("__test_%",))
        conn.execute("DELETE FROM entity_memory WHERE entity_id LIKE %s", ("__test_%",))
        conn.execute("DELETE FROM enrichment_costs WHERE entity_id LIKE %s", ("__test_%",))


def run():
    print("\n🧪 TEST FOUNDATION — Dev Intelligence Platform")
    print("=" * 50)

    _cleanup_test_data()

    section("1. Imports de módulos core")
    try:
        from db import get_connection, get_pool
        ok("db.get_connection + db.get_pool")
    except Exception as exc:
        fail(f"db import: {exc}")

    try:
        from db.catalog import VALID_EVENT_TYPES, get_category, validate_event_type
        ok(f"db.catalog ({len(VALID_EVENT_TYPES)} event types)")
    except Exception as exc:
        fail(f"db.catalog: {exc}")

    try:
        from db.events import emit_event
        ok("db.events.emit_event")
    except Exception as exc:
        fail(f"db.events: {exc}")

    try:
        from db.queries import (
            developer_exists,
            emit_signal,
            enqueue_enrichment,
            get_active_signals,
            get_developer,
            get_pending_enrichment,
            get_pending_queue,
            get_total_cost,
            log_enrichment_cost,
            repository_exists,
            update_queue_status,
            upsert_developer,
            upsert_repository,
        )
        ok("db.queries")
    except Exception as exc:
        fail(f"db.queries: {exc}")

    try:
        from db.memory_queries import get_latest_memory, get_narrative, write_memory
        ok("db.memory_queries")
    except Exception as exc:
        fail(f"db.memory_queries: {exc}")

    try:
        from enrichment.types import (
            Archetype,
            DeveloperStatus,
            EnrichmentResult,
            IntentTier,
            MaturityTier,
            PainCategory,
            PainSignal,
            StackSnapshot,
        )
        ok("enrichment.types")
    except Exception as exc:
        fail(f"enrichment.types: {exc}")

    section("2. Base de datos y tablas")
    try:
        with get_connection() as conn:
            tables = conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
                """
            ).fetchall()
        table_names = [row["table_name"] for row in tables]
        expected = [
            "developers",
            "enrichment_costs",
            "enrichment_queue",
            "entity_memory",
            "events",
            "fine_tuning_examples",
            "model_registry",
            "repositories",
            "score_history",
            "signals",
        ]
        for table_name in expected:
            if table_name in table_names:
                ok(f"tabla '{table_name}' existe")
            else:
                fail(f"tabla '{table_name}' faltante")
    except Exception as exc:
        fail(f"Conexión a DB: {exc}")

    section("3. emit_event() y deduplicación")
    from db.events import emit_event

    test_handle = "__test_foundation__"
    test_repo = "__test_org__/__test_repo__"

    event_id = emit_event(
        "developer.discovered",
        test_handle,
        "developer",
        {"name": "Test Dev", "source": "foundation_test"},
        source="internal",
    )
    if event_id:
        ok(f"emit_event retornó event_id: {event_id[:8]}...")
    else:
        fail("emit_event retornó None")

    duplicate = emit_event(
        "developer.discovered",
        test_handle,
        "developer",
        {"name": "Test Dev", "source": "foundation_test"},
        source="internal",
    )
    if duplicate is None:
        ok("deduplicación funciona")
    else:
        warn("deduplicación no detectó duplicado")

    try:
        emit_event("evento.invalido.xyz", test_handle, "developer", {})
        fail("Debería fallar para event_type inválido")
    except ValueError:
        ok("ValueError para event_type inválido")

    test_event = emit_event("test.event", "__health__", "developer", {"msg": "test"})
    if test_event:
        ok("test.event emitido correctamente")
    else:
        warn("test.event fue tratado como duplicado")

    section("4. upsert_developer, JSONB y pool")
    from db.queries import developer_exists, get_developer, upsert_developer

    upsert_developer(
        {
            "id": test_handle,
            "name": "Test Developer",
            "email": "test@example.com",
            "github_url": f"https://github.com/{test_handle}",
        }
    )
    ok("upsert_developer ejecutado")

    from db.queries import update_developer_profile_fields

    update_developer_profile_fields(test_handle, linkedin_manual={"title": "Founder", "company": "TestCo"})
    dev = get_developer(test_handle)
    if dev and dev["name"] == "Test Developer":
        ok("get_developer retorna entidad correcta")
    else:
        fail("get_developer no retornó la entidad insertada")

    if isinstance(dev["linkedin_manual"], dict):
        ok("linkedin_manual usa JSONB nativo")
    else:
        fail("linkedin_manual no volvió como dict")

    if developer_exists(test_handle):
        ok("developer_exists retorna True")
    else:
        fail("developer_exists retorna False")

    pool = get_pool()
    raw_connections = [pool.getconn() for _ in range(3)]
    try:
        ok("pool abrió 3 conexiones simultáneas")
    finally:
        for raw_connection in raw_connections:
            pool.putconn(raw_connection)

    section("5. upsert_repository y repository_exists")
    from db.queries import repository_exists, upsert_repository

    upsert_repository(
        {
            "id": test_repo,
            "owner_id": test_handle,
            "primary_language": "Python",
            "topics": ["ai-agent", "mcp"],
            "stars": 42,
            "forks": 5,
            "open_issues": 3,
        }
    )
    ok("upsert_repository ejecutado")

    if repository_exists(test_repo):
        ok("repository_exists retorna True")
    else:
        fail("repository_exists retorna False")

    section("6. Enrichment queue")
    from db.queries import enqueue_enrichment, get_pending_queue, update_queue_status

    job_id = enqueue_enrichment(test_handle, "full", priority=1)
    ok(f"enqueue_enrichment retornó job_id: {job_id[:8]}...")

    queue = get_pending_queue(limit=5)
    if any(job["id"] == job_id for job in queue):
        ok("job aparece en get_pending_queue")
    else:
        fail("job no aparece en la cola")

    update_queue_status(job_id, "completed")
    queue_after = get_pending_queue(limit=5)
    if not any(job["id"] == job_id for job in queue_after):
        ok("job completado no aparece en cola pending")
    else:
        fail("job completado sigue en cola")

    section("7. emit_signal y get_active_signals")
    from db.queries import emit_signal, get_active_signals

    signal_id = emit_signal(
        entity_id=test_handle,
        category="api_cost",
        signal_type="llm_provider_migration",
        base_score=20.0,
        half_life_days=7.0,
        evidence="Switched from openai to anthropic in requirements.txt",
        source_event_id=event_id,
    )
    ok(f"emit_signal retornó signal_id: {signal_id[:8]}...")

    same_signal = emit_signal(
        entity_id=test_handle,
        category="api_cost",
        signal_type="llm_provider_migration",
        base_score=22.0,
        half_life_days=7.0,
        evidence="Updated evidence",
    )
    if same_signal == signal_id:
        ok("emit_signal hace upsert")
    else:
        warn("emit_signal creó duplicado")

    signals = get_active_signals(test_handle)
    if signals:
        ok(f"get_active_signals retorna {len(signals)} señal(es)")
    else:
        fail("get_active_signals retornó vacío")

    section("8. write_memory y JSONB nativo")
    from db.memory_queries import get_latest_memory, get_narrative, write_memory

    memory_v1 = {
        "narrative": "Developer construyendo herramientas de agentes en Python.",
        "archetype": "solo_agent_builder",
        "pain_signals": [{"category": "api_cost", "confidence": 0.85}],
        "scores": {"intent": 45.0, "maturity": 52.0},
    }

    version_1 = write_memory(test_handle, memory_v1, summary="Agente builder Python")
    ok(f"write_memory retornó versión: {version_1}")

    latest_memory = get_latest_memory(test_handle)
    if latest_memory and latest_memory.get("archetype") == "solo_agent_builder":
        ok("get_latest_memory retorna memory correcta")
    else:
        fail("get_latest_memory no retornó la memoria esperada")

    narrative = get_narrative(test_handle)
    if narrative == "Agente builder Python":
        ok("get_narrative retorna summary correcto")
    else:
        fail(f"get_narrative devolvió: {narrative}")

    version_2 = write_memory(test_handle, {**memory_v1, "scores": {"intent": 68.0, "maturity": 58.0}}, summary="Agente builder Python v2")
    latest_memory_v2 = get_latest_memory(test_handle)
    if latest_memory_v2 and latest_memory_v2["_version"] == version_2:
        ok(f"versioning correcto: v{version_1} → v{version_2}")
    else:
        fail("versioning de memory falló")

    section("9. Tracking de costos LLM")
    from db.queries import get_total_cost, log_enrichment_cost

    log_enrichment_cost(test_handle, "full", llm_calls=2, input_tokens=500, output_tokens=200)
    log_enrichment_cost(test_handle, "full", llm_calls=1, input_tokens=300, output_tokens=150)
    total_cost = get_total_cost()
    if total_cost > 0:
        ok(f"get_total_cost retorna ${total_cost:.6f}")
    else:
        fail("get_total_cost retornó 0")

    section("10. Redis operativo")
    try:
        client = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
        test_key = "foundation:test:key"
        payload = {"result": "ok"}
        if not client.ping():
            fail("Redis ping retornó False")
        client.set(test_key, json.dumps(payload), ex=60)
        cached = json.loads(client.get(test_key))
        client.delete(test_key)
        if cached == payload:
            ok("Redis set/get/delete funciona")
        else:
            fail("Redis no devolvió el payload esperado")
    except Exception as exc:
        fail(f"Redis: {exc}")

    section("11. Tipos canónicos e invariantes")
    from enrichment.types import EnrichmentResult, IntentTier, MaturityTier, PainCategory, PainSignal, StackSnapshot

    assert MaturityTier.from_score(0) == MaturityTier.PROTOTYPE
    assert MaturityTier.from_score(35) == MaturityTier.EARLY
    assert MaturityTier.from_score(55) == MaturityTier.INTERMEDIATE
    assert MaturityTier.from_score(72) == MaturityTier.PRODUCTION
    assert MaturityTier.from_score(85) == MaturityTier.SCALE_READY
    ok("MaturityTier.from_score correcto")

    assert IntentTier.from_score(75) == IntentTier.HOT
    assert IntentTier.from_score(50) == IntentTier.WARM
    assert IntentTier.from_score(30) == IntentTier.COLD
    assert IntentTier.from_score(5) == IntentTier.MONITOR
    ok("IntentTier.from_score correcto")

    try:
        PainSignal(PainCategory.SCALING, "desc", "", "readme", 0.8)
        fail("PainSignal aceptó evidence vacío")
    except ValueError:
        ok("PainSignal.evidence obligatorio")

    stack = StackSnapshot()
    stack.runtime_deps["payments"] = ["stripe"]
    stack.runtime_deps["ai_llm"] = ["openai", "anthropic"]
    assert stack.has_payments() is True
    assert stack.has_ai() is True
    assert stack.has_queues() is False
    ok("StackSnapshot helpers funcionan")

    enrichment_result = EnrichmentResult(developer_id=test_handle)
    assert enrichment_result.ready_for_outreach is False
    ok("EnrichmentResult.ready_for_outreach correcto")

    section("12. Config.toml")
    try:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        with open("config.toml", "rb") as config_file:
            config = tomllib.load(config_file)

        assert "ecosystem" in config
        assert "scoring" in config
        assert "llm" in config
        assert "collectors" in config
        ok(f"config.toml válido — ecosystem={config['ecosystem']['name']}")
    except Exception as exc:
        fail(f"config.toml: {exc}")

    print("\n✅ Foundation completo — PostgreSQL + Redis listos")


if __name__ == "__main__":
    run()
