import logging
import traceback

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)

from .schemas import ScrapeRequest, ScrapeResponse, ExportRequest
from .scraper import fetch_html, clean_html_for_ai, fallback_extract
from .ai_extractor import extract_with_ai
from .exporter import export_csv, export_json

load_dotenv()

app = FastAPI(title="AI Web Scraper API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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


@app.post("/export")
async def export_data(request: ExportRequest):
    export_format = request.format.lower().strip()

    if export_format == "json":
        return export_json(request.data)

    if export_format == "csv":
        return export_csv(request.data)

    raise HTTPException(status_code=400, detail="Format must be csv or json.")
