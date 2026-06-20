"""
NYSCEF Case Detail Tool — get detailed information for a specific NYSCEF case
by its docket ID, including parties and docket entries (filings).

Uses the agentbox Browser client to navigate NYSCEF, handle
Cloudflare/hCaptcha challenges, and parse the docket page.

"""

import logging
from collections.abc import Callable

from kgraphplanner.tool_manager.tool_inf import AbstractTool
from langchain_core.tools import tool
from pydantic import BaseModel

from agentbox.tools.nyscef.html_parser import parse_case_detail
from agentbox.tools.nyscef.models import (
    NyscefCaseDetailInput,
    NyscefCaseDetailOutput,
)
from agentbox.tools.nyscef.session_manager import NyscefSessionManager

log = logging.getLogger(__name__)


class NyscefCaseDetailTool(AbstractTool):

    def __init__(self, session_manager: NyscefSessionManager, config=None, tool_manager=None):
        self._session = session_manager
        super().__init__(
            config=config or {},
            tool_manager=tool_manager,
            name="nyscef_case_detail_tool",
            description="Get detailed information for a specific NYSCEF case by docket ID",
        )

    def get_tool_schema(self) -> type[BaseModel]:
        return NyscefCaseDetailInput

    def get_tool_function(self) -> Callable:
        session = self._session

        @tool(args_schema=NyscefCaseDetailInput)
        async def nyscef_case_detail_tool(
            docket_id: str,
            include_filings: bool = True,
        ) -> NyscefCaseDetailOutput:
            """Get detailed information for a specific NYSCEF case by docket ID."""
            try:
                html = await session.get_docket_page(docket_id)
                case = parse_case_detail(html, docket_id=docket_id)

                if not include_filings:
                    case.docket_entries = []

                return NyscefCaseDetailOutput(
                    tool="nyscef_case_detail_tool",
                    case=case,
                )

            except Exception as exc:
                log.error("NYSCEF case detail failed: %s", exc, exc_info=True)
                return NyscefCaseDetailOutput(
                    tool="nyscef_case_detail_tool",
                    error=str(exc),
                )

        return nyscef_case_detail_tool
