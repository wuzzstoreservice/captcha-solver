from __future__ import annotations

from fastapi import APIRouter, Request

from app import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request):
    pool = getattr(request.app.state, "pool", None)
    store = getattr(request.app.state, "store", None)
    return {
        "ok": True,
        "service": "captcha-solver",
        "version": __version__,
        "queue_pending": pool.pending if pool else 0,
        "inflight": pool.inflight if pool else 0,
        "tasks_cached": store.size if store else 0,
        "mock_solver": bool(getattr(request.app.state, "mock_solver", False)),
    }


@router.get("/metrics")
async def metrics(request: Request):
    pool = getattr(request.app.state, "pool", None)
    store = getattr(request.app.state, "store", None)
    body = {
        "service": "captcha-solver",
        "version": __version__,
        "mock_solver": bool(getattr(request.app.state, "mock_solver", False)),
        "tasks_cached": store.size if store else 0,
    }
    if pool is not None:
        body.update(pool.stats())
    else:
        body.update(
            {
                "queue_pending": 0,
                "inflight": 0,
                "solves_total": 0,
                "solves_ok": 0,
                "solves_fail": 0,
            }
        )
    return body
