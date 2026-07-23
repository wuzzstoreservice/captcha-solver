from __future__ import annotations

import asyncio
import time
from typing import Any, Dict

from app.solvers.base import SolveResult


class MockTurnstileSolver:
    """Deterministic solver for unit tests and CAPTCHA_SOLVER_MOCK_SOLVER=true."""

    type = "turnstile"

    def __init__(self) -> None:
        self.solve_count = 0
        self.recycle_count = 0

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def stats(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "mock": True,
            "solve_count": self.solve_count,
            "recycle_count": self.recycle_count,
            "pool_size": 0,
        }

    async def solve(self, task: Dict[str, Any]) -> SolveResult:
        await asyncio.sleep(0.05)
        self.solve_count += 1
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
