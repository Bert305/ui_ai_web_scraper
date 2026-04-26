# AI Web Scraper Starter

A full-stack starter app where a user can:

- Enter a URL
- Enter a natural-language scraping prompt
- Scrape page content
- Extract structured data from HTML
- Preview results in a table
- Export results as JSON or CSV

This is a starter project for building a custom scraping tool similar to Browse AI, Apify, or Octoparse.

## Tech Stack

Frontend:
- React
- Vite
- Axios

Backend:
- FastAPI
- BeautifulSoup
- Playwright
- Pandas
- OpenAI API optional

## Project Structure

```txt
ai-web-scraper-starter/
  backend/
    app/
      main.py
      scraper.py
      ai_extractor.py
      exporter.py
      schemas.py
    requirements.txt
    .env.example
  frontend/
    src/
      App.jsx
      api.js
      main.jsx
      styles.css
    package.json
    index.html
  README.md
```

## Backend Setup

```bash
cd backend
python -m venv venv
```

Windows:

```bash
venv\Scripts\activate
```

Mac/Linux:

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
python -m playwright install
```

Create your `.env` file:

```bash
copy .env.example .env
```

Mac/Linux:

```bash
cp .env.example .env
```

Add your OpenAI key if you want AI extraction:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

Run backend:

```bash
uvicorn app.main:app --reload --port 8000
```

Backend runs at:

```txt
http://localhost:8000
```

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at:

```txt
http://localhost:5173
```

## Example Prompts

```txt
Extract job title, company name, location, salary, and apply link.
```

```txt
Extract product name, price, rating, image URL, and product link.
```

```txt
Extract all article titles, authors, dates, summaries, and links.
```

## Notes

Some websites block scraping. Respect robots.txt, site terms, and rate limits.

For production, add:
- User authentication
- Queue/background jobs
- Database storage
- Rate limiting
- Proxy support
- Better selector detection
- robots.txt checks
- Scrape history
