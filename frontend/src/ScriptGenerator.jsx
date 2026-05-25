import { useState } from "react";
import { generateScript, downloadText } from "./api";

const LANGUAGE_OPTIONS = [
  { value: "python-playwright", label: "Python + Playwright (handles JS-rendered pages)" },
  { value: "python-bs4", label: "Python + Requests + BeautifulSoup (static HTML only)" },
  { value: "python-scrapy", label: "Python + Scrapy (single-file spider)" },
  { value: "node-puppeteer", label: "Node.js + Puppeteer (handles JS-rendered pages)" },
  { value: "node-cheerio", label: "Node.js + Axios + Cheerio (static HTML only)" },
];

export default function ScriptGenerator() {
  const [url, setUrl] = useState("");
  const [prompt, setPrompt] = useState(
    "Extract job title, company, location, salary, and apply link for each listing."
  );
  const [language, setLanguage] = useState("python-playwright");
  const [provider, setProvider] = useState("auto");
  const [groundOnHtml, setGroundOnHtml] = useState(true);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  async function handleGenerate(e) {
    e.preventDefault();
    setLoading(true);
    setError("");
    setResult(null);
    setCopied(false);

    try {
      const data = await generateScript({ url, prompt, language, provider, groundOnHtml });
      setResult(data);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function handleCopy() {
    if (!result?.code) return;
    try {
      await navigator.clipboard.writeText(result.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setError("Copy failed — your browser may have blocked clipboard access.");
    }
  }

  function handleDownload() {
    if (!result?.code) return;
    downloadText(result.code, result.filename);
  }

  return (
    <>
      <section className="card">
        <form onSubmit={handleGenerate} className="form">
          <label>
            Target URL
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/jobs"
              required
            />
          </label>

          <label>
            What should the script extract?
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={5}
              placeholder="Extract product name, price, rating, and product link for each item."
              required
            />
          </label>

          <label>
            Target Stack
            <select value={language} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label>
            AI Provider
            <select value={provider} onChange={(e) => setProvider(e.target.value)}>
              <option value="auto">Auto-detect (uses first available key)</option>
              <option value="anthropic">Anthropic (Claude)</option>
              <option value="gemini">Google Gemini</option>
              <option value="openai">OpenAI</option>
            </select>
          </label>

          <label className="checkbox">
            <input
              type="checkbox"
              checked={groundOnHtml}
              onChange={(e) => setGroundOnHtml(e.target.checked)}
            />
            Ground selectors on the live page (recommended — fetches the URL first so selectors match the real DOM)
          </label>

          <button disabled={loading} type="submit">
            {loading
              ? groundOnHtml
                ? "Fetching page and generating..."
                : "Generating..."
              : "Generate Script"}
          </button>
        </form>

        {error && <div className="error">{error}</div>}
      </section>

      {result && (
        <section className="card">
          <div className="resultHeader">
            <div>
              <h2>{result.filename}</h2>
              <p>
                {LANGUAGE_OPTIONS.find((o) => o.value === result.language)?.label}
                {" — "}
                {result.grounded ? "grounded on fetched HTML" : "generic (no HTML fetched)"}
              </p>
            </div>

            <div className="actions">
              <button onClick={handleCopy}>{copied ? "Copied!" : "Copy"}</button>
              <button onClick={handleDownload}>Download</button>
            </div>
          </div>

          <pre className="codeBlock">{result.code}</pre>
        </section>
      )}
    </>
  );
}
