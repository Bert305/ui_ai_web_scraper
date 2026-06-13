import { useEffect, useMemo, useRef, useState } from "react";
import { transformData, exportData, downloadText } from "./api";

const OPS = [
  "direct", "to_int", "to_float", "to_string", "to_bool", "to_date", "to_datetime",
  "lower", "upper", "trim", "constant", "concat", "coalesce", "default", "unmapped",
];
const MULTI_SOURCE = new Set(["concat", "coalesce"]);
const NEEDS_VALUE = new Set(["constant", "default"]);

const EXAMPLE_DDL = `CREATE TABLE customers (
  customer_id INT PRIMARY KEY,
  email TEXT NOT NULL,
  full_name TEXT,
  signup_date DATE,
  is_active BOOLEAN
);`;

const TARGET_MODES = [
  { id: "ddl", label: "Paste SQL DDL" },
  { id: "describe", label: "Describe in English" },
  { id: "infer", label: "Infer from source" },
  { id: "file", label: "Match a spreadsheet" },
];

const BADGE_STYLE = {
  ok: { label: "✓ match", bg: "#e7f7ee", fg: "#0f7a43" },
  cast: { label: "⚠ cast", bg: "#fff4e0", fg: "#9a6400" },
  missing: { label: "● unmapped", bg: "#fdeaea", fg: "#b42318" },
};

function Badge({ kind }) {
  const s = BADGE_STYLE[kind] || BADGE_STYLE.ok;
  return (
    <span style={{
      background: s.bg, color: s.fg, padding: "2px 8px",
      borderRadius: 999, fontSize: 12, fontWeight: 600, whiteSpace: "nowrap",
    }}>
      {s.label}
    </span>
  );
}

export default function Etl() {
  const [file, setFile] = useState(null);
  const [targetMode, setTargetMode] = useState("describe");
  const [targetDdl, setTargetDdl] = useState(EXAMPLE_DDL);
  const [targetPrompt, setTargetPrompt] = useState(
    "Normalize column names to snake_case, type the dates and numbers correctly, and one row per record."
  );
  const [targetFile, setTargetFile] = useState(null);
  const [provider, setProvider] = useState("auto");
  const [includeInserts, setIncludeInserts] = useState(true);
  const [includeDdl, setIncludeDdl] = useState(true);
  const [includeScript, setIncludeScript] = useState(true);

  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const [error, setError] = useState("");
  const [copiedKey, setCopiedKey] = useState("");
  const [exporting, setExporting] = useState("");

  // Editable copy of the raw mappings (source of truth for "re-run with my mapping").
  const [editMappings, setEditMappings] = useState([]);
  const [dirty, setDirty] = useState(false);

  const sourceInputRef = useRef(null);

  const previewColumns = useMemo(
    () => (result?.target_columns || []).map((c) => c.name),
    [result]
  );

  const sourceNames = useMemo(
    () => (result?.source_columns || []).map((c) => c.name),
    [result]
  );

  // When a fresh result arrives, reset the editable mapping to match it.
  useEffect(() => {
    setEditMappings(result?.plan?.mappings ? structuredClone(result.plan.mappings) : []);
    setDirty(false);
  }, [result]);

  function updateMapping(target, patch) {
    setEditMappings((prev) =>
      prev.map((m) => (m.target === target ? { ...m, ...patch } : m))
    );
    setDirty(true);
  }

  async function rerunWithEdits() {
    if (!file || !result?.plan) return;
    setRerunning(true);
    setError("");
    try {
      const planJson = JSON.stringify({
        target_table: result.plan.target_table,
        target_columns: result.plan.target_columns,
        mappings: editMappings,
      });
      const data = await transformData({
        file,
        targetMode,
        provider,
        includeInserts,
        includeDdl,
        includeScript,
        planJson,
      });
      setResult(data);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Re-run failed.");
    } finally {
      setRerunning(false);
    }
  }

  async function handleTransform(e) {
    e.preventDefault();
    if (!file) {
      setError("Choose a source CSV, Excel, or JSON file.");
      return;
    }
    if (targetMode === "ddl" && !targetDdl.trim()) {
      setError("Paste the target DDL, or pick another target mode.");
      return;
    }
    if (targetMode === "file" && !targetFile) {
      setError("Upload the spreadsheet whose columns define the target.");
      return;
    }
    setLoading(true);
    setError("");
    setResult(null);
    setCopiedKey("");

    try {
      const data = await transformData({
        file,
        targetMode,
        targetDdl,
        targetPrompt,
        targetFile,
        provider,
        includeInserts,
        includeDdl,
        includeScript,
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

  async function exportRows(format) {
    if (!result?.rows?.length) return;
    setExporting(format);
    setError("");
    try {
      await exportData(result.rows, format, result.target_table || "transformed");
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Export failed.");
    } finally {
      setExporting("");
    }
  }

  return (
    <>
      <section className="card">
        <form onSubmit={handleTransform} className="form">
          <label>
            Source file (CSV, Excel, or JSON)
            <input
              ref={sourceInputRef}
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
            Define the target schema by…
            <div className="checkboxGroup" role="radiogroup">
              {TARGET_MODES.map((m) => (
                <label className="checkbox" key={m.id}>
                  <input
                    type="radio"
                    name="targetMode"
                    checked={targetMode === m.id}
                    onChange={() => setTargetMode(m.id)}
                  />
                  {m.label}
                </label>
              ))}
            </div>
          </label>

          {targetMode === "ddl" && (
            <label>
              Target DDL (CREATE TABLE)
              <textarea
                value={targetDdl}
                onChange={(e) => setTargetDdl(e.target.value)}
                rows={9}
                placeholder="Paste the CREATE TABLE you want the data to fit..."
              />
            </label>
          )}

          {targetMode === "file" && (
            <label>
              Target spreadsheet (its columns + types become the target)
              <input
                type="file"
                accept=".csv,.tsv,.txt,.xlsx,.xlsm,.xls,.json,application/json,text/csv"
                onChange={(e) => setTargetFile(e.target.files?.[0] || null)}
              />
              {targetFile && (
                <span className="fileHint">Target: <strong>{targetFile.name}</strong></span>
              )}
            </label>
          )}

          <label>
            {targetMode === "describe"
              ? "Describe the target shape"
              : "Extra instructions (optional)"}
            <textarea
              value={targetPrompt}
              onChange={(e) => setTargetPrompt(e.target.value)}
              rows={3}
              placeholder="e.g. snake_case names, parse dates to ISO, drop the notes column."
              required={targetMode === "describe"}
            />
          </label>

          <div className="checkboxGroup">
            <label className="checkbox">
              <input type="checkbox" checked={includeDdl}
                onChange={(e) => setIncludeDdl(e.target.checked)} />
              Generate target DDL
            </label>
            <label className="checkbox">
              <input type="checkbox" checked={includeInserts}
                onChange={(e) => setIncludeInserts(e.target.checked)} />
              Generate SQL INSERT statements
            </label>
            <label className="checkbox">
              <input type="checkbox" checked={includeScript}
                onChange={(e) => setIncludeScript(e.target.checked)} />
              Generate a runnable pandas ETL script
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
            {loading ? "Transforming..." : "Map & Transform"}
          </button>
        </form>

        {error && <div className="error">{error}</div>}
      </section>

      {result && (
        <>
          <section className="card">
            <div className="resultHeader">
              <div>
                <h2>Column Mapping</h2>
                <p>
                  {result.filename} → <code>{result.target_table}</code> ·{" "}
                  {result.source_row_count.toLocaleString()} rows ·{" "}
                  {result.mapping.length} target columns
                </p>
              </div>
              <div className="actions">
                <button onClick={rerunWithEdits} disabled={rerunning || !dirty}>
                  {rerunning ? "Re-running..." : dirty ? "Re-run with my mapping" : "No edits"}
                </button>
              </div>
            </div>
            {result.notes && <p className="summary">{result.notes}</p>}
            <p className="chartMeta">
              Edit any source column or transform below, then re-run — the same pandas
              engine re-executes your mapping (no AI), so values stay exact.
            </p>

            <div className="tableWrap">
              <table>
                <thead>
                  <tr>
                    <th>Target column</th>
                    <th>Type</th>
                    <th>← Source</th>
                    <th>Transform</th>
                    <th>Match</th>
                  </tr>
                </thead>
                <tbody>
                  {result.mapping.map((m) => {
                    const edit = editMappings.find((e) => e.target === m.target) || {};
                    const op = edit.op || "direct";
                    return (
                      <tr key={m.target}>
                        <td>
                          <strong>{m.target}</strong>
                          {m.primary_key && <span title="primary key"> 🔑</span>}
                          {!m.nullable && !m.primary_key && (
                            <span title="NOT NULL" style={{ color: "#b42318" }}> *</span>
                          )}
                        </td>
                        <td><code>{m.target_type}</code></td>
                        <td>
                          {MULTI_SOURCE.has(op) ? (
                            <input
                              type="text"
                              value={(edit.sources || []).join(", ")}
                              placeholder="col_a, col_b"
                              onChange={(e) =>
                                updateMapping(m.target, {
                                  sources: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                                })
                              }
                              style={{ width: "100%" }}
                            />
                          ) : NEEDS_VALUE.has(op) && op === "constant" ? (
                            <em style={{ color: "#888" }}>constant</em>
                          ) : (
                            <select
                              value={edit.source || ""}
                              onChange={(e) => updateMapping(m.target, { source: e.target.value || null })}
                              style={{ width: "100%" }}
                            >
                              <option value="">— none —</option>
                              {sourceNames.map((n) => (
                                <option key={n} value={n}>{n}</option>
                              ))}
                            </select>
                          )}
                          {NEEDS_VALUE.has(op) && (
                            <input
                              type="text"
                              value={edit.value ?? ""}
                              placeholder="value / default"
                              onChange={(e) => updateMapping(m.target, { value: e.target.value })}
                              style={{ width: "100%", marginTop: 4 }}
                            />
                          )}
                        </td>
                        <td>
                          <select
                            value={op}
                            onChange={(e) => updateMapping(m.target, { op: e.target.value })}
                          >
                            {OPS.map((o) => <option key={o} value={o}>{o}</option>)}
                          </select>
                        </td>
                        <td><Badge kind={m.badge} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {result.issues?.length > 0 && (
              <div className="error" style={{ marginTop: 12 }}>
                <strong>Data issues:</strong>
                <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                  {result.issues.map((it, i) => <li key={i}>{it}</li>)}
                </ul>
              </div>
            )}
          </section>

          <section className="card">
            <div className="resultHeader">
              <div>
                <h2>Transformed Data</h2>
                <p>
                  {result.target_row_count.toLocaleString()} rows · showing first{" "}
                  {result.preview.length}
                </p>
              </div>
              <div className="actions">
                <button onClick={() => exportRows("csv")} disabled={exporting === "csv"}>
                  {exporting === "csv" ? "Exporting..." : "Download CSV"}
                </button>
                <button onClick={() => exportRows("json")} disabled={exporting === "json"}>
                  {exporting === "json" ? "Exporting..." : "Download JSON"}
                </button>
              </div>
            </div>
            <div className="tableWrap">
              <table>
                <thead>
                  <tr>{previewColumns.map((c) => <th key={c}>{c}</th>)}</tr>
                </thead>
                <tbody>
                  {result.preview.map((row, i) => (
                    <tr key={i}>
                      {previewColumns.map((c) => <td key={c}>{formatCell(row[c])}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {result.ddl && (
            <CodeCard
              title="Target DDL" subtitle="CREATE TABLE for the target schema"
              code={result.ddl} copyKey="ddl" filename={`${result.target_table}.sql`}
              copiedKey={copiedKey} onCopy={copyText}
            />
          )}
          {result.inserts && (
            <CodeCard
              title="SQL INSERT Statements" subtitle="Insert the transformed rows into the target table"
              code={result.inserts} copyKey="inserts" filename={`${result.target_table}_inserts.sql`}
              copiedKey={copiedKey} onCopy={copyText}
            />
          )}
          {result.script && (
            <CodeCard
              title="pandas ETL Script" subtitle="Runnable Python that reproduces this exact transform"
              code={result.script} copyKey="script" filename={`etl_${result.target_table}.py`}
              copiedKey={copiedKey} onCopy={copyText}
            />
          )}
        </>
      )}
    </>
  );
}

function CodeCard({ title, subtitle, code, copyKey, filename, copiedKey, onCopy }) {
  return (
    <section className="card">
      <div className="resultHeader">
        <div>
          <h2>{title}</h2>
          <p>{subtitle}</p>
        </div>
        <div className="actions">
          <button onClick={() => onCopy(copyKey, code)}>
            {copiedKey === copyKey ? "Copied!" : "Copy"}
          </button>
          <button onClick={() => downloadText(code, filename)}>Download</button>
        </div>
      </div>
      <pre className="codeBlock">{code}</pre>
    </section>
  );
}

function formatCell(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
