"""
Web Tools tests.

Tests model instantiation, HTML extract helpers (links, tables), and
tool registration with ToolManager.

Usage:
    python -m pytest test/test_web_tools.py -xvs
"""

import pytest

from agentbox.tools.web.models import (
    CaptchaInfo,
    ExtractionFormat,
    InteractionType,
    LinkItem,
    PageInfo,
    TableRow,
    WebAction,
    WebCloseInput,
    WebCloseOutput,
    WebExtractInput,
    WebExtractOutput,
    WebInteractInput,
    WebInteractOutput,
    WebNavigateInput,
    WebNavigateOutput,
)
from agentbox.tools.web.html_helpers import (
    _parse_links_from_html,
    _parse_table_from_html,
)


# --- Test HTML fixtures ---

LINKS_HTML = """
<html><body>
<a href="https://example.com/page1">Page One</a>
<a href="https://example.com/page2">Page Two</a>
<a href="javascript:void(0)">Skip</a>
<a href="#anchor">Also Skip</a>
<a href="https://example.com/page3">Page Three</a>
</body></html>
"""

TABLE_HTML = """
<html><body>
<table>
  <tr><th>Name</th><th>Age</th><th>City</th></tr>
  <tr><td>Alice</td><td>30</td><td>New York</td></tr>
  <tr><td>Bob</td><td>25</td><td>Chicago</td></tr>
  <tr><td>Carol</td><td>35</td><td>Boston</td></tr>
</table>
</body></html>
"""


# --- Model Instantiation ---

class TestWebModels:
    def test_page_info(self):
        pi = PageInfo(title="Test", url="https://example.com", session_id="abc123")
        assert pi.title == "Test"

    def test_captcha_info(self):
        ci = CaptchaInfo(captcha_encountered=True, captcha_solved=True, captcha_method="hcaptcha_solver")
        assert ci.captcha_solved is True

    def test_navigate_input(self):
        nav_in = WebNavigateInput(url="https://example.com", wait_for=".content")
        assert nav_in.url == "https://example.com"
        assert nav_in.wait_for == ".content"

    def test_navigate_output(self):
        nav_out = WebNavigateOutput(
            page=PageInfo(title="Example", url="https://example.com"),
            page_text="Hello world",
        )
        assert nav_out.page.title == "Example"
        assert nav_out.error is None

    def test_navigate_output_error(self):
        nav_err = WebNavigateOutput(error="Connection refused")
        assert nav_err.error == "Connection refused"

    def test_interact_input(self):
        actions = [
            WebAction(action=InteractionType.FILL, selector="#name", value="John"),
            WebAction(action=InteractionType.CLICK, selector="#submit"),
            WebAction(action=InteractionType.SELECT, selector="#country", value="US"),
            WebAction(action=InteractionType.WAIT, selector=".results", timeout=5000),
        ]
        int_in = WebInteractInput(actions=actions, submit=True)
        assert len(int_in.actions) == 4
        assert int_in.submit is True
        assert int_in.actions[0].action == InteractionType.FILL

    def test_interact_output(self):
        int_out = WebInteractOutput(actions_completed=3)
        assert int_out.actions_completed == 3

    def test_extract_input(self):
        ext_in = WebExtractInput(selector=".results", format=ExtractionFormat.TABLE, max_length=8000)
        assert ext_in.format == ExtractionFormat.TABLE

    def test_extract_output_text(self):
        ext_out = WebExtractOutput(content="some text", truncated=False)
        assert ext_out.content == "some text"

    def test_extract_output_links(self):
        ext_links = WebExtractOutput(
            links=[LinkItem(text="Link 1", href="https://example.com")],
        )
        assert len(ext_links.links) == 1

    def test_extract_output_table(self):
        ext_table = WebExtractOutput(
            table=[TableRow(values={"Name": "Alice", "Age": "30"})],
        )
        assert ext_table.table[0].values["Name"] == "Alice"

    def test_extract_output_screenshot(self):
        ext_ss = WebExtractOutput(screenshot_base64="iVBOR...")
        assert ext_ss.screenshot_base64 is not None

    def test_close_input(self):
        close_in = WebCloseInput(reason="Done browsing")
        assert close_in.reason == "Done browsing"

    def test_close_output(self):
        close_out = WebCloseOutput(session_id="abc123", closed=True)
        assert close_out.closed is True


# --- Parse Links ---

class TestParseLinks:
    def test_parse_links_from_html(self):
        links = _parse_links_from_html(LINKS_HTML)
        assert len(links) == 3, f"Expected 3 links (skipping javascript: and #), got {len(links)}"
        assert links[0].text == "Page One"
        assert links[0].href == "https://example.com/page1"
        assert links[1].text == "Page Two"
        assert links[2].text == "Page Three"

    def test_parse_links_empty_html(self):
        empty_links = _parse_links_from_html("<html><body></body></html>")
        assert len(empty_links) == 0


# --- Parse Table ---

class TestParseTable:
    def test_parse_table_from_html(self):
        rows = _parse_table_from_html(TABLE_HTML)
        assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}"
        assert rows[0].values["Name"] == "Alice"
        assert rows[0].values["Age"] == "30"
        assert rows[0].values["City"] == "New York"
        assert rows[1].values["Name"] == "Bob"
        assert rows[2].values["Name"] == "Carol"

    def test_parse_table_no_table(self):
        empty_rows = _parse_table_from_html("<html><body><p>No table here</p></body></html>")
        assert len(empty_rows) == 0


# --- Tool Registration ---

_has_kgraphplanner = True
try:
    import kgraphplanner  # noqa: F401
except ImportError:
    _has_kgraphplanner = False


@pytest.mark.skipif(not _has_kgraphplanner, reason="kgraphplanner not installed")
class TestWebToolRegistration:
    def test_all_web_tools_register(self):
        from kgraphplanner.tool_manager.tool_manager import ToolManager
        from agentbox.tools.web.web_navigate_tool import WebNavigateTool
        from agentbox.tools.web.web_interact_tool import WebInteractTool
        from agentbox.tools.web.web_extract_tool import WebExtractTool
        from agentbox.tools.web.web_close_tool import WebCloseTool

        tm = ToolManager()
        WebNavigateTool(tool_manager=tm)
        WebInteractTool(tool_manager=tm)
        WebExtractTool(tool_manager=tm)
        WebCloseTool(tool_manager=tm)

        available = tm.list_available_tools()
        expected = ["web_navigate", "web_interact", "web_extract", "web_close"]
        for name in expected:
            assert name in available, f"Tool '{name}' not found in {available}"

    def test_tool_functions_retrievable(self):
        from kgraphplanner.tool_manager.tool_manager import ToolManager
        from agentbox.tools.web.web_navigate_tool import WebNavigateTool
        from agentbox.tools.web.web_interact_tool import WebInteractTool
        from agentbox.tools.web.web_extract_tool import WebExtractTool
        from agentbox.tools.web.web_close_tool import WebCloseTool

        tm = ToolManager()
        WebNavigateTool(tool_manager=tm)
        WebInteractTool(tool_manager=tm)
        WebExtractTool(tool_manager=tm)
        WebCloseTool(tool_manager=tm)

        expected = ["web_navigate", "web_interact", "web_extract", "web_close"]
        for name in expected:
            fn = tm.get_tool_function(name)
            assert fn is not None, f"Tool function for '{name}' is None"
