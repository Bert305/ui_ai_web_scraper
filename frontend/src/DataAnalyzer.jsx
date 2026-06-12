import { useMemo, useRef, useState } from "react";
import { toJpeg } from "html-to-image";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import { analyzeData, downloadText } from "./api";

const CHART_COLORS = [
  "#233ee8", "#7c3aed", "#0ea5e9", "#10b981", "#f59e0b",
  "#ef4444", "#ec4899", "#14b8a6", "#8b5cf6", "#f97316",
];

function ChartCard({ chart }) {
  const data = chart.data || [];

  function body() {
    if (chart.type === "line") {
      return (
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eef0f6" />
          <XAxis dataKey="x" tick={{ fontSize: 12 }} />
          <YAxis tick={{ fontSize: 12 }} />
          <Tooltip />
          <Line type="monotone" dataKey="y" name={chart.y_label} stroke="#233ee8" strokeWidth={2} dot={false} />
        </LineChart>
      );
    }

    if (chart.type === "pie") {
      return (
        <PieChart>
          <Tooltip />
          <Legend />
          <Pie data={data} dataKey="y" nameKey="x" cx="50%" cy="50%" outerRadius={110} label>
            {data.map((_, i) => (
              <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
            ))}
          </Pie>
        </PieChart>
      );
    }

    if (chart.type === "scatter") {
      return (
        <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eef0f6" />
          <XAxis type="number" dataKey="x" name={chart.x_label} tick={{ fontSize: 12 }} />
          <YAxis type="number" dataKey="y" name={chart.y_label} tick={{ fontSize: 12 }} />
          <Tooltip cursor={{ strokeDasharray: "3 3" }} />
          <Scatter data={data} fill="#233ee8" />
        </ScatterChart>
      );
    }

    // bar (default)
    return (
      <BarChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#eef0f6" />
        <XAxis dataKey="x" tick={{ fontSize: 12 }} interval={0} angle={-12} textAnchor="end" height={50} />
        <YAxis tick={{ fontSize: 12 }} />
        <Tooltip />
        <Bar dataKey="y" name={chart.y_label} radius={[6, 6, 0, 0]}>
          {data.map((_, i) => (
            <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
          ))}
        </Bar>
      </BarChart>
    );
  }

  return (
    <div className="chartCard">
      <h3>{chart.title}</h3>
      <p className="chartMeta">
        {chart.type} · {chart.x_label} × {chart.y_label}
      </p>
      <div className="chartCanvas">
        <ResponsiveContainer width="100%" height={300}>
          {body()}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export default function DataAnalyzer() {
  const [file, setFile] = useState(null);
  const [prompt, setPrompt] = useState(
    "Find the most useful KPIs and metrics in this data, and chart the key breakdowns and trends."
  );
  const [provider, setProvider] = useState("auto");
  const [includeSql, setIncludeSql] = useState(true);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [exporting, setExporting] = useState(false);
  const fileInputRef = useRef(null);
  const captureRef = useRef(null);

  const sampleColumns = useMemo(() => {
    const rows = result?.sample || [];
    const keys = new Set();
    rows.forEach((row) => Object.keys(row).forEach((k) => keys.add(k)));
    return Array.from(keys);
  }, [result]);

  async function handleAnalyze(e) {
    e.preventDefault();
    if (!file) {
      setError("Choose a CSV, Excel, or JSON file to analyze.");
      return;
    }
    setLoading(true);
    setError("");
    setResult(null);
    setCopied(false);

    try {
      const data = await analyzeData({ file, prompt, provider, includeSql });
      setResult(data);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function copySql() {
    if (!result?.sql) return;
    try {
      await navigator.clipboard.writeText(result.sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setError("Copy failed — your browser may have blocked clipboard access.");
    }
  }

  async function downloadJpeg() {
    if (!captureRef.current) return;
    setExporting(true);
    setError("");
    try {
      const dataUrl = await toJpeg(captureRef.current, {
        quality: 0.95,
        backgroundColor: "#f6f7fb",
        pixelRatio: 2,
        cacheBust: true,
        filter: (node) => !node?.classList?.contains?.("noCapture"),
      });
      const baseName = (result?.filename || "data").replace(/\.[^.]+$/, "");
      const link = document.createElement("a");
      link.href = dataUrl;
      link.download = `${baseName}-insights.jpeg`;
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (err) {
      setError(err?.message || "Could not generate the JPEG image.");
    } finally {
      setExporting(false);
    }
  }

  return (
    <>
      <section className="card">
        <form onSubmit={handleAnalyze} className="form">
          <label>
            Spreadsheet file (CSV, Excel, or JSON)
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.tsv,.txt,.xlsx,.xlsm,.xls,.json,application/json,text/csv"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              required
            />
          </label>
          {file && (
            <p className="fileHint">
              Selected: <strong>{file.name}</strong> ({Math.max(1, Math.round(file.size / 1024))} KB)
            </p>
          )}

          <label>
            What stats, KPIs, or metrics do you want?
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={4}
              placeholder="e.g. Show total and average revenue, top regions by sales, and the monthly trend."
              required
            />
          </label>

          <label className="checkbox">
            <input
              type="checkbox"
              checked={includeSql}
              onChange={(e) => setIncludeSql(e.target.checked)}
            />
            Also generate the SQL query that finds the same stats (bonus)
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

          <button disabled={loading} type="submit">
            {loading ? "Analyzing..." : "Analyze & Visualize"}
          </button>
        </form>

        {error && <div className="error">{error}</div>}
      </section>

      {result && (
        <>
          <div ref={captureRef} className="captureRegion">
          <section className="card">
            <div className="resultHeader">
              <div>
                <h2>Insights</h2>
                <p>
                  {result.filename} — {result.row_count.toLocaleString()} rows ·{" "}
                  {result.columns.length} columns
                </p>
              </div>
              {(result.kpis?.length > 0 || result.charts?.length > 0) && (
                <div className="actions noCapture">
                  <button onClick={downloadJpeg} disabled={exporting}>
                    {exporting ? "Rendering..." : "Download JPEG"}
                  </button>
                </div>
              )}
            </div>

            {result.summary && <p className="summary">{result.summary}</p>}

            {result.kpis?.length > 0 && (
              <div className="kpiGrid">
                {result.kpis.map((kpi, i) => (
                  <div className="kpiCard" key={i}>
                    <p className="kpiLabel">{kpi.label}</p>
                    <p className="kpiValue">{kpi.formatted ?? kpi.value}</p>
                    {kpi.description && <p className="kpiDesc">{kpi.description}</p>}
                  </div>
                ))}
              </div>
            )}

            {result.kpis?.length === 0 && result.charts?.length === 0 && (
              <p>The AI did not produce any metrics for this file and prompt. Try a more specific prompt.</p>
            )}
          </section>

          {result.charts?.length > 0 && (
            <section className="card">
              <h2>Visualizations</h2>
              <div className="chartGrid">
                {result.charts.map((chart, i) => (
                  <ChartCard chart={chart} key={i} />
                ))}
              </div>
            </section>
          )}
          </div>

          {result.sql && (
            <section className="card">
              <div className="resultHeader">
                <div>
                  <h2>Equivalent SQL</h2>
                  <p>Runs against a table named <code>data</code> with your columns</p>
                </div>
                <div className="actions">
                  <button onClick={copySql}>{copied ? "Copied!" : "Copy"}</button>
                  <button onClick={() => downloadText(result.sql, "analysis.sql")}>Download</button>
                </div>
              </div>
              <pre className="codeBlock">{result.sql}</pre>
            </section>
          )}

          {result.sample?.length > 0 && (
            <section className="card">
              <h2>Data Preview</h2>
              <p className="chartMeta">First {result.sample.length} rows</p>
              <div className="tableWrap">
                <table>
                  <thead>
                    <tr>
                      {sampleColumns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.sample.map((row, i) => (
                      <tr key={i}>
                        {sampleColumns.map((c) => (
                          <td key={c}>{formatCell(row[c])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </>
  );
}

function formatCell(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
