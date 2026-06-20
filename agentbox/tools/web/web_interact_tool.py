"""
Web Interact Tool — fill forms, click buttons, select options on the current page.

"""

import logging
from collections.abc import Callable

from kgraphplanner.tool_manager.tool_inf import AbstractTool
from langchain_core.tools import tool
from pydantic import BaseModel

from agentbox.tools.web.models import (
    CaptchaInfo,
    InteractionType,
    PageInfo,
    WebAction,
    WebInteractInput,
    WebInteractOutput,
)
from agentbox.tools.web.session_store import get_browser, has_active_session

log = logging.getLogger(__name__)


class WebInteractTool(AbstractTool):

    def __init__(self, config=None, tool_manager=None):
        super().__init__(
            config=config or {},
            tool_manager=tool_manager,
            name="web_interact",
            description="Interact with a web page: fill forms, click buttons, select options. Requires an active browser session from web_navigate.",
        )

    def get_tool_schema(self) -> type[BaseModel]:
        return WebInteractInput

    def get_tool_function(self) -> Callable:

        @tool(args_schema=WebInteractInput)
        async def web_interact(
            actions: list[WebAction],
            submit: bool = False,
        ) -> WebInteractOutput:
            """Interact with a web page: fill forms, click buttons, select options."""
            if not has_active_session():
                return WebInteractOutput(
                    error="No active browser session. Use web_navigate first.",
                )

            try:
                b = await get_browser()
                completed = 0
                last_fill_selector = None

                for action in actions:
                    try:
                        if action.action == InteractionType.FILL:
                            await b.fill(action.selector, action.value or "")
                            last_fill_selector = action.selector
                        elif action.action == InteractionType.CLICK:
                            await b.click(action.selector)
                        elif action.action == InteractionType.SELECT:
                            await b.select(action.selector, action.value or "")
                        elif action.action == InteractionType.CHECK:
                            await b.click(action.selector)
                        elif action.action == InteractionType.WAIT:
                            timeout = action.timeout or 10000
                            await b.evaluate(
                                f"await new Promise(r => {{"
                                f"  const i = setInterval(() => {{"
                                f"    if (document.querySelector('{action.selector}')) {{ clearInterval(i); r(); }}"
                                f"  }}, 100);"
                                f"  setTimeout(() => {{ clearInterval(i); r(); }}, {timeout});"
                                f"}})"
                            )
                        else:
                            continue
                    except Exception as action_exc:
                        return WebInteractOutput(
                            actions_completed=completed,
                            error=f"Action {completed + 1} ({action.action}) failed: {action_exc}",
                        )
                    completed += 1

                # Submit: press Enter on the last filled field
                if submit and last_fill_selector:
                    await b.evaluate(
                        f"document.querySelector('{last_fill_selector}')?.form?.submit()"
                    )
                    import asyncio
                    await asyncio.sleep(3)

                # Check for CAPTCHA after interactions
                captcha = CaptchaInfo()
                title = await b.title()
                if title and ("just a moment" in title.lower() or "captcha" in title.lower()):
                    captcha.captcha_encountered = True
                    solve_result = await b.solve_captcha()
                    if isinstance(solve_result, dict):
                        captcha.captcha_solved = solve_result.get("solved", False)
                        captcha.captcha_method = solve_result.get("method")
                    title = await b.title()

                final_url = await b.url()
                page_text = await b.evaluate(
                    "document.body ? document.body.innerText.substring(0, 2000) : ''"
                )

                return WebInteractOutput(
                    page=PageInfo(
                        title=title,
                        url=final_url,
                        session_id=b.session_id,
                    ),
                    page_text=page_text,
                    captcha=captcha,
                    actions_completed=completed,
                )

            except Exception as exc:
                log.error("web_interact failed: %s", exc, exc_info=True)
                return WebInteractOutput(error=str(exc))

        return web_interact
