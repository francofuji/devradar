# Dev Intelligence Platform

Continuous intelligence system for developer ecosystems. Monitors GitHub and Hacker News to detect developers building in the AI agents, MCP infrastructure, and browser automation space. Builds longitudinal technical profiles with evolving memory, detects intent transitions, and generates contextual outreach backed by explicit evidence.

**Not a CRM. Not a monitoring tool. Not a SaaS.**
Operated by a single person, running on your own infrastructure.

---

## How it works

Every action in the system produces an **immutable, append-only event**. A developer's memory is a projection of their events — never a directly editable record. This guarantees full traceability: you can always explain why the system says what it says.

```
Collectors (every N hours)
  → emit_event() → events table (enrichment_status='pending')
  → trigger.py (every 15min) → enrichment_queue
  → dispatcher.py → full_enrichment or partial_enrichment
  → dependency_parser + github_profile + readme_extractor + pain_detector
  → memory_writer → entity_memory (new version)
  → score_entities (nightly) → signal decay + intent_score + trajectory
  → detect_transitions → state machine → transition events
  → generate_digest (07:00) → output/daily/YYYY-MM-DD.md
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Database | PostgreSQL 16 + JSONB via `psycopg2` + `ThreadedConnectionPool` |
| Cache | Redis 7 |
| API | FastAPI |
| Frontend | React + Vite |
| Scheduler | APScheduler (inside worker container) |
| LLM | Anthropic SDK — Haiku for extraction, Sonnet for narrative and drafts |
| Local LLM | Ollama |
| CLI | Click |
| Orchestration | Docker Compose (7 services) |

---

## Services

| Service | Role |
|---|---|
| `postgres` | Primary database (JSONB, real indexes) |
| `redis` | Cache and operational state |
| `ollama` | Local LLM provider |
| `api` | FastAPI + operational endpoints |
| `web` | React/Vite frontend |
| `worker` | Collectors, enrichment, APScheduler jobs |
| `adminer` | PostgreSQL visual inspector (port 8080) |

---

## Setup

### Prerequisites

- Docker + Docker Compose
- GitHub personal access token (scopes: `public_repo`, `read:user`)
- Anthropic API key

### Initial setup

```bash
cp .env.example .env
# Edit .env — set GITHUB_TOKEN and ANTHROPIC_API_KEY
make up
make migrate
make test
```

### Environment variables

```
POSTGRES_DB          dev_intelligence
POSTGRES_USER        devint
POSTGRES_PASSWORD    changeme_in_production
DATABASE_URL         postgresql://devint:...@postgres:5432/dev_intelligence
REDIS_URL            redis://redis:6379/0
GITHUB_TOKEN         ghp_xxxx
ANTHROPIC_API_KEY    sk-ant-xxxx
OLLAMA_HOST          http://ollama:11434
APP_ENV              development
API_PORT             8000
WEB_PORT             5173
API_TOKEN            generate with: openssl rand -hex 32
```

---

## Daily operation

```bash
make collect      # Run all collectors (GitHub + HN)
make enrich       # Process enrichment queue (one pass)
make digest       # Generate today's daily digest
make health       # Run health checks
make cache-stats  # Show Redis LLM cache stats
make backup       # Dump PostgreSQL to backups/
```

### Other useful commands

```bash
make logs              # Stream all service logs
make logs-api          # Stream API logs only
make logs-worker       # Stream worker logs only
make shell-api         # bash into api container
make shell-db          # psql into postgres
make shell-redis       # redis-cli
make github-rate       # Check remaining GitHub API rate limit
make restore FILE=...  # Restore from a backup file
```

### Direct container commands

```bash
docker compose exec api python db/migrate.py
docker compose exec worker python collectors/run_all.py --collector all
docker compose exec worker python enrichment/dispatcher.py --once
docker compose exec api python intelligence/generate_digest.py
docker compose exec api python scripts/test_foundation.py
```

---

## CLI

The operational CLI runs inside the `api` container:

```bash
docker compose exec api python cli/ops.py [COMMAND]
```

| Command | Description |
|---|---|
| `show --entity <handle>` | Display a developer's summary, pain signals, narrative, and hooks |
| `note --entity <handle> --text <text>` | Add an operator note and version memory |
| `linkedin --entity <handle>` | Capture LinkedIn context interactively |
| `disqualify --entity <handle> --reason <reason>` | Mark entity as disqualified |
| `outreach --entity <handle> --channel <email\|twitter\|linkedin>` | Record that outreach was sent |
| `reply --entity <handle> --outcome <positive\|negative\|neutral> --notes <text>` | Record a reply |
| `enrich --entity <handle> --mode <full\|partial>` | Trigger immediate enrichment, bypassing the queue |
| `training-stats` | Show fine-tuning example counts and quality metrics |

---

## Developer lifecycle

```
DISCOVERED → PROFILED → MONITORED → WARM → QUALIFIED → OUTREACHED → ENGAGED → CLOSED
```

---

## Scoring

### Intent score — signal points

**Layer 1 — Budget signals**
- Stripe in dependencies: +25
- OpenAI/Anthropic API key in `.env.example`: +20
- Paid SaaS in `.env.example`: +15
- External pricing page: +15
- Funding < 6 months ago: +20

**Layer 2 — Active evaluation**
- Issue "looking for alternatives": +20
- README "Alternatives" section: +15
- 3+ similar repos starred this month: +15
- Related job posting: +18
- Tool comparison in issue/PR: +20

**Layer 3 — Scaling pressure**
- Queue library recently added: +12
- Redis/cache recently added: +12
- Stars growing >50% in 30 days: +15
- Issue "how do I scale": +18
- Multiple replicas in docker-compose: +10

**Temporal multipliers**

| Age | Multiplier |
|---|---|
| < 48h | ×2.0 |
| 2–7 days | ×1.5 |
| 7–21 days | ×1.0 |
| > 21 days | ×0.5 |

### Intent tiers

| Tier | Score |
|---|---|
| `hot` | ≥ 60 |
| `warm` | 40–59 |
| `cold` | 20–39 |
| `monitor` | < 20 |

### Signal decay (half-life in days)

| Signal category | Half-life |
|---|---|
| product_launch | 2 |
| tool_comparison | 3 |
| stars_spike | 5 |
| dependency_added (hot stack) | 7 |
| commit_velocity | 10 |
| hiring_signal | 14 |
| article_published | 14 |
| funding_event | 21 |
| issue_pain | 30 |
| stack_inference | never expires |

---

## Developer archetypes

| Archetype | Description |
|---|---|
| `solo_agent_builder` | Individual building autonomous AI agents |
| `automation_builder` | Focused on workflow and process automation |
| `mcp_platform_builder` | Building MCP infrastructure or tooling |
| `technical_founder` | Founder with hands-on technical involvement |
| `ai_agency_builder` | Building AI-native agency or service business |
| `growth_engineer` | Engineering focused on distribution and growth |
| `unknown` | Insufficient signal to classify |

---

## Intelligence outputs

- **Daily digest** — `output/daily/YYYY-MM-DD.md` — new entities, state transitions, intent alerts, stack changes, LLM cost
- **Alerts** — `output/alerts/` — individual high-intent entity alerts
- **Outreach drafts** — `output/drafts/` — LLM-generated contextual messages per entity

---

## Project structure

```
api/               FastAPI application and routers
cli/ops.py         Operational CLI (show, note, enrich, outreach, reply, …)
collectors/        GitHub trending + HN digest collectors
db/                Schema, migrations, event emission, queries, memory queries
enrichment/        7-step enrichment pipeline + all canonical types
fine_tuning/       Dataset capture, preparation, training, and evaluation
intelligence/      Scoring, transitions, digest, alerts, draft generation
scripts/           Validation and health check scripts
taxonomy/          dependencies.json — package → category mapping (source of truth)
worker/            APScheduler jobs and scheduler entry point
output/            Generated digests, alerts, and drafts
```

---

## Invariants

1. **`events` is append-only.** Never UPDATE or DELETE rows. New information = new event.
2. **Evidence is mandatory.** Every `PainSignal` and `ArchetypeResult` requires a non-empty `evidence` field. No evidence → no object → not used in outreach.
3. **Heuristic before LLM.** If the taxonomy or a deterministic rule resolves a classification with ≥ 80% accuracy, skip the LLM call.
4. **Confidence gate.** Any inference with `confidence < 0.6` is stored in DB but not surfaced to the operator and not used in message generation.
5. **Rate limit logging.** Every GitHub API call logs the remaining rate limit after execution.
6. **Cost tracking.** Every `llm_client.call_llm()` call records token usage in the `enrichment_costs` table.
7. **No raw DB access.** All database interaction goes through `psycopg2` via `db.get_connection()`. Never use sqlite3.
8. **No host-side Python.** All scripts run via `docker compose exec {service} python {script}`. Never run directly on the host.
