from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from app.metrics import Metrics
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
        metrics: Optional[Metrics] = None,
    ) -> None:
        self.store = store
        self.solvers = solvers
        self.sem = asyncio.Semaphore(max(1, concurrency))
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=max(1, max_queue))
        self.solve_timeout = solve_timeout
        self.metrics = metrics or Metrics()
        self._runner: Optional[asyncio.Task] = None
        self._cleanup: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()
        self._inflight = 0

    @property
    def pending(self) -> int:
        return self.queue.qsize()

    @property
    def inflight(self) -> int:
        return self._inflight

    def stats(self) -> Dict[str, Any]:
        snap = self.metrics.snapshot()
        snap["queue_pending"] = self.pending
        snap["inflight"] = self.inflight
        snap["solvers"] = {}
        for name, solver in self.solvers.items():
            if hasattr(solver, "stats") and callable(getattr(solver, "stats")):
                try:
                    snap["solvers"][name] = solver.stats()  # type: ignore[attr-defined]
                except Exception as exc:
                    snap["solvers"][name] = {"error": str(exc)[:120]}
            else:
                snap["solvers"][name] = {"type": getattr(solver, "type", name)}
        return snap

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
            self.metrics.record_queue_reject()
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
            self._inflight += 1
            t0 = time.time()
            try:
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
                    self.metrics.record_fail(elapsed_s=time.time() - t0)
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
                        self.metrics.record_fail(elapsed_s=time.time() - t0)
                        return
                    await self.store.set_ready(task_id, result.to_dict())
                    elapsed = result.elapsed_time if result.elapsed_time is not None else (time.time() - t0)
                    self.metrics.record_ok(elapsed_s=float(elapsed))
                    logger.info(
                        "task=%s type=%s ok elapsed=%.3fs",
                        task_id[:8],
                        captcha_type,
                        float(elapsed),
                    )
                except asyncio.TimeoutError:
                    await self.store.set_failed(
                        task_id,
                        "ERROR_CAPTCHA_UNSOLVABLE",
                        f"Solve timed out after {timeout}s",
                    )
                    self.metrics.record_fail(timeout=True, elapsed_s=time.time() - t0)
                    logger.warning("task=%s timeout after %ss", task_id[:8], timeout)
                except Exception as exc:
                    logger.exception("solve failed task=%s", task_id)
                    await self.store.set_failed(
                        task_id,
                        "ERROR_CAPTCHA_UNSOLVABLE",
                        str(exc)[:300],
                    )
                    self.metrics.record_fail(elapsed_s=time.time() - t0)
            finally:
                self._inflight = max(0, self._inflight - 1)

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
