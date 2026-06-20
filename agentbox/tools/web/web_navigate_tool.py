"""
Web Navigate Tool — navigate to a URL, handle CAPTCHAs, return page summary.

"""

import logging
from collections.abc import Callable

from kgraphplanner.tool_manager.tool_inf import AbstractTool
from langchain_core.tools import tool
from pydantic import BaseModel

from agentbox.tools.web.models import (
    CaptchaInfo,
    PageInfo,
    WebNavigateInput,
    WebNavigateOutput,
)
from agentbox.tools.web.session_store import get_browser

log = logging.getLogger(__name__)


class WebNavigateTool(AbstractTool):

    def __init__(self, config=None, tool_manager=None):
        super().__init__(
            config=config or {},
            tool_manager=tool_manager,
            name="web_navigate",
            description="Navigate to a URL in a browser session. Handles Cloudflare and CAPTCHA challenges automatically.",
        )

    def get_tool_schema(self) -> type[BaseModel]:
        return WebNavigateInput

    def get_tool_function(self) -> Callable:

        @tool(args_schema=WebNavigateInput)
        async def web_navigate(
            url: str,
            wait_for: str | None = None,
        ) -> WebNavigateOutput:
            """Navigate to a URL in a browser session. Handles Cloudflare and CAPTCHA challenges automatically."""
            try:
                b = await get_browser()

                # Navigate
                await b.goto(url)

                # Wait for a specific element if requested
                if wait_for:
                    await b.evaluate(
                        f"await new Promise(r => {{"
                        f"  const i = setInterval(() => {{"
                        f"    if (document.querySelector('{wait_for}')) {{ clearInterval(i); r(); }}"
                        f"  }}, 100);"
                        f"  setTimeout(() => {{ clearInterval(i); r(); }}, 15000);"
                        f"}})"
                    )

                # Check for CAPTCHA challenges
                captcha = CaptchaInfo()
                title = await b.title()
                if title and ("just a moment" in title.lower() or "captcha" in title.lower()):
                    captcha.captcha_encountered = True
                    solve_result = await b.solve_captcha()
                    if isinstance(solve_result, dict):
                        captcha.captcha_solved = solve_result.get("solved", False)
                        captcha.captcha_method = solve_result.get("method")
                    # Re-read title after solve
                    title = await b.title()

                # Get page URL
                final_url = await b.url()

                # Get visible text (first ~2000 chars)
                page_text = await b.evaluate(
                    "document.body ? document.body.innerText.substring(0, 2000) : ''"
                )

                return WebNavigateOutput(
                    page=PageInfo(
                        title=title,
                        url=final_url,
                        session_id=b.session_id,
                    ),
                    page_text=page_text,
                    captcha=captcha,
                )

            except Exception as exc:
                log.error("web_navigate failed: %s", exc, exc_info=True)
                return WebNavigateOutput(error=str(exc))

        return web_navigate
