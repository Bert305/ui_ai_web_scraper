import { useMemo, useState } from "react";
import { scrapeWebsite, exportData } from "./api";

export default function Scraper() {
  const [url, setUrl] = useState("");
  const [prompt, setPrompt] = useState(
    "Extract title, description, price, location, company name, and link if available."
  );
  const [useAi, setUseAi] = useState(true);
  const [provider, setProvider] = useState("auto");
  const [result, setResult] = useState(null);
  const [rawPreviewOpen, setRawPreviewOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const rows = result?.data || [];

  const columns = useMemo(() => {
    const keys = new Set();
    rows.forEach((row) => {
      Object.keys(row).forEach((key) => keys.add(key));
    });
    return Array.from(keys);
  }, [rows]);

  async function handleScrape(e) {
    e.preventDefault();
    setLoading(true);
    setError("");
    setResult(null);

    try {
      const data = await scrapeWebsite({ url, prompt, useAi, provider });
      setResult(data);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function handleExport(format) {
    if (!rows.length) return;
    await exportData(rows, format);
  }

  return (
    <>
      <section className="card">
        <form onSubmit={handleScrape} className="form">
          <label>
            URL to Scrape
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/jobs"
              required
            />
          </label>

          <label>
            Scraping Prompt
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={5}
              placeholder="Extract job title, company, location, salary, and apply link."
              required
            />
          </label>

          <label className="checkbox">
            <input
              type="checkbox"
              checked={useAi}
              onChange={(e) => setUseAi(e.target.checked)}
            />
            Use AI extraction
          </label>

          {useAi && (
            <label>
              AI Provider
              <select value={provider} onChange={(e) => setProvider(e.target.value)}>
                <option value="auto">Auto-detect (uses first available key)</option>
                <option value="anthropic">Anthropic (Claude)</option>
                <option value="gemini">Google Gemini</option>
                <option value="openai">OpenAI</option>
              </select>
            </label>
          )}

          <button disabled={loading} type="submit">
            {loading ? "Scraping..." : "Scrape Website"}
          </button>
        </form>

        {error && <div className="error">{error}</div>}
        {result?.ai_error && (
          <div className="error">
            AI extraction failed — showing fallback table data instead.<br />
            <small>{result.ai_error}</small>
          </div>
        )}
      </section>

      {result && (
        <section className="card">
          <div className="resultHeader">
            <div>
              <h2>Scraped Results</h2>
              <p>{rows.length} record(s) found</p>
            </div>

            <div className="actions">
              <button onClick={() => handleExport("csv")} disabled={!rows.length}>
                Export CSV
              </button>
              <button onClick={() => handleExport("json")} disabled={!rows.length}>
                Export JSON
              </button>
            </div>
          </div>

          {rows.length > 0 ? (
            <div className="tableWrap">
              <table>
                <thead>
                  <tr>
                    {columns.map((column) => (
                      <th key={column}>{column}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, index) => (
                    <tr key={index}>
                      {columns.map((column) => (
                        <td key={column}>{formatCell(row[column])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p>No data returned.</p>
          )}

          <button
            className="secondary"
            onClick={() => setRawPreviewOpen((value) => !value)}
          >
            {rawPreviewOpen ? "Hide HTML Preview" : "Show Cleaned HTML Preview"}
          </button>

          {rawPreviewOpen && (
            <pre className="rawPreview">{result.raw_preview}</pre>
          )}
        </section>
      )}
    </>
  );
}

function formatCell(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
