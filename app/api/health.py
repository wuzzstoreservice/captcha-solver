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
        "tasks_cached": store.size if store else 0,
        "mock_solver": bool(getattr(request.app.state, "mock_solver", False)),
    }
