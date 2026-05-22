.PHONY: up down logs logs-api logs-worker migrate test collect enrich digest health shell-api shell-db shell-redis pull-model cache-stats github-rate backup restore api-run

up:
	docker compose up -d

api-run:
	python api/run.py

down:
	docker compose down

logs:
	docker compose logs -f

logs-api:
	docker compose logs -f api

logs-worker:
	docker compose logs -f worker

migrate:
	docker compose exec api python db/migrate.py

test:
	docker compose exec api python scripts/test_foundation.py

collect:
	docker compose exec worker python collectors/run_all.py --collector all

enrich:
	docker compose exec worker python enrichment/dispatcher.py --once

digest:
	docker compose exec api python intelligence/generate_digest.py

health:
	docker compose exec api python scripts/health_check.py

shell-api:
	docker compose exec api bash

shell-db:
	docker compose exec postgres psql -U $${POSTGRES_USER:-devint} -d $${POSTGRES_DB:-dev_intelligence}

shell-redis:
	docker compose exec redis redis-cli

pull-model:
	docker compose exec ollama ollama pull llama3.2:3b

cache-stats:
	docker compose exec api python -c "import os,redis; r=redis.from_url(os.getenv('REDIS_URL')); keys=r.keys('llm:*'); info=r.info('memory'); print(f'LLM cache keys: {len(keys)}'); print(f'Memory used: {info[\"used_memory_human\"]}')"

github-rate:
	docker compose exec api python -c "import os,redis; r=redis.from_url(os.getenv('REDIS_URL')); rem=r.get('github:rate_limit:remaining'); print(f'GitHub API remaining: {rem.decode() if rem else \"unknown\"}')"

backup:
	@mkdir -p backups
	docker compose exec -T postgres pg_dump -U $${POSTGRES_USER:-devint} -d $${POSTGRES_DB:-dev_intelligence} | gzip > backups/backup_$$(date +%Y%m%d_%H%M%S).sql.gz
	@echo "✅ Backup guardado en backups/"

restore:
	@test -n "$(FILE)" || (echo "Usar: make restore FILE=backups/backup_xxx.sql.gz" && exit 1)
	gunzip -c $(FILE) | docker compose exec -T postgres psql -U $${POSTGRES_USER:-devint} -d $${POSTGRES_DB:-dev_intelligence}
	@echo "✅ Restore completado desde $(FILE)"
