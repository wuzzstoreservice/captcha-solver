from __future__ import annotations

import asyncio
import logging
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.solvers.base import SolveResult

logger = logging.getLogger("captcha-solver.turnstile")


def _parse_proxy(proxy: str) -> dict:
    """Parse proxy string into Playwright/Camoufox proxy options."""
    if "://" not in proxy and proxy.count(":") >= 3:
        # user:pass:host:port
        parts = proxy.split(":")
        if len(parts) == 4:
            user, password, host, port = parts
            return {
                "server": f"http://{host}:{port}",
                "username": user,
                "password": password,
            }
    if "@" in proxy:
        scheme_part, auth_part = proxy.split("://", 1)
        auth, address = auth_part.split("@", 1)
        username, password = auth.split(":", 1)
        return {
            "server": f"{scheme_part}://{address}",
            "username": username,
            "password": password,
        }
    parts = proxy.split(":")
    if len(parts) == 5:
        proxy_scheme, proxy_ip, proxy_port, proxy_user, proxy_pass = parts
        return {
            "server": f"{proxy_scheme}://{proxy_ip}:{proxy_port}",
            "username": proxy_user,
            "password": proxy_pass,
        }
    if len(parts) == 3 or "://" in proxy:
        return {"server": proxy}
    raise ValueError(f"Invalid proxy format: {proxy}")


class TurnstileSolver:
    """Camoufox-based Cloudflare Turnstile solver (ported from grok-register-web)."""

    type = "turnstile"

    def __init__(
        self,
        *,
        thread: int = 1,
        headless: bool = True,
        debug: bool = False,
        proxy_support: bool = True,
        proxies_file: Optional[Path] = None,
        solve_timeout: int = 120,
    ) -> None:
        self.thread = max(1, int(thread))
        self.headless = headless
        self.debug = debug
        self.proxy_support = proxy_support
        self.proxies_file = proxies_file
        self.solve_timeout = solve_timeout
        self.browser_pool: asyncio.Queue = asyncio.Queue()
        self._camoufox = None
        self._started = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._started:
                return
            try:
                from camoufox.async_api import AsyncCamoufox
            except ImportError as exc:
                raise RuntimeError(
                    "camoufox not installed. Run: pip install -r requirements-browser.txt "
                    "&& python -m camoufox fetch"
                ) from exc

            logger.info("Starting Camoufox pool (thread=%s headless=%s)", self.thread, self.headless)
            self._camoufox = AsyncCamoufox(headless=self.headless)
            for i in range(self.thread):
                browser = await self._camoufox.start()
                await self.browser_pool.put((i + 1, browser, {"browser_name": "camoufox"}))
                if self.debug:
                    logger.debug("Browser %s ready", i + 1)
            self._started = True
            logger.info("Browser pool size=%s", self.browser_pool.qsize())

    async def stop(self) -> None:
        async with self._lock:
            if not self._started:
                return
            while not self.browser_pool.empty():
                try:
                    index, browser, _ = self.browser_pool.get_nowait()
                    try:
                        await browser.close()
                    except Exception as exc:
                        logger.warning("Browser %s close failed: %s", index, exc)
                except asyncio.QueueEmpty:
                    break
            self._camoufox = None
            self._started = False
            logger.info("Turnstile solver stopped")

    def _select_file_proxy(self) -> Optional[str]:
        if not self.proxy_support or not self.proxies_file:
            return None
        path = Path(self.proxies_file)
        if not path.exists():
            return None
        try:
            lines = [
                ln.strip()
                for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
            return random.choice(lines) if lines else None
        except Exception as exc:
            logger.warning("proxy file read error: %s", exc)
            return None

    async def _create_context(
        self,
        browser,
        proxy: Optional[str],
        index: int,
    ) -> Tuple[Any, Any]:
        context_options: Dict[str, Any] = {"no_viewport": True}
        if proxy:
            context_options["proxy"] = _parse_proxy(proxy)
            if self.debug:
                logger.debug("Browser %s: proxy server set", index)

        try:
            page = await browser.new_page(**context_options)
            return page.context, page
        except Exception as e1:
            try:
                context = await browser.new_context(**context_options)
                page = await context.new_page()
                return context, page
            except Exception as e2:
                raise RuntimeError(
                    f"Camoufox context failed: new_page={e1!s:.120}; new_context={e2!s:.120}"
                ) from e2

    async def _antishadow_inject(self, page) -> None:
        await page.add_init_script(
            """
          (function() {
            const originalAttachShadow = Element.prototype.attachShadow;
            Element.prototype.attachShadow = function(init) {
              const shadow = originalAttachShadow.call(this, init);
              if (init.mode === 'closed') {
                window.__lastClosedShadowRoot = shadow;
              }
              return shadow;
            };
          })();
        """
        )

    async def _optimized_route_handler(self, route) -> None:
        url = route.request.url
        resource_type = route.request.resource_type
        allowed_types = {"document", "script", "xhr", "fetch"}
        allowed_domains = [
            "challenges.cloudflare.com",
            "static.cloudflareinsights.com",
            "cloudflare.com",
        ]
        if resource_type in allowed_types or any(d in url for d in allowed_domains):
            await route.continue_()
        else:
            await route.abort()

    async def _block_rendering(self, page) -> None:
        await page.route("**/*", self._optimized_route_handler)

    async def _unblock_rendering(self, page) -> None:
        await page.unroute("**/*", self._optimized_route_handler)

    async def _inject_captcha(
        self,
        page,
        website_key: str,
        action: str = "",
        cdata: str = "",
    ) -> None:
        action_attr = f'captchaDiv.setAttribute("data-action", "{action}");' if action else ""
        cdata_attr = f'captchaDiv.setAttribute("data-cdata", "{cdata}");' if cdata else ""
        action_opt = f'action: "{action}",' if action else ""
        cdata_opt = f'cdata: "{cdata}",' if cdata else ""
        script = f"""
        document.querySelectorAll('.cf-turnstile').forEach(el => el.remove());
        document.querySelectorAll('[data-sitekey]').forEach(el => el.remove());

        const captchaDiv = document.createElement('div');
        captchaDiv.className = 'cf-turnstile';
        captchaDiv.setAttribute('data-sitekey', '{website_key}');
        captchaDiv.setAttribute('data-callback', 'onTurnstileCallback');
        {action_attr}
        {cdata_attr}
        captchaDiv.style.position = 'fixed';
        captchaDiv.style.top = '20px';
        captchaDiv.style.left = '20px';
        captchaDiv.style.zIndex = '9999';
        captchaDiv.style.backgroundColor = 'white';
        captchaDiv.style.padding = '15px';
        document.body.appendChild(captchaDiv);

        const loadTurnstile = () => {{
            const script = document.createElement('script');
            script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
            script.async = true;
            script.defer = true;
            script.onload = function() {{
                setTimeout(() => {{
                    if (window.turnstile && window.turnstile.render) {{
                        try {{
                            window.turnstile.render(captchaDiv, {{
                                sitekey: '{website_key}',
                                {action_opt}
                                {cdata_opt}
                                callback: function(token) {{
                                    let tokenInput = document.querySelector('input[name="cf-turnstile-response"]');
                                    if (!tokenInput) {{
                                        tokenInput = document.createElement('input');
                                        tokenInput.type = 'hidden';
                                        tokenInput.name = 'cf-turnstile-response';
                                        document.body.appendChild(tokenInput);
                                    }}
                                    tokenInput.value = token;
                                }},
                                'error-callback': function(error) {{
                                    console.log('Turnstile error:', error);
                                }}
                            }});
                        }} catch (e) {{
                            console.log('Turnstile render error:', e);
                        }}
                    }}
                }}, 1000);
            }};
            document.head.appendChild(script);
        }};

        if (window.turnstile) {{
            try {{
                window.turnstile.render(captchaDiv, {{
                    sitekey: '{website_key}',
                    {action_opt}
                    {cdata_opt}
                    callback: function(token) {{
                        let tokenInput = document.querySelector('input[name="cf-turnstile-response"]');
                        if (!tokenInput) {{
                            tokenInput = document.createElement('input');
                            tokenInput.type = 'hidden';
                            tokenInput.name = 'cf-turnstile-response';
                            document.body.appendChild(tokenInput);
                        }}
                        tokenInput.value = token;
                    }}
                }});
            }} catch (e) {{
                loadTurnstile();
            }}
        }} else {{
            loadTurnstile();
        }}

        window.onTurnstileCallback = function(token) {{
            let tokenInput = document.querySelector('input[name="cf-turnstile-response"]');
            if (!tokenInput) {{
                tokenInput = document.createElement('input');
                tokenInput.type = 'hidden';
                tokenInput.name = 'cf-turnstile-response';
                document.body.appendChild(tokenInput);
            }}
            tokenInput.value = token;
        }};
        """
        await page.evaluate(script)

    async def _safe_click(self, page, selector: str) -> bool:
        try:
            await page.locator(selector).first.click(timeout=1000)
            return True
        except Exception:
            return False

    async def _find_and_click_checkbox(self, page) -> bool:
        iframe_selectors = [
            'iframe[src*="challenges.cloudflare.com"]',
            'iframe[src*="turnstile"]',
            'iframe[title*="widget"]',
        ]
        for selector in iframe_selectors:
            try:
                iframe_locator = page.locator(selector).first
                try:
                    count = await iframe_locator.count()
                except Exception:
                    count = 0
                if count == 0:
                    continue
                iframe_element = await iframe_locator.element_handle()
                frame = await iframe_element.content_frame() if iframe_element else None
                if not frame:
                    continue
                for cb_sel in (
                    'input[type="checkbox"]',
                    '.cb-lb input[type="checkbox"]',
                    'label input[type="checkbox"]',
                ):
                    try:
                        await frame.locator(cb_sel).first.click(timeout=2000)
                        return True
                    except Exception:
                        continue
                try:
                    await iframe_locator.click(timeout=1000)
                    return True
                except Exception:
                    pass
            except Exception:
                continue
        return False

    async def _try_click_strategies(self, page) -> bool:
        strategies = [
            lambda: self._find_and_click_checkbox(page),
            lambda: self._safe_click(page, ".cf-turnstile"),
            lambda: self._safe_click(page, 'iframe[src*="turnstile"]'),
            lambda: page.evaluate("document.querySelector('.cf-turnstile')?.click()"),
            lambda: self._safe_click(page, "[data-sitekey]"),
        ]
        for strategy in strategies:
            try:
                result = await strategy()
                if result is True or result is None:
                    return True
            except Exception:
                continue
        return False

    async def solve(self, task: Dict[str, Any]) -> SolveResult:
        if not self._started:
            await self.start()

        payload = task.get("payload") or {}
        url = payload.get("url") or ""
        sitekey = payload.get("sitekey") or ""
        action = payload.get("action") or ""
        cdata = payload.get("cdata") or ""
        proxy = (payload.get("proxy") or "").strip() or None
        if not proxy:
            proxy = self._select_file_proxy()

        if not url or not sitekey:
            raise ValueError("url and sitekey are required")

        start_time = time.time()
        index, browser, browser_config = await self.browser_pool.get()
        context = None
        try:
            if hasattr(browser, "is_connected") and not browser.is_connected():
                raise RuntimeError("browser disconnected")

            context, page = await self._create_context(browser, proxy, index)
            await self._antishadow_inject(page)
            await self._block_rendering(page)

            if self.debug:
                logger.debug(
                    "Browser %s solve url=%s sitekey=%s proxy=%s",
                    index,
                    url,
                    sitekey[:12],
                    bool(proxy),
                )

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self._unblock_rendering(page)
            await self._inject_captcha(page, sitekey, action, cdata)
            await asyncio.sleep(3)

            locator = page.locator('input[name="cf-turnstile-response"]')
            max_attempts = 30
            click_count = 0
            max_clicks = 10

            for attempt in range(max_attempts):
                try:
                    try:
                        count = await locator.count()
                    except Exception:
                        count = 0

                    tokens: List[str] = []
                    if count == 1:
                        try:
                            token = await locator.input_value(timeout=500)
                            if token:
                                tokens.append(token)
                        except Exception:
                            pass
                    elif count > 1:
                        for i in range(count):
                            try:
                                t = await locator.nth(i).input_value(timeout=500)
                                if t:
                                    tokens.append(t)
                            except Exception:
                                continue

                    if tokens:
                        elapsed = round(time.time() - start_time, 3)
                        logger.info(
                            "Browser %s solved turnstile in %ss token=%s...",
                            index,
                            elapsed,
                            tokens[0][:10],
                        )
                        return SolveResult(token=tokens[0], elapsed_time=elapsed)

                    if attempt > 2 and attempt % 3 == 0 and click_count < max_clicks:
                        await self._try_click_strategies(page)
                        click_count += 1

                    await asyncio.sleep(min(0.5 + (attempt * 0.05), 2.0))
                except Exception as exc:
                    if self.debug:
                        logger.debug("Browser %s attempt %s error: %s", index, attempt + 1, exc)
                    continue

            elapsed = round(time.time() - start_time, 3)
            raise TimeoutError(f"Turnstile not solved in {elapsed}s")
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception as exc:
                    if self.debug:
                        logger.debug("Browser %s context close: %s", index, exc)
            try:
                if hasattr(browser, "is_connected") and not browser.is_connected():
                    logger.warning("Browser %s disconnected; not returning to pool", index)
                else:
                    await self.browser_pool.put((index, browser, browser_config))
            except Exception as exc:
                logger.warning("Browser %s return to pool failed: %s", index, exc)
