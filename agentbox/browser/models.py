"""
Request/response models for the browser WebSocket and REST APIs.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --- WebSocket message models ---

class BrowserAction(str, Enum):
    """Actions the client can request over WebSocket."""
    NAVIGATE = "navigate"
    FILL = "fill"
    CLICK = "click"
    SELECT = "select"
    GET_CONTENT = "get_content"
    GET_TITLE = "get_title"
    GET_URL = "get_url"
    WAIT = "wait"
    WAIT_FOR_SELECTOR = "wait_for_selector"
    WAIT_FOR_LOAD_STATE = "wait_for_load_state"
    CLICK_AND_WAIT = "click_and_wait"
    SOLVE_CAPTCHA = "solve_captcha"
    SCREENSHOT = "screenshot"
    EVALUATE = "evaluate"
    CLOSE = "close"


class BrowserCommand(BaseModel):
    """A command sent from client to browser worker over WebSocket."""
    action: BrowserAction
    url: str | None = None
    selector: str | None = None
    value: str | None = None
    timeout: int | None = None
    wait_until: str | None = None
    state: str | None = None
    expression: str | None = None
    options: dict[str, Any] | None = None


class ResponseStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    INFO = "info"


class PageState(BaseModel):
    """Current page URL, title, and content fingerprint — included in every response."""
    url: str = ""
    title: str = ""
    html_length: int = 0
    content_hash: str = ""


class BrowserResponse(BaseModel):
    """A response sent from browser worker to client over WebSocket."""
    status: ResponseStatus
    data: Any | None = None
    message: str | None = None
    action: str | None = None
    page: PageState | None = None


# --- Session configuration ---

class ProxyConfig(BaseModel):
    """Proxy configuration for a browser session."""
    server: str = Field(..., description="Proxy server URL (e.g. 'http://proxy:8080', 'socks5://proxy:1080')")
    username: str | None = Field(default=None, description="Proxy username")
    password: str | None = Field(default=None, description="Proxy password")


class SessionConfig(BaseModel):
    """Configuration provided at session creation time."""
    browser_type: str = Field(default="chrome", description="Browser engine: 'chrome' or 'camoufox'")
    headless: bool = Field(default=True, description="Run browser in headless mode (set False for Xvfb)")
    use_system_chrome: bool = Field(default=False, description="Use system Chrome (channel='chrome') vs Playwright bundled Chromium")
    proxy: ProxyConfig | None = Field(default=None, description="Proxy to use (omit for direct connection)")
    viewport_width: int = Field(default=1280, description="Browser viewport width", ge=320, le=3840)
    viewport_height: int = Field(default=720, description="Browser viewport height", ge=240, le=2160)
    user_agent: str | None = Field(default=None, description="Custom User-Agent string (omit for Chrome default)")
    locale: str | None = Field(default=None, description="Browser locale (e.g. 'en-US')")
    timezone_id: str | None = Field(default=None, description="Timezone (e.g. 'America/New_York')")
    extra_args: list[str] = Field(default_factory=list, description="Additional Chrome launch arguments")
    geolocation: dict[str, float] | None = Field(
        default=None, description="Geolocation override {latitude, longitude, accuracy}"
    )


# --- REST models ---

class SessionInfo(BaseModel):
    """Information about an active browser session."""
    session_id: str
    created_at: str
    request_count: int = 0
    idle_seconds: float = 0.0
    config: SessionConfig | None = None


class CreateBrowserRequest(BaseModel):
    """Request body for POST /browsers (or /internal/browsers)."""
    config: SessionConfig | None = None


class ServiceStatus(BaseModel):
    """Overall browser worker status."""
    healthy: bool = True
    active_sessions: int = 0
    max_sessions: int = 3
    sessions: list[SessionInfo] = Field(default_factory=list)
