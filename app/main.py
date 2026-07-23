from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict

from fastapi import FastAPI

from app import __version__
from app.api import health, legacy, v1
from app.config import Settings, get_settings, load_yaml_overrides
from app.queue.worker_pool import WorkerPool
from app.solvers.base import BaseSolver
from app.solvers.mock import MockTurnstileSolver
from app.solvers.turnstile import TurnstileSolver
from app.store.memory_store import ResultStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("captcha-solver")


def build_solvers(settings: Settings) -> Dict[str, BaseSolver]:
    if settings.mock_solver:
        logger.warning("Using MOCK turnstile solver")
        return {"turnstile": MockTurnstileSolver()}
    return {
        "turnstile": TurnstileSolver(
            thread=settings.thread,
            headless=settings.headless,
            debug=settings.debug,
            proxy_support=settings.proxy_support,
            proxies_file=settings.proxies_path,
            solve_timeout=settings.solve_timeout_seconds,
        )
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    load_yaml_overrides()
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = ResultStore()
        await store.init()
        solvers = build_solvers(settings)
        pool = WorkerPool(
            store,
            solvers,
            concurrency=settings.thread,
            max_queue=settings.max_queue,
            solve_timeout=settings.solve_timeout_seconds,
        )
        app.state.settings = settings
        app.state.store = store
        app.state.pool = pool
        app.state.mock_solver = settings.mock_solver
        await pool.start()
        logger.info(
            "captcha-solver v%s listening config host=%s port=%s thread=%s mock=%s",
            __version__,
            settings.host,
            settings.port,
            settings.thread,
            settings.mock_solver,
        )
        try:
            yield
        finally:
            await pool.stop()
            logger.info("captcha-solver stopped")

    app = FastAPI(
        title="Captcha Solver",
        version=__version__,
        description="Self-hosted captcha solver API. MVP: Cloudflare Turnstile.",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(legacy.router)
    app.include_router(v1.router)
    return app


app = create_app()
