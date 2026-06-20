"""
Web Extract Tool — extract content from the current page in various formats.

"""

import logging
from collections.abc import Callable

from kgraphplanner.tool_manager.tool_inf import AbstractTool
from langchain_core.tools import tool
from pydantic import BaseModel

from agentbox.tools.web.models import (
    ExtractionFormat,
    PageInfo,
    WebExtractInput,
    WebExtractOutput,
)
from agentbox.tools.web.html_helpers import _parse_links_from_html, _parse_table_from_html  # noqa: F401
from agentbox.tools.web.session_store import get_browser, has_active_session

log = logging.getLogger(__name__)


class WebExtractTool(AbstractTool):

    def __init__(self, config=None, tool_manager=None):
        super().__init__(
            config=config or {},
            tool_manager=tool_manager,
            name="web_extract",
            description="Extract content from the current web page as text, HTML, table data, links, or a screenshot. Requires an active browser session from web_navigate.",
        )

    def get_tool_schema(self) -> type[BaseModel]:
        return WebExtractInput

    def get_tool_function(self) -> Callable:

        @tool(args_schema=WebExtractInput)
        async def web_extract(
            selector: str | None = None,
            format: ExtractionFormat = ExtractionFormat.TEXT,
            max_length: int = 4000,
        ) -> WebExtractOutput:
            """Extract content from the current web page as text, HTML, table data, links, or a screenshot."""
            if not has_active_session():
                return WebExtractOutput(
                    error="No active browser session. Use web_navigate first.",
                )

            try:
                b = await get_browser()

                # Get page info
                title = await b.title()
                current_url = await b.url()
                page = PageInfo(
                    title=title,
                    url=current_url,
                    session_id=b.session_id,
                )

                # Screenshot format
                if format == ExtractionFormat.SCREENSHOT:
                    ss_b64 = await b.screenshot()
                    return WebExtractOutput(
                        page=page,
                        screenshot_base64=ss_b64,
                    )

                # Get HTML content
                if selector:
                    html = await b.evaluate(
                        f"(() => {{"
                        f"  const el = document.querySelector('{selector}');"
                        f"  return el ? el.outerHTML : null;"
                        f"}})()"
                    )
                    if html is None:
                        return WebExtractOutput(
                            page=page,
                            error=f"Selector '{selector}' not found on page",
                        )
                else:
                    html = await b.content()

                # Format-specific extraction
                if format == ExtractionFormat.HTML:
                    truncated = len(html) > max_length
                    return WebExtractOutput(
                        page=page,
                        content=html[:max_length],
                        truncated=truncated,
                    )

                if format == ExtractionFormat.LINKS:
                    links = _parse_links_from_html(html)
                    return WebExtractOutput(
                        page=page,
                        links=links,
                    )

                if format == ExtractionFormat.TABLE:
                    table = _parse_table_from_html(html)
                    return WebExtractOutput(
                        page=page,
                        table=table,
                    )

                # Default: text
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                text = soup.get_text(separator="\n", strip=True)
                truncated = len(text) > max_length
                return WebExtractOutput(
                    page=page,
                    content=text[:max_length],
                    truncated=truncated,
                )

            except Exception as exc:
                log.error("web_extract failed: %s", exc, exc_info=True)
                return WebExtractOutput(error=str(exc))

        return web_extract
