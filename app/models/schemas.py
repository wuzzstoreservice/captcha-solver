from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

CaptchaType = Literal["turnstile"]  # extend later: cf_clearance, recaptcha_v3, aws_waf


class CreateTaskRequest(BaseModel):
    type: CaptchaType = "turnstile"
    url: str
    sitekey: Optional[str] = None
    action: Optional[str] = None
    cdata: Optional[str] = None
    proxy: Optional[str] = None
    user_agent: Optional[str] = None
    timeout: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CreateTaskResponse(BaseModel):
    errorId: int = 0
    taskId: str
    errorCode: Optional[str] = None
    errorDescription: Optional[str] = None


class Solution(BaseModel):
    token: Optional[str] = None
    cookies: Optional[Dict[str, str]] = None
    user_agent: Optional[str] = None
    elapsed_time: Optional[float] = None
    raw: Optional[Dict[str, Any]] = None


class TaskResultResponse(BaseModel):
    errorId: int = 0
    status: Literal["processing", "ready", "failed"] = "processing"
    solution: Optional[Solution] = None
    errorCode: Optional[str] = None
    errorDescription: Optional[str] = None
