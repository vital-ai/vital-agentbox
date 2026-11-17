"""
HTML parsers for NYSCEF search results and docket (case detail) pages.

Uses BeautifulSoup to extract structured data from the HTML responses.

"""

import logging
import re
from urllib.parse import parse_qs, urlparse

from agentbox.tools.nyscef.models import (
    NyscefCaseDetail,
    NyscefCaseSummary,
    NyscefDocketEntry,
    NyscefParty,
)

log = logging.getLogger(__name__)


def parse_search_results(html: str) -> list[NyscefCaseSummary]:
    """Parse NYSCEF CaseSearchResults HTML into a list of NyscefCaseSummary.

    The results are in a ``<table class="NewSearchResults">`` with rows containing:
      - Column 0: link to DocumentList (contains docketId), index number, filing date
      - Column 1: e-filing status, case status (in ``<span class="grayItalic">``)
      - Column 2: caption
      - Column 3: court, case type (in ``<span class="grayItalic">``)
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="NewSearchResults")
    if not table:
        log.debug("No NewSearchResults table found in HTML (%d chars)", len(html))
        return []

    cases: list[NyscefCaseSummary] = []

    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        # Column 0: index number + docket link + filing date
        link = cells[0].find("a", href=True)
        index_number = link.get_text(strip=True) if link else None
        docket_id = _extract_docket_id(link["href"]) if link else None
        filing_date = _extract_secondary_text(cells[0])

        # Column 1: efiling status + case status
        efiling_status = _extract_primary_text(cells[1])
        case_status = _extract_gray_italic(cells[1])

        # Column 2: caption
        caption = cells[2].get_text(strip=True) if cells[2] else None

        # Column 3: court + case type
        court = _extract_primary_text(cells[3])
        case_type = _extract_gray_italic(cells[3])

        cases.append(NyscefCaseSummary(
            index_number=index_number,
            docket_id=docket_id,
            caption=caption,
            case_type=case_type,
            case_status=case_status,
            court=court,
            efiling_status=efiling_status,
            filing_date=filing_date,
        ))

    log.debug("Parsed %d cases from search results", len(cases))
    return cases


def parse_result_count(html: str) -> int | None:
    """Estimate result count from the search results page.

    NYSCEF does not display an explicit total.  This function counts the
    rows on the current page and multiplies by the number of pages (from
    the pagination "Last" link) to produce an upper-bound estimate.
    Returns the count of rows on the current page if there is no pagination.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    # Count rows in the results table
    table = soup.find("table", class_="NewSearchResults")
    if not table:
        return None
    rows = [r for r in table.find_all("tr") if len(r.find_all("td")) >= 4]
    page_count = len(rows)
    if page_count == 0:
        return None

    # Find the "Last" pagination link to get total pages
    last_link = soup.find("a", class_="pageOff", string="Last")
    if last_link and last_link.get("href"):
        match = re.search(r"PageNum=(\d+)", last_link["href"])
        if match:
            total_pages = int(match.group(1))
            return page_count * total_pages

    return page_count


def parse_case_detail(
    html: str,
    docket_id: str | None = None,
    case_details_html: str | None = None,
) -> NyscefCaseDetail:
    """Parse NYSCEF case pages into NyscefCaseDetail.

    ``html`` is the DocumentList (docket) page or the CaseDetails page; both share
    the header:
      - ``<h1 class="PageHeading">`` with the index number (``<a class="skipTo">``,
        e.g. "150793/2020" or "129361-2021") and the court
        (``<span class="PageHeadingDesc">``), separated by " - ";
      - ``<span class="captionText">`` with the short caption;
      - ``<span>Case Type: <strong>…</strong></span>``, likewise Case Status and
        eFiling Status.
    The DocumentList page holds the filings table (columns #, Document, Filed By,
    Status). Parties are only on the CaseDetails page (tables under the
    "Plaintiffs/Petitioners" and "Defendants/Respondents" headings, plus the
    "Full Caption"); pass it as ``case_details_html`` to get them.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    details = BeautifulSoup(case_details_html, "html.parser") if case_details_html else None
    pages = [s for s in (soup, details) if s is not None]

    def first(fn):
        for page in pages:
            value = fn(page)
            if value:
                return value
        return None

    index_number, court = None, None
    for page in pages:
        index_number, court = _parse_heading(page)
        if index_number or court:
            break

    parties: list[NyscefParty] = []
    for page in reversed(pages):  # CaseDetails first
        parties = _parse_parties(page)
        if parties:
            break

    return NyscefCaseDetail(
        docket_id=docket_id,
        index_number=index_number,
        court=court,
        case_type=first(lambda p: _labeled_value(p, "Case Type")),
        case_status=first(lambda p: _labeled_value(p, "Case Status")),
        efiling_status=first(lambda p: _labeled_value(p, "eFiling Status")),
        judge=first(lambda p: _labeled_value(p, "Justice") or _labeled_value(p, "Judge")
                    or _labeled_value(p, "Assigned Judge")),
        filing_date=first(lambda p: _labeled_value(p, "Date Filed") or _labeled_value(p, "Filing Date")),
        caption=first(_caption),
        full_caption=first(_full_caption),
        parties=parties,
        docket_entries=_parse_docket_entries(soup),
    )


# --- Internal helpers ---

def _extract_docket_id(href: str) -> str | None:
    """Extract docketId parameter from a DocumentList URL."""
    try:
        parsed = urlparse(href)
        params = parse_qs(parsed.query)
        ids = params.get("docketId", [])
        return ids[0] if ids else None
    except Exception:
        return None


def _extract_primary_text(cell) -> str | None:
    """Extract primary text from a cell (before any <br> or <span>)."""
    for child in cell.children:
        if isinstance(child, str):
            text = child.strip()
            if text:
                return text
        elif child.name and child.name not in ("span", "br"):
            text = child.get_text(strip=True)
            if text:
                return text
    return None


def _extract_secondary_text(cell) -> str | None:
    """Extract text after the first <br> in a cell (e.g. filing date)."""
    found_br = False
    for child in cell.children:
        if hasattr(child, "name") and child.name == "br":
            found_br = True
            continue
        if found_br:
            text = child.strip() if isinstance(child, str) else child.get_text(strip=True)
            if text:
                return text
    return None


def _extract_gray_italic(cell) -> str | None:
    """Extract text from <span class="grayItalic"> within a cell."""
    span = cell.find("span", class_="grayItalic")
    return span.get_text(strip=True) if span else None


def _clean(text: str | None) -> str | None:
    """Collapse whitespace; empty → None."""
    if text is None:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _cell_lines(cell) -> list[str]:
    """Text of a cell split at ``<br>``, each line whitespace-collapsed, empties dropped."""
    lines, current = [], []
    for el in cell.descendants:
        if getattr(el, "name", None) == "br":
            lines.append("".join(current))
            current = []
        elif isinstance(el, str):
            current.append(el)
    lines.append("".join(current))
    return [c for c in (_clean(line) for line in lines) if c]


def _parse_heading(soup) -> tuple[str | None, str | None]:
    """Index number and court from ``<h1 class="PageHeading">``.

    Index numbers contain "/" or "-" ("150793/2020", "129361-2021"), so the
    court is split off at " - " (with spaces), never at a bare "-".
    """
    h1 = soup.find("h1", class_="PageHeading") or soup.find("h1")
    if not h1:
        return None, None
    idx_el = h1.find("a", class_="skipTo")
    court_el = h1.find("span", class_="PageHeadingDesc")
    text = _clean(h1.get_text(" ")) or ""
    head, _, tail = text.partition(" - ")
    index_number = _clean(idx_el.get_text()) if idx_el else _clean(head)
    court = _clean(court_el.get_text()) if court_el else _clean(tail)
    if index_number and index_number.lower().startswith("index not"):
        index_number = None
    return index_number, court


def _labeled_value(soup, label: str) -> str | None:
    """Value of a ``<span>Label: <strong>value</strong></span>`` header field.

    Matches the label exactly (case-insensitive, colon optional) at the start of
    the element's own text, so "Status" never matches "eFiling Status". The value
    is the ``<strong>``, else the rest of the element's own text, else the next
    sibling element.
    """
    want = label.lower().rstrip(":")
    for el in soup.find_all(["span", "td", "th", "dt", "label", "div"]):
        own = _clean("".join(el.find_all(string=True, recursive=False))) or ""
        if not own.lower().startswith(want):
            continue
        rest = own[len(want):]
        if rest and not rest.startswith(":"):
            continue
        strong = el.find("strong")
        if strong:
            return _clean(strong.get_text(" "))
        value = _clean(rest.lstrip(":"))
        if value:
            return value
        sibling = el.find_next_sibling()
        if sibling is not None:
            return _clean(sibling.get_text(" "))
    return None


def _caption(soup) -> str | None:
    el = soup.find(class_="captionText")
    return _clean(el.get_text(" ")) if el else None


def _full_caption(soup) -> str | None:
    """``<span class="DataRow"><strong>Full Caption</strong><br/>…</span>`` on CaseDetails."""
    for strong in soup.find_all("strong"):
        if (_clean(strong.get_text()) or "").lower() == "full caption":
            parent = strong.parent
            text = _clean(parent.get_text(" ")) or ""
            value = _clean(text[len("Full Caption"):]) if text.startswith("Full Caption") else None
            if value:
                return value
    return None


_PARTY_ROLE_BY_SUMMARY = {"petitioners": "Plaintiffs/Petitioners", "respondents": "Defendants/Respondents"}


def _parse_parties(soup) -> list[NyscefParty]:
    """Parties from the CaseDetails page.

    Each side is a ``table.NewSearchResults`` (columns Name, Represented By)
    under a ``div.tableHeading`` ("Plaintiffs/Petitioners", "Defendants/Respondents");
    its ``summary`` reads "Petitioners in this case" / "Respondents in this case".
    The role is the heading text, else derived from the summary. "none recorded"
    in Represented By means no attorney.
    """
    parties: list[NyscefParty] = []
    for table in soup.find_all("table", class_="NewSearchResults"):
        header = [(_clean(th.get_text()) or "").lower() for th in table.find_all("th")]
        if not header or header[0] != "name":
            continue
        role = None
        heading = table.find_previous("div", class_="tableHeading")
        if heading is not None:
            role = _clean(heading.get_text(" "))
        summary = (table.get("summary") or "").lower()
        for key, value in _PARTY_ROLE_BY_SUMMARY.items():
            if key in summary and not role:
                role = value
        body = table.find("tbody") or table
        for row in body.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue
            name = _clean(cells[0].get_text(" "))
            attorney = None
            if len(cells) > 1:
                lines = _cell_lines(cells[1])
                if lines and lines != ["none recorded"]:
                    attorney = "; ".join(lines)
            if name:
                parties.append(NyscefParty(name=name, role=role, attorney=attorney))
    return parties


def _parse_docket_entries(soup) -> list[NyscefDocketEntry]:
    """Parse docket entries (filings) from the DocumentList page.

    The table is ``table.NewSearchResults`` with headers #, Document, Filed By,
    Status. Cells, as NYSCEF renders them:
      - Document: the document type as a ``ViewDocument`` link (plain text when
        there is no viewable document), then optional exhibit letter,
        description and redaction note after ``<br>``s;
      - Filed By: filer name, ``<br>Filed: MM/DD/YYYY``,
        ``<br><span class="grayItalic">Received: MM/DD/YYYY</span>``
        (empty for filings returned for correction);
      - Status: e.g. ``<strong>Processed</strong>`` then a confirmation-notice link.
    """
    entries: list[NyscefDocketEntry] = []

    doc_table = None
    for table in soup.find_all("table", class_="NewSearchResults"):
        header = [(_clean(th.get_text()) or "").lower() for th in table.find_all("th")]
        if "#" in header or "document" in header:
            doc_table = table
            break
    if not doc_table:
        return entries

    col_map = {}
    header_row = doc_table.find("tr")
    for i, cell in enumerate(header_row.find_all(["th", "td"]) if header_row else []):
        text = (_clean(cell.get_text()) or "").lower()
        if text == "#":
            col_map["number"] = i
        elif "document" in text:
            col_map["document"] = i
        elif "filed by" in text:
            col_map["filed_by"] = i
        elif "status" in text:
            col_map["status"] = i

    for row in doc_table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        def cell(name: str):
            idx = col_map.get(name)
            return cells[idx] if idx is not None and idx < len(cells) else None

        num_cell, doc_cell, by_cell, status_cell = cell("number"), cell("document"), cell("filed_by"), cell("status")

        doc_index = _clean(num_cell.get_text()) if num_cell else None
        document_type = description = None
        if doc_cell is not None:
            link = doc_cell.find("a")
            lines = _cell_lines(doc_cell)
            document_type = _clean(link.get_text(" ")) if link else (lines[0] if lines else None)
            description = _clean(" ".join(lines))

        filed_by = filing_date = received_date = None
        if by_cell is not None:
            for line in _cell_lines(by_cell):
                m = re.match(r"(Filed|Received):\s*(\S.*)", line, re.IGNORECASE)
                if m and m.group(1).lower() == "filed":
                    filing_date = m.group(2)
                elif m:
                    received_date = m.group(2)
                elif filed_by is None:
                    filed_by = line

        status = None
        if status_cell is not None:
            strong = status_cell.find("strong")
            lines = _cell_lines(status_cell)
            status = _clean(strong.get_text(" ")) if strong else (lines[0] if lines else None)

        if doc_index or description:
            entries.append(NyscefDocketEntry(
                doc_index=doc_index,
                filing_date=filing_date,
                received_date=received_date,
                description=description,
                filed_by=filed_by,
                document_type=document_type,
                status=status,
            ))

    log.debug("Parsed %d docket entries", len(entries))
    return entries
