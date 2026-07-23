from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter(tags=["legacy"])


@router.get("/turnstile")
async def process_turnstile(
    request: Request,
    url: Optional[str] = None,
    sitekey: Optional[str] = None,
    action: Optional[str] = None,
    cdata: Optional[str] = None,
    proxy: Optional[str] = None,
):
    """Legacy-compatible create endpoint used by grok-register-web."""
    if not url or not sitekey:
        return JSONResponse(
            {
                "errorId": 1,
                "errorCode": "ERROR_WRONG_PAGEURL",
                "errorDescription": "Both 'url' and 'sitekey' are required",
            }
        )

    pool = request.app.state.pool
    task_id = str(uuid.uuid4())
    payload = {
        "url": url,
        "sitekey": sitekey,
        "action": action,
        "cdata": cdata,
        "proxy": proxy,
    }
    try:
        await pool.submit(task_id, "turnstile", payload)
    except RuntimeError as exc:
        return JSONResponse(
            {
                "errorId": 1,
                "errorCode": "ERROR_UNKNOWN",
                "errorDescription": str(exc),
            }
        )

    return JSONResponse({"errorId": 0, "taskId": task_id})


@router.get("/result")
async def get_result(request: Request, id: Optional[str] = None):
    """Legacy-compatible poll endpoint."""
    if not id:
        return JSONResponse(
            {
                "errorId": 1,
                "errorCode": "ERROR_WRONG_CAPTCHA_ID",
                "errorDescription": "Invalid task ID/Request parameter",
            }
        )

    store = request.app.state.store
    result = await store.get_task(id)
    if not result:
        return JSONResponse(
            {
                "errorId": 1,
                "errorCode": "ERROR_CAPTCHA_UNSOLVABLE",
                "errorDescription": "Task not found",
            }
        )

    status = result.get("status")
    if status in ("queued", "processing") or result.get("value") is None and status != "failed":
        if status != "failed" and status != "ready":
            return JSONResponse({"status": "processing"})

    if status == "failed" or result.get("value") == "CAPTCHA_FAIL":
        return JSONResponse(
            {
                "errorId": 1,
                "errorCode": result.get("errorCode") or "ERROR_CAPTCHA_UNSOLVABLE",
                "errorDescription": result.get("errorDescription")
                or "Workers could not solve the Captcha",
            }
        )

    if status == "ready" and result.get("value"):
        return JSONResponse(
            {
                "errorId": 0,
                "status": "ready",
                "solution": {"token": result["value"]},
            }
        )

    return JSONResponse(
        {
            "errorId": 1,
            "errorCode": "ERROR_CAPTCHA_UNSOLVABLE",
            "errorDescription": "Workers could not solve the Captcha",
        }
    )


@router.get("/", response_class=HTMLResponse)
async def index():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Captcha Solver API</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-900 text-gray-200 min-h-screen flex items-center justify-center">
        <div class="bg-gray-800 p-8 rounded-lg shadow-md max-w-2xl w-full border border-emerald-500">
            <h1 class="text-3xl font-bold mb-6 text-center text-emerald-400">Captcha Solver API</h1>
            <p class="mb-4 text-gray-300">MVP: Cloudflare Turnstile. Bind: localhost. Port default: 5080.</p>
            <ul class="list-disc pl-6 mb-6 text-gray-300 space-y-2">
                <li><code class="bg-gray-700 px-2 py-1 rounded">GET /health</code></li>
                <li><code class="bg-gray-700 px-2 py-1 rounded">GET /turnstile?url=...&amp;sitekey=...</code> (legacy)</li>
                <li><code class="bg-gray-700 px-2 py-1 rounded">GET /result?id=TASK_ID</code> (legacy)</li>
                <li><code class="bg-gray-700 px-2 py-1 rounded">POST /v1/task</code> + <code class="bg-gray-700 px-2 py-1 rounded">GET /v1/task/{id}</code></li>
                <li><code class="bg-gray-700 px-2 py-1 rounded">/docs</code> OpenAPI</li>
            </ul>
            <div class="bg-gray-700 p-4 rounded-lg border border-emerald-600">
                <p class="font-semibold mb-2 text-emerald-300">Example (legacy):</p>
                <code class="text-sm break-all text-emerald-200">/turnstile?url=https://example.com&amp;sitekey=0x4AAAA...</code>
            </div>
        </div>
    </body>
    </html>
    """
