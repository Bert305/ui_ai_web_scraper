import { useRef, useState } from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
} from "recharts";
import { inspectColumns, trainModel, downloadText } from "./api";

const CHART_COLORS = [
  "#233ee8", "#7c3aed", "#0ea5e9", "#10b981", "#f59e0b",
  "#ef4444", "#ec4899", "#14b8a6", "#8b5cf6", "#f97316",
];

const MODEL_OPTIONS = [
  { value: "auto", label: "Auto (Random Forest)" },
  { value: "random_forest", label: "Random Forest" },
  { value: "gradient_boosting", label: "Gradient Boosting" },
  { value: "linear", label: "Linear / Logistic Regression" },
];

// --- Confusion matrix rendered as a shaded table (recharts has no heatmap). ---
function ConfusionMatrix({ chart }) {
  const { labels = [], matrix = [] } = chart;
  const max = Math.max(1, ...matrix.flat());
  return (
    <div className="confusionWrap">
      <table className="confusionTable">
        <thead>
          <tr>
            <th className="confusionCorner">actual ＼ predicted</th>
            {labels.map((l) => (
              <th key={l}>{l}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => (
            <tr key={i}>
              <th>{labels[i]}</th>
              {row.map((value, j) => {
                const intensity = value / max;
                const correct = i === j;
                const bg = correct
                  ? `rgba(16, 185, 129, ${0.12 + intensity * 0.7})`
                  : `rgba(239, 68, 68, ${value ? 0.1 + intensity * 0.55 : 0})`;
                return (
                  <td key={j} style={{ background: bg }} title={`actual ${labels[i]} → predicted ${labels[j]}: ${value}`}>
                    {value}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ModelChartCard({ chart }) {
  if (chart.type === "matrix") {
    return (
      <div className="chartCard">
        <h3>{chart.title}</h3>
        <p className="chartMeta">rows = actual class · columns = predicted class</p>
        <ConfusionMatrix chart={chart} />
      </div>
    );
  }

  const data = chart.data || [];

  function body() {
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

    // bar (default) — target distribution, feature importance
    return (
      <BarChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#eef0f6" />
        <XAxis dataKey="x" tick={{ fontSize: 12 }} interval={0} angle={-12} textAnchor="end" height={60} />
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

export default function ModelTrainer() {
  const [file, setFile] = useState(null);
  const [columns, setColumns] = useState([]);
  const [target, setTarget] = useState("");
  const [task, setTask] = useState("auto");
  const [model, setModel] = useState("auto");
  const [testSize, setTestSize] = useState(0.2);
  const [includePython, setIncludePython] = useState(false);

  const [inspecting, setInspecting] = useState(false);
  const [training, setTraining] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [pythonCopied, setPythonCopied] = useState(false);
  const fileInputRef = useRef(null);

  async function handleFileChange(e) {
    const chosen = e.target.files?.[0] || null;
    setFile(chosen);
    setColumns([]);
    setTarget("");
    setResult(null);
    setError("");
    if (!chosen) return;

    setInspecting(true);
    try {
      const profile = await inspectColumns({ file: chosen });
      setColumns(profile.columns || []);
      // Default the target to the last column (commonly the label/outcome).
      const cols = profile.columns || [];
      if (cols.length) {
        const last = cols[cols.length - 1];
        setTarget(last.name);
      }
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Could not read the file's columns.");
    } finally {
      setInspecting(false);
    }
  }

  const selectedColumn = columns.find((c) => c.name === target);

  async function handleTrain(e) {
    e.preventDefault();
    if (!file) {
      setError("Choose a CSV, Excel, or JSON file first.");
      return;
    }
    if (!target) {
      setError("Select the target column you want the model to predict.");
      return;
    }
    setTraining(true);
    setError("");
    setResult(null);
    setPythonCopied(false);

    try {
      const data = await trainModel({ file, target, task, model, testSize, includePython });
      setResult(data);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Training failed.");
    } finally {
      setTraining(false);
    }
  }

  async function copyPython() {
    if (!result?.python_code) return;
    try {
      await navigator.clipboard.writeText(result.python_code);
      setPythonCopied(true);
      setTimeout(() => setPythonCopied(false), 1800);
    } catch {
      setError("Copy failed — your browser may have blocked clipboard access.");
    }
  }

  return (
    <>
      <section className="card">
        <form onSubmit={handleTrain} className="form">
          <label>
            Training data (CSV, Excel, or JSON)
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.tsv,.txt,.xlsx,.xlsm,.xls,.json,application/json,text/csv"
              onChange={handleFileChange}
              required
            />
          </label>
          {file && (
            <p className="fileHint">
              Selected: <strong>{file.name}</strong> ({Math.max(1, Math.round(file.size / 1024))} KB)
              {inspecting && " — reading columns..."}
            </p>
          )}

          {columns.length > 0 && (
            <>
              <label>
                Target column to predict
                <select value={target} onChange={(e) => setTarget(e.target.value)} required>
                  {columns.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name} ({c.type})
                    </option>
                  ))}
                </select>
              </label>
              {selectedColumn && (
                <p className="fileHint">
                  Suggested task for <strong>{selectedColumn.name}</strong>:{" "}
                  <strong>{selectedColumn.suggested_task}</strong> · {selectedColumn.unique} unique values
                </p>
              )}

              <div className="fieldRow">
                <label>
                  Problem type
                  <select value={task} onChange={(e) => setTask(e.target.value)}>
                    <option value="auto">Auto-detect</option>
                    <option value="classification">Classification</option>
                    <option value="regression">Regression</option>
                  </select>
                </label>

                <label>
                  Model
                  <select value={model} onChange={(e) => setModel(e.target.value)}>
                    {MODEL_OPTIONS.map((m) => (
                      <option key={m.value} value={m.value}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label>
                  Test split: {Math.round(testSize * 100)}%
                  <input
                    type="range"
                    min="0.1"
                    max="0.5"
                    step="0.05"
                    value={testSize}
                    onChange={(e) => setTestSize(parseFloat(e.target.value))}
                  />
                </label>
              </div>

              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={includePython}
                  onChange={(e) => setIncludePython(e.target.checked)}
                />
                Also generate a runnable scikit-learn training script that reproduces this model
              </label>
            </>
          )}

          <button disabled={training || inspecting || !columns.length} type="submit">
            {training ? "Training model..." : "Train & Evaluate"}
          </button>
        </form>

        {error && <div className="error">{error}</div>}
      </section>

      {result && (
        <>
          <section className="card">
            <div className="resultHeader">
              <div>
                <h2>Model Results</h2>
                <p>
                  {result.model_name} · predicting <code>{result.target}</code>
                </p>
              </div>
              <div className="badgeRow noCapture">
                <span className={`badge badge-${result.task}`}>
                  {result.task}
                  {result.task_auto_detected ? " (auto)" : ""}
                </span>
              </div>
            </div>

            {result.summary && <p className="summary">{result.summary}</p>}

            <p className="chartMeta">
              {result.n_rows_used.toLocaleString()} rows · trained on {result.n_train.toLocaleString()}, tested on{" "}
              {result.n_test.toLocaleString()} · {result.n_features} features
              {result.skipped_columns?.length > 0 &&
                ` · skipped ${result.skipped_columns.length} column(s): ${result.skipped_columns.join(", ")}`}
            </p>

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
          </section>

          {result.charts?.length > 0 && (
            <section className="card">
              <h2>Visualizations</h2>
              <div className="chartGrid">
                {result.charts.map((chart, i) => (
                  <ModelChartCard chart={chart} key={i} />
                ))}
              </div>
            </section>
          )}

          {result.python_code && (
            <section className="card">
              <div className="resultHeader">
                <div>
                  <h2>scikit-learn Script</h2>
                  <p>Reproduces this model's pipeline and metrics — train it yourself with one command</p>
                </div>
                <div className="actions">
                  <button onClick={copyPython}>{pythonCopied ? "Copied!" : "Copy"}</button>
                  <button onClick={() => downloadText(result.python_code, "train_model.py")}>Download</button>
                </div>
              </div>
              <pre className="codeBlock">{result.python_code}</pre>
            </section>
          )}
        </>
      )}
    </>
  );
}
