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
from agentbox.tools.nyscef.html_parser import (
    SEARCH_CHALLENGE,
    SEARCH_RESULTS,
    classify_search_page,
    parse_pagination,
)

log = logging.getLogger(__name__)

NYSCEF_BASE = "https://iapps.courts.state.ny.us/nyscef"
NYSCEF_SEARCH_URL = f"{NYSCEF_BASE}/CaseSearch?TAB=name"
NYSCEF_INDEX_SEARCH_URL = f"{NYSCEF_BASE}/CaseSearch?TAB=caseIdentifier"
NYSCEF_DOCKET_URL = f"{NYSCEF_BASE}/DocumentList"
NYSCEF_CASE_DETAILS_URL = f"{NYSCEF_BASE}/CaseDetails"
NYSCEF_RESULTS_PAGE_URL = f"{NYSCEF_BASE}/CaseSearchResults?PageNum={{page}}"
MAX_RESULT_PAGES = 10

# Every field of the party search form: all are written on every search, empty when not asked for, because the form
# keeps the previous search's values (a person search after a business search is rejected otherwise).
NAME_FORM_FIELDS = {
    "business_name": 'input[name="txtBusinessOrgName"]',
    "last_name": 'input[name="txtPartyLastName"]',
    "first_name": 'input[name="txtPartyFirstName"]',
    "start_date": 'input[name="txtFilingDateFrom"]',
    "end_date": 'input[name="txtFilingDateTo"]',
}


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

    def __init__(self, session_config: dict | None = None, orchestrator_url: str | None = None,
                 auth_token: str | None = None):
        """``orchestrator_url`` / ``auth_token``: passed to ``Browser.create`` (native runtime); default to the
        ``AGENTBOX_ORCHESTRATOR_URL`` / ``AGENTBOX_AUTH_TOKEN`` environment."""
        self._session_config = session_config or {}
        self._orchestrator_url = orchestrator_url
        self._auth_token = auth_token
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()

    async def _ensure_connected(self):
        """Ensure we have an active Browser session."""
        if self._browser and not self._browser._closed:
            return
        self._browser = await Browser.create(config=self._session_config or None,
                                             orchestrator_url=self._orchestrator_url, auth_token=self._auth_token)
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
        """Navigate to the name search form, fill it, submit, and return the first results page's HTML.

        Retries with a fresh browser session up to ``MAX_SESSION_RETRIES`` times if CAPTCHA solving fails or the
        search doesn't land on a results page. See ``search_pages`` for more than the first page.
        """
        return (await self.search_pages(business_name, last_name, first_name, start_date, end_date))[0]

    async def search_pages(
        self,
        business_name: str | None = None,
        last_name: str | None = None,
        first_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        max_pages: int = 1,
    ) -> list[str]:
        """The name search's results pages (25 rows each), up to ``max_pages``: always at least the first.

        Every page returned is a recognised results page (``classify_search_page``); a challenge, a rejected form or
        an unknown page raises ``NyscefSessionError`` after the retries, never reads as "nothing found".
        """
        max_pages = max(1, min(int(max_pages or 1), MAX_RESULT_PAGES))
        last_err: Exception | None = None
        for attempt in range(1, MAX_SESSION_RETRIES + 1):
            try:
                return await self._search_by_name_once(
                    attempt, business_name, last_name, first_name, start_date, end_date, max_pages,
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

    async def get_case_details_page(self, docket_id: str) -> str:
        """Navigate to a case's CaseDetails page (parties, full caption) and return its HTML."""
        last_err: Exception | None = None
        for attempt in range(1, MAX_SESSION_RETRIES + 1):
            try:
                return await self._get_page_once(
                    attempt, f"{NYSCEF_CASE_DETAILS_URL}?docketId={docket_id}", "case_details_page")
            except NyscefSessionError as exc:
                last_err = exc
                log.warning("get_case_details_page attempt %d/%d failed: %s", attempt, MAX_SESSION_RETRIES, exc)
                if attempt < MAX_SESSION_RETRIES:
                    await self._reset_session()
                    await asyncio.sleep(5)
        raise NyscefSessionError(
            f"get_case_details_page failed after {MAX_SESSION_RETRIES} session attempts: {last_err}"
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
        max_pages: int = 1,
    ) -> list[str]:
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

            # Fill every field, clearing those not asked for: the form keeps the previous search's values.
            values = {"business_name": business_name, "last_name": last_name, "first_name": first_name,
                      "start_date": start_date, "end_date": end_date}
            for key, selector in NAME_FORM_FIELDS.items():
                await b.fill(selector, values[key] or "")

            # Submit — click and wait for navigation (results page or CAPTCHA)
            log.debug("Submitting search form")
            await b.click_and_wait_for_navigation('button[type="submit"]')

            # Handle post-submit challenge (hCaptcha typically triggers here)
            await self._handle_challenge(b, "post_submit")

            pages = [await self._results_page(b, "post_submit")]
            _, last = parse_pagination(pages[0])
            for page in range(2, min(last, max_pages) + 1):
                await b.goto(NYSCEF_RESULTS_PAGE_URL.format(page=page))
                await self._handle_challenge(b, f"results_page_{page}")
                pages.append(await self._results_page(b, f"results_page_{page}"))
            log.debug("Search returned %d page(s) of %d", len(pages), last)
            return pages

    async def _results_page(self, b: Browser, label: str) -> str:
        """The current page's HTML when it's a results page; else ``NyscefSessionError`` (retried)."""
        html = await b.content()
        kind = classify_search_page(html)
        if kind != SEARCH_RESULTS:
            raise NyscefSessionError(f"[{label}] not a results page: {kind}")
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
            return await self._results_page(b, "index_submit")

    async def _get_docket_page_once(self, attempt: int, docket_id: str) -> str:
        return await self._get_page_once(
            attempt, f"{NYSCEF_DOCKET_URL}?docketId={docket_id}&display=all", "docket_page")

    async def _get_page_once(self, attempt: int, url: str, label: str) -> str:
        async with self._lock:
            await self._ensure_connected()
            b = self._browser

            log.info("%s session attempt %d/%d", label, attempt, MAX_SESSION_RETRIES)

            await b.goto(url)
            await self._handle_challenge(b, label)
            return await b.content()

    async def _handle_challenge(self, b: Browser, label: str):
        """Check page title and invoke solve_captcha if a challenge is detected.

        Raises NyscefSessionError if the challenge cannot be solved, which
        triggers a fresh-session retry at the caller level.
        """
        t = (await b.title()).lower()
        if "just a moment" not in t and "captcha" not in t \
                and classify_search_page(await b.content()) != SEARCH_CHALLENGE:
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
