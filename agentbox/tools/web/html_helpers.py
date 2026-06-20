"""
HTML parsing helpers for link and table extraction.

Extracted from web_extract_tool so they can be imported without
kgraphplanner dependency.
"""

from agentbox.tools.web.models import LinkItem, TableRow


def _parse_links_from_html(html: str) -> list[LinkItem]:
    """Extract links from an HTML string."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        href = a["href"]
        if href and not href.startswith(("javascript:", "#")):
            links.append(LinkItem(text=text or None, href=href))
    return links


def _parse_table_from_html(html: str) -> list[TableRow]:
    """Extract the first table from HTML as a list of row dicts."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []

    # Extract headers
    headers = []
    header_row = table.find("tr")
    if header_row:
        for th in header_row.find_all(["th", "td"]):
            headers.append(th.get_text(strip=True))

    rows = []
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        values = {}
        for i, cell in enumerate(cells):
            key = headers[i] if i < len(headers) else f"col_{i}"
            values[key] = cell.get_text(strip=True) or None
        rows.append(TableRow(values=values))
    return rows
