"""
E2E tests for the adapted web/nyscef tools against the live browser service.

Uses agentbox.browser_client.Browser to hit real Chromium sessions, then
feeds the HTML through the adapted parsers and session store.

Usage:
    docker compose up --build -d
    python -m pytest test/test_tools_e2e.py -xvs --log-cli-level=INFO
"""

import logging
import os

import pytest
import pytest_asyncio

from agentbox.browser_client import Browser, BrowserError
from agentbox.tools.web.models import (
    ExtractionFormat,
    LinkItem,
    PageInfo,
    TableRow,
)
from agentbox.tools.web.html_helpers import _parse_links_from_html, _parse_table_from_html

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fixture: create + destroy a Browser session per test
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def browser():
    """Create a Browser session via the orchestrator, close after test."""
    b = await Browser.create()
    log.info("Created browser session: %s", b.session_id)
    yield b
    await b.close()
    log.info("Closed browser session: %s", b.session_id)


# ---------------------------------------------------------------------------
# Browser client basics
# ---------------------------------------------------------------------------

class TestBrowserNavigation:

    @pytest.mark.asyncio
    async def test_navigate_and_title(self, browser: Browser):
        """Navigate to example.com and verify title."""
        await browser.goto("https://example.com")
        title = await browser.title()
        log.info("Title: %s", title)
        assert "Example Domain" in title

    @pytest.mark.asyncio
    async def test_navigate_and_url(self, browser: Browser):
        """Verify URL after navigation."""
        await browser.goto("https://example.com")
        url = await browser.url()
        log.info("URL: %s", url)
        assert "example.com" in url

    @pytest.mark.asyncio
    async def test_navigate_and_content(self, browser: Browser):
        """Get full HTML content."""
        await browser.goto("https://example.com")
        html = await browser.content()
        log.info("HTML length: %d", len(html))
        assert len(html) > 100
        assert "Example Domain" in html

    @pytest.mark.asyncio
    async def test_screenshot(self, browser: Browser):
        """Take a screenshot and verify it's a valid PNG."""
        import base64

        await browser.goto("https://example.com")
        b64 = await browser.screenshot()
        png = base64.b64decode(b64)
        assert png[:4] == b"\x89PNG"
        assert len(png) > 1000
        log.info("Screenshot: %d bytes", len(png))

    @pytest.mark.asyncio
    async def test_evaluate_js(self, browser: Browser):
        """Evaluate JavaScript and return the result."""
        await browser.goto("https://example.com")
        result = await browser.evaluate("document.title")
        assert "Example Domain" in result


# ---------------------------------------------------------------------------
# Interaction: click, fill
# ---------------------------------------------------------------------------

class TestBrowserInteraction:

    @pytest.mark.asyncio
    async def test_click_link(self, browser: Browser):
        """Click the 'More information...' link on example.com → iana.org."""
        await browser.goto("https://example.com")
        await browser.click("a")
        # Wait a moment for navigation
        import asyncio
        await asyncio.sleep(2)
        url = await browser.url()
        log.info("After click, URL: %s", url)
        assert "iana.org" in url

    @pytest.mark.asyncio
    async def test_fill_input(self, browser: Browser):
        """Inject an input, fill it, verify the value."""
        await browser.goto("https://example.com")
        # Inject an input
        await browser.evaluate(
            'document.body.innerHTML = \'<input id="q" type="text" />\'; "ok"'
        )
        await browser.fill("#q", "hello from agentbox")
        value = await browser.evaluate('document.querySelector("#q").value')
        log.info("Input value: %s", value)
        assert value == "hello from agentbox"


# ---------------------------------------------------------------------------
# HTML helpers on real pages
# ---------------------------------------------------------------------------

class TestHtmlHelpersLive:

    @pytest.mark.asyncio
    async def test_parse_links_from_live_page(self, browser: Browser):
        """Extract links from example.com HTML."""
        await browser.goto("https://example.com")
        html = await browser.content()
        links = _parse_links_from_html(html)
        log.info("Found %d links", len(links))
        assert len(links) >= 1
        hrefs = [l.href for l in links]
        log.info("Links: %s", hrefs)
        assert any("iana.org" in h for h in hrefs)

    @pytest.mark.asyncio
    async def test_parse_table_from_live_page(self, browser: Browser):
        """Inject a table into the page, then parse it."""
        await browser.goto("https://example.com")
        await browser.evaluate("""
            document.body.innerHTML = `
            <table>
              <tr><th>Name</th><th>Value</th></tr>
              <tr><td>Alpha</td><td>1</td></tr>
              <tr><td>Beta</td><td>2</td></tr>
            </table>`;
            "ok"
        """)
        html = await browser.content()
        rows = _parse_table_from_html(html)
        log.info("Parsed %d rows", len(rows))
        assert len(rows) == 2
        assert rows[0].values["Name"] == "Alpha"
        assert rows[1].values["Value"] == "2"

    @pytest.mark.asyncio
    async def test_extract_text_from_live_page(self, browser: Browser):
        """Get visible text via evaluate (same as WebExtractTool text mode)."""
        await browser.goto("https://example.com")
        text = await browser.evaluate(
            "document.body ? document.body.innerText.substring(0, 2000) : ''"
        )
        log.info("Text (first 200): %s", text[:200])
        assert "Example Domain" in text


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------

class TestSessionStore:

    @pytest.mark.asyncio
    async def test_get_and_close_browser(self):
        """Test the session store get_browser / close_browser cycle."""
        from agentbox.tools.web.session_store import get_browser, close_browser, has_active_session

        assert not has_active_session()

        b = await get_browser()
        log.info("Session store created session: %s", b.session_id)
        assert has_active_session()

        # Second call should return the same instance
        b2 = await get_browser()
        assert b2.session_id == b.session_id

        # Navigate to verify it works
        await b.goto("https://example.com")
        title = await b.title()
        assert "Example Domain" in title

        # Close
        sid = await close_browser()
        assert sid == b.session_id
        assert not has_active_session()
        log.info("Session store closed session: %s", sid)


# ---------------------------------------------------------------------------
# Multi-step workflow
# ---------------------------------------------------------------------------

class TestMultiStepWorkflow:

    @pytest.mark.asyncio
    async def test_navigate_extract_links_follow(self, browser: Browser):
        """Navigate → extract links → follow first link."""
        # Step 1: Navigate
        await browser.goto("https://example.com")
        title = await browser.title()
        assert "Example Domain" in title

        # Step 2: Extract links
        html = await browser.content()
        links = _parse_links_from_html(html)
        assert len(links) >= 1
        target = links[0].href
        log.info("Following link: %s", target)

        # Step 3: Follow the link
        await browser.goto(target)
        import asyncio
        await asyncio.sleep(1)
        new_url = await browser.url()
        new_title = await browser.title()
        log.info("Landed on: %s — %s", new_url, new_title)
        assert new_url != "https://example.com/"
