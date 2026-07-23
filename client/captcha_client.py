from __future__ import annotations

import time
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx


class CaptchaClient:
    """Thin client for captcha-solver (legacy + v1)."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:5080",
        *,
        timeout: float = 120.0,
        poll_interval: float = 1.0,
        api_key: Optional[str] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.api_key = api_key

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            return {}
        return {"X-API-Key": self.api_key}

    def health(self) -> Dict[str, Any]:
        with httpx.Client(timeout=10.0, headers=self._headers()) as client:
            r = client.get(f"{self.base_url}/health")
            r.raise_for_status()
            return r.json()

    def solve_turnstile(
        self,
        url: str,
        sitekey: str,
        *,
        action: Optional[str] = None,
        cdata: Optional[str] = None,
        proxy: Optional[str] = None,
        use_v1: bool = False,
    ) -> str:
        if use_v1:
            return self._solve_v1(url, sitekey, action=action, cdata=cdata, proxy=proxy)
        return self._solve_legacy(url, sitekey, action=action, cdata=cdata, proxy=proxy)

    def _solve_legacy(
        self,
        url: str,
        sitekey: str,
        *,
        action: Optional[str] = None,
        cdata: Optional[str] = None,
        proxy: Optional[str] = None,
    ) -> str:
        params = [f"url={quote(url, safe='')}", f"sitekey={quote(sitekey, safe='')}"]
        if action:
            params.append(f"action={quote(action, safe='')}")
        if cdata:
            params.append(f"cdata={quote(cdata, safe='')}")
        if proxy:
            params.append(f"proxy={quote(proxy, safe='')}")
        create_url = f"{self.base_url}/turnstile?" + "&".join(params)

        deadline = time.time() + self.timeout
        with httpx.Client(timeout=30.0, headers=self._headers()) as client:
            r = client.get(create_url)
            r.raise_for_status()
            data = r.json()
            if data.get("errorId", 0) != 0 or not data.get("taskId"):
                raise RuntimeError(data.get("errorDescription") or f"create failed: {data}")
            task_id = data["taskId"]

            while time.time() < deadline:
                pr = client.get(f"{self.base_url}/result", params={"id": task_id})
                pr.raise_for_status()
                body = pr.json()
                if body.get("status") == "processing":
                    time.sleep(self.poll_interval)
                    continue
                if body.get("errorId", 0) != 0:
                    raise RuntimeError(body.get("errorDescription") or str(body))
                if body.get("status") == "ready":
                    token = (body.get("solution") or {}).get("token")
                    if not token:
                        raise RuntimeError("ready without token")
                    return token
                time.sleep(self.poll_interval)
        raise TimeoutError(f"solve timed out after {self.timeout}s")

    def _solve_v1(
        self,
        url: str,
        sitekey: str,
        *,
        action: Optional[str] = None,
        cdata: Optional[str] = None,
        proxy: Optional[str] = None,
    ) -> str:
        payload = {
            "type": "turnstile",
            "url": url,
            "sitekey": sitekey,
            "action": action,
            "cdata": cdata,
            "proxy": proxy,
        }
        deadline = time.time() + self.timeout
        with httpx.Client(timeout=30.0, headers=self._headers()) as client:
            r = client.post(f"{self.base_url}/v1/task", json=payload)
            r.raise_for_status()
            data = r.json()
            if data.get("errorId", 0) != 0 or not data.get("taskId"):
                raise RuntimeError(data.get("errorDescription") or f"create failed: {data}")
            task_id = data["taskId"]
            while time.time() < deadline:
                pr = client.get(f"{self.base_url}/v1/task/{task_id}")
                pr.raise_for_status()
                body = pr.json()
                if body.get("status") == "processing":
                    time.sleep(self.poll_interval)
                    continue
                if body.get("status") == "ready":
                    token = (body.get("solution") or {}).get("token")
                    if not token:
                        raise RuntimeError("ready without token")
                    return token
                raise RuntimeError(body.get("errorDescription") or str(body))
        raise TimeoutError(f"solve timed out after {self.timeout}s")
