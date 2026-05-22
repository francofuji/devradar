from __future__ import annotations

import logging
import os
import sys

import structlog


def configure_logging(service: str):
    app_env = os.getenv("APP_ENV", "development").lower()
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if app_env == "production"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout, force=True)
    structlog.configure(
        processors=[*processors, renderer],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
    return structlog.get_logger().bind(service=service)
