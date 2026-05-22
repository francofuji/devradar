from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from apscheduler.schedulers.blocking import BlockingScheduler

from app_logging import configure_logging
from worker.jobs import JOB_DEFINITIONS, JOB_HANDLERS

log = configure_logging("worker")

scheduler = BlockingScheduler(timezone="UTC")


def _register_jobs() -> None:
    for definition in JOB_DEFINITIONS:
        job_id = definition["id"]
        trigger_type = definition["type"]
        handler = JOB_HANDLERS[job_id]
        trigger_args = {key: value for key, value in definition.items() if key not in {"id", "type"}}
        scheduler.add_job(handler, trigger=trigger_type, id=job_id, replace_existing=True, **trigger_args)
        log.info("worker.job_registered", job_id=job_id, trigger=trigger_type, schedule=trigger_args)


if __name__ == "__main__":
    log.info("worker.scheduler_starting", app_env=os.getenv("APP_ENV", "development"))
    _register_jobs()
    scheduler.start()
