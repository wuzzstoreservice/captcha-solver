from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import CreateTaskRequest, CreateTaskResponse, Solution, TaskResultResponse

router = APIRouter(prefix="/v1", tags=["v1"])


@router.post("/task", response_model=CreateTaskResponse)
async def create_task(body: CreateTaskRequest, request: Request) -> CreateTaskResponse:
    if body.type != "turnstile":
        return CreateTaskResponse(
            errorId=1,
            taskId="",
            errorCode="ERROR_CAPTCHA_UNSOLVABLE",
            errorDescription=f"Unsupported captcha type: {body.type}",
        )
    if not body.url or not body.sitekey:
        return CreateTaskResponse(
            errorId=1,
            taskId="",
            errorCode="ERROR_WRONG_PAGEURL",
            errorDescription="Both 'url' and 'sitekey' are required",
        )

    pool = request.app.state.pool
    task_id = str(uuid.uuid4())
    payload = {
        "url": body.url,
        "sitekey": body.sitekey,
        "action": body.action,
        "cdata": body.cdata,
        "proxy": body.proxy,
        "user_agent": body.user_agent,
        "timeout": body.timeout,
        "metadata": body.metadata,
    }
    try:
        await pool.submit(task_id, body.type, payload)
    except RuntimeError as exc:
        if "queue full" in str(exc).lower():
            raise HTTPException(status_code=429, detail="queue full") from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return CreateTaskResponse(errorId=0, taskId=task_id)


@router.get("/task/{task_id}", response_model=TaskResultResponse)
async def get_task(task_id: str, request: Request) -> TaskResultResponse:
    store = request.app.state.store
    task = await store.get_task(task_id)
    if not task:
        return TaskResultResponse(
            errorId=1,
            status="failed",
            errorCode="ERROR_CAPTCHA_UNSOLVABLE",
            errorDescription="Task not found",
        )

    status = task.get("status")
    if status in ("queued", "processing"):
        return TaskResultResponse(errorId=0, status="processing")

    if status == "ready":
        sol = task.get("solution") or {}
        return TaskResultResponse(
            errorId=0,
            status="ready",
            solution=Solution(**{k: sol.get(k) for k in ("token", "cookies", "user_agent", "elapsed_time", "raw")}),
        )

    return TaskResultResponse(
        errorId=1,
        status="failed",
        errorCode=task.get("errorCode") or "ERROR_CAPTCHA_UNSOLVABLE",
        errorDescription=task.get("errorDescription") or "Workers could not solve the Captcha",
    )
