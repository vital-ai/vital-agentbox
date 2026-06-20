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


def parse_case_detail(html: str, docket_id: str | None = None) -> NyscefCaseDetail:
    """Parse a NYSCEF DocumentList (docket) page into NyscefCaseDetail.

    Real NYSCEF docket page structure:
      - ``<h1>`` contains index number, court, and sometimes case type
        e.g. "100234/2024-New York County Supreme Court-Commercial"
      - ``.captionText`` contains the case caption
      - ``table.NewSearchResults`` contains the document list with
        columns: #, Document, Filed By, Status
      - ``fieldLabel`` spans/tds may contain metadata like Judge, Status
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    # Caption — in .captionText element
    caption = None
    caption_el = soup.find(class_="captionText")
    if caption_el:
        caption = caption_el.get_text(strip=True)
    if not caption:
        caption_el = soup.find("caption") or soup.find("h2")
        if caption_el:
            caption = caption_el.get_text(strip=True)

    # Parse <h1> for index number, court, case type
    # Format: "100234/2024-New York County Supreme Court-Commercial"
    # or: "Index not Assigned-Queens County Supreme Court"
    index_number = None
    court = None
    case_type = None
    h1 = soup.find("h1")
    if h1:
        h1_text = h1.get_text(strip=True)
        parts = [p.strip() for p in h1_text.split("-", maxsplit=2)]
        if parts:
            idx_part = parts[0]
            if idx_part.lower().startswith("index not"):
                index_number = None
            else:
                index_number = idx_part or None
        if len(parts) >= 2:
            court = parts[1] or None
        if len(parts) >= 3:
            case_type = parts[2] or None

    # Extract metadata from fieldLabel elements (Judge, Status, etc.)
    case_status = _extract_meta_value(soup, "Disposition/Status") or _extract_meta_value(soup, "Status")
    judge = _extract_meta_value(soup, "Justice/Judge") or _extract_meta_value(soup, "Judge")
    filing_date = _extract_meta_value(soup, "Date Filed") or _extract_meta_value(soup, "Filed")

    # Parse parties
    parties = _parse_parties(soup)

    # Parse docket entries (filings table)
    docket_entries = _parse_docket_entries(soup)

    return NyscefCaseDetail(
        docket_id=docket_id,
        index_number=index_number,
        case_type=case_type,
        case_status=case_status,
        court=court,
        judge=judge,
        filing_date=filing_date,
        caption=caption,
        parties=parties,
        docket_entries=docket_entries,
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


def _extract_meta_value(soup, label: str) -> str | None:
    """Extract a metadata value from a label/value pattern on the docket page.

    Handles patterns like:
      <td class="fieldLabel">Index Number</td><td>100234/2024</td>
      <span class="fieldLabel">Court:</span> New York County
    """
    # Pattern 1: td.fieldLabel followed by sibling td
    label_el = soup.find(
        lambda tag: tag.name in ("td", "th", "span", "label", "dt")
        and label.lower() in tag.get_text(strip=True).lower()
    )
    if label_el:
        # Check next sibling
        sibling = label_el.find_next_sibling()
        if sibling:
            text = sibling.get_text(strip=True)
            if text:
                return text
        # Check parent's next element (for inline patterns)
        if label_el.next_sibling:
            text = label_el.next_sibling
            if isinstance(text, str):
                text = text.strip().lstrip(":").strip()
                if text:
                    return text
    return None


def _parse_parties(soup) -> list[NyscefParty]:
    """Parse party information from the docket page."""
    parties: list[NyscefParty] = []

    # Look for a parties table or section
    party_table = soup.find("table", id=lambda x: x and "part" in x.lower()) if soup else None
    if not party_table:
        party_table = soup.find(
            "table",
            class_=lambda x: x and any("part" in c.lower() for c in (x if isinstance(x, list) else [x])),
        )

    if party_table:
        for row in party_table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) >= 2:
                name = cells[0].get_text(strip=True)
                role = cells[1].get_text(strip=True) if len(cells) > 1 else None
                attorney = cells[2].get_text(strip=True) if len(cells) > 2 else None
                if name:
                    parties.append(NyscefParty(name=name, role=role, attorney=attorney))

    return parties


def _parse_docket_entries(soup) -> list[NyscefDocketEntry]:
    """Parse docket entries (filings) from the docket page.

    Real NYSCEF docket table uses ``table.NewSearchResults`` with
    headers: #, Document, Filed By, Status.  Rows may have 2-4 cells
    (deleted filings often have only 2).
    """
    entries: list[NyscefDocketEntry] = []

    # Find the document table — same class as search results
    doc_table = None
    for table in soup.find_all("table", class_="NewSearchResults"):
        header_text = table.get_text()[:200].lower()
        if "document" in header_text or "#" in header_text:
            doc_table = table
            break

    if not doc_table:
        return entries

    # Determine column mapping from header row
    header_row = doc_table.find("tr")
    col_map = {}  # column name -> index
    if header_row:
        for i, cell in enumerate(header_row.find_all(["th", "td"])):
            text = cell.get_text(strip=True).lower()
            if text == "#":
                col_map["number"] = i
            elif "document" in text:
                col_map["document"] = i
            elif "filed by" in text:
                col_map["filed_by"] = i
            elif "status" in text:
                col_map["status"] = i
            elif "filing date" in text or "date" in text:
                col_map["date"] = i

    rows = doc_table.find_all("tr")[1:]  # skip header
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        def _col(name: str) -> str | None:
            idx = col_map.get(name)
            if idx is not None and idx < len(cells):
                return cells[idx].get_text(strip=True) or None
            return None

        doc_index = _col("number")
        doc_text = _col("document")
        filed_by = _col("filed_by")
        status = _col("status")
        filing_date = _col("date")

        # The "Document" column often contains description text
        description = doc_text

        if doc_index or description:
            entries.append(NyscefDocketEntry(
                doc_index=doc_index,
                filing_date=filing_date,
                description=description,
                filed_by=filed_by,
                document_type=status,
            ))

    log.debug("Parsed %d docket entries", len(entries))
    return entries
