"""
Pydantic models for the generic web browsing tools.

Defines inputs and outputs for web_navigate, web_interact, web_extract,
and web_close tools.

"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# --- Shared / common ---

class PageInfo(BaseModel):
    """Common page state returned by most web tools."""
    title: str | None = None
    url: str | None = None
    session_id: str | None = None


class CaptchaInfo(BaseModel):
    """CAPTCHA encounter details."""
    captcha_encountered: bool = False
    captcha_solved: bool = False
    captcha_method: str | None = None


# --- web_navigate ---

class WebNavigateInput(BaseModel):
    """Input for the web_navigate tool."""
    url: str = Field(..., description="URL to navigate to")
    wait_for: str | None = Field(
        default=None,
        description="Optional CSS selector to wait for after page load",
    )

class WebNavigateOutput(BaseModel):
    """Output from the web_navigate tool."""
    tool: str = "web_navigate"
    page: PageInfo = Field(default_factory=PageInfo)
    page_text: str | None = Field(
        default=None,
        description="First ~2000 chars of visible page text",
    )
    captcha: CaptchaInfo = Field(default_factory=CaptchaInfo)
    error: str | None = None


# --- web_interact ---

class InteractionType(str, Enum):
    FILL = "fill"
    CLICK = "click"
    SELECT = "select"
    CHECK = "check"
    WAIT = "wait"

class WebAction(BaseModel):
    """A single browser interaction."""
    action: InteractionType = Field(..., description="Type of interaction")
    selector: str = Field(..., description="CSS selector for the target element")
    value: str | None = Field(
        default=None,
        description="Value for fill/select actions",
    )
    timeout: int | None = Field(
        default=None,
        description="Timeout in ms for wait actions",
    )

class WebInteractInput(BaseModel):
    """Input for the web_interact tool."""
    actions: list[WebAction] = Field(
        ...,
        description="Ordered list of interactions to perform",
    )
    submit: bool = Field(
        default=False,
        description="If true, press Enter after the last fill action to submit",
    )

class WebInteractOutput(BaseModel):
    """Output from the web_interact tool."""
    tool: str = "web_interact"
    page: PageInfo = Field(default_factory=PageInfo)
    page_text: str | None = Field(
        default=None,
        description="First ~2000 chars of visible page text after interactions",
    )
    captcha: CaptchaInfo = Field(default_factory=CaptchaInfo)
    actions_completed: int = 0
    error: str | None = None


# --- web_extract ---

class ExtractionFormat(str, Enum):
    TEXT = "text"
    HTML = "html"
    TABLE = "table"
    LINKS = "links"
    SCREENSHOT = "screenshot"

class WebExtractInput(BaseModel):
    """Input for the web_extract tool."""
    selector: str | None = Field(
        default=None,
        description="CSS selector to extract from (None = full page body)",
    )
    format: ExtractionFormat = Field(
        default=ExtractionFormat.TEXT,
        description="Extraction format: text, html, table, links, or screenshot",
    )
    max_length: int = Field(
        default=4000,
        description="Max character length for text/html output",
        ge=100,
        le=50000,
    )

class LinkItem(BaseModel):
    """A single extracted link."""
    text: str | None = None
    href: str | None = None

class TableRow(BaseModel):
    """A single row from an extracted table, as key-value pairs."""
    values: dict[str, str | None] = Field(default_factory=dict)

class WebExtractOutput(BaseModel):
    """Output from the web_extract tool."""
    tool: str = "web_extract"
    page: PageInfo = Field(default_factory=PageInfo)
    content: str | None = Field(
        default=None,
        description="Extracted text or HTML content",
    )
    links: list[LinkItem] | None = Field(
        default=None,
        description="Extracted links (when format=links)",
    )
    table: list[TableRow] | None = Field(
        default=None,
        description="Extracted table rows (when format=table)",
    )
    screenshot_base64: str | None = Field(
        default=None,
        description="Base64 PNG screenshot (when format=screenshot)",
    )
    truncated: bool = False
    error: str | None = None


# --- web_close ---

class WebCloseInput(BaseModel):
    """Input for the web_close tool."""
    reason: str | None = Field(
        default=None,
        description="Optional reason for closing the session (for logging)",
    )

class WebCloseOutput(BaseModel):
    """Output from the web_close tool."""
    tool: str = "web_close"
    session_id: str | None = None
    closed: bool = False
    error: str | None = None
