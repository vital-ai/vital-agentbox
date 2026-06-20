"""
NYSCEF Case Search Tool — search the New York State Courts Electronic Filing
system by party name, business name, or index number.

Uses the agentbox Browser client to navigate NYSCEF, handle
Cloudflare/hCaptcha challenges, and parse search results.

"""

import logging
from collections.abc import Callable

from kgraphplanner.tool_manager.tool_inf import AbstractTool
from langchain_core.tools import tool
from pydantic import BaseModel

from agentbox.tools.nyscef.html_parser import parse_result_count, parse_search_results
from agentbox.tools.nyscef.models import (
    NyscefCaseSearchInput,
    NyscefCaseSearchOutput,
)
from agentbox.tools.nyscef.session_manager import NyscefSessionManager

log = logging.getLogger(__name__)


class NyscefCaseSearchTool(AbstractTool):

    def __init__(self, session_manager: NyscefSessionManager, config=None, tool_manager=None):
        self._session = session_manager
        super().__init__(
            config=config or {},
            tool_manager=tool_manager,
            name="nyscef_case_search_tool",
            description="Search NYSCEF for court cases by party name, business name, or index number",
        )

    def get_tool_schema(self) -> type[BaseModel]:
        return NyscefCaseSearchInput

    def get_tool_function(self) -> Callable:
        session = self._session

        @tool(args_schema=NyscefCaseSearchInput)
        async def nyscef_case_search_tool(
            business_name: str | None = None,
            last_name: str | None = None,
            first_name: str | None = None,
            index_number: str | None = None,
            start_date: str | None = None,
            end_date: str | None = None,
        ) -> NyscefCaseSearchOutput:
            """Search NYSCEF for court cases by party name, business name, or index number."""
            try:
                if index_number:
                    html = await session.search_by_index(index_number)
                elif business_name or last_name:
                    html = await session.search_by_name(
                        business_name=business_name,
                        last_name=last_name,
                        first_name=first_name,
                        start_date=start_date,
                        end_date=end_date,
                    )
                else:
                    return NyscefCaseSearchOutput(
                        tool="nyscef_case_search_tool",
                        error="At least one of business_name, last_name, or index_number is required",
                    )

                cases = parse_search_results(html)
                total_count = parse_result_count(html)

                return NyscefCaseSearchOutput(
                    tool="nyscef_case_search_tool",
                    cases=cases,
                    total_count=total_count,
                )

            except Exception as exc:
                log.error("NYSCEF case search failed: %s", exc, exc_info=True)
                return NyscefCaseSearchOutput(
                    tool="nyscef_case_search_tool",
                    error=str(exc),
                )

        return nyscef_case_search_tool
