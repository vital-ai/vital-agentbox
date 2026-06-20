"""
NYSCEF Tools tests.

Tests model instantiation, HTML parsers (search results, result count,
case detail, empty HTML), and tool registration with ToolManager.

Usage:
    python -m pytest test/test_nyscef_tools.py -xvs
"""

import pytest

from agentbox.tools.nyscef.html_parser import (
    parse_case_detail,
    parse_result_count,
    parse_search_results,
)
from agentbox.tools.nyscef.models import (
    NyscefCaseDetail,
    NyscefCaseDetailInput,
    NyscefCaseDetailOutput,
    NyscefCaseSearchInput,
    NyscefCaseSearchOutput,
    NyscefCaseSummary,
    NyscefDocketEntry,
    NyscefParty,
)


# --- Test HTML fixtures ---

SEARCH_RESULTS_HTML = """
<html><body>
<table class="NewSearchResults">
  <tr>
    <th>Index No. / Filing Date</th><th>eFiling Status</th><th>Caption</th><th>Court</th>
  </tr>
  <tr>
    <td><a href="DocumentList?docketId=abc123&amp;display=all&amp;courtType=Supreme">100234/2024</a><br>01/15/2024</td>
    <td>Filed<br><span class="grayItalic">Active</span></td>
    <td>Smith v. Jones</td>
    <td>New York County<br><span class="grayItalic">Commercial</span></td>
  </tr>
  <tr>
    <td><a href="DocumentList?docketId=def456&amp;display=all">200567/2023</a><br>06/01/2023</td>
    <td>Filed<br><span class="grayItalic">Disposed</span></td>
    <td>Acme Corp v. Widget Inc</td>
    <td>Kings County<br><span class="grayItalic">Torts</span></td>
  </tr>
</table>
<a href="CaseSearchResults?PageNum=1" class="pageOn">1</a>
<a href="CaseSearchResults?PageNum=2" class="pageOff">2</a>
<a href="CaseSearchResults?PageNum=3" class="pageOff">3</a>
<a href="CaseSearchResults?PageNum=3" class="pageOff">Last</a>
</body></html>
"""

DOCKET_PAGE_HTML = """
<html><body>
<h1>100234/2024-New York County Supreme Court-Commercial</h1>
<span class="captionText">Smith v. Jones</span>
<table>
  <tr><td class="fieldLabel">Justice/Judge</td><td>Hon. Jane Doe</td></tr>
  <tr><td class="fieldLabel">Disposition/Status</td><td>Active</td></tr>
  <tr><td class="fieldLabel">Date Filed</td><td>01/15/2024</td></tr>
</table>
<table class="NewSearchResults">
  <tr><th>#</th><th>Document</th><th>Filed By</th><th>Status</th></tr>
  <tr>
    <td>1</td><td>Summons and complaint</td><td>Plaintiff</td><td>Filed</td>
  </tr>
  <tr>
    <td>2</td><td>Motion to dismiss</td><td>Defendant</td><td>Filed</td>
  </tr>
</table>
</body></html>
"""


# --- Model Instantiation ---

class TestNyscefModels:
    def test_case_summary(self):
        cs = NyscefCaseSummary(
            index_number="100234/2024", docket_id="abc123",
            caption="Smith v. Jones", case_type="Commercial",
        )
        assert cs.index_number == "100234/2024"
        assert cs.caption == "Smith v. Jones"

    def test_case_summary_empty(self):
        cs_empty = NyscefCaseSummary()
        assert cs_empty.index_number is None

    def test_party(self):
        p = NyscefParty(name="John Smith", role="Plaintiff", attorney="Law Firm LLP")
        assert p.name == "John Smith"

    def test_docket_entry(self):
        de = NyscefDocketEntry(filing_date="01/15/2024", document_type="Motion")
        assert de.filing_date == "01/15/2024"

    def test_case_detail(self):
        cd = NyscefCaseDetail(
            docket_id="abc123", index_number="100234/2024",
            parties=[NyscefParty(name="Smith", role="Plaintiff")],
            docket_entries=[NyscefDocketEntry(filing_date="01/15/2024")],
        )
        assert len(cd.parties) == 1
        assert len(cd.docket_entries) == 1

    def test_case_search_input(self):
        si = NyscefCaseSearchInput(business_name="Acme Corp")
        assert si.business_name == "Acme Corp"
        assert si.last_name is None

    def test_case_search_output(self):
        so = NyscefCaseSearchOutput(
            tool="nyscef_case_search_tool",
            cases=[NyscefCaseSummary(index_number="100234/2024")],
            total_count=1,
        )
        assert so.tool == "nyscef_case_search_tool"
        assert len(so.cases) == 1

    def test_case_search_output_error(self):
        so_err = NyscefCaseSearchOutput(tool="nyscef_case_search_tool", error="Session failed")
        assert so_err.error == "Session failed"
        assert so_err.cases == []

    def test_case_detail_input(self):
        di = NyscefCaseDetailInput(docket_id="abc123")
        assert di.docket_id == "abc123"
        assert di.include_filings is True

    def test_case_detail_output(self):
        do = NyscefCaseDetailOutput(
            tool="nyscef_case_detail_tool",
            case=NyscefCaseDetail(docket_id="abc123"),
        )
        assert do.case.docket_id == "abc123"


# --- Parse Search Results ---

class TestParseSearchResults:
    def test_parse_search_results(self):
        cases = parse_search_results(SEARCH_RESULTS_HTML)
        assert len(cases) == 2, f"Expected 2 cases, got {len(cases)}"

        c0 = cases[0]
        assert c0.index_number == "100234/2024"
        assert c0.docket_id == "abc123"
        assert c0.caption == "Smith v. Jones"
        assert c0.case_type == "Commercial"
        assert c0.case_status == "Active"
        assert c0.court == "New York County"
        assert c0.filing_date == "01/15/2024"

        c1 = cases[1]
        assert c1.index_number == "200567/2023"
        assert c1.docket_id == "def456"
        assert c1.caption == "Acme Corp v. Widget Inc"
        assert c1.case_type == "Torts"
        assert c1.case_status == "Disposed"

    def test_parse_search_results_empty(self):
        cases = parse_search_results("<html><body>No results</body></html>")
        assert cases == []


# --- Parse Result Count ---

class TestParseResultCount:
    def test_parse_result_count(self):
        count = parse_result_count(SEARCH_RESULTS_HTML)
        assert count == 6, f"Expected 6 (2 rows * 3 pages), got {count}"

    def test_parse_result_count_missing(self):
        count = parse_result_count("<html><body></body></html>")
        assert count is None


# --- Parse Case Detail ---

class TestParseCaseDetail:
    def test_parse_case_detail(self):
        detail = parse_case_detail(DOCKET_PAGE_HTML, docket_id="abc123")
        assert detail.docket_id == "abc123"
        assert detail.index_number == "100234/2024"
        assert detail.case_type == "Commercial"
        assert detail.court == "New York County Supreme Court"
        assert detail.judge == "Hon. Jane Doe"
        assert detail.case_status == "Active"
        assert detail.filing_date == "01/15/2024"
        assert detail.caption == "Smith v. Jones"

        assert len(detail.docket_entries) == 2
        e0 = detail.docket_entries[0]
        assert e0.doc_index == "1"
        assert e0.description == "Summons and complaint"
        assert e0.filed_by == "Plaintiff"
        assert e0.document_type == "Filed"

    def test_parse_case_detail_empty(self):
        detail = parse_case_detail("<html><body></body></html>", docket_id="missing")
        assert detail.docket_id == "missing"
        assert detail.index_number is None
        assert detail.docket_entries == []


# --- Tool Registration ---

_has_kgraphplanner = True
try:
    import kgraphplanner  # noqa: F401
except ImportError:
    _has_kgraphplanner = False


@pytest.mark.skipif(not _has_kgraphplanner, reason="kgraphplanner not installed")
class TestNyscefToolRegistration:
    def test_tools_register(self):
        from kgraphplanner.tool_manager.tool_manager import ToolManager
        from agentbox.tools.nyscef.nyscef_case_detail_tool import NyscefCaseDetailTool
        from agentbox.tools.nyscef.nyscef_case_search_tool import NyscefCaseSearchTool
        from agentbox.tools.nyscef.session_manager import NyscefSessionManager

        tm = ToolManager()
        session = NyscefSessionManager()

        NyscefCaseSearchTool(session, tool_manager=tm)
        NyscefCaseDetailTool(session, tool_manager=tm)

        available = tm.list_available_tools()
        expected = ["nyscef_case_search_tool", "nyscef_case_detail_tool"]
        for name in expected:
            assert name in available, f"{name} not registered"

    def test_tool_functions_retrievable(self):
        from kgraphplanner.tool_manager.tool_manager import ToolManager
        from agentbox.tools.nyscef.nyscef_case_detail_tool import NyscefCaseDetailTool
        from agentbox.tools.nyscef.nyscef_case_search_tool import NyscefCaseSearchTool
        from agentbox.tools.nyscef.session_manager import NyscefSessionManager

        tm = ToolManager()
        session = NyscefSessionManager()

        NyscefCaseSearchTool(session, tool_manager=tm)
        NyscefCaseDetailTool(session, tool_manager=tm)

        expected = ["nyscef_case_search_tool", "nyscef_case_detail_tool"]
        for name in expected:
            fn = tm.get_tool_function(name)
            assert fn is not None, f"No function for {name}"
