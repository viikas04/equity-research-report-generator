# Bull AI — Research Report Generator

**Live demo:** https://equity-research-report-generator.onrender.com
*(free tier — first request after inactivity may take up to a minute to wake up)*

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

The pipeline runs in five stages, each in its own file:

1. **Upload** (PDF/CSV/TXT) comes in through the frontend.
2. **`backend/extract.py`** — `load_source_text()` pulls raw text plus
   separately-parsed tables out of the source file; `extract_fields()`
   sends it to Gemini for structured JSON with source quotes (LLM pass 1);
   `verify_extraction()` re-checks every field and nulls out anything
   unverifiable (LLM pass 2).
3. **`backend/charts.py`** — renders bar+line combo charts (matplotlib)
   from the extracted quarterly series, as base64 PNGs.
4. **`backend/render.py`** — fills `templates/report.html` (Jinja2) with
   the data and charts, then converts it to a PDF via WeasyPrint.
5. **`backend/main.py`** — the FastAPI endpoint tying all of the above
   together, and serving the frontend.

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

## Running it locally

    cd backend
    pip install -r requirements.txt
    cp ../.env.example ../.env
    # then edit .env and paste your real Gemini key
    uvicorn main:app --reload --app-dir .

Then open `http://localhost:8000` — upload a company name + a financial
document, and download the generated PDF.

### Running it with Docker

The included `Dockerfile` bundles the system libraries WeasyPrint needs
for PDF rendering, so it works consistently regardless of host OS:

    docker build -t equity-research-report-generator .
    docker run -p 8000:8000 -e GEMINI_API_KEY=your_key_here equity-research-report-generator

This is also how the live demo above is deployed (on Render, free tier).

### Testing the pipeline without the API

`samples/sample_eternal.json` is a hand-written example of what
`extract.py` would output for the provided Eternal Ltd. / Geojit sample.
You can render it directly, skipping the LLM calls, to sanity-check the
PDF layout:

    cd backend
    python3 render.py ../samples/sample_eternal.json ../samples/test_output.pdf

## Tech used

- **FastAPI** — backend API
- **Google Gemini** (`gemini-flash-lite-latest`, free tier) — extraction +
  verification. Get a free key at https://aistudio.google.com/apikey — no
  card required. Uses the `-latest` alias rather than a pinned version, so
  it keeps working as Google rotates model versions.
- **pdfplumber** — PDF text extraction, including a separate table-parsing
  pass so multi-column layouts don't get scrambled into plain text
- **matplotlib** — chart generation
- **Jinja2 + WeasyPrint** — HTML → PDF report rendering
- **Docker** — for consistent deployment across environments
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
- Free-tier hosting means the live demo cold-starts after ~15 minutes of
  inactivity — the first request after a gap can take up to a minute.
