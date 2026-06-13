"""ETL / Transform: take an uploaded source dataset (CSV / Excel / JSON), a target
schema (pasted SQL DDL, an English description, inferred from the source, or a
second uploaded spreadsheet), and reshape the source into the target.

Same philosophy as the analyzer: the AI proposes the *plan* — the resolved target
columns and a column-by-column mapping — but pandas *executes* it, so the output
rows are exact, never hallucinated. The AI only ever sees a compact profile of the
data (column names, types, a few sample values), not the full dataset.

Outputs (any subset, chosen by the caller):
  - transformed rows (preview + downloadable CSV/JSON)
  - the source->target mapping, annotated with a type-compatibility badge per column
  - SQL INSERT statements against the target table
  - the target CREATE TABLE DDL
  - a runnable pandas ETL script that reproduces the transform end-to-end
"""

import io
import json
import re
from typing import Any, Dict, List, Optional

import pandas as pd

# Reuse the analyzer's battle-tested file reading, profiling, JSON-safety, and
# multi-provider AI plumbing so behaviour stays consistent across tabs.
from .data_analyzer import (
    read_table,
    profile_dataframe,
    _jsonsafe,
    _strip_json,
    _resolve_provider,
    _CALLERS,
)

# --------------------------------------------------------------------------- #
# AI: produce the target schema + mapping plan (one call, any target mode)
# --------------------------------------------------------------------------- #
PLAN_SYSTEM = """
You are a senior data engineer building an ETL mapping. Given a profile of a SOURCE
dataset and a description of the desired TARGET schema, produce a PLAN that resolves
the target columns and maps each one to the source. You do NOT transform the data
yourself — a pandas engine executes your plan and produces the exact rows.

Output rules:
- Return ONLY a single valid JSON object. No prose, no markdown, no code fences.
- Use the EXACT source column names from the profile. Never invent source columns.
- Shape:
{
  "target_table": "snake_case_table_name",
  "target_columns": [
    {"name": "customer_id", "type": "int", "nullable": false, "primary_key": true}
  ],
  "mappings": [
    {"target": "customer_id", "op": "to_int", "source": "Cust ID", "sources": null, "value": null, "separator": null, "note": "cast the text id to integer"}
  ],
  "notes": "one or two sentences on the key decisions"
}

Resolving target_columns:
- If a SQL DDL is given, parse its CREATE TABLE columns EXACTLY: keep the column
  names, simplify types to one of (int, bigint, numeric, float, text, varchar,
  boolean, date, timestamp, json, uuid), and set nullable=false when the DDL says
  NOT NULL or PRIMARY KEY. Set primary_key=true for PRIMARY KEY columns.
- If a TARGET SPREADSHEET profile is given, use ITS columns and infer types from them.
- If only an English description is given, design sensible target columns + types.
- If asked to INFER from the source, produce a cleaned target: snake_case the names,
  tighten the types, drop obviously useless columns.

Mapping ops (choose the simplest that fits each target column):
- "direct"     copy the source column unchanged (use "source")
- "to_int"     numeric then integer            (use "source")
- "to_float"   numeric (decimal)               (use "source")
- "to_string"  stringify                       (use "source")
- "to_bool"    interpret as boolean            (use "source")
- "to_date"    parse to ISO date (YYYY-MM-DD)  (use "source")
- "to_datetime" parse to ISO timestamp         (use "source")
- "lower" / "upper" / "trim"  text normalization (use "source")
- "constant"   same fixed value for every row  (use "value")
- "concat"     join several source columns     (use "sources" + optional "separator", default " ")
- "coalesce"   first non-null of several columns (use "sources")
- "default"    like direct, but fill nulls     (use "source" + "value")
- "unmapped"   no source fits this target column (engine fills null/default)

Rules:
- Provide EXACTLY one mapping per target column, in the same order as target_columns.
- Prefer a type-appropriate op so the target type is satisfied (e.g. to_int for an int column).
- Set unused fields (source/sources/value/separator) to null.
""".strip()


def _profile_brief(profile: Dict[str, Any]) -> str:
    """Compact one-line-per-column rendering the AI can map against."""
    lines = [f"rows: {profile['row_count']}", "columns:"]
    for c in profile["columns"]:
        extra = ""
        if c["type"] == "numeric":
            extra = f" min={c.get('min')} max={c.get('max')}"
        else:
            sample = ", ".join(str(v) for v in (c.get("sample_values") or [])[:5])
            if sample:
                extra = f" e.g. [{sample}]"
        lines.append(f"  - {c['name']} ({c['type']}){extra}")
    return "\n".join(lines)


def _build_plan_message(
    source_profile: Dict[str, Any],
    target_mode: str,
    target_ddl: Optional[str],
    target_prompt: Optional[str],
    target_profile: Optional[Dict[str, Any]],
) -> str:
    parts = [
        "SOURCE dataset profile:",
        _profile_brief(source_profile),
        "",
        "TARGET definition:",
    ]
    if target_mode == "ddl" and target_ddl:
        parts.append("Parse this SQL DDL into the target columns (use them exactly):")
        parts.append(f"--- BEGIN DDL ---\n{target_ddl}\n--- END DDL ---")
    elif target_mode == "file" and target_profile:
        parts.append("Use the columns of this TARGET spreadsheet as the target schema:")
        parts.append(_profile_brief(target_profile))
    elif target_mode == "infer":
        parts.append(
            "No explicit schema. INFER a clean target from the source: snake_case "
            "the column names, tighten the types, and keep the useful columns."
        )
    else:  # describe
        parts.append("Design the target schema from this description:")
        parts.append(target_prompt or "Produce a clean, well-typed version of the source.")

    if target_prompt and target_mode != "describe":
        parts.append("")
        parts.append(f"Additional instructions from the user:\n{target_prompt}")

    parts.append("")
    parts.append("Return ONLY the plan JSON object.")
    return "\n".join(parts)


def build_plan(
    source_profile: Dict[str, Any],
    target_mode: str,
    target_ddl: Optional[str],
    target_prompt: Optional[str],
    target_profile: Optional[Dict[str, Any]],
    provider: Optional[str],
) -> Dict[str, Any]:
    resolved = _resolve_provider(provider)
    message = _build_plan_message(
        source_profile, target_mode, target_ddl, target_prompt, target_profile
    )
    raw = _CALLERS[resolved](PLAN_SYSTEM, message)
    plan = _strip_json(raw)
    if not isinstance(plan, dict):
        raise ValueError("AI plan must be a JSON object.")
    if not plan.get("target_columns"):
        raise ValueError("AI plan did not resolve any target columns.")
    return plan


# --------------------------------------------------------------------------- #
# Type compatibility badge (for the editable mapping UI)
# --------------------------------------------------------------------------- #
_TYPE_FAMILY = {
    "int": "number", "integer": "number", "bigint": "number", "smallint": "number",
    "serial": "number", "bigserial": "number", "numeric": "number", "decimal": "number",
    "float": "number", "double": "number", "real": "number", "money": "number",
    "text": "text", "varchar": "text", "char": "text", "string": "text", "uuid": "text",
    "json": "text", "jsonb": "text",
    "bool": "boolean", "boolean": "boolean",
    "date": "date",
    "timestamp": "datetime", "timestamptz": "datetime", "datetime": "datetime",
}


def _target_family(target_type: str) -> str:
    base = re.split(r"[(\s]", (target_type or "").strip().lower(), 1)[0]
    return _TYPE_FAMILY.get(base, "text")


def _badge(source_kind: Optional[str], target_type: str, op: str, nullable: bool) -> str:
    """ok | cast | missing — a hint for the UI, not a hard rule. pandas does the
    real coercion and reports actual failures afterwards."""
    if op in ("constant",):
        return "ok"
    if op == "unmapped" or source_kind is None:
        return "ok" if nullable else "missing"
    fam = _target_family(target_type)
    if fam == "text":
        return "ok"  # everything stringifies cleanly
    if fam == "number":
        return "ok" if source_kind == "numeric" else "cast"
    if fam in ("date", "datetime"):
        return "ok" if source_kind == "datetime" else "cast"
    if fam == "boolean":
        return "ok" if source_kind == "boolean" else "cast"
    return "ok"


# --------------------------------------------------------------------------- #
# Plan execution (pandas — the source of truth for the transformed rows)
# --------------------------------------------------------------------------- #
_TRUE = {"true", "t", "yes", "y", "1", "on"}
_FALSE = {"false", "f", "no", "n", "0", "off"}


def _to_bool_series(s: pd.Series) -> pd.Series:
    def conv(v):
        if pd.isna(v):
            return None
        text = str(v).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        return None
    return s.map(conv)


def _apply_op(df: pd.DataFrame, m: Dict[str, Any]) -> tuple[pd.Series, int]:
    """Return (resulting Series aligned to df.index, count of values that failed to
    convert). Unknown/missing source columns degrade gracefully to all-null."""
    op = (m.get("op") or "direct").strip().lower()
    src = m.get("source")
    sources = m.get("sources") or ([src] if src else [])
    value = m.get("value")
    sep = m.get("separator")
    sep = " " if sep is None else str(sep)
    n = len(df)

    def col(name):
        return df[name] if name in df.columns else pd.Series([None] * n, index=df.index)

    if op == "constant":
        return pd.Series([value] * n, index=df.index), 0

    if op == "concat":
        cols = [col(c).astype("string").fillna("") for c in sources]
        if not cols:
            return pd.Series([None] * n, index=df.index), 0
        out = cols[0]
        for c in cols[1:]:
            out = out.str.cat(c, sep=sep)
        return out, 0

    if op == "coalesce":
        out = pd.Series([None] * n, index=df.index, dtype="object")
        for c in sources:
            s = col(c)
            out = out.where(out.notna(), s)
        return out, 0

    base = col(src)

    if op in ("direct", "default"):
        out = base
        if op == "default" and value is not None:
            out = out.where(out.notna(), value)
        return out, 0
    if op == "to_string":
        return base.astype("string"), 0
    if op in ("trim", "lower", "upper"):
        s = base.astype("string")
        s = {"trim": s.str.strip(), "lower": s.str.lower(), "upper": s.str.upper()}[op]
        return s, 0
    if op in ("to_int", "to_float"):
        num = pd.to_numeric(base, errors="coerce")
        failed = int((base.notna() & num.isna()).sum())
        if op == "to_int":
            num = num.round().astype("Int64")
        return num, failed
    if op == "to_bool":
        out = _to_bool_series(base)
        failed = int((base.notna() & out.isna()).sum())
        return out.astype("boolean"), failed
    if op in ("to_date", "to_datetime"):
        dt = pd.to_datetime(base, errors="coerce")
        failed = int((base.notna() & dt.isna()).sum())
        if op == "to_date":
            out = dt.dt.strftime("%Y-%m-%d")
        else:
            out = dt.dt.strftime("%Y-%m-%dT%H:%M:%S")
        out = out.where(dt.notna(), None)
        return out, failed
    if op == "unmapped":
        return pd.Series([None] * n, index=df.index), 0

    # Unknown op -> treat as direct copy.
    return base, 0


def execute_plan(df: pd.DataFrame, plan: Dict[str, Any], source_profile: Dict[str, Any]):
    """Run the mapping. Returns (transformed_df, mapping_report, issues)."""
    source_kind = {c["name"]: c["type"] for c in source_profile["columns"]}
    mappings = {m.get("target"): m for m in (plan.get("mappings") or []) if isinstance(m, dict)}

    out = {}
    mapping_report: List[Dict[str, Any]] = []
    issues: List[str] = []

    for tc in plan["target_columns"]:
        tname = tc.get("name")
        if not tname:
            continue
        ttype = tc.get("type") or "text"
        nullable = bool(tc.get("nullable", True))
        m = mappings.get(tname, {"op": "unmapped", "target": tname})
        op = (m.get("op") or "direct").lower()

        series, failed = _apply_op(df, m)
        out[tname] = series.reset_index(drop=True)

        src_label = m.get("source") or (
            " + ".join(m.get("sources") or []) if m.get("sources") else None
        )
        if op == "constant":
            src_label = f"= {m.get('value')!r}"
        sk = source_kind.get(m.get("source")) if m.get("source") else None

        null_count = int(series.isna().sum())
        if not nullable and null_count:
            issues.append(
                f"{tname}: {null_count} null value(s) but the target column is NOT NULL."
            )
        if failed:
            issues.append(f"{tname}: {failed} value(s) could not convert to {ttype} (set to null).")

        mapping_report.append({
            "target": tname,
            "target_type": ttype,
            "nullable": nullable,
            "primary_key": bool(tc.get("primary_key", False)),
            "op": op,
            "source": src_label,
            "badge": _badge(sk, ttype, op, nullable),
            "note": m.get("note") or "",
            "null_count": null_count,
            "convert_failures": failed,
        })

    target_df = pd.DataFrame(out)
    return target_df, mapping_report, issues


# --------------------------------------------------------------------------- #
# Output generators (DDL / INSERT / pandas script)
# --------------------------------------------------------------------------- #
def _quote_ident(name: str) -> str:
    return name if re.fullmatch(r"[a-z_][a-z0-9_]*", name or "") else '"' + str(name).replace('"', '""') + '"'


def _sql_literal(value: Any, family: str) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "NULL"
    try:
        if pd.isna(value):
            return "NULL"
    except (TypeError, ValueError):
        pass
    if family == "number":
        return str(value)
    if family == "boolean":
        return "TRUE" if bool(value) else "FALSE"
    return "'" + str(value).replace("'", "''") + "'"


def build_target_ddl(plan: Dict[str, Any]) -> str:
    table = plan.get("target_table") or "target_table"
    cols = plan["target_columns"]
    lines = []
    for c in cols:
        parts = [f"  {_quote_ident(c['name'])} {(c.get('type') or 'text').upper()}"]
        if c.get("primary_key"):
            parts.append("PRIMARY KEY")
        elif not c.get("nullable", True):
            parts.append("NOT NULL")
        lines.append(" ".join(parts))
    return f"CREATE TABLE {_quote_ident(table)} (\n" + ",\n".join(lines) + "\n);"


def build_inserts(plan: Dict[str, Any], df: pd.DataFrame, batch: int = 100, max_rows: int = 1000) -> str:
    table = plan.get("target_table") or "target_table"
    cols = [c["name"] for c in plan["target_columns"]]
    families = {c["name"]: _target_family(c.get("type") or "text") for c in plan["target_columns"]}
    col_sql = ", ".join(_quote_ident(c) for c in cols)

    rows = df.head(max_rows)
    statements: List[str] = []
    values_rows: List[str] = []
    for _, row in rows.iterrows():
        vals = ", ".join(_sql_literal(_jsonsafe(row.get(c)), families[c]) for c in cols)
        values_rows.append(f"  ({vals})")
        if len(values_rows) >= batch:
            statements.append(
                f"INSERT INTO {_quote_ident(table)} ({col_sql}) VALUES\n"
                + ",\n".join(values_rows) + ";"
            )
            values_rows = []
    if values_rows:
        statements.append(
            f"INSERT INTO {_quote_ident(table)} ({col_sql}) VALUES\n"
            + ",\n".join(values_rows) + ";"
        )

    out = "\n\n".join(statements)
    if len(df) > max_rows:
        out += f"\n\n-- Showing INSERTs for the first {max_rows} of {len(df)} rows."
    return out


def build_python_script(plan: Dict[str, Any], source_filename: str) -> str:
    """A runnable pandas script that reproduces the exact transform — the
    executable twin of the plan we just ran. Fits the app's 'generator' identity."""
    table = plan.get("target_table") or "target_table"
    mappings_json = json.dumps(plan.get("mappings", []), indent=4)
    target_cols_json = json.dumps(
        [{"name": c["name"], "type": c.get("type", "text")} for c in plan["target_columns"]],
        indent=4,
    )
    return f'''"""Generated ETL script — reshapes "{source_filename}" into the `{table}` schema.

Run:  python etl_{table}.py <source_file>  [--csv out.csv | --json out.json]
Requires: pandas (pip install pandas openpyxl)
"""
import sys
import json
import pandas as pd

SOURCE = sys.argv[1] if len(sys.argv) > 1 else "{source_filename}"

TARGET_COLUMNS = {target_cols_json}

MAPPINGS = {mappings_json}

_TRUE = {{"true", "t", "yes", "y", "1", "on"}}
_FALSE = {{"false", "f", "no", "n", "0", "off"}}


def read_source(path):
    low = path.lower()
    if low.endswith((".xlsx", ".xlsm", ".xls")):
        return pd.read_excel(path)
    if low.endswith(".json"):
        with open(path, encoding="utf-8-sig") as fh:
            parsed = json.load(fh)
        if isinstance(parsed, dict):
            parsed = next((v for v in parsed.values() if isinstance(v, list)), [parsed])
        return pd.json_normalize(parsed)
    return pd.read_csv(path, sep="\\t" if low.endswith(".tsv") else ",")


def to_bool(s):
    def conv(v):
        if pd.isna(v):
            return None
        t = str(v).strip().lower()
        return True if t in _TRUE else False if t in _FALSE else None
    return s.map(conv)


def apply_op(df, m):
    op = (m.get("op") or "direct").lower()
    src, value = m.get("source"), m.get("value")
    sources = m.get("sources") or ([src] if src else [])
    sep = " " if m.get("separator") is None else str(m["separator"])
    n = len(df)
    col = lambda c: df[c] if c in df.columns else pd.Series([None] * n, index=df.index)

    if op == "constant":
        return pd.Series([value] * n, index=df.index)
    if op == "concat":
        cols = [col(c).astype("string").fillna("") for c in sources]
        out = cols[0]
        for c in cols[1:]:
            out = out.str.cat(c, sep=sep)
        return out
    if op == "coalesce":
        out = pd.Series([None] * n, index=df.index, dtype="object")
        for c in sources:
            out = out.where(out.notna(), col(c))
        return out
    base = col(src)
    if op == "default":
        return base.where(base.notna(), value)
    if op == "to_string":
        return base.astype("string")
    if op in ("trim", "lower", "upper"):
        s = base.astype("string")
        return {{"trim": s.str.strip(), "lower": s.str.lower(), "upper": s.str.upper()}}[op]
    if op == "to_int":
        return pd.to_numeric(base, errors="coerce").round().astype("Int64")
    if op == "to_float":
        return pd.to_numeric(base, errors="coerce")
    if op == "to_bool":
        return to_bool(base)
    if op in ("to_date", "to_datetime"):
        dt = pd.to_datetime(base, errors="coerce")
        fmt = "%Y-%m-%d" if op == "to_date" else "%Y-%m-%dT%H:%M:%S"
        return dt.dt.strftime(fmt).where(dt.notna(), None)
    if op == "unmapped":
        return pd.Series([None] * n, index=df.index)
    return base


def transform(df):
    by_target = {{m["target"]: m for m in MAPPINGS}}
    out = {{}}
    for tc in TARGET_COLUMNS:
        m = by_target.get(tc["name"], {{"op": "unmapped", "target": tc["name"]}})
        out[tc["name"]] = apply_op(df, m).reset_index(drop=True)
    return pd.DataFrame(out)


if __name__ == "__main__":
    df = transform(read_source(SOURCE))
    if "--json" in sys.argv:
        path = sys.argv[sys.argv.index("--json") + 1]
        df.to_json(path, orient="records", indent=2)
    else:
        path = sys.argv[sys.argv.index("--csv") + 1] if "--csv" in sys.argv else "{table}.csv"
        df.to_csv(path, index=False)
    print(f"Wrote {{len(df)}} rows to {{path}}")
'''


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def transform_data(
    source_bytes: bytes,
    source_filename: str,
    target_mode: str,
    target_ddl: Optional[str] = None,
    target_prompt: Optional[str] = None,
    target_bytes: Optional[bytes] = None,
    target_filename: Optional[str] = None,
    provider: Optional[str] = None,
    include_inserts: bool = True,
    include_ddl: bool = True,
    include_script: bool = True,
    preview_rows: int = 50,
    plan_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    source_df = read_table(source_bytes, source_filename)
    source_profile = profile_dataframe(source_df)

    if plan_override is not None:
        # Re-run with a user-edited mapping — skip the AI, execute the given plan.
        if not isinstance(plan_override, dict) or not plan_override.get("target_columns"):
            raise RuntimeError("plan override must include target_columns.")
        plan = plan_override
    else:
        target_mode = (target_mode or "describe").strip().lower()
        if target_mode not in ("ddl", "describe", "infer", "file"):
            raise RuntimeError("target_mode must be one of: ddl, describe, infer, file.")
        if target_mode == "ddl" and not (target_ddl or "").strip():
            raise RuntimeError("target_mode 'ddl' requires target DDL text.")
        if target_mode == "file" and not target_bytes:
            raise RuntimeError("target_mode 'file' requires a target spreadsheet upload.")

        target_profile = None
        if target_mode == "file":
            target_df_schema = read_table(target_bytes, target_filename or "target.csv")
            target_profile = profile_dataframe(target_df_schema)

        plan = build_plan(
            source_profile, target_mode, target_ddl, target_prompt, target_profile, provider
        )

    target_df, mapping_report, issues = execute_plan(source_df, plan, source_profile)

    preview = [
        {k: _jsonsafe(v) for k, v in row.items()}
        for row in target_df.head(preview_rows).to_dict(orient="records")
    ]
    full_rows = [
        {k: _jsonsafe(v) for k, v in row.items()}
        for row in target_df.to_dict(orient="records")
    ]

    return {
        "target_table": plan.get("target_table") or "target_table",
        "target_columns": plan["target_columns"],
        "mapping": mapping_report,
        # Raw plan echoed back so the UI can edit the mapping and re-run it verbatim.
        "plan": {
            "target_table": plan.get("target_table") or "target_table",
            "target_columns": plan["target_columns"],
            "mappings": plan.get("mappings") or [],
        },
        "notes": plan.get("notes") or "",
        "issues": issues,
        "source_row_count": source_profile["row_count"],
        "target_row_count": int(len(target_df)),
        "source_columns": source_profile["columns"],
        "preview": preview,
        "rows": full_rows,
        "ddl": build_target_ddl(plan) if include_ddl else None,
        "inserts": build_inserts(plan, target_df) if include_inserts else None,
        "script": build_python_script(plan, source_filename) if include_script else None,
    }
