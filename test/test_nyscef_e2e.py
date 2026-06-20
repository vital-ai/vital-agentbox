"""
NYSCEF End-to-End — live tests running inside the Pyodide sandbox.

Agent code inside the sandbox uses ``agentbox.browser_client.Browser`` and
``agentbox.tools.nyscef`` (session_manager, html_parser) to search NYSCEF,
parse results, and fetch docket pages.

Architecture:
    Pyodide → sendMessage bridge → host → orchestrator → browser-worker (camoufox)

Usage:
    docker compose up --build -d
    python -m pytest test/test_nyscef_e2e.py -xvs --log-cli-level=INFO
"""

import logging
import os
import textwrap

import pytest
import pytest_asyncio

from agentbox.client import AgentBoxClient

log = logging.getLogger(__name__)

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8090")


@pytest_asyncio.fixture
async def sandbox():
    """Create a sandbox via the orchestrator, destroy after test."""
    async with AgentBoxClient(ORCHESTRATOR_URL) as client:
        sb = await client.create_sandbox()
        log.info("Created sandbox: %s", sb.sandbox_id)
        yield sb
        await sb.destroy()
        log.info("Destroyed sandbox: %s", sb.sandbox_id)


async def run_in_sandbox(sandbox, code: str, timeout: int = 120):
    """Execute Python code in the Pyodide sandbox, return (stdout, stderr, exit_code)."""
    result = await sandbox.execute(textwrap.dedent(code), language="python", timeout=timeout)
    log.info("stdout: %s", result.stdout.strip())
    if result.stderr.strip():
        log.warning("stderr: %s", result.stderr.strip())
    return result.stdout, result.stderr, result.exit_code


@pytest.mark.asyncio
async def test_nyscef_name_search(sandbox):
    """Sandbox code searches NYSCEF by name via NyscefSessionManager."""
    stdout, stderr, rc = await run_in_sandbox(sandbox, """
import micropip
await micropip.install(['pydantic', 'beautifulsoup4'])

from agentbox.tools.nyscef.session_manager import NyscefSessionManager
from agentbox.tools.nyscef.html_parser import parse_search_results, parse_result_count
from bs4 import BeautifulSoup
import time

mgr = NyscefSessionManager(session_config={"browser_type": "camoufox"})
try:
    t0 = time.time()
    html = await mgr.search_by_name(business_name="Cardiff")
    elapsed = time.time() - t0
    print(f"SEARCH_TIME:{elapsed:.1f}")

    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title else "(no title)"
    print(f"PAGE_TITLE:{title}")
    print(f"HTML_LENGTH:{len(html)}")

    cases = parse_search_results(html)
    count = parse_result_count(html)
    print(f"CASE_COUNT:{len(cases)}")
    print(f"TOTAL_ESTIMATED:{count}")

    if cases:
        c = cases[0]
        print(f"FIRST_INDEX:{c.index_number}")
        print(f"FIRST_CAPTION:{c.caption}")
        print(f"FIRST_DOCKET_ID:{c.docket_id}")
        print(f"FIRST_COURT:{c.court}")
finally:
    await mgr.close()
""")
    assert rc == 0, f"exit_code={rc}, stderr={stderr}"
    assert "CASE_COUNT:" in stdout
    case_count = int(stdout.split("CASE_COUNT:")[1].split("\n")[0])
    assert case_count > 0, "Expected at least one search result"
    assert "FIRST_DOCKET_ID:" in stdout
    docket_id = stdout.split("FIRST_DOCKET_ID:")[1].split("\n")[0]
    assert len(docket_id) > 0
    log.info("NYSCEF search in sandbox: %d cases found", case_count)


@pytest.mark.asyncio
async def test_nyscef_search_then_docket(sandbox):
    """Sandbox code: search → get docket_id → fetch docket page → parse."""
    stdout, stderr, rc = await run_in_sandbox(sandbox, """
import micropip
await micropip.install(['pydantic', 'beautifulsoup4'])

from agentbox.tools.nyscef.session_manager import NyscefSessionManager
from agentbox.tools.nyscef.html_parser import (
    parse_search_results, parse_case_detail,
)
import time

mgr = NyscefSessionManager(session_config={"browser_type": "camoufox"})
try:
    # Step 1: Search
    t0 = time.time()
    html = await mgr.search_by_name(business_name="Cardiff")
    search_time = time.time() - t0
    print(f"SEARCH_TIME:{search_time:.1f}")

    cases = parse_search_results(html)
    print(f"CASE_COUNT:{len(cases)}")
    assert len(cases) > 0, "No search results"

    docket_id = cases[0].docket_id
    print(f"DOCKET_ID:{docket_id}")
    print(f"CAPTION:{cases[0].caption}")

    # Step 2: Docket page
    t1 = time.time()
    docket_html = await mgr.get_docket_page(docket_id)
    docket_time = time.time() - t1
    print(f"DOCKET_TIME:{docket_time:.1f}")

    detail = parse_case_detail(docket_html, docket_id)
    print(f"DETAIL_DOCKET_ID:{detail.docket_id}")
    print(f"DETAIL_CAPTION:{detail.caption}")
    print(f"DETAIL_COURT:{detail.court}")
    print(f"DETAIL_ENTRIES:{len(detail.docket_entries)}")

    if detail.docket_entries:
        e = detail.docket_entries[0]
        print(f"FIRST_ENTRY:{e.doc_index}|{e.description}")

    print(f"TOTAL_TIME:{search_time + docket_time:.1f}")
finally:
    await mgr.close()
""")
    assert rc == 0, f"exit_code={rc}, stderr={stderr}"

    case_count = int(stdout.split("CASE_COUNT:")[1].split("\n")[0])
    assert case_count > 0

    assert "DETAIL_DOCKET_ID:" in stdout
    detail_id = stdout.split("DETAIL_DOCKET_ID:")[1].split("\n")[0]
    docket_id = stdout.split("DOCKET_ID:")[1].split("\n")[0]
    assert detail_id == docket_id

    assert "DETAIL_CAPTION:" in stdout or "DETAIL_COURT:" in stdout
    log.info("NYSCEF search+docket in sandbox: %d cases, docket fetched", case_count)
