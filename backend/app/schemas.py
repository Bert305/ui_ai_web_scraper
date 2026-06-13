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


class SqlGenerationRequest(BaseModel):
    schema_sql: str
    prompt: str
    dialect: str = "postgresql"
    include_queries: bool = True
    include_erd: bool = True
    provider: Optional[str] = None  # anthropic | gemini | openai | auto


class SqlGenerationResponse(BaseModel):
    dialect: str
    prompt: str
    queries: Optional[str] = None
    erd_mermaid: Optional[str] = None


class DataAnalysisResponse(BaseModel):
    filename: str
    prompt: str
    row_count: int
    columns: List[Dict[str, Any]]
    sample: List[Dict[str, Any]] = []
    summary: Optional[str] = None
    kpis: List[Dict[str, Any]] = []
    charts: List[Dict[str, Any]] = []
    sql: Optional[str] = None


class TransformResponse(BaseModel):
    filename: str
    target_mode: str  # ddl | describe | infer | file
    target_table: str
    target_columns: List[Dict[str, Any]]
    mapping: List[Dict[str, Any]]  # per target column: source, op, type badge, notes
    plan: Optional[Dict[str, Any]] = None  # raw plan, for editing + re-running the mapping
    notes: Optional[str] = None
    issues: List[str] = []
    source_row_count: int
    target_row_count: int
    source_columns: List[Dict[str, Any]] = []
    preview: List[Dict[str, Any]] = []  # first N transformed rows
    rows: List[Dict[str, Any]] = []     # full transformed rows (for CSV/JSON export)
    ddl: Optional[str] = None           # target CREATE TABLE
    inserts: Optional[str] = None       # SQL INSERT statements
    script: Optional[str] = None        # generated pandas ETL script
