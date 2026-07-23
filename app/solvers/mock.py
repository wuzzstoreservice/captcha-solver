from __future__ import annotations

import asyncio
import time
from typing import Any, Dict

from app.solvers.base import SolveResult


class MockTurnstileSolver:
    """Deterministic solver for unit tests and CAPTCHA_SOLVER_MOCK_SOLVER=true."""

    type = "turnstile"

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def solve(self, task: Dict[str, Any]) -> SolveResult:
        await asyncio.sleep(0.05)
        task_id = task.get("id") or "unknown"
        payload = task.get("payload") or {}
        return SolveResult(
            token=f"mock-token-{str(task_id)[:8]}",
            elapsed_time=0.05,
            raw={
                "url": payload.get("url"),
                "sitekey": payload.get("sitekey"),
                "mock": True,
                "ts": time.time(),
            },
        )
