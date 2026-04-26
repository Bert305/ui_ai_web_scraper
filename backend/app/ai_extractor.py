import os
import json
from typing import Any, Dict, List
from openai import OpenAI


def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAI(api_key=api_key)


def normalize_json_response(text: str) -> List[Dict[str, Any]]:
    """
    Attempts to safely parse model output into a list of dictionaries.
    """
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end])
        else:
            raise ValueError("AI response was not valid JSON.")

    if isinstance(parsed, dict):
        if "data" in parsed and isinstance(parsed["data"], list):
            parsed = parsed["data"]
        else:
            parsed = [parsed]

    if not isinstance(parsed, list):
        raise ValueError("AI response must be a JSON list.")

    return [item for item in parsed if isinstance(item, dict)]


def extract_with_ai(cleaned_html: str, user_prompt: str) -> List[Dict[str, Any]]:
    """
    Uses OpenAI to convert cleaned HTML into structured JSON.
    """
    client = get_openai_client()

    if client is None:
        raise RuntimeError("OPENAI_API_KEY is missing.")

    system_message = """
You are a web scraping extraction assistant.
Your job is to extract structured data from simplified HTML.

Rules:
- Return ONLY valid JSON.
- Return a JSON array of objects.
- Do not include markdown.
- Do not explain anything.
- Use null when a field is missing.
- Preserve URLs exactly when available.
- Extract repeated records when the page contains multiple listings, jobs, products, articles, or rows.
"""

    user_message = f"""
User scraping instruction:
{user_prompt}

Simplified HTML:
{cleaned_html}

Return only a JSON array of objects.
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system_message.strip()},
            {"role": "user", "content": user_message.strip()},
        ],
        temperature=0,
    )

    text = response.choices[0].message.content
    return normalize_json_response(text)
