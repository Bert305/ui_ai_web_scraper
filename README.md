# AI Web Scraper


A full-stack web scraper and database-tooling app with three modes:

**Scrape Data** — for end users:
- Enter a URL and a natural-language prompt
- Scrape JavaScript-heavy pages using a headless browser
- Extract structured data with your choice of AI provider
- Preview results in a table
- Export as CSV or JSON

**Generate Script** — for developers:
- Enter a URL, describe what to extract, pick a target stack (Python+Playwright, Python+BS4, Scrapy, Node+Puppeteer, Node+Cheerio)
- The backend fetches the page and feeds the cleaned HTML to the AI so generated selectors match the real DOM
- Copy or download a single runnable script file

**SQL & ERD** — for working against a database schema:
- Paste your PostgreSQL DDL (CREATE TABLE statements) and describe what you want
- Generate SQL queries (SELECT / INSERT / UPDATE / DELETE) grounded in your exact tables and columns
- Generate a Mermaid ERD that renders inline in the browser
- Copy or download queries (`.sql`) and ERD source (`.mmd`)

Built as a custom alternative to tools like Browse AI, Apify, or Octoparse.

## Tech Stack

**Frontend:** React, Vite, Axios, Mermaid

**Backend:** FastAPI, Playwright, BeautifulSoup, Anthropic SDK, Google Generative AI, OpenAI SDK

## AI Providers

The tool supports three AI providers. Set any key in `.env` — the backend auto-detects whichever is available, preferring Anthropic first. You can also select a provider manually per request from the UI dropdown.

| Provider | Key | Model |
|---|---|---|
| Anthropic (Claude) | `ANTHROPIC_API_KEY` | claude-sonnet-4-6 |
| Google Gemini | `GEMINI_API_KEY` | gemini-2.0-flash |
| OpenAI | `OPENAI_API_KEY` | gpt-4.1-mini |

If AI extraction fails, the scraper automatically falls back to a BeautifulSoup-based extractor that reads table headers and rows directly from the HTML — no AI required.

## Project Structure

```
ui_ai_web_scraper/
  backend/
    app/
      main.py             # FastAPI routes
      scraper.py          # Playwright fetch + HTML cleaning + fallback extractor
      ai_extractor.py     # AI data-extraction logic (Anthropic / Gemini / OpenAI)
      script_generator.py # AI script-generation logic (per-stack prompting)
      sql_generator.py    # AI SQL-query + Mermaid-ERD generation
      exporter.py         # CSV and JSON export
      schemas.py          # Request/response models
    requirements.txt
    .env
  frontend/
    src/
      App.jsx              # Tabbed UI shell (Scrape Data / Generate Script / SQL & ERD)
      Scraper.jsx          # Scrape Data tab
      ScriptGenerator.jsx  # Generate Script tab
      SqlGenerator.jsx     # SQL & ERD tab (Mermaid rendered inline)
      api.js               # Axios calls to backend
      main.jsx
  README.md
```

## Backend Setup

```bash
cd backend
python -m venv venv
```

**Windows:**
```bash
venv\Scripts\activate
```

**Mac/Linux:**
```bash
source venv/bin/activate
```

Install dependencies and Playwright browsers:

```bash
pip install -r requirements.txt
python -m playwright install
```

Create your `.env` file and add at least one AI key:

```env
ANTHROPIC_API_KEY=your_anthropic_key_here
GEMINI_API_KEY=your_gemini_key_here
OPENAI_API_KEY=your_openai_key_here
```

Run the backend:

```bash
uvicorn app.main:app --reload --port 8000
```

Runs at `http://localhost:8000`

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Runs at `http://localhost:5173`

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/scrape` | Fetch a URL, extract structured data with AI (or fallback) |
| `POST` | `/generate-script` | Fetch a URL, generate a runnable scraping script in the requested language |
| `POST` | `/generate-sql` | From a pasted PostgreSQL DDL + prompt, return SQL queries and/or a Mermaid ERD |
| `POST` | `/export` | Convert a JSON array to CSV or JSON download |

## How It Works

1. Playwright loads the page in a headless Chromium browser (handles JavaScript-rendered content)
2. BeautifulSoup cleans the HTML — tables are extracted first and preserved as structured `<table><tr><td>` markup; surrounding page chrome is excluded when tables are present
3. The cleaned HTML is sent to the selected AI provider with your prompt
4. The AI returns a JSON array of objects; the backend parses and recovers partial responses if the output was truncated
5. Results are displayed in a table and available for export

## Example Prompts

```
Extract job title, company name, location, salary, and apply link.
```

```
Extract product name, price, rating, and product link for each item.
```

```
Extract all article titles, authors, publish dates, and links.
```

```
Give me the trade or occupation, committee name, and type for each row.
```

## Example SQL Prompts

Paste your `CREATE TABLE` statements into the **SQL & ERD** tab, then describe what you want:

```
Give me a query for the top 10 customers by total spend in the last 30 days,
and a query to insert a new order for a customer by email.
```

```
Show all orders placed in the last 7 days that have no shipment record yet.
```

```
Update product prices by 5% for items in the "electronics" category.
```

The generator grounds every query on the exact tables and columns in your DDL — it won't invent column names. The ERD output is Mermaid source that renders inline in the browser and can be downloaded as a `.mmd` file.

## Windows Note

Playwright requires a `ProactorEventLoop` to spawn subprocesses on Windows. The backend sets `WindowsProactorEventLoopPolicy` automatically before each Playwright call — no manual configuration needed.

## Notes

- Some websites block scraping. Respect `robots.txt`, site terms, and rate limits.
- If AI extraction is disabled, the fallback extractor still returns full table data using column headers from `<th>` elements.
- AI errors are shown in the UI so you can see exactly what failed rather than silently receiving wrong data.

For production, consider adding:
- User authentication
- Background job queue
- Database storage for scrape history
- Rate limiting and proxy support
- `robots.txt` compliance checks
