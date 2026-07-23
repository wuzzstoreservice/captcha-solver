from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional


class Metrics:
    """Process-local counters for solve success/fail + latency."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started_at = time.time()
        self.solves_total = 0
        self.solves_ok = 0
        self.solves_fail = 0
        self.timeouts = 0
        self.queue_rejects = 0
        self.browser_recycles = 0
        self._latencies_ms: List[float] = []
        self._lat_cap = 500  # rolling window

    def record_ok(self, elapsed_s: Optional[float] = None) -> None:
        with self._lock:
            self.solves_total += 1
            self.solves_ok += 1
            if elapsed_s is not None:
                self._push_latency(elapsed_s * 1000.0)

    def record_fail(self, *, timeout: bool = False, elapsed_s: Optional[float] = None) -> None:
        with self._lock:
            self.solves_total += 1
            self.solves_fail += 1
            if timeout:
                self.timeouts += 1
            if elapsed_s is not None:
                self._push_latency(elapsed_s * 1000.0)

    def record_queue_reject(self) -> None:
        with self._lock:
            self.queue_rejects += 1

    def record_browser_recycle(self) -> None:
        with self._lock:
            self.browser_recycles += 1

    def _push_latency(self, ms: float) -> None:
        self._latencies_ms.append(ms)
        if len(self._latencies_ms) > self._lat_cap:
            self._latencies_ms = self._latencies_ms[-self._lat_cap :]

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            lats = list(self._latencies_ms)
            data = {
                "uptime_seconds": round(time.time() - self.started_at, 1),
                "solves_total": self.solves_total,
                "solves_ok": self.solves_ok,
                "solves_fail": self.solves_fail,
                "timeouts": self.timeouts,
                "queue_rejects": self.queue_rejects,
                "browser_recycles": self.browser_recycles,
                "success_rate": (
                    round(self.solves_ok / self.solves_total, 4) if self.solves_total else None
                ),
                "latency_ms": _latency_stats(lats),
            }
            return data


def _latency_stats(lats: List[float]) -> Dict[str, Optional[float]]:
    if not lats:
        return {"count": 0, "avg": None, "p50": None, "p95": None, "max": None}
    s = sorted(lats)
    n = len(s)

    def pct(p: float) -> float:
        idx = min(n - 1, max(0, int(round((p / 100.0) * (n - 1)))))
        return round(s[idx], 1)

    return {
        "count": n,
        "avg": round(sum(s) / n, 1),
        "p50": pct(50),
        "p95": pct(95),
        "max": round(s[-1], 1),
    }
