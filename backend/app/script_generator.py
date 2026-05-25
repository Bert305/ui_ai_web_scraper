import os
import re
from typing import Optional

LANGUAGES = {
    "python-playwright": {
        "label": "Python + Playwright",
        "filename": "scraper.py",
        "notes": (
            "Use playwright.sync_api with a headless Chromium browser. "
            "Wait for networkidle. Parse the rendered HTML with BeautifulSoup (lxml). "
            "Write the extracted rows to scraped_data.csv and scraped_data.json. "
            "Handle relative URLs with urllib.parse.urljoin."
        ),
    },
    "python-bs4": {
        "label": "Python + Requests + BeautifulSoup",
        "filename": "scraper.py",
        "notes": (
            "Use requests with a realistic User-Agent header. Parse with BeautifulSoup (lxml). "
            "This will not execute JavaScript — only use selectors that are visible in the static HTML. "
            "Write the extracted rows to scraped_data.csv and scraped_data.json."
        ),
    },
    "python-scrapy": {
        "label": "Python + Scrapy (single-file spider)",
        "filename": "spider.py",
        "notes": (
            "Write a single-file Scrapy spider that can be run with `scrapy runspider spider.py -o out.json`. "
            "Subclass scrapy.Spider, set name and start_urls, use CSS or XPath selectors in parse(), and yield dicts. "
            "Do not include a separate settings.py — put any needed settings in custom_settings."
        ),
    },
    "node-puppeteer": {
        "label": "Node.js + Puppeteer",
        "filename": "scraper.js",
        "notes": (
            "Use puppeteer with headless: 'new'. waitUntil 'networkidle2'. "
            "Use page.evaluate to extract structured data inside the browser context. "
            "Write the result to scraped_data.json and scraped_data.csv. Use ESM or CommonJS — pick one and stay consistent."
        ),
    },
    "node-cheerio": {
        "label": "Node.js + Axios + Cheerio",
        "filename": "scraper.js",
        "notes": (
            "Use axios with a realistic User-Agent. Parse with cheerio. No JavaScript execution. "
            "Write the result to scraped_data.json and scraped_data.csv."
        ),
    },
}

SYSTEM_MESSAGE = """
You are a senior web scraping engineer. Your job is to write a single, complete, runnable scraping script.

Hard rules:
- Output ONLY the source code. No prose, no explanation, no markdown fences.
- The script must be a single file, runnable as-is once dependencies are installed.
- Include a short header comment at the top: target URL, what is being extracted, and the exact install/run commands.
- Use the selectors that match the HTML the user provides. Do not invent class names or IDs.
- If HTML is provided, ground every selector in what you actually see. If HTML is not provided, write reasonable defensive selectors and add a brief // or # comment noting that selectors should be verified.
- Always save the extracted data to both a JSON file and a CSV file using the filename prefix scraped_data.
- Resolve relative URLs to absolute URLs.
- Be resilient: skip rows where a required field is missing rather than crashing.
- Do not embed secrets or API keys.
""".strip()


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    # Drop leading ```lang and trailing ```
    text = re.sub(r"^```[a-zA-Z0-9_+-]*\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _build_user_message(url: str, prompt: str, language: str, cleaned_html: Optional[str]) -> str:
    spec = LANGUAGES[language]
    parts = [
        f"Target URL: {url}",
        f"What the user wants extracted:\n{prompt}",
        f"Target stack: {spec['label']}",
        f"Stack-specific guidance: {spec['notes']}",
        f"Output filename: {spec['filename']}",
    ]
    if cleaned_html:
        parts.append(
            "Below is the cleaned HTML actually fetched from the target page. "
            "Base every selector on this HTML — class names, IDs, tag structure, attribute names — "
            "so the generated script works against the real page.\n\n"
            f"--- BEGIN HTML ---\n{cleaned_html}\n--- END HTML ---"
        )
    else:
        parts.append(
            "No HTML was fetched. Write defensive, generic selectors and leave a brief comment "
            "noting the selectors should be verified against the live page."
        )
    parts.append("Return ONLY the contents of the script file. No commentary.")
    return "\n\n".join(parts)


def _generate_with_anthropic(user_message: str) -> str:
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is missing.")
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=SYSTEM_MESSAGE,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def _generate_with_gemini(user_message: str) -> str:
    import google.generativeai as genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=SYSTEM_MESSAGE,
    )
    response = model.generate_content(user_message)
    return response.text


def _generate_with_openai(user_message: str) -> str:
    from openai import OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": user_message},
        ],
        temperature=0,
    )
    return response.choices[0].message.content


_GENERATORS = {
    "anthropic": _generate_with_anthropic,
    "gemini": _generate_with_gemini,
    "openai": _generate_with_openai,
}

_AUTO_DETECT_ORDER = ["anthropic", "gemini", "openai"]
_KEY_NAMES = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def generate_script(
    url: str,
    prompt: str,
    language: str,
    cleaned_html: Optional[str],
    provider: Optional[str] = None,
) -> tuple[str, str]:
    """Returns (code, filename)."""
    if language not in LANGUAGES:
        raise RuntimeError(
            f"Unknown language '{language}'. Use one of: {', '.join(LANGUAGES.keys())}."
        )

    user_message = _build_user_message(url, prompt, language, cleaned_html)

    if provider and provider != "auto":
        if provider not in _GENERATORS:
            raise RuntimeError(f"Unknown provider '{provider}'. Use: anthropic, gemini, openai.")
        raw = _GENERATORS[provider](user_message)
    else:
        chosen = next((n for n in _AUTO_DETECT_ORDER if os.getenv(_KEY_NAMES[n])), None)
        if not chosen:
            raise RuntimeError(
                "No AI API key found. Set ANTHROPIC_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY in your .env file."
            )
        raw = _GENERATORS[chosen](user_message)

    code = _strip_code_fences(raw)
    return code, LANGUAGES[language]["filename"]
