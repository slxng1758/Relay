"""
FastAPI application factory and entry point.

Run with `uvicorn app.main:app` (see `infra/docker/Dockerfile`) or
`opsgraph serve` (see `app/cli.py`).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.middleware.request_context import RequestContextMiddleware
from app.api.routes import agents, graph, health, ingestion
from app.core.config import settings
from app.core.database import close_db
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_queue, close_redis
from app.core.security import get_current_principal

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info("app.startup", app_env=settings.app_env)
    yield
    await close_db()
    await close_redis()
    await close_queue()
    logger.info("app.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="opsgraph",
        description="Multi-agent AI system for operational graph modeling across teams",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, tags=["health"])
    app.include_router(
        agents.router,
        prefix="/api/agents",
        tags=["agents"],
        dependencies=[Depends(get_current_principal)],
    )
    app.include_router(ingestion.router, prefix="/api/ingestion", tags=["ingestion"])
    app.include_router(graph.router, prefix="/api/graph", tags=["graph"])

    Instrumentator().instrument(app).expose(app, include_in_schema=False)

    return app


app = create_app()
