import logging
import traceback

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

logging.basicConfig(level=logging.INFO)

from .schemas import (
    ScrapeRequest,
    ScrapeResponse,
    ExportRequest,
    ScriptGenerationRequest,
    ScriptGenerationResponse,
    SqlGenerationRequest,
    SqlGenerationResponse,
    DataAnalysisResponse,
)
from .scraper import fetch_html, clean_html_for_ai, fallback_extract
from .ai_extractor import extract_with_ai
from .script_generator import generate_script
from .sql_generator import generate_sql
from .data_analyzer import analyze_data
from .exporter import export_csv, export_json

load_dotenv()

app = FastAPI(title="AI Web Scraper API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health_check():
    return {"status": "ok", "message": "AI Web Scraper API is running"}


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(request: ScrapeRequest):
    url = str(request.url)

    try:
        html = await fetch_html(url)
        cleaned_html = clean_html_for_ai(html, base_url=url)

        ai_error = None
        if request.use_ai:
            try:
                data = extract_with_ai(cleaned_html, request.prompt, provider=request.provider)
            except Exception as exc:
                logging.error("AI extraction failed:\n%s", traceback.format_exc())
                ai_error = str(exc)
                data = fallback_extract(html, url)
        else:
            data = fallback_extract(html, url)

        fields = sorted({key for row in data for key in row.keys()})

        return ScrapeResponse(
            url=url,
            prompt=request.prompt,
            data=data,
            fields=fields,
            raw_preview=cleaned_html[:3000],
            ai_error=ai_error,
        )

    except Exception as error:
        logging.error("Scrape error:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(error))


@app.post("/generate-script", response_model=ScriptGenerationResponse)
async def generate_script_endpoint(request: ScriptGenerationRequest):
    url = str(request.url)

    try:
        cleaned_html = None
        if request.ground_on_html:
            html = await fetch_html(url)
            cleaned_html = clean_html_for_ai(html, base_url=url)

        code, filename = generate_script(
            url=url,
            prompt=request.prompt,
            language=request.language,
            cleaned_html=cleaned_html,
            provider=request.provider,
        )

        return ScriptGenerationResponse(
            url=url,
            prompt=request.prompt,
            language=request.language,
            filename=filename,
            code=code,
            grounded=cleaned_html is not None,
        )

    except Exception as error:
        logging.error("Script generation error:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(error))


@app.post("/generate-sql", response_model=SqlGenerationResponse)
async def generate_sql_endpoint(request: SqlGenerationRequest):
    try:
        result = generate_sql(
            schema_sql=request.schema_sql,
            prompt=request.prompt,
            dialect=request.dialect,
            include_queries=request.include_queries,
            include_erd=request.include_erd,
            provider=request.provider,
        )

        return SqlGenerationResponse(
            dialect=request.dialect,
            prompt=request.prompt,
            queries=result["queries"],
            erd_mermaid=result["erd_mermaid"],
        )

    except Exception as error:
        logging.error("SQL generation error:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(error))


@app.post("/analyze-data", response_model=DataAnalysisResponse)
async def analyze_data_endpoint(
    file: UploadFile = File(...),
    prompt: str = Form(...),
    provider: Optional[str] = Form(None),
    include_sql: bool = Form(True),
):
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        result = analyze_data(
            file_bytes=content,
            filename=file.filename or "upload.csv",
            prompt=prompt,
            provider=provider,
            include_sql=include_sql,
        )

        return DataAnalysisResponse(
            filename=file.filename or "upload.csv",
            prompt=prompt,
            **result,
        )

    except HTTPException:
        raise
    except Exception as error:
        logging.error("Data analysis error:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(error))


@app.post("/export")
async def export_data(request: ExportRequest):
    export_format = request.format.lower().strip()

    if export_format == "json":
        return export_json(request.data)

    if export_format == "csv":
        return export_csv(request.data)

    raise HTTPException(status_code=400, detail="Format must be csv or json.")
