from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from urllib.parse import urljoin
from typing import Dict, List, Any


async def fetch_html(url: str) -> str:
    """
    Loads a webpage with Playwright.
    This works better than requests for JavaScript-heavy websites.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )

        await page.goto(url, wait_until="networkidle", timeout=45000)
        html = await page.content()
        await browser.close()

    return html


def clean_html_for_ai(html: str, max_chars: int = 15000) -> str:
    """
    Removes noisy tags and returns simplified text/html.
    This keeps enough structure for AI extraction without sending huge HTML.
    """
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript", "svg", "canvas", "iframe"]):
        tag.decompose()

    meaningful_tags = []
    for tag in soup.find_all(["h1", "h2", "h3", "p", "a", "li", "span", "div", "article", "section"]):
        text = tag.get_text(" ", strip=True)
        if text and len(text) > 2:
            attrs = {}
            if tag.get("class"):
                attrs["class"] = " ".join(tag.get("class"))
            if tag.get("id"):
                attrs["id"] = tag.get("id")
            if tag.name == "a" and tag.get("href"):
                attrs["href"] = tag.get("href")

            attr_text = " ".join([f'{k}="{v}"' for k, v in attrs.items()])
            meaningful_tags.append(f"<{tag.name} {attr_text}>{text}</{tag.name}>")

    cleaned = "\n".join(meaningful_tags)
    return cleaned[:max_chars]


def fallback_extract(html: str, base_url: str) -> List[Dict[str, Any]]:
    """
    Basic non-AI fallback extractor.
    Returns headings and links.
    """
    soup = BeautifulSoup(html, "lxml")

    results = []

    headings = []
    for h in soup.find_all(["h1", "h2", "h3"]):
        text = h.get_text(" ", strip=True)
        if text:
            headings.append(text)

    links = []
    for a in soup.find_all("a"):
        text = a.get_text(" ", strip=True)
        href = a.get("href")
        if text and href:
            links.append({
                "text": text,
                "url": urljoin(base_url, href)
            })

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
