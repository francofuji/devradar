CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY,
    event_type TEXT NOT NULL,
    event_category TEXT NOT NULL CHECK(event_category IN ('discovery', 'activity', 'enrichment', 'intent', 'system')),
    occurred_at TIMESTAMPTZ NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT,
    entity_id TEXT,
    entity_type TEXT CHECK(entity_type IN ('developer', 'repository', 'organization', 'technology')),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    enrichment_status TEXT NOT NULL DEFAULT 'pending' CHECK(enrichment_status IN ('pending', 'queued', 'completed', 'skipped')),
    processing_ver TEXT NOT NULL DEFAULT '0.1.0'
);

CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_enrichment ON events(enrichment_status, occurred_at ASC);
CREATE INDEX IF NOT EXISTS idx_events_payload ON events USING GIN (payload);

CREATE TABLE IF NOT EXISTS developers (
    id TEXT PRIMARY KEY,
    name TEXT,
    email TEXT,
    github_url TEXT,
    twitter TEXT,
    personal_site TEXT,
    linkedin_manual JSONB,
    status TEXT NOT NULL DEFAULT 'DISCOVERED' CHECK(status IN ('DISCOVERED', 'PROFILED', 'MONITORED', 'WARM', 'QUALIFIED', 'OUTREACHED', 'ENGAGED', 'CLOSED')),
    intent_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    maturity_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    trajectory_direction TEXT,
    trajectory_7d DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    trajectory_30d DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    archetype TEXT,
    arch_confidence DOUBLE PRECISION,
    outreach_status TEXT NOT NULL DEFAULT 'none' CHECK(outreach_status IN ('none', 'drafted', 'sent', 'replied', 'converted', 'disqualified')),
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active TIMESTAMPTZ,
    last_enriched TIMESTAMPTZ,
    enrichment_ver INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_developers_status ON developers(status, intent_score DESC);
CREATE INDEX IF NOT EXISTS idx_developers_score ON developers(intent_score DESC, trajectory_7d DESC);

CREATE TABLE IF NOT EXISTS repositories (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    primary_language TEXT,
    topics JSONB NOT NULL DEFAULT '[]'::jsonb,
    description TEXT,
    homepage TEXT,
    stars INTEGER NOT NULL DEFAULT 0,
    forks INTEGER NOT NULL DEFAULT 0,
    open_issues INTEGER NOT NULL DEFAULT 0,
    last_push TIMESTAMPTZ,
    maturity_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    stack_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    has_ci BOOLEAN NOT NULL DEFAULT FALSE,
    has_docker BOOLEAN NOT NULL DEFAULT FALSE,
    has_tests BOOLEAN NOT NULL DEFAULT FALSE,
    has_payments BOOLEAN NOT NULL DEFAULT FALSE,
    has_auth BOOLEAN NOT NULL DEFAULT FALSE,
    has_monitoring BOOLEAN NOT NULL DEFAULT FALSE,
    dependency_hash TEXT,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    last_enriched TIMESTAMPTZ,
    last_monitored TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_repos_owner ON repositories(owner_id);
CREATE INDEX IF NOT EXISTS idx_repos_monitored ON repositories(last_monitored ASC);
CREATE INDEX IF NOT EXISTS idx_repos_primary ON repositories(owner_id, is_primary DESC);
CREATE INDEX IF NOT EXISTS idx_stack_gin ON repositories USING GIN (stack_snapshot);

CREATE TABLE IF NOT EXISTS entity_memory (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'developer',
    version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'archived')),
    memory JSONB NOT NULL,
    summary TEXT,
    diff JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_version ON entity_memory(entity_id, version);
CREATE INDEX IF NOT EXISTS idx_memory_latest ON entity_memory(entity_id, version DESC);
CREATE INDEX IF NOT EXISTS idx_memory_gin ON entity_memory USING GIN (memory);

CREATE TABLE IF NOT EXISTS signals (
    id UUID PRIMARY KEY,
    entity_id TEXT NOT NULL,
    category TEXT NOT NULL CHECK(category IN ('api_cost', 'scaling', 'auth', 'observability', 'reliability', 'budget', 'evaluation', 'activity')),
    signal_type TEXT NOT NULL,
    base_score DOUBLE PRECISION NOT NULL,
    current_score DOUBLE PRECISION NOT NULL,
    half_life_days DOUBLE PRECISION NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'DECAYING', 'EXPIRED')),
    evidence TEXT,
    source_event_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_signals_entity ON signals(entity_id, status);
CREATE INDEX IF NOT EXISTS idx_signals_active ON signals(status, expires_at ASC);

CREATE TABLE IF NOT EXISTS enrichment_queue (
    id UUID PRIMARY KEY,
    entity_id TEXT NOT NULL,
    enrichment_type TEXT NOT NULL CHECK(enrichment_type IN ('full', 'partial', 'pain_check', 'readme_only')),
    priority INTEGER NOT NULL DEFAULT 2 CHECK(priority IN (1, 2, 3)),
    source_event_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'running', 'completed', 'failed')),
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_queue_pending ON enrichment_queue(status, priority ASC, created_at ASC);

CREATE TABLE IF NOT EXISTS score_history (
    entity_id TEXT NOT NULL,
    intent_score DOUBLE PRECISION NOT NULL,
    maturity_score DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (entity_id, recorded_at)
);

CREATE INDEX IF NOT EXISTS idx_score_history_entity ON score_history(entity_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS enrichment_costs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_id TEXT NOT NULL,
    enrichment_type TEXT,
    llm_calls INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    provider TEXT,
    prompt_preview TEXT,
    response_preview TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fine_tuning_examples (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_type TEXT NOT NULL CHECK(task_type IN ('narrative', 'draft', 'extraction')),
    system_prompt TEXT NOT NULL,
    user_input TEXT NOT NULL,
    model_output TEXT NOT NULL,
    approved_output TEXT NOT NULL,
    was_edited BOOLEAN NOT NULL DEFAULT FALSE,
    edit_distance DOUBLE PRECISION,
    entity_id TEXT,
    outcome TEXT,
    provider TEXT,
    model_used TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMPTZ,
    quality_score DOUBLE PRECISION,
    variant_label TEXT,
    source TEXT DEFAULT 'ollama'
);

CREATE INDEX IF NOT EXISTS idx_ft_task ON fine_tuning_examples(task_type, quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_ft_outcome ON fine_tuning_examples(outcome, task_type);

CREATE TABLE IF NOT EXISTS model_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_type TEXT NOT NULL,
    model_name TEXT NOT NULL,
    base_model TEXT NOT NULL,
    training_examples INTEGER,
    eval_rouge_l DOUBLE PRECISION,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    deployed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes TEXT
);
