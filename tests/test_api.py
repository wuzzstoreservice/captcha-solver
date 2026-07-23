from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Force mock solver for unit tests (no browser)
os.environ["CAPTCHA_SOLVER_MOCK_SOLVER"] = "true"
os.environ["CAPTCHA_SOLVER_THREAD"] = "1"

from app.config import get_settings
from app.main import create_app
from app.store.memory_store import ResultStore


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def app():
    get_settings.cache_clear()
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["service"] == "captcha-solver"
    assert body["mock_solver"] is True


@pytest.mark.asyncio
async def test_store_create_ready():
    store = ResultStore()
    await store.init()
    await store.create_task("t1", "turnstile", {"url": "https://x", "sitekey": "k"})
    row = await store.get_task("t1")
    assert row["status"] == "queued"
    await store.set_processing("t1")
    await store.set_ready("t1", {"token": "abc"})
    row = await store.get_task("t1")
    assert row["status"] == "ready"
    assert row["solution"]["token"] == "abc"
    assert row["value"] == "abc"


@pytest.mark.asyncio
async def test_legacy_requires_params(client):
    r = await client.get("/turnstile")
    assert r.status_code == 200
    assert r.json()["errorId"] == 1
    assert r.json()["errorCode"] == "ERROR_WRONG_PAGEURL"


@pytest.mark.asyncio
async def test_legacy_create_and_poll(client):
    r = await client.get(
        "/turnstile",
        params={"url": "https://example.com", "sitekey": "0x4AAAA-test"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["errorId"] == 0
    task_id = data["taskId"]
    assert task_id

    # poll until ready (mock is fast)
    token = None
    for _ in range(50):
        pr = await client.get("/result", params={"id": task_id})
        body = pr.json()
        if body.get("status") == "processing":
            import asyncio

            await asyncio.sleep(0.05)
            continue
        assert body.get("errorId") == 0
        assert body.get("status") == "ready"
        token = body["solution"]["token"]
        break
    assert token and token.startswith("mock-token-")


@pytest.mark.asyncio
async def test_legacy_poll_unknown(client):
    r = await client.get("/result", params={"id": "nope"})
    assert r.json()["errorId"] == 1


@pytest.mark.asyncio
async def test_v1_create_and_poll(client):
    r = await client.post(
        "/v1/task",
        json={
            "type": "turnstile",
            "url": "https://example.com",
            "sitekey": "0x4AAAA-test",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["errorId"] == 0
    task_id = data["taskId"]

    import asyncio

    for _ in range(50):
        pr = await client.get(f"/v1/task/{task_id}")
        body = pr.json()
        if body.get("status") == "processing":
            await asyncio.sleep(0.05)
            continue
        assert body["status"] == "ready"
        assert body["solution"]["token"].startswith("mock-token-")
        return
    raise AssertionError("task not ready")


@pytest.mark.asyncio
async def test_v1_missing_sitekey(client):
    r = await client.post(
        "/v1/task",
        json={"type": "turnstile", "url": "https://example.com", "sitekey": None},
    )
    # pydantic may 422 if sitekey required optional — we allow optional then check in handler
    # if validation passes with null:
    if r.status_code == 422:
        return
    body = r.json()
    assert body["errorId"] == 1


@pytest.mark.asyncio
async def test_metrics_after_solve(client):
    r = await client.get("/metrics")
    assert r.status_code == 200
    before = r.json()
    assert before["service"] == "captcha-solver"
    assert "solves_total" in before
    assert "latency_ms" in before
    assert "queue_pending" in before

    create = await client.get(
        "/turnstile",
        params={"url": "https://example.com", "sitekey": "0x4AAAA-test"},
    )
    task_id = create.json()["taskId"]

    import asyncio

    for _ in range(50):
        pr = await client.get("/result", params={"id": task_id})
        if pr.json().get("status") == "ready":
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("task not ready")

    after = (await client.get("/metrics")).json()
    assert after["solves_total"] >= before["solves_total"] + 1
    assert after["solves_ok"] >= before.get("solves_ok", 0) + 1
    assert after["latency_ms"]["count"] >= 1
    assert "solvers" in after
    assert "turnstile" in after["solvers"]


@pytest.mark.asyncio
async def test_metrics_unit_counters():
    from app.metrics import Metrics

    m = Metrics()
    m.record_ok(elapsed_s=0.12)
    m.record_ok(elapsed_s=0.2)
    m.record_fail(timeout=True, elapsed_s=1.0)
    m.record_queue_reject()
    m.record_browser_recycle()
    snap = m.snapshot()
    assert snap["solves_total"] == 3
    assert snap["solves_ok"] == 2
    assert snap["solves_fail"] == 1
    assert snap["timeouts"] == 1
    assert snap["queue_rejects"] == 1
    assert snap["browser_recycles"] == 1
    assert snap["latency_ms"]["count"] == 3
    assert snap["success_rate"] == round(2 / 3, 4)
