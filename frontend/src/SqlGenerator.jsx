import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";
import { generateSql, downloadText } from "./api";

const EXAMPLE_DDL = `CREATE TABLE customers (
  id SERIAL PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE orders (
  id SERIAL PRIMARY KEY,
  customer_id INT NOT NULL REFERENCES customers(id),
  total NUMERIC(10,2) NOT NULL,
  placed_at TIMESTAMP DEFAULT now()
);`;

mermaid.initialize({ startOnLoad: false, theme: "default", securityLevel: "loose" });

function MermaidDiagram({ source }) {
  const containerRef = useRef(null);
  const [renderError, setRenderError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setRenderError("");

    async function render() {
      if (!source || !containerRef.current) return;
      const id = `erd-${Date.now()}`;
      try {
        const { svg } = await mermaid.render(id, source);
        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = svg;
        }
      } catch (err) {
        if (!cancelled) {
          setRenderError(err?.message || "Failed to render ERD.");
        }
      }
    }

    render();
    return () => {
      cancelled = true;
    };
  }, [source]);

  return (
    <>
      <div ref={containerRef} className="erdDiagram" />
      {renderError && (
        <div className="error">
          ERD render error: {renderError}
        </div>
      )}
    </>
  );
}

export default function SqlGenerator() {
  const [schemaSql, setSchemaSql] = useState(EXAMPLE_DDL);
  const [prompt, setPrompt] = useState(
    "Give me queries to find the top 10 customers by total spend in the last 30 days, " +
      "and a query to insert a new order for a customer by email."
  );
  const [dialect] = useState("postgresql");
  const [includeQueries, setIncludeQueries] = useState(true);
  const [includeErd, setIncludeErd] = useState(true);
  const [provider, setProvider] = useState("auto");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copiedKey, setCopiedKey] = useState("");

  async function handleGenerate(e) {
    e.preventDefault();
    if (!includeQueries && !includeErd) {
      setError("Pick at least one output: queries or ERD.");
      return;
    }
    setLoading(true);
    setError("");
    setResult(null);
    setCopiedKey("");

    try {
      const data = await generateSql({
        schemaSql,
        prompt,
        dialect,
        includeQueries,
        includeErd,
        provider,
      });
      setResult(data);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function copyText(key, text) {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(""), 1800);
    } catch {
      setError("Copy failed — your browser may have blocked clipboard access.");
    }
  }

  return (
    <>
      <section className="card">
        <form onSubmit={handleGenerate} className="form">
          <label>
            Database DDL (PostgreSQL)
            <textarea
              value={schemaSql}
              onChange={(e) => setSchemaSql(e.target.value)}
              rows={10}
              placeholder="Paste CREATE TABLE statements here..."
              required
            />
          </label>

          <label>
            What do you want?
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={4}
              placeholder="e.g. Show me the top 10 customers by revenue in the last 30 days."
              required={includeQueries}
            />
          </label>

          <div className="checkboxGroup">
            <label className="checkbox">
              <input
                type="checkbox"
                checked={includeQueries}
                onChange={(e) => setIncludeQueries(e.target.checked)}
              />
              Generate SQL queries (SELECT / INSERT / UPDATE / DELETE)
            </label>

            <label className="checkbox">
              <input
                type="checkbox"
                checked={includeErd}
                onChange={(e) => setIncludeErd(e.target.checked)}
              />
              Generate ERD visual (Mermaid)
            </label>
          </div>

          <label>
            AI Provider
            <select value={provider} onChange={(e) => setProvider(e.target.value)}>
              <option value="auto">Auto-detect (uses first available key)</option>
              <option value="anthropic">Anthropic (Claude)</option>
              <option value="gemini">Google Gemini</option>
              <option value="openai">OpenAI</option>
            </select>
          </label>

          <button disabled={loading} type="submit">
            {loading ? "Generating..." : "Generate"}
          </button>
        </form>

        {error && <div className="error">{error}</div>}
      </section>

      {result?.queries && (
        <section className="card">
          <div className="resultHeader">
            <div>
              <h2>SQL Queries</h2>
              <p>PostgreSQL — grounded on your DDL</p>
            </div>
            <div className="actions">
              <button onClick={() => copyText("queries", result.queries)}>
                {copiedKey === "queries" ? "Copied!" : "Copy"}
              </button>
              <button onClick={() => downloadText(result.queries, "queries.sql")}>
                Download
              </button>
            </div>
          </div>
          <pre className="codeBlock">{result.queries}</pre>
        </section>
      )}

      {result?.erd_mermaid && (
        <section className="card">
          <div className="resultHeader">
            <div>
              <h2>ERD</h2>
              <p>Rendered from Mermaid source</p>
            </div>
            <div className="actions">
              <button onClick={() => copyText("erd", result.erd_mermaid)}>
                {copiedKey === "erd" ? "Copied!" : "Copy Mermaid"}
              </button>
              <button onClick={() => downloadText(result.erd_mermaid, "erd.mmd")}>
                Download
              </button>
            </div>
          </div>
          <MermaidDiagram source={result.erd_mermaid} />
          <details className="mermaidSource">
            <summary>Mermaid source</summary>
            <pre className="codeBlock">{result.erd_mermaid}</pre>
          </details>
        </section>
      )}
    </>
  );
}
