from __future__ import annotations

import asyncio
import time
from copy import deepcopy
from typing import Any, Dict, Optional


class ResultStore:
    """In-memory task/result store (drop-in simple, enough for single-node MVP)."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tasks: Dict[str, Dict[str, Any]] = {}

    async def init(self) -> None:
        return None

    async def create_task(
        self,
        task_id: str,
        captcha_type: str,
        payload: Dict[str, Any],
    ) -> None:
        async with self._lock:
            self._tasks[task_id] = {
                "id": task_id,
                "type": captcha_type,
                "status": "queued",
                "createTime": int(time.time()),
                "payload": dict(payload),
                "solution": None,
                "errorCode": None,
                "errorDescription": None,
                "value": None,  # legacy field
            }

    async def set_processing(self, task_id: str) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["status"] = "processing"

    async def set_ready(self, task_id: str, solution: Dict[str, Any]) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["status"] = "ready"
            task["solution"] = solution
            # legacy compat: token stored as value
            token = solution.get("token")
            if token:
                task["value"] = token

    async def set_failed(
        self,
        task_id: str,
        code: str,
        description: str,
    ) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["status"] = "failed"
            task["errorCode"] = code
            task["errorDescription"] = description
            task["value"] = "CAPTCHA_FAIL"

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            task = self._tasks.get(task_id)
            return deepcopy(task) if task else None

    async def cleanup_expired(self, ttl_seconds: int) -> int:
        now = time.time()
        async with self._lock:
            to_delete = [
                tid
                for tid, t in self._tasks.items()
                if now - t.get("createTime", now) > ttl_seconds
            ]
            for tid in to_delete:
                del self._tasks[tid]
            return len(to_delete)

    @property
    def size(self) -> int:
        return len(self._tasks)
