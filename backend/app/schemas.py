from pydantic import BaseModel, HttpUrl
from typing import Any, Dict, List, Optional


class ScrapeRequest(BaseModel):
    url: HttpUrl
    prompt: str
    use_ai: bool = True


class ScrapeResponse(BaseModel):
    url: str
    prompt: str
    data: List[Dict[str, Any]]
    fields: List[str]
    raw_preview: Optional[str] = None


class ExportRequest(BaseModel):
    data: List[Dict[str, Any]]
    format: str
