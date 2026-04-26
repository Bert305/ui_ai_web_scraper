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
