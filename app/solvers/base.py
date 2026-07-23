from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol


@dataclass
class SolveResult:
    token: Optional[str] = None
    cookies: Optional[Dict[str, str]] = None
    user_agent: Optional[str] = None
    elapsed_time: Optional[float] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        if self.token is not None:
            data["token"] = self.token
        if self.cookies is not None:
            data["cookies"] = self.cookies
        if self.user_agent is not None:
            data["user_agent"] = self.user_agent
        if self.elapsed_time is not None:
            data["elapsed_time"] = self.elapsed_time
        if self.raw:
            data["raw"] = self.raw
        return data


class BaseSolver(Protocol):
    type: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def solve(self, task: Dict[str, Any]) -> SolveResult: ...
