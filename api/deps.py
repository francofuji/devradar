from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Generator

import redis as redis_lib
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from db import get_connection, get_pool
from enrichment.llm_client import LLMClient

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

log = structlog.get_logger().bind(module="api.deps")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.toml"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


def get_db() -> Generator:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@lru_cache(maxsize=1)
def _redis_client():
    return redis_lib.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
        socket_connect_timeout=2,
    )


def get_redis():
    return _redis_client()


def _load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("rb") as fh:
        return tomllib.load(fh)


def get_config() -> dict[str, Any]:
    return _load_config()


@lru_cache(maxsize=1)
def _llm_client() -> LLMClient:
    return LLMClient(config=_load_config())


def get_llm_client() -> LLMClient:
    return _llm_client()


def clear_dependency_caches() -> None:
    _redis_client.cache_clear()
    _llm_client.cache_clear()


def ensure_runtime_ready() -> dict[str, bool]:
    pool_ready = False
    redis_ready = False

    try:
        get_pool()
        pool_ready = True
    except Exception as exc:  # pragma: no cover - exercised in integration
        log.error("deps.pool_init_failed", error=str(exc))

    try:
        get_redis().ping()
        redis_ready = True
    except Exception as exc:  # pragma: no cover - exercised in integration
        log.error("deps.redis_init_failed", error=str(exc))

    return {"db_pool": pool_ready, "redis": redis_ready}


def verify_token(token: str | None = Depends(oauth2_scheme)) -> None:
    expected = os.getenv("API_TOKEN", "").strip()
    if not expected:
        return
    if token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

