from __future__ import annotations

from contextlib import asynccontextmanager
import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app_logging import configure_logging
from api.deps import ensure_runtime_ready, verify_token
from api.routers import entities as entities_router
from api.routers import intelligence as intelligence_router
from api.routers import llm as llm_router
from api.routers import outreach as outreach_router
from api.routers import system as system_router
from api.routers import training as training_router
from api.routers import logs as logs_router
from api import sse as sse_router

log = configure_logging("api")

APP_VERSION = "2.0.0"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    readiness = ensure_runtime_ready()
    log.info("api.starting", app_env=os.getenv("APP_ENV", "development"), readiness=readiness)
    yield
    log.info("api.stopping")


app = FastAPI(title="Dev Intelligence API", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(system_router.router)
app.include_router(logs_router.router, dependencies=[Depends(verify_token)])
app.include_router(sse_router.router, dependencies=[Depends(verify_token)])
app.include_router(llm_router.router, dependencies=[Depends(verify_token)])
app.include_router(training_router.router, dependencies=[Depends(verify_token)])
app.include_router(entities_router.router, dependencies=[Depends(verify_token)])
app.include_router(outreach_router.router, dependencies=[Depends(verify_token)])
app.include_router(intelligence_router.router, dependencies=[Depends(verify_token)])


@app.get("/")
def root() -> dict:
    return {"status": "ok", "version": APP_VERSION}


@app.get("/health")
def health() -> dict:
    return system_router.api_health()
