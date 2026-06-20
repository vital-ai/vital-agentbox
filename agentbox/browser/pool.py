"""
Session pool — manages multiple concurrent browser sessions.

Enforces a max session limit, handles idle timeout cleanup,
and provides session lifecycle management.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from playwright.async_api import Playwright, async_playwright

from agentbox.browser.session import BrowserSession
from agentbox.browser.models import SessionConfig

log = logging.getLogger(__name__)

MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "3"))
IDLE_TIMEOUT = int(os.getenv("SESSION_IDLE_TIMEOUT", "300"))  # seconds


class SessionPoolFull(Exception):
    """Raised when the pool cannot create a new session."""


class SessionNotFound(Exception):
    """Raised when a session ID is not found."""


class SessionPool:
    """Pool of browser sessions sharing one Playwright instance."""

    def __init__(self, max_sessions: int | None = None, idle_timeout: int | None = None):
        self._max_sessions = max_sessions or MAX_SESSIONS
        self._idle_timeout = idle_timeout or IDLE_TIMEOUT
        self._sessions: dict[str, BrowserSession] = {}
        self._playwright: Playwright | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self):
        """Start the Playwright instance and background cleanup task."""
        log.info("Starting session pool (max=%d, idle_timeout=%ds)", self._max_sessions, self._idle_timeout)
        self._playwright = await async_playwright().start()
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self):
        """Close all sessions and stop Playwright."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        async with self._lock:
            for session in list(self._sessions.values()):
                await session.close()
            self._sessions.clear()

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        log.info("Session pool stopped")

    async def create_session(
        self, session_id: str | None = None, config: SessionConfig | None = None
    ) -> BrowserSession:
        """Create a new browser session. Raises SessionPoolFull if at capacity."""
        async with self._lock:
            if len(self._sessions) >= self._max_sessions:
                raise SessionPoolFull(
                    f"Pool full: {len(self._sessions)}/{self._max_sessions} sessions active"
                )
            session = BrowserSession(session_id=session_id, config=config)
            await session.start(self._playwright)
            self._sessions[session.session_id] = session
            log.info("Session created: %s (%d/%d)", session.session_id, len(self._sessions), self._max_sessions)
            return session

    async def get_session(self, session_id: str) -> BrowserSession:
        """Get an existing session by ID. Raises SessionNotFound if not found."""
        session = self._sessions.get(session_id)
        if not session:
            raise SessionNotFound(f"Session not found: {session_id}")
        return session

    async def close_session(self, session_id: str):
        """Close and remove a session."""
        async with self._lock:
            session = self._sessions.pop(session_id, None)
            if session:
                await session.close()
                log.info("Session closed: %s (%d/%d)", session_id, len(self._sessions), self._max_sessions)
            else:
                raise SessionNotFound(f"Session not found: {session_id}")

    def list_sessions(self) -> list[dict]:
        """Return info about all active sessions."""
        now = time.time()
        return [
            {
                "session_id": s.session_id,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(s.created_at)),
                "request_count": s.request_count,
                "idle_seconds": round(now - s.last_activity, 1),
                "config": s.config,
            }
            for s in self._sessions.values()
        ]

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    @property
    def max_sessions(self) -> int:
        return self._max_sessions

    async def _cleanup_loop(self):
        """Periodically close idle sessions."""
        while True:
            await asyncio.sleep(30)
            try:
                await self._cleanup_idle()
            except Exception as exc:
                log.warning("Cleanup error: %s", exc)

    async def _cleanup_idle(self):
        """Close sessions that have been idle longer than the timeout."""
        now = time.time()
        to_close = [
            sid for sid, s in self._sessions.items()
            if (now - s.last_activity) > self._idle_timeout
        ]
        for sid in to_close:
            log.info("Closing idle session %s (idle %.0fs)", sid, now - self._sessions[sid].last_activity)
            try:
                await self.close_session(sid)
            except SessionNotFound:
                pass
