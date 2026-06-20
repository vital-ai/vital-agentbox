"""
Singleton session store for the generic web browsing tools.

Manages a single Browser instance that is shared across
web_navigate, web_interact, web_extract, and web_close tool calls.
The session opens on the first navigate call and stays open until
explicitly closed via web_close.

"""

from __future__ import annotations

import asyncio
import logging

from agentbox.browser_client import Browser

log = logging.getLogger(__name__)

# Module-level singleton
_browser: Browser | None = None
_lock = asyncio.Lock()


async def get_browser() -> Browser:
    """Get or create the shared Browser session.

    If no browser exists or the current one is closed, a new
    session is created.
    """
    global _browser

    async with _lock:
        if _browser is not None and not _browser._closed:
            return _browser

        _browser = await Browser.create()
        log.info("Created browser session: %s", _browser.session_id)
        return _browser


async def close_browser() -> str | None:
    """Close the shared Browser session and return the session ID that was closed.

    Returns None if no session was active.
    """
    global _browser

    async with _lock:
        if _browser is None:
            return None
        session_id = _browser.session_id
        try:
            await _browser.close()
        except Exception as exc:
            log.warning("Error closing browser: %s", exc)
        _browser = None
        return session_id


def has_active_session() -> bool:
    """Check whether there is an active browser session."""
    return _browser is not None and not _browser._closed
