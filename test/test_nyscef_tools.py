"""
NYSCEF Tools tests.

Tests model instantiation, HTML parsers (search results, result count,
case detail, empty HTML), tool registration with ToolManager, and the
case-detail tool's page fetching.

Usage:
    python -m pytest test/test_nyscef_tools.py -xvs

The tool tests need kgraphplanner, which is not a dependency here (it depends
on vital-agentbox). Put its source on the path to run them:
    PYTHONPATH=../kgraphplanner python -m pytest test/test_nyscef_tools.py -xvs
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

# Docket (DocumentList) and CaseDetails pages: markup copied from live NYSCEF pages
# (2026-11), names invented.

_PAGE_HEADER = """
<div class="headingContainer">
<h1 class="PageHeading">
<a class="skipTo" id="content">{index}</a> - <span class="PageHeadingDesc">Kings County Supreme Court</span>
</h1>
</div>
<div class="row">
<span style="vertical-align:top">Short Caption: </span>
<span class="captionText">ACME FUNDING LLC v. WIDGET WORKS LLC et al</span>
</div>
<span class="row"><span>Case Type: <strong>Other Matters - Contract - Other</strong></span></span>
<span class="row"><span>Case Status: <strong>Pre-RJI</strong></span></span>
<span class="row"><span>eFiling Status:     <strong><a style="cursor:help" title="One or more parties have not recorded their participation in e-filing.">Partial Participation Recorded</a></strong> </span></span>
"""

DOCKET_PAGE_HTML = "<html><body><main>" + _PAGE_HEADER.format(index="123456-2021") + """
<table class="NewSearchResults">
<tr>
<th scope="col" style="width:3em">#</th>
<th scope="col">Document</th>
<th scope="col" style="width:13em">Filed By</th>
<th scope="col" style="width:11em">Status</th>
</tr>
<tr>
<td style="font-size:.9;padding-right:0">
              1
        </td>
<td>
<a aria-label=" SUMMONS + COMPLAINT, page opens in new tab" href="ViewDocument?docIndex=aaa==" target="_blank">SUMMONS + COMPLAINT</a>
</td>
<td>
                DOE, JANE
              <br/>Filed: 04/27/2021
            <br/><span class="grayItalic">
                Received: 04/28/2021
            </span>
</td>
<td>
<span class="green"><strong>Processed</strong></span>
<br/>
<a aria-label="confirmation notice, page opens in new tab" href="ConfirmationNotice?docId=aaa==" target="_blank">Confirmation Notice</a>
<br/>
</td>
</tr>
<tr class="changeColor">
<td style="font-size:.9;padding-right:0">
              2
        </td>
<td>
<a aria-label=" EXHIBIT(S), page opens in new tab" href="ViewDocument?docIndex=bbb==" target="_blank">EXHIBIT(S)</a> - A <br/><span class="italic">MERCHANT AGREEMENT </span> <br/><span class="blueItalicBold">Redacted</span> <span class="italic">per 22 NYCRR \u00a7202.5(e) </span>
</td>
<td>
                DOE, JANE
              <br/>Filed: 04/27/2021
            <br/><span class="grayItalic">
                Received: 04/27/2021
            </span>
</td>
<td>
<span class="green"><strong>Processed</strong></span>
<br/>
</td>
</tr>
<tr>
<td style="font-size:.9;padding-right:0">
              3
        </td>
<td>
                JUDGMENT - CLERK DEFAULT (PROPOSED)
        </td>
<td>
</td>
<td>
<span class="red"><strong>Returned For Correction</strong></span>
</td>
</tr>
</table>
</main></body></html>
"""

CASE_DETAILS_HTML = "<html><body><main>" + _PAGE_HEADER.format(index="123456-2021") + """
<span class="DataRow">
<strong>Full Caption</strong>
<br/>Acme Funding Llc v. Widget Works Llc, Widget Works, John Q Public
    </span>
<div class="tableHeading">
        Plaintiffs/Petitioners
    </div>
<table class="NewSearchResults" style="width:54em;" summary="Petitioners in this case">
<thead>
<tr>
<th scope="col">Name</th>
<th scope="col" style="width:50%">Represented By</th>
</tr>
</thead>
<tbody>
<tr>
<td>
                 ACME FUNDING LLC
        </td>
<td style="line-height:1.5em">
                    DOE, JANE on 04/27/2021
                    <br/>Doe &amp; Roe, PLLC
        </td>
</tr>
</tbody>
</table>
<div class="tableHeading">Defendants/Respondents</div>
<table class="NewSearchResults" style="width:54em;" summary="Respondents in this case">
<thead>
<tr>
<th scope="col">Name</th>
<th scope="col" style="width:50%">Represented By</th>
</tr>
</thead>
<tbody>
<tr>
<td>
                 WIDGET WORKS LLC
            DBA WIDGETS
        </td>
<td style="line-height:1.5em">
<span class="redItalic">none recorded</span>
</td>
</tr>
<tr class="changeColor">
<td>
                 John Q Public
        </td>
<td style="line-height:1.5em">
<span class="redItalic">none recorded</span>
</td>
</tr>
</tbody>
</table>
</main></body></html>
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
    def test_header_fields(self):
        detail = parse_case_detail(DOCKET_PAGE_HTML, docket_id="abc123")
        assert detail.docket_id == "abc123"
        # Hyphenated index numbers stay whole; the court is split off at " - ".
        assert detail.index_number == "123456-2021"
        assert detail.court == "Kings County Supreme Court"
        assert detail.case_type == "Other Matters - Contract - Other"
        assert detail.case_status == "Pre-RJI"
        assert detail.efiling_status == "Partial Participation Recorded"
        assert detail.caption == "ACME FUNDING LLC v. WIDGET WORKS LLC et al"
        # Neither page shows a case filing date (the search summary has it).
        assert detail.filing_date is None
        assert detail.judge is None

    def test_docket_entries(self):
        entries = parse_case_detail(DOCKET_PAGE_HTML).docket_entries
        assert len(entries) == 3
        e0, e1, e2 = entries
        assert e0.doc_index == "1"
        assert e0.document_type == "SUMMONS + COMPLAINT"
        assert e0.description == "SUMMONS + COMPLAINT"
        assert e0.filed_by == "DOE, JANE"
        assert e0.filing_date == "04/27/2021"
        assert e0.received_date == "04/28/2021"
        assert e0.status == "Processed"
        assert e1.document_type == "EXHIBIT(S)"
        assert e1.description == "EXHIBIT(S) - A MERCHANT AGREEMENT Redacted per 22 NYCRR \u00a7202.5(e)"
        # Unlinked document, filing returned for correction: no filer or dates.
        assert e2.document_type == "JUDGMENT - CLERK DEFAULT (PROPOSED)"
        assert e2.filed_by is None and e2.filing_date is None
        assert e2.status == "Returned For Correction"

    def test_docket_page_has_no_parties(self):
        assert parse_case_detail(DOCKET_PAGE_HTML).parties == []

    def test_parties_from_case_details(self):
        detail = parse_case_detail(DOCKET_PAGE_HTML, docket_id="abc123",
                                   case_details_html=CASE_DETAILS_HTML)
        assert [(p.name, p.role, p.attorney) for p in detail.parties] == [
            ("ACME FUNDING LLC", "Plaintiffs/Petitioners", "DOE, JANE on 04/27/2021; Doe & Roe, PLLC"),
            ("WIDGET WORKS LLC DBA WIDGETS", "Defendants/Respondents", None),
            ("John Q Public", "Defendants/Respondents", None),
        ]
        assert detail.full_caption == "Acme Funding Llc v. Widget Works Llc, Widget Works, John Q Public"
        assert len(detail.docket_entries) == 3

    def test_case_details_page_alone(self):
        detail = parse_case_detail(CASE_DETAILS_HTML, docket_id="abc123")
        assert detail.index_number == "123456-2021"
        assert len(detail.parties) == 3
        assert detail.docket_entries == []

    def test_parse_case_detail_empty(self):
        detail = parse_case_detail("<html><body></body></html>", docket_id="missing")
        assert detail.docket_id == "missing"
        assert detail.index_number is None
        assert detail.parties == []
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


class _FakeNyscefSession:
    """Stands in for NyscefSessionManager: serves fixture pages, records calls."""

    def __init__(self):
        self.calls = []

    async def get_case_details_page(self, docket_id):
        self.calls.append(("case_details", docket_id))
        return CASE_DETAILS_HTML

    async def get_docket_page(self, docket_id):
        self.calls.append(("docket", docket_id))
        return DOCKET_PAGE_HTML


@pytest.mark.skipif(not _has_kgraphplanner, reason="kgraphplanner not installed")
class TestNyscefCaseDetailTool:
    def _run(self, **args):
        import asyncio
        from agentbox.tools.nyscef.nyscef_case_detail_tool import NyscefCaseDetailTool

        session = _FakeNyscefSession()
        fn = NyscefCaseDetailTool(session).get_tool_function()
        return asyncio.run(fn.ainvoke(args)), session

    def test_parties_and_filings(self):
        out, session = self._run(docket_id="abc123")
        assert session.calls == [("case_details", "abc123"), ("docket", "abc123")]
        assert out.error is None
        assert out.case.index_number == "123456-2021"
        assert len(out.case.parties) == 3
        assert len(out.case.docket_entries) == 3

    def test_without_filings_skips_docket_page(self):
        out, session = self._run(docket_id="abc123", include_filings=False)
        assert session.calls == [("case_details", "abc123")]
        assert len(out.case.parties) == 3
        assert out.case.docket_entries == []
