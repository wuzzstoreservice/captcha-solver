from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from app.solvers.base import BaseSolver
from app.store.memory_store import ResultStore

logger = logging.getLogger("captcha-solver.worker")


class WorkerPool:
    def __init__(
        self,
        store: ResultStore,
        solvers: Dict[str, BaseSolver],
        *,
        concurrency: int = 1,
        max_queue: int = 20,
        solve_timeout: int = 120,
    ) -> None:
        self.store = store
        self.solvers = solvers
        self.sem = asyncio.Semaphore(max(1, concurrency))
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=max(1, max_queue))
        self.solve_timeout = solve_timeout
        self._runner: Optional[asyncio.Task] = None
        self._cleanup: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()

    @property
    def pending(self) -> int:
        return self.queue.qsize()

    async def start(self) -> None:
        for solver in self.solvers.values():
            await solver.start()
        self._stopped.clear()
        self._runner = asyncio.create_task(self._run_forever(), name="worker-pool")
        self._cleanup = asyncio.create_task(self._cleanup_loop(), name="cleanup-loop")
        logger.info(
            "WorkerPool started solvers=%s concurrency=%s",
            list(self.solvers),
            self.sem._value,
        )

    async def stop(self) -> None:
        self._stopped.set()
        if self._runner:
            self._runner.cancel()
            try:
                await self._runner
            except asyncio.CancelledError:
                pass
        if self._cleanup:
            self._cleanup.cancel()
            try:
                await self._cleanup
            except asyncio.CancelledError:
                pass
        for solver in self.solvers.values():
            try:
                await solver.stop()
            except Exception as exc:
                logger.warning("solver stop error: %s", exc)

    async def submit(self, task_id: str, captcha_type: str, payload: Dict[str, Any]) -> None:
        if self.queue.full():
            raise RuntimeError("queue full")
        await self.store.create_task(task_id, captcha_type, payload)
        await self.queue.put(task_id)

    async def _run_forever(self) -> None:
        while not self._stopped.is_set():
            try:
                task_id = await asyncio.wait_for(self.queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            asyncio.create_task(self._run_one(task_id), name=f"solve-{task_id[:8]}")

    async def _run_one(self, task_id: str) -> None:
        async with self.sem:
            task = await self.store.get_task(task_id)
            if not task:
                return
            await self.store.set_processing(task_id)
            captcha_type = task.get("type") or "turnstile"
            solver = self.solvers.get(captcha_type)
            if not solver:
                await self.store.set_failed(
                    task_id,
                    "ERROR_CAPTCHA_UNSOLVABLE",
                    f"No solver for type={captcha_type}",
                )
                return
            timeout = (task.get("payload") or {}).get("timeout") or self.solve_timeout
            try:
                result = await asyncio.wait_for(solver.solve(task), timeout=float(timeout))
                if not result.token and not result.cookies:
                    await self.store.set_failed(
                        task_id,
                        "ERROR_CAPTCHA_UNSOLVABLE",
                        "Solver returned empty solution",
                    )
                    return
                await self.store.set_ready(task_id, result.to_dict())
            except asyncio.TimeoutError:
                await self.store.set_failed(
                    task_id,
                    "ERROR_CAPTCHA_UNSOLVABLE",
                    f"Solve timed out after {timeout}s",
                )
            except Exception as exc:
                logger.exception("solve failed task=%s", task_id)
                await self.store.set_failed(
                    task_id,
                    "ERROR_CAPTCHA_UNSOLVABLE",
                    str(exc)[:300],
                )

    async def _cleanup_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                await asyncio.sleep(60)
                deleted = await self.store.cleanup_expired(ttl_seconds=600)
                if deleted:
                    logger.info("cleaned %s expired tasks", deleted)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("cleanup error: %s", exc)
