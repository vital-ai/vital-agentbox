"""
Web Close Tool — explicitly close the active browser session.

"""

import logging
from collections.abc import Callable

from kgraphplanner.tool_manager.tool_inf import AbstractTool
from langchain_core.tools import tool
from pydantic import BaseModel

from agentbox.tools.web.models import WebCloseInput, WebCloseOutput
from agentbox.tools.web.session_store import close_browser, has_active_session

log = logging.getLogger(__name__)


class WebCloseTool(AbstractTool):

    def __init__(self, config=None, tool_manager=None):
        super().__init__(
            config=config or {},
            tool_manager=tool_manager,
            name="web_close",
            description="Close the active browser session to free resources. Call when finished browsing.",
        )

    def get_tool_schema(self) -> type[BaseModel]:
        return WebCloseInput

    def get_tool_function(self) -> Callable:

        @tool(args_schema=WebCloseInput)
        async def web_close(
            reason: str | None = None,
        ) -> WebCloseOutput:
            """Close the active browser session to free resources."""
            if not has_active_session():
                return WebCloseOutput(
                    closed=False,
                    error="No active browser session to close.",
                )

            try:
                if reason:
                    log.info("Closing browser session: %s", reason)
                session_id = await close_browser()
                return WebCloseOutput(
                    session_id=session_id,
                    closed=True,
                )
            except Exception as exc:
                log.error("web_close failed: %s", exc, exc_info=True)
                return WebCloseOutput(error=str(exc))

        return web_close
