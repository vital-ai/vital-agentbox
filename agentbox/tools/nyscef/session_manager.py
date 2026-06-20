"""
NYSCEF browser session manager.

Orchestrates NYSCEF-specific navigation (search forms, docket pages) via
the agentbox Browser client.

Uses ``agentbox.browser_client.Browser`` which works via the
sendMessage bridge (Pyodide) or native websockets (AgentCore).
"""

import asyncio
import logging

from agentbox.browser_client import Browser, BrowserError

log = logging.getLogger(__name__)

NYSCEF_BASE = "https://iapps.courts.state.ny.us/nyscef"
NYSCEF_SEARCH_URL = f"{NYSCEF_BASE}/CaseSearch?TAB=name"
NYSCEF_INDEX_SEARCH_URL = f"{NYSCEF_BASE}/CaseSearch?TAB=caseIdentifier"
NYSCEF_DOCKET_URL = f"{NYSCEF_BASE}/DocumentList"


class NyscefSessionError(BrowserError):
    """Raised when a NYSCEF session operation fails."""


MAX_SESSION_RETRIES = 3


class NyscefSessionManager:
    """Orchestrates NYSCEF navigation via the agentbox Browser client.

    Creates a browser session, drives the NYSCEF search forms,
    handles CAPTCHA challenges, and returns raw HTML for parsing
    by the tool layer.

    On CAPTCHA failure the manager closes the session and retries with a
    fresh browser context (up to ``MAX_SESSION_RETRIES`` times).
    """

    def __init__(self, session_config: dict | None = None):
        self._session_config = session_config or {}
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()

    async def _ensure_connected(self):
        """Ensure we have an active Browser session."""
        if self._browser and not self._browser._closed:
            return
        self._browser = await Browser.create(config=self._session_config or None)
        log.info("Created browser session: %s", self._browser.session_id)

    async def _reset_session(self):
        """Close the current session so the next call gets a fresh browser context."""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        log.info("Session reset — next attempt will use a fresh browser context")

    # ------------------------------------------------------------------
    # Public API — each method retries with fresh sessions on CAPTCHA failure
    # ------------------------------------------------------------------

    async def search_by_name(
        self,
        business_name: str | None = None,
        last_name: str | None = None,
        first_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> str:
        """Navigate to the name search form, fill it, submit, and return results HTML.

        Retries with a fresh browser session up to ``MAX_SESSION_RETRIES``
        times if CAPTCHA solving fails.
        """
        last_err: Exception | None = None
        for attempt in range(1, MAX_SESSION_RETRIES + 1):
            try:
                return await self._search_by_name_once(
                    attempt, business_name, last_name, first_name, start_date, end_date,
                )
            except NyscefSessionError as exc:
                last_err = exc
                log.warning("search_by_name attempt %d/%d failed: %s", attempt, MAX_SESSION_RETRIES, exc)
                if attempt < MAX_SESSION_RETRIES:
                    await self._reset_session()
                    await asyncio.sleep(5)
        raise NyscefSessionError(
            f"search_by_name failed after {MAX_SESSION_RETRIES} session attempts: {last_err}"
        )

    async def search_by_index(self, index_number: str) -> str:
        """Search by index number and return results HTML."""
        last_err: Exception | None = None
        for attempt in range(1, MAX_SESSION_RETRIES + 1):
            try:
                return await self._search_by_index_once(attempt, index_number)
            except NyscefSessionError as exc:
                last_err = exc
                log.warning("search_by_index attempt %d/%d failed: %s", attempt, MAX_SESSION_RETRIES, exc)
                if attempt < MAX_SESSION_RETRIES:
                    await self._reset_session()
                    await asyncio.sleep(5)
        raise NyscefSessionError(
            f"search_by_index failed after {MAX_SESSION_RETRIES} session attempts: {last_err}"
        )

    async def get_docket_page(self, docket_id: str) -> str:
        """Navigate to a docket (DocumentList) page and return its HTML."""
        last_err: Exception | None = None
        for attempt in range(1, MAX_SESSION_RETRIES + 1):
            try:
                return await self._get_docket_page_once(attempt, docket_id)
            except NyscefSessionError as exc:
                last_err = exc
                log.warning("get_docket_page attempt %d/%d failed: %s", attempt, MAX_SESSION_RETRIES, exc)
                if attempt < MAX_SESSION_RETRIES:
                    await self._reset_session()
                    await asyncio.sleep(5)
        raise NyscefSessionError(
            f"get_docket_page failed after {MAX_SESSION_RETRIES} session attempts: {last_err}"
        )

    async def close(self):
        """Close the browser session."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        log.info("NYSCEF session manager closed")

    # ------------------------------------------------------------------
    # Internal — single-attempt implementations
    # ------------------------------------------------------------------

    async def _search_by_name_once(
        self,
        attempt: int,
        business_name: str | None,
        last_name: str | None,
        first_name: str | None,
        start_date: str | None,
        end_date: str | None,
    ) -> str:
        async with self._lock:
            await self._ensure_connected()
            b = self._browser

            log.info("search_by_name session attempt %d/%d", attempt, MAX_SESSION_RETRIES)

            # Navigate to search form
            await b.goto(NYSCEF_SEARCH_URL)
            await self._handle_challenge(b, "search_form")

            t = await b.title()
            if "case search" not in t.lower():
                raise NyscefSessionError(f"Expected 'Case Search' page, got '{t}'")

            # Fill form fields
            if business_name:
                await b.fill('input[name="txtBusinessOrgName"]', business_name)
            if last_name:
                await b.fill('input[name="txtPartyLastName"]', last_name)
            if first_name:
                await b.fill('input[name="txtPartyFirstName"]', first_name)
            if start_date:
                await b.fill('input[name="txtFilingDateFrom"]', start_date)
            if end_date:
                await b.fill('input[name="txtFilingDateTo"]', end_date)

            # Submit — click and wait for navigation (results page or CAPTCHA)
            log.debug("Submitting search form")
            await b.click_and_wait_for_navigation('button[type="submit"]')

            # Handle post-submit challenge (hCaptcha typically triggers here)
            await self._handle_challenge(b, "post_submit")

            html = await b.content()
            log.debug("Search returned %d chars of HTML", len(html))
            return html

    async def _search_by_index_once(self, attempt: int, index_number: str) -> str:
        async with self._lock:
            await self._ensure_connected()
            b = self._browser

            log.info("search_by_index session attempt %d/%d", attempt, MAX_SESSION_RETRIES)

            await b.goto(NYSCEF_INDEX_SEARCH_URL)
            await self._handle_challenge(b, "index_form")

            await b.fill('input[name="txtCaseNumber"]', index_number)
            await b.click_and_wait_for_navigation('button[type="submit"]')

            await self._handle_challenge(b, "index_submit")
            return await b.content()

    async def _get_docket_page_once(self, attempt: int, docket_id: str) -> str:
        async with self._lock:
            await self._ensure_connected()
            b = self._browser

            log.info("get_docket_page session attempt %d/%d", attempt, MAX_SESSION_RETRIES)

            url = f"{NYSCEF_DOCKET_URL}?docketId={docket_id}&display=all"
            await b.goto(url)

            await self._handle_challenge(b, "docket_page")
            return await b.content()

    async def _handle_challenge(self, b: Browser, label: str):
        """Check page title and invoke solve_captcha if a challenge is detected.

        Raises NyscefSessionError if the challenge cannot be solved, which
        triggers a fresh-session retry at the caller level.
        """
        t = (await b.title()).lower()
        if "just a moment" not in t and "captcha" not in t:
            return  # No challenge

        log.info("[%s] Challenge detected (title: %s), invoking solver", label, t)
        result = await b.solve_captcha()
        log.info("[%s] Solve result: %s", label, result)

        if not result.get("solved"):
            raise NyscefSessionError(
                f"[{label}] CAPTCHA not solved: {result.get('message', 'unknown')}"
            )

        # Post-solve diagnostics: verify we actually landed on the right page
        post_title = await b.title()
        log.info("[%s] Post-solve page title: '%s'", label, post_title)
        html = await b.content()
        log.info("[%s] Post-solve HTML length: %d chars", label, len(html))
        if "captcha" in post_title.lower() or "just a moment" in post_title.lower():
            log.warning("[%s] Page still shows challenge after solver reported success!", label)
            raise NyscefSessionError(
                f"[{label}] Solver reported success but page title is still '{post_title}'"
            )
