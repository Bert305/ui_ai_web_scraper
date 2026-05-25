from pydantic import BaseModel, HttpUrl
from typing import Any, Dict, List, Optional


class ScrapeRequest(BaseModel):
    url: HttpUrl
    prompt: str
    use_ai: bool = True
    provider: Optional[str] = None  # anthropic | gemini | openai | auto (None = auto)


class ScrapeResponse(BaseModel):
    url: str
    prompt: str
    data: List[Dict[str, Any]]
    fields: List[str]
    raw_preview: Optional[str] = None
    ai_error: Optional[str] = None


class ExportRequest(BaseModel):
    data: List[Dict[str, Any]]
    format: str


class ScriptGenerationRequest(BaseModel):
    url: HttpUrl
    prompt: str
    language: str  # python-playwright | python-bs4 | python-requests | python-scrapy | node-puppeteer | node-cheerio
    provider: Optional[str] = None  # anthropic | gemini | openai | auto
    ground_on_html: bool = True  # fetch the page and feed cleaned HTML to the AI for accurate selectors


class ScriptGenerationResponse(BaseModel):
    url: str
    prompt: str
    language: str
    filename: str
    code: str
    grounded: bool
