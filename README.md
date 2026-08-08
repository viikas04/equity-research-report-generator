# Bull AI — Research Report Generator

Upload a company's financial context document (PDF/CSV/TXT), get back a
formatted PDF research report — tables, narrative summaries, and charts —
matching the layout of the provided Geojit sample.

## Why this isn't a naive "LLM writes PDF" pipeline

Financial reports need traceable numbers, not confident-sounding ones. So
extraction runs in **two passes**:

1. **Extract** — an LLM reads the source document and pulls structured
   fields (financials, metrics, narrative), tagging every number with the
   exact source sentence it came from.
2. **Verify** — a second LLM pass re-checks each extracted field against
   the source text. Anything that doesn't actually check out gets nulled
   out rather than kept — the template then renders it as `N/A` instead
   of a plausible-looking but unverified figure.

This is what "handles missing fields gracefully" in the acceptance
criteria actually means for a finance product: no invented numbers, ever.

## Architecture

```
Upload (PDF/CSV/TXT)
        │
        ▼
backend/extract.py  ── load_source_text()   → raw text
                     ── extract_fields()     → structured JSON + source quotes  (LLM pass 1)
                     ── verify_extraction()  → nulls out unverifiable fields    (LLM pass 2)
        │
        ▼
backend/charts.py   ── renders bar+line combo charts (matplotlib) from the
                        extracted quarterly series → base64 PNGs
        │
        ▼
backend/render.py   ── fills templates/report.html (Jinja2) with the data
                        + charts, converts to PDF via WeasyPrint
        │
        ▼
backend/main.py     ── FastAPI endpoint tying it together, serves frontend/
```

## Where report fields are defined

Everything the report can contain — every table column, every chart type,
every narrative field — is declared once in **`templates/field_schema.json`**.
The HTML template (`templates/report.html`) and the extraction prompt
(`backend/extract.py`) both read from this schema. To add a new field or
support a new company type:

1. Add the field to `field_schema.json`
2. Reference it in `report.html` (one Jinja line)
3. No other code changes needed — the extraction prompt already includes
   the schema as context, so the LLM picks up new fields automatically.

Page 4 (rating criteria + disclaimer) is **static**, defined in
`templates/static/`, and is never sent to the LLM — it's identical for
every company, so there's no reason to burn tokens regenerating it.

## Running it

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env   # then edit .env and paste your real Gemini key
uvicorn main:app --reload --app-dir .
```

Then open `http://localhost:8000` — upload a company name + a financial
document, and download the generated PDF.

### Testing the pipeline without the API

`samples/sample_eternal.json` is a hand-written example of what
`extract.py` would output for the provided Eternal Ltd. / Geojit sample.
You can render it directly, skipping the LLM calls, to sanity-check the
PDF layout:

```bash
cd backend
python3 render.py ../samples/sample_eternal.json ../samples/test_output.pdf
```

## Tech used

- **FastAPI** — backend API
- **Google Gemini** (`gemini-2.0-flash`, free tier) — extraction + verification.
  Get a free key at https://aistudio.google.com/apikey — no card required.
- **pdfplumber** — PDF text extraction from uploaded source documents
- **matplotlib** — chart generation
- **Jinja2 + WeasyPrint** — HTML → PDF report rendering
- Plain HTML/CSS/JS frontend — no build step

## Security

Scoped deliberately to what actually matters for this app (an internal,
single-purpose tool per the JD), not padded with irrelevant enterprise
checklist items:

- **Upload size capped** at 20MB, enforced by streaming the file in chunks
  rather than trusting a client-supplied `Content-Length` header
- **File type allow-list** — only `.pdf/.csv/.txt/.md` accepted
- **Filenames sanitized** before touching the filesystem — the company name
  is stripped to safe characters before being used in an output filename
- **No secrets in the repo** — `.env` is gitignored, `.env.example` shows
  what's needed without a real key ever being committed
- **No files left on disk** — the uploaded source is deleted immediately
  after processing, and the generated PDF is deleted right after it's sent
  to the client (via a `BackgroundTask`), so nothing accumulates in temp
  storage over time

Not added, deliberately: authentication (single-purpose internal tool, not
multi-user), encryption at rest (nothing sensitive persists), rate limiting
(out of scope for an assessment demo — noted here so it's clear it was a
choice, not an oversight).

## Known limitations / next steps

- Page 3 (full consolidated financials — P&L, balance sheet, cashflow,
  ratios) is wired in the schema and template but extraction currently
  prioritizes pages 1–2 (narrative + primary financials + charts), since
  that's where the AI-assisted work actually is. Given more time, the
  extraction prompt would be split per-table for higher accuracy on the
  dense financial statements.
- Currently supports one context document per report. Multi-document
  merging (e.g. a PDF + a supplementary CSV) is a straightforward
  extension of `load_source_text()`.
