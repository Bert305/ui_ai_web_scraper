import asyncio
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from urllib.parse import urljoin
from typing import Dict, List, Any

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _fetch_html_sync(url: str) -> str:
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=_USER_AGENT)
        page.goto(url, wait_until="networkidle", timeout=45000)
        html = page.content()
        browser.close()
    return html


async def fetch_html(url: str) -> str:
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        html = await loop.run_in_executor(pool, _fetch_html_sync, url)
    return html


def clean_html_for_ai(html: str, base_url: str = "", max_chars: int = 25000) -> str:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript", "svg", "canvas", "iframe"]):
        tag.decompose()

    parts = []
    has_tables = False

    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = []
            for cell in tr.find_all(["th", "td"]):
                text = cell.get_text(" ", strip=True)
                if text:
                    cells.append(f"<{cell.name}>{text}</{cell.name}>")
            if cells:
                rows.append(f"<tr>{''.join(cells)}</tr>")
        if rows:
            has_tables = True
            parts.append(f"<table>{''.join(rows)}</table>")
        table.decompose()

    # Only include non-table content when the page has no tables — avoids flooding
    # the context with chrome text that duplicates what's already in the table HTML.
    if not has_tables:
        for tag in soup.find_all(["h1", "h2", "h3", "p", "a", "li"]):
            text = tag.get_text(" ", strip=True)
            if not text or len(text) <= 2:
                continue
            attrs = {}
            if tag.name == "a" and tag.get("href"):
                href = tag.get("href")
                if base_url and not href.startswith(("http://", "https://", "mailto:", "//")):
                    href = urljoin(base_url, href)
                attrs["href"] = href
            attr_text = " ".join([f'{k}="{v}"' for k, v in attrs.items()])
            parts.append(f"<{tag.name} {attr_text}>{text}</{tag.name}>")

    combined = "\n".join(parts)
    if len(combined) <= max_chars:
        return combined

    # Truncate at a complete </tr> so the AI never sees a broken row
    truncated = combined[:max_chars]
    last_row = truncated.rfind("</tr>")
    if last_row > 0:
        return truncated[: last_row + len("</tr>")]
    return truncated


def fallback_extract(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    results = []

    # Extract tables first — this is the primary path for data pages
    for table in soup.find_all("table"):
        raw_headers = [th.get_text(" ", strip=True) for th in table.find_all("th")]
        headers = [h.lower().replace(" ", "_").replace("/", "_") for h in raw_headers]

        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if not cells:
                continue
            row = {}
            for i, cell in enumerate(cells):
                key = headers[i] if i < len(headers) else f"col_{i + 1}"
                text = cell.get_text(" ", strip=True)
                if not text:
                    continue
                a = cell.find("a")
                if a and a.get("href"):
                    href = a["href"]
                    if base_url and not href.startswith(("http://", "https://", "mailto://", "//")):
                        href = urljoin(base_url, href)
                    row[key] = text
                    row[f"{key}_url"] = href
                else:
                    row[key] = text
            if row:
                results.append(row)

    if results:
        return results[:500]

    # No tables — fall back to headings + links
    headings = [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"]) if h.get_text(strip=True)]
    links = [
        {"text": a.get_text(" ", strip=True), "url": urljoin(base_url, a.get("href", ""))}
        for a in soup.find_all("a")
        if a.get_text(strip=True) and a.get("href")
    ]

    max_len = max(len(headings), len(links), 1)
    for i in range(max_len):
        row = {}
        if i < len(headings):
            row["heading"] = headings[i]
        if i < len(links):
            row["link_text"] = links[i]["text"]
            row["link_url"] = links[i]["url"]
        if row:
            results.append(row)

    return results[:100]
