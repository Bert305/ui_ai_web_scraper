"""Spreadsheet analytics: profile an uploaded CSV/Excel file, ask the AI for an
analysis *plan* (which columns and aggregations answer the user's prompt), then
execute that plan with pandas so the KPI and chart numbers are exact — not
hallucinated. Also returns an equivalent SQL query as a bonus.

The AI never sees the full dataset (only a compact profile + sample rows), so it
decides *what* to compute; pandas decides the *values*. This keeps results
accurate even for large files.
"""

import io
import os
import json
import math
import re
from typing import Any, Dict, List, Optional

import pandas as pd

ANALYSIS_SYSTEM = """
You are a senior data analyst. Given a profile of a tabular dataset and the user's request,
produce an ANALYSIS PLAN describing which columns and aggregations answer the request.
You do NOT compute the numbers yourself — a pandas engine executes your plan and fills in exact values.

Output rules:
- Return ONLY a single valid JSON object. No prose, no markdown, no code fences.
- Use the EXACT column names from the profile. Never invent columns.
- Shape:
{
  "summary": "1-2 sentence plain-language overview of what the analysis shows",
  "kpis": [
    {"label": "Total Revenue", "agg": "sum", "column": "revenue", "format": "currency", "description": "short why-it-matters"}
  ],
  "charts": [
    {"title": "Revenue by Region", "type": "bar", "x": "region", "y": "revenue", "agg": "sum", "sort": "desc", "limit": 10}
  ],
  "sql": "SELECT region, SUM(revenue) AS revenue FROM data GROUP BY region ORDER BY revenue DESC LIMIT 10;"
}

Field rules:
- agg is one of: sum, mean, median, min, max, count, nunique. Use "count" for row counts (column may be null).
- KPI "format" is one of: number, currency, percent. Choose what reads best.
- Chart "type" is one of: bar, line, pie, scatter.
    bar/pie: x = a categorical column to group by, y = numeric column to aggregate (or null with agg=count).
    line: x = a time/ordered column, y = numeric column to aggregate.
    scatter: x and y are both numeric columns (no aggregation).
- "sort" is "asc" or "desc" (applies to bar/pie by aggregated value). "limit" caps categories (default 10).
- Propose 3-6 KPIs and 2-4 charts that best satisfy the request and suit the column types.
- The SQL targets a single table literally named `data` whose columns are the profile columns.
  Use standard SQL that reproduces the headline metric(s) from the request. One statement, no fences.
""".strip()

_AGG_ALIASES = {"avg": "mean", "average": "mean"}
_VALID_AGGS = {"sum", "mean", "median", "min", "max", "count", "nunique"}


# --------------------------------------------------------------------------- #
# File reading
# --------------------------------------------------------------------------- #
def _read_json(file_bytes: bytes) -> pd.DataFrame:
    """Accept a JSON array of objects, or an object wrapping one under a
    list-valued key (e.g. {"data": [...]}), or a single object."""
    parsed = json.loads(file_bytes.decode("utf-8-sig"))
    if isinstance(parsed, dict):
        records = next((v for v in parsed.values() if isinstance(v, list)), None)
        parsed = records if records is not None else [parsed]
    if not isinstance(parsed, list):
        raise RuntimeError("JSON must be an array of objects (records).")
    return pd.json_normalize(parsed)


def read_table(file_bytes: bytes, filename: str) -> pd.DataFrame:
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        df = pd.read_excel(io.BytesIO(file_bytes))
    elif name.endswith(".json"):
        df = _read_json(file_bytes)
    elif name.endswith((".csv", ".tsv", ".txt")):
        sep = "\t" if name.endswith(".tsv") else ","
        df = pd.read_csv(io.BytesIO(file_bytes), sep=sep)
    else:
        # Best effort: try CSV, then JSON, then Excel.
        for reader in (
            lambda b: pd.read_csv(io.BytesIO(b)),
            _read_json,
            lambda b: pd.read_excel(io.BytesIO(b)),
        ):
            try:
                df = reader(file_bytes)
                break
            except Exception:
                continue
        else:
            raise RuntimeError("Could not parse the file as CSV, JSON, or Excel.")

    if df.empty:
        raise RuntimeError("The uploaded file has no rows.")
    # Normalize column names to strings and strip whitespace.
    df.columns = [str(c).strip() for c in df.columns]
    return df


# --------------------------------------------------------------------------- #
# JSON-safe helpers
# --------------------------------------------------------------------------- #
def _jsonsafe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, (int, str, bool)):
        return value
    # numpy scalars / timestamps / etc.
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return _jsonsafe(value.item())
        except Exception:
            pass
    return str(value)


def _column_kind(series: pd.Series) -> str:
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "categorical"


# --------------------------------------------------------------------------- #
# Profiling
# --------------------------------------------------------------------------- #
def profile_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    columns: List[Dict[str, Any]] = []
    for name in df.columns:
        series = df[name]
        kind = _column_kind(series)
        info: Dict[str, Any] = {
            "name": name,
            "type": kind,
            "non_null": int(series.notna().sum()),
            "unique": int(series.nunique(dropna=True)),
        }
        if kind == "numeric":
            info["min"] = _jsonsafe(series.min())
            info["max"] = _jsonsafe(series.max())
            info["mean"] = _jsonsafe(series.mean())
        else:
            info["sample_values"] = [
                _jsonsafe(v) for v in series.dropna().astype(str).unique()[:8]
            ]
        columns.append(info)

    sample = [
        {k: _jsonsafe(v) for k, v in row.items()}
        for row in df.head(5).to_dict(orient="records")
    ]
    return {"row_count": int(len(df)), "columns": columns, "sample": sample}


# --------------------------------------------------------------------------- #
# AI plan
# --------------------------------------------------------------------------- #
def _build_plan_message(profile: Dict[str, Any], prompt: str, include_sql: bool) -> str:
    sql_note = (
        "Include a useful `sql` value."
        if include_sql
        else "Set `sql` to null (the user does not want SQL)."
    )
    return (
        f"User request:\n{prompt}\n\n"
        f"Dataset profile (JSON):\n{json.dumps(profile, indent=2)}\n\n"
        f"{sql_note}\n"
        "Return ONLY the analysis plan JSON object."
    )


def _strip_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_+-]*\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        raise ValueError("AI did not return a JSON object.")


def _call_anthropic(system: str, user_message: str) -> str:
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is missing.")
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def _call_gemini(system: str, user_message: str) -> str:
    import google.generativeai as genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name="gemini-2.0-flash", system_instruction=system)
    response = model.generate_content(user_message)
    return response.text


def _call_openai(system: str, user_message: str) -> str:
    from openai import OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
        temperature=0,
    )
    return response.choices[0].message.content


_CALLERS = {"anthropic": _call_anthropic, "gemini": _call_gemini, "openai": _call_openai}
_AUTO_DETECT_ORDER = ["anthropic", "gemini", "openai"]
_KEY_NAMES = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def _resolve_provider(provider: Optional[str]) -> str:
    if provider and provider != "auto":
        if provider not in _CALLERS:
            raise RuntimeError(f"Unknown provider '{provider}'. Use: anthropic, gemini, openai.")
        return provider
    chosen = next((n for n in _AUTO_DETECT_ORDER if os.getenv(_KEY_NAMES[n])), None)
    if not chosen:
        raise RuntimeError(
            "No AI API key found. Set ANTHROPIC_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY in your .env file."
        )
    return chosen


def build_analysis_plan(
    profile: Dict[str, Any], prompt: str, provider: Optional[str], include_sql: bool
) -> Dict[str, Any]:
    resolved = _resolve_provider(provider)
    raw = _CALLERS[resolved](ANALYSIS_SYSTEM, _build_plan_message(profile, prompt, include_sql))
    plan = _strip_json(raw)
    if not isinstance(plan, dict):
        raise ValueError("AI plan must be a JSON object.")
    return plan


# --------------------------------------------------------------------------- #
# Plan execution (pandas — the source of truth for all numbers)
# --------------------------------------------------------------------------- #
def _normalize_agg(agg: Optional[str]) -> str:
    agg = (agg or "count").strip().lower()
    agg = _AGG_ALIASES.get(agg, agg)
    return agg if agg in _VALID_AGGS else "count"


def _format_value(value: Optional[float], fmt: str) -> Optional[str]:
    if value is None:
        return None
    fmt = (fmt or "number").lower()
    is_int = isinstance(value, (int,)) or (isinstance(value, float) and value == int(value))
    if fmt == "currency":
        return f"${value:,.2f}"
    if fmt == "percent":
        return f"{value:,.1f}%"
    if is_int and abs(value) < 1e15:
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _compute_kpi(df: pd.DataFrame, spec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    label = spec.get("label") or "Metric"
    agg = _normalize_agg(spec.get("agg"))
    column = spec.get("column")
    fmt = spec.get("format", "number")

    if agg == "count" and not column:
        value: Optional[float] = float(len(df))
    elif column and column in df.columns:
        series = df[column]
        try:
            if agg == "count":
                value = float(series.notna().sum())
            elif agg == "nunique":
                value = float(series.nunique(dropna=True))
            else:
                numeric = pd.to_numeric(series, errors="coerce")
                value = _jsonsafe(getattr(numeric, agg)())
        except Exception:
            return None
    else:
        return None

    if value is None:
        return None

    return {
        "label": str(label),
        "value": _jsonsafe(value),
        "formatted": _format_value(value, fmt),
        "description": spec.get("description") or "",
    }


def _compute_chart(df: pd.DataFrame, spec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    ctype = (spec.get("type") or "bar").strip().lower()
    if ctype not in ("bar", "line", "pie", "scatter"):
        ctype = "bar"
    x = spec.get("x")
    y = spec.get("y")
    agg = _normalize_agg(spec.get("agg"))
    title = spec.get("title") or "Chart"
    limit = spec.get("limit")
    try:
        limit = int(limit) if limit else 10
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 50))

    if not x or x not in df.columns:
        return None

    if ctype == "scatter":
        if not y or y not in df.columns:
            return None
        sub = df[[x, y]].copy()
        sub[x] = pd.to_numeric(sub[x], errors="coerce")
        sub[y] = pd.to_numeric(sub[y], errors="coerce")
        sub = sub.dropna().head(500)
        data = [{"x": _jsonsafe(a), "y": _jsonsafe(b)} for a, b in zip(sub[x], sub[y])]
        if not data:
            return None
        return {"title": str(title), "type": "scatter", "x_label": x, "y_label": y, "data": data}

    # bar / line / pie -> group by x, aggregate y
    use_count = agg == "count" or not y or y not in df.columns
    work = df[[x] + ([] if use_count else [y])].copy()
    work = work[work[x].notna()]
    if work.empty:
        return None

    if use_count:
        series = work.groupby(x).size()
        y_label = "count"
    else:
        work[y] = pd.to_numeric(work[y], errors="coerce")
        series = work.dropna(subset=[y]).groupby(x)[y].agg(agg)
        y_label = f"{agg} of {y}"

    if series.empty:
        return None

    if ctype == "line":
        series = series.sort_index()
    else:
        ascending = str(spec.get("sort", "desc")).lower() == "asc"
        series = series.sort_values(ascending=ascending)

    series = series.head(limit)
    data = [{"x": _jsonsafe(idx), "y": _jsonsafe(val)} for idx, val in series.items()]
    return {"title": str(title), "type": ctype, "x_label": x, "y_label": y_label, "data": data}


def execute_plan(df: pd.DataFrame, plan: Dict[str, Any]) -> Dict[str, Any]:
    kpis = [
        kpi
        for spec in (plan.get("kpis") or [])
        if isinstance(spec, dict) and (kpi := _compute_kpi(df, spec))
    ]
    charts = [
        chart
        for spec in (plan.get("charts") or [])
        if isinstance(spec, dict) and (chart := _compute_chart(df, spec))
    ]
    sql = plan.get("sql")
    sql = sql.strip() if isinstance(sql, str) and sql.strip() else None
    summary = plan.get("summary")
    summary = summary.strip() if isinstance(summary, str) else None
    return {"summary": summary, "kpis": kpis, "charts": charts, "sql": sql}


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def analyze_data(
    file_bytes: bytes,
    filename: str,
    prompt: str,
    provider: Optional[str] = None,
    include_sql: bool = True,
) -> Dict[str, Any]:
    if not prompt or not prompt.strip():
        raise RuntimeError("prompt is empty — describe the stats, KPIs, or metrics you want.")

    df = read_table(file_bytes, filename)
    profile = profile_dataframe(df)

    plan = build_analysis_plan(profile, prompt, provider, include_sql)
    executed = execute_plan(df, plan)

    return {
        "row_count": profile["row_count"],
        "columns": profile["columns"],
        "sample": profile["sample"],
        **executed,
    }
