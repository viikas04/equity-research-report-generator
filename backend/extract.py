"""
extract.py — turns a raw financial document (PDF/CSV/TXT) into the structured
JSON that templates/field_schema.json expects.

Two-pass design (this is the differentiator, not boilerplate):
  Pass 1 (extract):  read source doc -> structured JSON, each numeric field
                      tagged with the exact source sentence it came from.
  Pass 2 (verify):    re-check every extracted field against the source text.
                      Anything not actually present gets marked missing
                      instead of silently hallucinated -> template renders
                      "N/A" for it (acceptance criteria: "handles missing
                      fields gracefully").

Why this matters for a finance product: a number with no traceable source
is a liability, not a feature. Showing the source sentence next to each
number is what makes this demo-able to a non-technical founder.

Uses Google Gemini (free tier) rather than a paid API — see README for
where to get a free key.
"""

import json
import os
import csv
from pathlib import Path

import google.genai as genai
from google.genai import types
import pdfplumber

MODEL = "gemini-flash-lite-latest"  # alias — always points to the current stable Flash-Lite release, so this won't go stale like a hardcoded version number does

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError(
        "GEMINI_API_KEY is not set. Get a free key at https://aistudio.google.com/apikey "
        "and run: export GEMINI_API_KEY=your_key_here"
    )
client = genai.Client(api_key=api_key)

SCHEMA_PATH = Path(__file__).parent.parent / "templates" / "field_schema.json"
FIELD_SCHEMA = json.loads(SCHEMA_PATH.read_text())

# --- security: cap how much source text we'll ever send in one call ---
MAX_SOURCE_CHARS = 100_000


# ---------- Step 1: pull raw text out of whatever the user uploaded ----------

def load_source_text(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()

    if ext == ".pdf":
        chunks = []
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                chunks.append(f"--- PAGE {i + 1} TEXT ---\n{text}")

                # Multi-column layouts (like the Geojit report format) often
                # scramble numeric tables when read as plain text - columns
                # bleed into each other and rows lose alignment. Extracting
                # tables separately, as clean pipe-delimited rows, gives the
                # model an unambiguous version of the same data to prefer
                # over the jumbled prose version.
                tables = page.extract_tables()
                for t_idx, table in enumerate(tables):
                    rows = [
                        " | ".join(cell if cell else "" for cell in row)
                        for row in table
                    ]
                    chunks.append(f"--- PAGE {i + 1} TABLE {t_idx + 1} (clean rows) ---\n" + "\n".join(rows))
        return "\n\n".join(chunks)

    if ext == ".csv":
        with open(file_path, newline="", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return "\n".join(",".join(row) for row in rows)

    if ext in (".txt", ".md"):
        return Path(file_path).read_text(encoding="utf-8", errors="ignore")

    raise ValueError(f"Unsupported file type: {ext}. Supported: .pdf, .csv, .txt")


# ---------- Step 2: extraction pass ----------

EXTRACTION_SYSTEM_PROMPT = """You are a financial data extraction engine for an
equity research report generator. Given a company's financial context document,
extract the fields below as JSON. For every NUMERIC field, also record the exact
sentence or table row from the source that the number came from — this is
mandatory, not optional.

The source document below contains both raw page text (marked "TEXT") and,
where the page has tables, a separately parsed clean version of those tables
(marked "TABLE", with cells separated by " | "). Multi-column layouts often
scramble numbers when read as plain text, so when a number appears in both a
TEXT block and a TABLE block, trust the TABLE version — it preserves row/column
alignment that the prose version may have lost. Read every TABLE block
carefully; sidebar data (company stats, multi-year estimates, quarterly
comparisons) is usually easiest to recover correctly from these blocks rather
than the surrounding paragraph text.

Rules:
- Never invent a number. If a field genuinely is not in the source document,
  set its value to null and do not include a source for it.
- Before marking a table row entirely null, check every TABLE block on every
  page - do not conclude a field is missing just because it wasn't in the
  narrative text.
- Numbers should be plain numbers (no commas, no currency symbols) — units are
  handled separately by the template.
- Write "company_overview", "outlook_valuation" and both bullet lists yourself,
  in your own words, grounded only in facts present in the source document.
- Return ONLY valid JSON, no markdown fences, no preamble.

Output shape:
{
  "meta": {"company_name": str, "sector": str},
  "rating_block": {"rating": str, "target_price": num|null, "cmp": num|null},
  "company_data": { ... numeric fields from schema, null if absent ... },
  "narrative": {
    "company_overview": str,
    "key_bullets": [str, ...],
    "outlook_valuation": str,
    "key_highlights_page2": [str, ...]
  },
  "estimates_table": { "years": [...], "rows": {row_name: [values...]} },
  "quarterly_financials": { "rows": {row_name: {latest, prior_yoy, yoy_growth_pct, prior_qoq, qoq_growth_pct}} },
  "charts": { "revenue_trend": {"quarters": [...], "values": [...]}, ... any of the available_types you have data for ... },
  "field_sources": { "field.path.here": "exact quote from source" }
}
"""

extraction_config = types.GenerateContentConfig(
    system_instruction=EXTRACTION_SYSTEM_PROMPT,
    response_mime_type="application/json",
)


def extract_fields(source_text: str) -> dict:
    prompt = (
        f"Field schema for reference:\n{json.dumps(FIELD_SCHEMA, indent=2)}\n\n"
        f"Source document:\n{source_text[:MAX_SOURCE_CHARS]}"
    )
    resp = client.models.generate_content(model=MODEL, contents=prompt, config=extraction_config)
    return json.loads(resp.text)


# ---------- Step 3: verification pass (the trust-building step) ----------

VERIFY_SYSTEM_PROMPT = """You are a fact-checker. You will be given (a) a source
document and (b) a JSON object of extracted financial fields with claimed source
quotes. For each field with a source quote, confirm the quote actually appears
in (or is a faithful paraphrase of) the source document and the number matches.

Return ONLY JSON:
{
  "verified_fields": [list of field paths that check out],
  "flagged_fields": [{"field": str, "reason": str}, ...]
}
"""

verify_config = types.GenerateContentConfig(
    system_instruction=VERIFY_SYSTEM_PROMPT,
    response_mime_type="application/json",
)


def verify_extraction(source_text: str, extracted: dict) -> dict:
    prompt = (
        f"Extracted JSON:\n{json.dumps(extracted)}\n\n"
        f"Source document:\n{source_text[:MAX_SOURCE_CHARS]}"
    )
    resp = client.models.generate_content(model=MODEL, contents=prompt, config=verify_config)
    verification = json.loads(resp.text)

    # Null out anything flagged so the template renders it as N/A rather than
    # showing an unverified number.
    for flag in verification.get("flagged_fields", []):
        _null_out(extracted, flag["field"])

    extracted["extraction_metadata"] = {
        "field_sources": extracted.pop("field_sources", {}),
        "missing_fields": [f["field"] for f in verification.get("flagged_fields", [])],
    }
    return extracted


def _null_out(data: dict, dotted_path: str):
    """Set data[a][b][c] = None given 'a.b.c', ignoring paths that don't exist."""
    parts = dotted_path.split(".")
    node = data
    for p in parts[:-1]:
        if not isinstance(node, dict) or p not in node:
            return
        node = node[p]
    if isinstance(node, dict):
        node[parts[-1]] = None


# ---------- Public entry point ----------

def process_document(file_path: str) -> dict:
    source_text = load_source_text(file_path)
    extracted = extract_fields(source_text)
    verified = verify_extraction(source_text, extracted)
    return verified


if __name__ == "__main__":
    import sys
    result = process_document(sys.argv[1])
    print(json.dumps(result, indent=2))

