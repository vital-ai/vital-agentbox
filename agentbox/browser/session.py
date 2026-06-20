"""
Single browser session — wraps a Playwright browser context.

Each session has its own persistent context (isolated cookies, storage)
and manages its own page. Multiple sessions can share one Playwright
instance and one Xvfb display.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import time
import uuid

from playwright.async_api import BrowserContext, Page, Playwright

from agentbox.browser.models import SessionConfig

log = logging.getLogger(__name__)


class BrowserSession:
    """A single browser session backed by a Playwright browser context."""

    def __init__(
        self,
        session_id: str | None = None,
        config: SessionConfig | None = None,
    ):
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.config = config or SessionConfig()
        self._browser = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self.created_at = time.time()
        self.last_activity = time.time()
        self.request_count = 0

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_activity

    def _touch(self):
        self.last_activity = time.time()
        self.request_count += 1

    async def start(self, playwright: Playwright):
        """Launch a browser and create a context using the session config."""
        cfg = self.config
        log.info(
            "[%s] Starting browser session (browser=%s, proxy=%s, viewport=%dx%d)",
            self.session_id, cfg.browser_type,
            cfg.proxy.server if cfg.proxy else "direct",
            cfg.viewport_width, cfg.viewport_height,
        )

        proxy_dict = None
        if cfg.proxy:
            proxy_dict = {"server": cfg.proxy.server}
            if cfg.proxy.username:
                proxy_dict["username"] = cfg.proxy.username
            if cfg.proxy.password:
                proxy_dict["password"] = cfg.proxy.password

        if cfg.browser_type == "camoufox":
            self._context = await self._start_camoufox(playwright, cfg, proxy_dict)
        else:
            self._context = await self._start_chrome(playwright, cfg, proxy_dict)

        self._page = await self._context.new_page()
        log.info("[%s] Browser session started (%s)", self.session_id, cfg.browser_type)

    async def _start_chrome(self, playwright: Playwright, cfg, proxy_dict) -> BrowserContext:
        """Launch Chrome and create an ephemeral browser context."""
        args = [
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--ignore-certificate-errors",
            *cfg.extra_args,
        ]

        launch_opts: dict = {
            "headless": cfg.headless,
            "args": args,
        }
        if cfg.use_system_chrome:
            launch_opts["channel"] = "chrome"

        self._browser = await playwright.chromium.launch(**launch_opts)

        context_opts: dict = {
            "viewport": {"width": cfg.viewport_width, "height": cfg.viewport_height},
        }
        if proxy_dict:
            context_opts["proxy"] = proxy_dict
        if cfg.user_agent:
            context_opts["user_agent"] = cfg.user_agent
        if cfg.locale:
            context_opts["locale"] = cfg.locale
        if cfg.timezone_id:
            context_opts["timezone_id"] = cfg.timezone_id
        if cfg.geolocation:
            context_opts["geolocation"] = cfg.geolocation
            context_opts["permissions"] = ["geolocation"]

        return await self._browser.new_context(**context_opts)

    async def _start_camoufox(self, playwright: Playwright, cfg, proxy_dict) -> BrowserContext:
        """Launch Camoufox (anti-detect Firefox) via its Playwright wrapper."""
        from camoufox.async_api import AsyncNewBrowser

        camoufox_opts: dict = {
            "persistent_context": True,
            "headless": False,  # uses existing Xvfb (DISPLAY=:99)
            "humanize": True,
            "user_data_dir": f"/tmp/browser-session-{self.session_id}",
            "viewport": {"width": cfg.viewport_width, "height": cfg.viewport_height},
        }

        if proxy_dict:
            camoufox_opts["proxy"] = proxy_dict
        if cfg.locale:
            camoufox_opts["locale"] = cfg.locale
        if cfg.timezone_id:
            camoufox_opts["timezone_id"] = cfg.timezone_id
        if cfg.geolocation:
            camoufox_opts["geoip"] = True
            camoufox_opts["geolocation"] = cfg.geolocation
            camoufox_opts["permissions"] = ["geolocation"]

        return await AsyncNewBrowser(playwright, **camoufox_opts)

    async def get_page_state(self) -> dict:
        """Return current page URL, title, html_length, and content_hash."""
        url, title, html_length, content_hash = "", "", 0, ""
        try:
            if self._page:
                url = self._page.url or ""
                title = await self._page.title() or ""
                html = await self._page.content()
                html_length = len(html)
                content_hash = hashlib.sha256(html.encode()).hexdigest()[:12]
        except Exception:
            pass
        return {"url": url, "title": title, "html_length": html_length, "content_hash": content_hash}

    async def navigate(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 60000) -> str:
        """Navigate to a URL. Returns the page title."""
        self._touch()
        log.debug("[%s] navigate → %s", self.session_id, url)
        await self._page.goto(url, wait_until=wait_until, timeout=timeout)
        try:
            await self._page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        return await self._page.title()

    async def wait_for_load_state(self, state: str = "networkidle", timeout: int = 10000) -> None:
        """Wait for a specific page load state."""
        self._touch()
        await self._page.wait_for_load_state(state, timeout=timeout)

    async def click_and_wait_for_navigation(self, selector: str, wait_until: str = "domcontentloaded", timeout: int = 30000) -> str:
        """Click an element and wait for navigation. Returns the new page title."""
        self._touch()
        async with self._page.expect_navigation(wait_until=wait_until, timeout=timeout):
            await self._page.click(selector)
        return await self._page.title()

    async def fill(self, selector: str, value: str) -> None:
        """Fill a form field."""
        self._touch()
        await self._page.fill(selector, value)

    async def click(self, selector: str) -> None:
        """Click an element."""
        self._touch()
        await self._page.click(selector)

    async def select(self, selector: str, value: str) -> None:
        """Select an option from a dropdown."""
        self._touch()
        await self._page.select_option(selector, value)

    async def get_content(self) -> str:
        """Get the current page HTML."""
        self._touch()
        if self._page is None:
            raise RuntimeError("Page is None — session may have been closed by idle timeout")
        return await self._page.content()

    async def get_title(self) -> str:
        """Get the current page title."""
        self._touch()
        if self._page is None:
            raise RuntimeError("Page is None — session may have been closed by idle timeout")
        return await self._page.title()

    async def get_url(self) -> str:
        """Get the current page URL."""
        self._touch()
        return self._page.url

    async def wait(self, ms: int) -> None:
        """Wait for a specified number of milliseconds."""
        self._touch()
        await self._page.wait_for_timeout(ms)

    async def wait_for_selector(self, selector: str, timeout: int = 30000) -> bool:
        """Wait for an element to appear. Returns True if found."""
        self._touch()
        try:
            await self._page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:
            return False

    async def screenshot(self) -> str:
        """Take a screenshot, return as base64-encoded PNG."""
        self._touch()
        png_bytes = await self._page.screenshot()
        return base64.b64encode(png_bytes).decode("ascii")

    async def evaluate(self, expression: str) -> str:
        """Evaluate a JavaScript expression and return the result as a string."""
        self._touch()
        result = await self._page.evaluate(expression)
        return str(result)

    async def solve_captcha(self, on_progress=None) -> dict:
        """Detect and solve Cloudflare / hCaptcha challenges on the current page.

        Args:
            on_progress: Optional async callback(message: str) called at each stage.

        Returns a dict with keys: solved (bool), method (str), message (str).
        """
        self._touch()
        page = self._page

        async def _progress(msg: str):
            self._touch()
            log.info("[%s] %s", self.session_id, msg)
            if on_progress:
                await on_progress(msg)

        title = (await page.title()).lower()
        if "just a moment" not in title and "captcha" not in title:
            return {"solved": True, "method": "none", "message": "No challenge detected"}

        await _progress(f"Challenge detected (title: '{title}'), waiting for Cloudflare JS...")

        # Wait for Cloudflare JS challenge to auto-resolve
        resolved, elapsed = await self._poll_title_cleared(timeout_ms=15000, interval_ms=500)
        if resolved:
            await _progress(f"Cloudflare JS resolved after {elapsed}ms")
            return {"solved": True, "method": "cloudflare_auto", "message": f"Cloudflare resolved after {elapsed}ms"}

        await _progress("Cloudflare JS did not auto-resolve, checking for hCaptcha...")

        # Check for hCaptcha
        has_hcaptcha = any("hcaptcha" in f.url for f in page.frames)
        if not has_hcaptcha:
            return {"solved": False, "method": "none", "message": "Challenge present but no hCaptcha found"}

        # Step A: Click checkbox
        await _progress("hCaptcha detected, clicking checkbox...")
        checkbox_clicked = await self._click_hcaptcha_checkbox()
        if not checkbox_clicked:
            return {"solved": False, "method": "hcaptcha", "message": "Could not click hCaptcha checkbox"}

        await _progress("Checkbox clicked, checking if challenge resolved...")

        resolved, elapsed = await self._poll_title_cleared(timeout_ms=3000, interval_ms=500)
        if resolved:
            await _progress(f"Solved by checkbox click alone ({elapsed}ms)")
            return {"solved": True, "method": "hcaptcha_checkbox", "message": f"Solved by checkbox click alone ({elapsed}ms)"}

        # Step B: Invoke solver
        max_attempts = 1
        for attempt in range(1, max_attempts + 1):
            await _progress(f"Image challenge present — invoking AI solver (attempt {attempt}/{max_attempts})...")
            solved = await self._run_hcaptcha_solver()

            await _progress(f"Solver attempt {attempt} finished, checking result...")

            resolved, elapsed = await self._poll_title_cleared(timeout_ms=5000, interval_ms=500)
            if resolved:
                await _progress(f"CAPTCHA solved on attempt {attempt} ({elapsed}ms)")
                return {"solved": True, "method": "hcaptcha_solver", "message": f"Solved on attempt {attempt} ({elapsed}ms)"}

            if attempt < max_attempts:
                await _progress(f"Attempt {attempt} did not resolve, retrying...")
                has_hcaptcha = any("hcaptcha" in f.url for f in page.frames)
                if has_hcaptcha:
                    await self._click_hcaptcha_checkbox()
                    await self._poll_title_cleared(timeout_ms=2000, interval_ms=500)

        return {"solved": False, "method": "hcaptcha_solver", "message": "Solver completed but challenge persists"}

    async def _poll_title_cleared(self, timeout_ms: int = 5000, interval_ms: int = 500) -> tuple[bool, int]:
        """Poll the page title until it no longer indicates a challenge."""
        page = self._page
        elapsed = 0
        while elapsed < timeout_ms:
            self._touch()
            try:
                title = (await page.title()).lower()
            except Exception:
                log.info("[%s] Page navigated during poll, waiting for new page", self.session_id)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                try:
                    title = (await page.title()).lower()
                except Exception:
                    title = ""
                resolved = "just a moment" not in title and "captcha" not in title
                return resolved, elapsed
            if "just a moment" not in title and "captcha" not in title:
                return True, elapsed
            await page.wait_for_timeout(interval_ms)
            elapsed += interval_ms
        return False, elapsed

    async def _click_hcaptcha_checkbox(self) -> bool:
        """Find and click the hCaptcha checkbox iframe."""
        try:
            for frame in self._page.frames:
                if "hcaptcha" in frame.url and "checkbox" in frame.url:
                    checkbox = frame.locator("#checkbox")
                    if await checkbox.count() > 0:
                        await checkbox.click()
                        log.info("[%s] hCaptcha checkbox clicked", self.session_id)
                        return True
            log.debug("[%s] No hCaptcha checkbox frame found", self.session_id)
        except Exception as exc:
            log.warning("[%s] Checkbox click error: %s", self.session_id, exc)
        return False

    async def _run_hcaptcha_solver(self) -> bool:
        """Invoke hcaptcha-challenger to solve the image challenge."""
        try:
            from hcaptcha_challenger import AgentConfig, AgentV

            log.info("[%s] Invoking hcaptcha-challenger solver", self.session_id)
            config = AgentConfig(
                IMAGE_CLASSIFIER_MODEL="gemini-2.5-pro",
                SPATIAL_POINT_REASONER_MODEL="gemini-2.5-pro",
                SPATIAL_PATH_REASONER_MODEL="gemini-2.5-pro",
                CHALLENGE_CLASSIFIER_MODEL="gemini-2.5-flash",
            )
            agent = AgentV(page=self._page, agent_config=config)
            response = await agent.wait_for_challenge()
            log.info("[%s] Solver response: %s", self.session_id, response)
            return "SUCCESS" in str(response).upper()
        except Exception as exc:
            log.error("[%s] hCaptcha solver error: %s", self.session_id, exc, exc_info=True)
            return False

    async def close(self):
        """Close the browser context, browser, and release resources."""
        if self._context:
            try:
                await self._context.close()
            except Exception as exc:
                log.warning("[%s] Error closing context: %s", self.session_id, exc)
            self._context = None
            self._page = None
        if self._browser:
            try:
                await self._browser.close()
            except Exception as exc:
                log.warning("[%s] Error closing browser: %s", self.session_id, exc)
            self._browser = None
        log.info("[%s] Session closed", self.session_id)
