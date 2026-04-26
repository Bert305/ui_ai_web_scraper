import os
import json
from typing import Any, Dict, List

SYSTEM_MESSAGE = """
You are a web scraping extraction assistant.
Your job is to extract structured data from simplified HTML.

Rules:
- Return ONLY valid JSON.
- Return a JSON array of objects.
- Do not include markdown, code fences, or explanations.
- Use null when a field is missing.
- Preserve URLs exactly as they appear — do not shorten or modify them.
- Extract every repeated record when the page contains multiple listings, jobs, products, articles, or table rows.
""".strip()


def _recover_partial_json_array(text: str) -> List[Dict[str, Any]]:
    """Recover complete objects from a truncated JSON array."""
    start = text.find("[")
    if start < 0:
        raise ValueError("No JSON array found in response.")
    # Walk backwards from end to find the last complete object
    for marker in ("}\n]", "},\n", "},", "}\n", "}"):
        pos = text.rfind(marker)
        if pos < start:
            continue
        candidate = text[start : pos + 1] + "]"
        try:
            result = json.loads(candidate)
            if isinstance(result, list):
                return [r for r in result if isinstance(r, dict)]
        except json.JSONDecodeError:
            continue
    raise ValueError("Could not recover any complete records from truncated response.")


def normalize_json_response(text: str) -> List[Dict[str, Any]]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0].strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start:end])
            except json.JSONDecodeError:
                # Response was truncated mid-stream — recover complete rows
                return _recover_partial_json_array(text)
        else:
            # No closing bracket — likely truncated; recover what we can
            return _recover_partial_json_array(text)

    if isinstance(parsed, dict):
        parsed = parsed.get("data", [parsed])

    if not isinstance(parsed, list):
        raise ValueError("AI response must be a JSON list.")

    return [item for item in parsed if isinstance(item, dict)]


def _build_user_message(cleaned_html: str, user_prompt: str) -> str:
    return (
        f"User scraping instruction:\n{user_prompt}\n\n"
        f"Simplified HTML:\n{cleaned_html}\n\n"
        "Return only a JSON array of objects."
    )


def extract_with_anthropic(cleaned_html: str, user_prompt: str) -> List[Dict[str, Any]]:
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is missing.")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=SYSTEM_MESSAGE,
        messages=[{"role": "user", "content": _build_user_message(cleaned_html, user_prompt)}],
    )
    return normalize_json_response(response.content[0].text)


def extract_with_gemini(cleaned_html: str, user_prompt: str) -> List[Dict[str, Any]]:
    import google.generativeai as genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing.")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=SYSTEM_MESSAGE,
    )
    response = model.generate_content(_build_user_message(cleaned_html, user_prompt))
    return normalize_json_response(response.text)


def extract_with_openai(cleaned_html: str, user_prompt: str) -> List[Dict[str, Any]]:
    from openai import OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing.")

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": _build_user_message(cleaned_html, user_prompt)},
        ],
        temperature=0,
    )
    return normalize_json_response(response.choices[0].message.content)


_EXTRACTORS = {
    "anthropic": extract_with_anthropic,
    "gemini": extract_with_gemini,
    "openai": extract_with_openai,
}

_AUTO_DETECT_ORDER = ["anthropic", "gemini", "openai"]
_KEY_NAMES = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def extract_with_ai(
    cleaned_html: str, user_prompt: str, provider: str = None
) -> List[Dict[str, Any]]:
    if provider and provider != "auto":
        if provider not in _EXTRACTORS:
            raise RuntimeError(f"Unknown provider '{provider}'. Use: anthropic, gemini, openai.")
        return _EXTRACTORS[provider](cleaned_html, user_prompt)

    for name in _AUTO_DETECT_ORDER:
        if os.getenv(_KEY_NAMES[name]):
            return _EXTRACTORS[name](cleaned_html, user_prompt)

    raise RuntimeError(
        "No AI API key found. Set ANTHROPIC_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY in your .env file."
    )
