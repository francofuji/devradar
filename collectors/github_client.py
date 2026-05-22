"""
Wrapper de PyGitHub para el sistema de inteligencia.
Centraliza autenticación, rate limit logging, retry en 403 y rate limiting
proactivo via Redis (E10).
"""
from __future__ import annotations

import os
import time
from typing import Iterator, Optional

import structlog
from dotenv import load_dotenv
from github import Github, GithubException, Auth
from github.Repository import Repository

try:
    import redis as redis_lib
except ImportError:
    redis_lib = None  # type: ignore

load_dotenv()

log = structlog.get_logger().bind(module="collectors.github_client")

_RATE_LIMIT_KEY_REMAINING = "github:rate_limit:remaining"
_RATE_LIMIT_KEY_RESET = "github:rate_limit:reset"
_RATE_LIMIT_LOW_THRESHOLD = 200  # pausa cuando quedan < 200 requests (era 50, muy bajo)


class GitHubClient:
    def __init__(self, token: str | None = None):
        _token = token or os.getenv("GITHUB_TOKEN")
        if not _token:
            raise ValueError("GITHUB_TOKEN no encontrado. Configurar en .env o pasar como argumento.")
        auth = Auth.Token(_token)
        self._gh = Github(auth=auth, per_page=100)

        # Redis para rate limiting proactivo — opcional
        self._redis = None
        if redis_lib is not None:
            try:
                r = redis_lib.from_url(
                    os.getenv("REDIS_URL", "redis://redis:6379/0"),
                    decode_responses=True,
                    socket_connect_timeout=2,
                )
                r.ping()
                self._redis = r
                log.info("github_client.redis_ready")
            except Exception as exc:
                log.warning("github_client.redis_unavailable", error=str(exc))

    # ------------------------------------------------------------------
    # Rate limit helpers
    # ------------------------------------------------------------------

    def _log_rate_limit(self, context: str = "") -> int:
        remaining, limit = self._gh.rate_limiting
        log.info("github_client.rate_limit", remaining=remaining, limit=limit, context=context)
        self._update_rate_limit_cache(remaining)
        return remaining

    def get_rate_limit_remaining(self) -> int:
        remaining, _ = self._gh.rate_limiting
        return remaining

    def _update_rate_limit_cache(self, remaining: int) -> None:
        if self._redis is None:
            return
        try:
            # reset_time viene de PyGitHub — es el epoch real del reset de GitHub
            reset_time = self._gh.rate_limiting_resettime  # epoch UTC real
            ttl = max(60, reset_time - int(time.time()) + 10)
            self._redis.set(_RATE_LIMIT_KEY_REMAINING, str(remaining), ex=ttl)
            self._redis.set(_RATE_LIMIT_KEY_RESET, str(reset_time), ex=ttl)
        except Exception as exc:
            log.warning("github_client.redis_write_error", error=str(exc))

    def _check_rate_limit_proactive(self) -> None:
        if self._redis is None:
            return
        try:
            remaining_raw = self._redis.get(_RATE_LIMIT_KEY_REMAINING)
            if remaining_raw is None:
                return
            remaining = int(remaining_raw)
            if remaining < _RATE_LIMIT_LOW_THRESHOLD:
                reset_raw = self._redis.get(_RATE_LIMIT_KEY_RESET)
                wait = max(0, int(reset_raw or 0) - int(time.time())) + 5 if reset_raw else 60
                log.warning(
                    "github_client.rate_limit_proactive_wait",
                    remaining=remaining,
                    wait_seconds=wait,
                )
                time.sleep(wait)
        except Exception as exc:
            log.warning("github_client.rate_limit_check_error", error=str(exc))

    def search_repos(
        self,
        topics: list[str],
        languages: list[str],
        min_stars: int,
        max_stars: int,
        created_after: str,
        max_per_query: int = 100,
    ) -> Iterator[Repository]:
        """
        Busca repos por cada combinación topic × language.
        Deduplica por full_name. Maneja rate limit con retry 1x.
        """
        seen: set[str] = set()

        for topic in topics:
            for language in languages:
                query = (
                    f"topic:{topic} language:{language} "
                    f"stars:{min_stars}..{max_stars} "
                    f"created:>{created_after}"
                )
                log.info("github_client.search", query=query)

                results = None
                for attempt in range(2):
                    self._check_rate_limit_proactive()
                    try:
                        results = self._gh.search_repositories(
                            query, sort="updated", order="desc"
                        )
                        count = 0
                        for repo in results:
                            if count >= max_per_query:
                                break
                            if repo.full_name not in seen:
                                seen.add(repo.full_name)
                                yield repo
                                count += 1
                        self._log_rate_limit(f"topic:{topic} lang:{language}")
                        break  # success

                    except GithubException as e:
                        if e.status == 403 and attempt == 0:
                            log.warning("github_client.rate_limit_403", topic=topic, lang=language)
                            time.sleep(60)
                        elif e.status == 403 and attempt == 1:
                            log.error("github_client.rate_limit_persists", topic=topic, lang=language)
                            break
                        else:
                            log.error("github_client.search_error", status=e.status, topic=topic, lang=language)
                            break

                    except Exception as e:
                        log.error("github_client.search_unexpected", error=str(e), topic=topic, lang=language)
                        break

    def get_repo(self, full_name: str) -> Optional[Repository]:
        """
        Fetch de un repo por full_name. Retorna None si no existe.
        Retry 1x en 403.
        """
        for attempt in range(2):
            self._check_rate_limit_proactive()
            try:
                repo = self._gh.get_repo(full_name)
                self._log_rate_limit(f"get_repo {full_name}")
                return repo

            except GithubException as e:
                if e.status == 404:
                    log.warning("github_client.repo_not_found", repo=full_name)
                    return None
                elif e.status == 403 and attempt == 0:
                    log.warning("github_client.rate_limit_403_get_repo", repo=full_name)
                    time.sleep(60)
                elif e.status == 403 and attempt == 1:
                    log.error("github_client.rate_limit_persists_get_repo", repo=full_name)
                    raise
                else:
                    log.error("github_client.get_repo_error", status=e.status, repo=full_name)
                    raise

            except Exception as e:
                log.error("github_client.get_repo_unexpected", error=str(e), repo=full_name)
                raise

        return None
