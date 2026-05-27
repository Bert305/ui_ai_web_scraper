import os
import re
from typing import Optional

DIALECTS = {
    "postgresql": {"label": "PostgreSQL"},
}

QUERIES_SYSTEM = """
You are a senior database engineer. Produce SQL queries that satisfy the user's request, grounded in the provided schema (DDL).

Hard rules:
- Output ONLY SQL. No prose, no explanation, no markdown fences.
- Use the EXACT table and column names from the provided DDL. Do not invent columns.
- Target the requested SQL dialect. Use that dialect's idioms (e.g. PostgreSQL uses RETURNING, ILIKE, ::cast, etc.).
- Produce one or more of: SELECT, INSERT, UPDATE, DELETE — whatever the prompt asks for.
- Separate each statement with a blank line and a brief single-line `-- comment` describing it.
- Use parameter placeholders ($1, $2 for PostgreSQL) where the prompt implies user-supplied values.
- Quote identifiers only when necessary (reserved words, mixed case).
- Always include sensible WHERE clauses for UPDATE and DELETE — never produce an unbounded UPDATE or DELETE.
""".strip()

ERD_SYSTEM = """
You are a database visualization tool. Convert the provided SQL DDL into a Mermaid ERD diagram.

Hard rules:
- Output ONLY Mermaid source. No prose, no explanation, no markdown fences.
- Begin with the line: erDiagram
- For each CREATE TABLE in the DDL, emit a Mermaid entity block with its columns and types.
- Mark primary keys with PK and foreign keys with FK after the column name.
- Use simplified type names (int, bigint, text, varchar, timestamp, boolean, numeric, uuid, json, date).
- Infer relationships from REFERENCES clauses or `<table>_id` column naming, using Mermaid cardinality syntax:
    one-to-many:  PARENT ||--o{ CHILD : "label"
    one-to-one:   A ||--|| B : "label"
    many-to-many: A }o--o{ B : "label"
- Entity names must match the table names from the DDL exactly (case included).
- Do not include CREATE TABLE statements, comments, or any text outside Mermaid syntax.
""".strip()


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    text = re.sub(r"^```[a-zA-Z0-9_+-]*\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _build_queries_message(schema_sql: str, prompt: str, dialect: str) -> str:
    spec = DIALECTS[dialect]
    return (
        f"SQL dialect: {spec['label']}\n\n"
        f"What the user wants:\n{prompt}\n\n"
        "Schema DDL (use exactly these tables and columns):\n"
        f"--- BEGIN DDL ---\n{schema_sql}\n--- END DDL ---\n\n"
        "Return ONLY the SQL statements."
    )


def _build_erd_message(schema_sql: str) -> str:
    return (
        "Convert this DDL into a Mermaid erDiagram. Return ONLY Mermaid source.\n\n"
        f"--- BEGIN DDL ---\n{schema_sql}\n--- END DDL ---"
    )


def _call_anthropic(system: str, user_message: str) -> str:
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is missing.")
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
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
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=system,
    )
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


_CALLERS = {
    "anthropic": _call_anthropic,
    "gemini": _call_gemini,
    "openai": _call_openai,
}

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


def generate_sql(
    schema_sql: str,
    prompt: str,
    dialect: str,
    include_queries: bool,
    include_erd: bool,
    provider: Optional[str] = None,
) -> dict:
    if dialect not in DIALECTS:
        raise RuntimeError(
            f"Unknown dialect '{dialect}'. Use one of: {', '.join(DIALECTS.keys())}."
        )
    if not schema_sql.strip():
        raise RuntimeError("schema_sql is empty — paste the database DDL to ground generation.")

    resolved = _resolve_provider(provider)
    call = _CALLERS[resolved]

    result = {
        "queries": None,
        "erd_mermaid": None,
    }

    if include_queries:
        if not prompt.strip():
            raise RuntimeError("prompt is empty — describe what SQL you want generated.")
        raw = call(QUERIES_SYSTEM, _build_queries_message(schema_sql, prompt, dialect))
        result["queries"] = _strip_code_fences(raw)

    if include_erd:
        raw = call(ERD_SYSTEM, _build_erd_message(schema_sql))
        result["erd_mermaid"] = _strip_code_fences(raw)

    return result
