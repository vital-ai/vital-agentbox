"""
Integration tests: code in an AgentBox sandbox (Pyodide) drives the browser worker.

Creates a sandbox via the orchestrator, then executes Python code INSIDE the
Pyodide sandbox that uses the sendMessage bridge to create browser sessions
and send commands. The host (code worker) proxies these to the orchestrator,
which proxies to the browser-worker — real Chromium, real websites.

Architecture (per browser-worker.md):
    Pyodide → sendMessage bridge → host → HTTP/WS → orchestrator → browser-worker

Usage:
    docker compose up --build -d
    python -m pytest test/test_browser_pool.py -xvs --log-cli-level=INFO
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


async def run_in_sandbox(sandbox, code: str) -> tuple[str, str, int]:
    """Execute Python code in the Pyodide sandbox, return (stdout, stderr, exit_code)."""
    result = await sandbox.execute(textwrap.dedent(code), language="python", timeout=60)
    log.info("stdout: %s", result.stdout.strip())
    if result.stderr.strip():
        log.warning("stderr: %s", result.stderr.strip())
    return result.stdout, result.stderr, result.exit_code


# --- Navigate Wikipedia from inside sandbox ---

@pytest.mark.asyncio
async def test_sandbox_navigate_wikipedia(sandbox):
    """Sandbox code creates a browser session, navigates to Wikipedia."""
    stdout, stderr, rc = await run_in_sandbox(sandbox, """
from agentbox.browser_client import Browser

async with await Browser.create() as b:
    result = await b.goto("https://en.wikipedia.org/wiki/Python_(programming_language)")
    print(f"SESSION:{b.session_id}")
    t = await b.title()
    print(f"TITLE:{t}")
    html = await b.content()
    print(f"HTML_LENGTH:{len(html)}")
""")
    assert rc == 0, f"exit_code={rc}, stderr={stderr}"
    assert "SESSION:" in stdout
    assert "Python" in stdout
    length = int(stdout.split("HTML_LENGTH:")[1].split("\n")[0])
    assert length > 10000
    log.info("Wikipedia HTML from sandbox: %d chars", length)


# --- Screenshot from inside sandbox ---

@pytest.mark.asyncio
async def test_sandbox_screenshot(sandbox):
    """Sandbox code navigates to HN and takes a screenshot."""
    stdout, stderr, rc = await run_in_sandbox(sandbox, """
import base64
from agentbox.browser_client import Browser

async with await Browser.create() as b:
    await b.goto("https://news.ycombinator.com")
    png_b64 = await b.screenshot()
    png = base64.b64decode(png_b64)
    print(f"SCREENSHOT_BYTES:{len(png)}")
    print(f"PNG_HEADER:{png[:4] == b'\\x89PNG'}")
""")
    assert rc == 0, f"exit_code={rc}, stderr={stderr}"
    size = int(stdout.split("SCREENSHOT_BYTES:")[1].split("\n")[0])
    assert size > 5000
    assert "PNG_HEADER:True" in stdout
    log.info("Screenshot from sandbox: %d bytes", size)


# --- Evaluate JS from inside sandbox ---

@pytest.mark.asyncio
async def test_sandbox_evaluate_hackernews(sandbox):
    """Sandbox code navigates to HN and extracts stories via JS evaluation."""
    stdout, stderr, rc = await run_in_sandbox(sandbox, """
from agentbox.browser_client import Browser

async with await Browser.create() as b:
    await b.goto("https://news.ycombinator.com")
    count = await b.evaluate("document.querySelectorAll('.titleline > a').length")
    print(f"STORY_COUNT:{count}")
    top = await b.evaluate("document.querySelector('.titleline > a')?.textContent")
    print(f"TOP_STORY:{top}")
""")
    assert rc == 0, f"exit_code={rc}, stderr={stderr}"
    count = int(stdout.split("STORY_COUNT:")[1].split("\n")[0])
    assert count >= 20
    top = stdout.split("TOP_STORY:")[1].split("\n")[0]
    assert len(top) > 3
    log.info("HN from sandbox: %d stories, #1 = %r", count, top)


# --- Click and navigate from inside sandbox ---

@pytest.mark.asyncio
async def test_sandbox_click_wikipedia(sandbox):
    """Sandbox code navigates to Wikipedia, clicks a link, verifies new URL."""
    stdout, stderr, rc = await run_in_sandbox(sandbox, """
from agentbox.browser_client import Browser

async with await Browser.create() as b:
    await b.goto("https://en.wikipedia.org/wiki/Python_(programming_language)")
    await b.click('a[title="Guido van Rossum"]')
    t = await b.title()
    print(f"TITLE:{t}")
""")
    assert rc == 0, f"exit_code={rc}, stderr={stderr}"
    assert "Guido" in stdout
    log.info("Click from sandbox: %s", stdout.strip())


# --- Get GitHub page content from inside sandbox ---

@pytest.mark.asyncio
async def test_sandbox_github_content(sandbox):
    """Sandbox code navigates to GitHub and retrieves page content."""
    stdout, stderr, rc = await run_in_sandbox(sandbox, """
from agentbox.browser_client import Browser

async with await Browser.create() as b:
    await b.goto("https://github.com/microsoft/playwright")
    t = await b.title()
    print(f"TITLE:{t}")
    html = await b.content()
    print(f"CONTENT_LENGTH:{len(html)}")
    print(f"HAS_PLAYWRIGHT:{'playwright' in html.lower()}")
""")
    assert rc == 0, f"exit_code={rc}, stderr={stderr}"
    length = int(stdout.split("CONTENT_LENGTH:")[1].split("\n")[0])
    assert length > 5000
    assert "HAS_PLAYWRIGHT:True" in stdout
    log.info("GitHub content from sandbox: %d chars", length)


# ---------------------------------------------------------------------------
# Browser tool integration tests
# ---------------------------------------------------------------------------

# --- Extract links from a page (cf. case_web_tools._test_parse_links) ---

@pytest.mark.asyncio
async def test_sandbox_extract_links(sandbox):
    """Sandbox code navigates to Wikipedia and extracts links via JS."""
    stdout, stderr, rc = await run_in_sandbox(sandbox, """
import json
from agentbox.browser_client import Browser

async with await Browser.create() as b:
    await b.goto("https://en.wikipedia.org/wiki/Python_(programming_language)")

    links_json = await b.evaluate('''
        JSON.stringify(
            Array.from(document.querySelectorAll('#bodyContent a[href^="/wiki/"]'))
                .slice(0, 10)
                .map(a => ({text: a.textContent.trim(), href: a.getAttribute("href")}))
        )
    ''')
    links = json.loads(links_json)
    print(f"LINK_COUNT:{len(links)}")
    for i, link in enumerate(links[:3]):
        print(f"LINK_{i}:{link['text']}|{link['href']}")
""")
    assert rc == 0, f"exit_code={rc}, stderr={stderr}"
    count = int(stdout.split("LINK_COUNT:")[1].split("\n")[0])
    assert count == 10
    assert "LINK_0:" in stdout
    log.info("Extracted %d links from Wikipedia in sandbox", count)


# --- Extract table from a page (cf. case_web_tools._test_parse_table) ---

@pytest.mark.asyncio
async def test_sandbox_extract_table(sandbox):
    """Sandbox code navigates to Wikipedia and extracts an infobox table."""
    stdout, stderr, rc = await run_in_sandbox(sandbox, """
import json
from agentbox.browser_client import Browser

async with await Browser.create() as b:
    await b.goto("https://en.wikipedia.org/wiki/Python_(programming_language)")

    table_json = await b.evaluate('''
        (() => {
            const rows = document.querySelectorAll('.infobox tr');
            const data = [];
            for (const row of rows) {
                const th = row.querySelector('th');
                const td = row.querySelector('td');
                if (th && td) {
                    data.push({key: th.textContent.trim(), value: td.textContent.trim().substring(0, 100)});
                }
            }
            return JSON.stringify(data);
        })()
    ''')
    rows = json.loads(table_json)
    print(f"TABLE_ROWS:{len(rows)}")
    for r in rows[:5]:
        print(f"ROW:{r['key']}={r['value']}")
""")
    assert rc == 0, f"exit_code={rc}, stderr={stderr}"
    row_count = int(stdout.split("TABLE_ROWS:")[1].split("\n")[0])
    assert row_count >= 3
    assert "ROW:" in stdout
    log.info("Extracted %d table rows from Wikipedia infobox", row_count)


# --- Form fill + submit (cf. case_nyscef_e2e search flow) ---

@pytest.mark.asyncio
async def test_sandbox_form_fill_submit(sandbox):
    """Sandbox code fills a search form on Wikipedia and submits it."""
    stdout, stderr, rc = await run_in_sandbox(sandbox, """
from agentbox.browser_client import Browser

async with await Browser.create() as b:
    await b.goto("https://en.wikipedia.org/wiki/Main_Page")
    t1 = await b.title()
    print(f"BEFORE_TITLE:{t1}")

    await b.fill('input[name="search"]', 'Playwright browser automation')
    await b.press('input[name="search"]', 'Enter')

    t2 = await b.title()
    print(f"AFTER_TITLE:{t2}")
    html = await b.content()
    print(f"HAS_RESULTS:{'search' in html.lower() or 'playwright' in html.lower()}")
""")
    assert rc == 0, f"exit_code={rc}, stderr={stderr}"
    assert "BEFORE_TITLE:" in stdout
    assert "AFTER_TITLE:" in stdout
    assert "HAS_RESULTS:True" in stdout
    log.info("Form fill+submit from sandbox: %s", stdout.strip())


# --- Multi-step workflow: navigate → click → extract (cf. case_nyscef_e2e) ---

@pytest.mark.asyncio
async def test_sandbox_multi_step_workflow(sandbox):
    """Sandbox code does a multi-step workflow: HN → click story → extract."""
    stdout, stderr, rc = await run_in_sandbox(sandbox, """
from agentbox.browser_client import Browser

async with await Browser.create() as b:
    # Step 1: Navigate to HN
    await b.goto("https://news.ycombinator.com")
    t1 = await b.title()
    print(f"STEP1_TITLE:{t1}")

    # Step 2: Get the first story link text
    first_story = await b.evaluate("document.querySelector('.titleline > a')?.textContent")
    print(f"STEP2_STORY:{first_story}")

    # Step 3: Click the first story
    await b.click('.titleline > a')
    t2 = await b.title()
    print(f"STEP3_TITLE:{t2}")

    # Step 4: Go back
    await b.back()
    t3 = await b.title()
    print(f"STEP4_BACK_TITLE:{t3}")
""")
    assert rc == 0, f"exit_code={rc}, stderr={stderr}"
    assert "Hacker News" in stdout.split("STEP1_TITLE:")[1].split("\n")[0]
    assert "STEP2_STORY:" in stdout
    step2 = stdout.split("STEP2_STORY:")[1].split("\n")[0]
    assert len(step2) > 3
    assert "STEP4_BACK_TITLE:" in stdout
    log.info("Multi-step workflow from sandbox completed")


# --- Element text extraction (cf. WebExtract selector pattern) ---

@pytest.mark.asyncio
async def test_sandbox_text_extraction(sandbox):
    """Sandbox code extracts text from specific elements using selectors."""
    stdout, stderr, rc = await run_in_sandbox(sandbox, """
from agentbox.browser_client import Browser

async with await Browser.create() as b:
    await b.goto("https://en.wikipedia.org/wiki/Python_(programming_language)")

    heading = await b.text('h1')
    print(f"HEADING:{heading}")

    first_p = await b.evaluate('''
        document.querySelector('#mw-content-text .mw-parser-output > p:not(.mw-empty-elt)')?.textContent?.substring(0, 200)
    ''')
    print(f"FIRST_P_LENGTH:{len(first_p) if first_p else 0}")
    print(f"HAS_PYTHON:{'Python' in (first_p or '')}")

    toc_count = await b.evaluate("document.querySelectorAll('#toc li, .toc li, .mw-parser-output .toctext').length")
    print(f"TOC_ITEMS:{toc_count}")
""")
    assert rc == 0, f"exit_code={rc}, stderr={stderr}"
    assert "Python" in stdout.split("HEADING:")[1].split("\n")[0]
    assert "HAS_PYTHON:True" in stdout
    toc = int(stdout.split("TOC_ITEMS:")[1].split("\n")[0])
    assert toc >= 10
    log.info("Text extraction from sandbox: TOC has %d items", toc)


# --- Multiple sessions (cf. pool capacity tests) ---

@pytest.mark.asyncio
async def test_sandbox_multiple_sessions(sandbox):
    """Sandbox code creates two browser sessions and uses both."""
    stdout, stderr, rc = await run_in_sandbox(sandbox, """
from agentbox.browser_client import Browser

b1 = await Browser.create()
b2 = await Browser.create()
try:
    await b1.goto("https://en.wikipedia.org/wiki/Python_(programming_language)")
    await b2.goto("https://en.wikipedia.org/wiki/JavaScript")

    t1 = await b1.title()
    t2 = await b2.title()
    print(f"SESSION1:{b1.session_id}")
    print(f"SESSION2:{b2.session_id}")
    print(f"TITLE1:{t1}")
    print(f"TITLE2:{t2}")
    print(f"DIFFERENT:{b1.session_id != b2.session_id}")
finally:
    await b1.close()
    await b2.close()
""")
    assert rc == 0, f"exit_code={rc}, stderr={stderr}"
    assert "DIFFERENT:True" in stdout
    assert "Python" in stdout.split("TITLE1:")[1].split("\n")[0]
    assert "JavaScript" in stdout.split("TITLE2:")[1].split("\n")[0]
    log.info("Multiple sessions from sandbox: both independent")
