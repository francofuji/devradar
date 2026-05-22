from __future__ import annotations

import asyncio
import json
import select
from typing import AsyncGenerator

import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from db import get_pool, release_connection

log = structlog.get_logger().bind(module="api.sse")
router = APIRouter(tags=["events"])


def _blocking_wait(conn, timeout: float) -> bool:
    """Run in executor — returns True if data is ready, False on timeout."""
    ready, _, _ = select.select([conn], [], [], timeout)
    return bool(ready)


async def _event_stream() -> AsyncGenerator[str, None]:
    loop = asyncio.get_event_loop()
    raw_connection = get_pool().getconn()
    raw_connection.set_isolation_level(0)
    cursor = raw_connection.cursor()
    cursor.execute("LISTEN dev_intel_events;")
    log.info("sse.listener_started", channel="dev_intel_events")

    try:
        while True:
            # Run the blocking select() in the thread pool so the event loop stays free
            ready = await loop.run_in_executor(None, _blocking_wait, raw_connection, 15.0)
            if not ready:
                yield ": keepalive\n\n"
                continue

            raw_connection.poll()
            while raw_connection.notifies:
                notify = raw_connection.notifies.pop(0)
                try:
                    body = json.loads(notify.payload)
                except json.JSONDecodeError:
                    body = {"type": "raw", "payload": notify.payload}
                yield f"data: {json.dumps(body, ensure_ascii=True)}\n\n"
    finally:
        cursor.close()
        release_connection(raw_connection)
        log.info("sse.listener_stopped", channel="dev_intel_events")


@router.get("/api/events")
async def stream_events() -> StreamingResponse:
    return StreamingResponse(_event_stream(), media_type="text/event-stream")

