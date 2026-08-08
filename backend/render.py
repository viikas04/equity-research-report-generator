"""
render.py — fills templates/report.html with extracted data and produces
the final PDF via WeasyPrint. Also loads the static page-4 content
(disclaimer, rating criteria) that's identical across every company and
therefore never sent to the LLM.
"""

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from charts import build_all_charts

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
STATIC_DIR = TEMPLATES_DIR / "static"

# Proper display names for the internal snake_case field keys used in table
# rows. Naive "replace _ with space, title-case it" turns "EV_EBITDA" into
# "Ev Ebitda" or leaves "PE"/"DE" as bare letters - this maps the handful of
# financial line items that actually need special-casing.
FIELD_DISPLAY_NAMES = {
    "Growth_pct": "Growth (%)", "Growth_pct_2": "Growth (%)", "Growth_pct_3": "Growth (%)",
    "EBITDA_Margin_pct": "EBITDA Margin (%)", "Margin_pct": "Margin (%)",
    "PE": "P/E (x)", "PB": "P/B (x)", "EV_EBITDA": "EV/EBITDA (x)",
    "ROE_pct": "ROE (%)", "DE": "D/E (x)",
    "Rep_PAT": "Reported PAT", "Adj_PAT": "Adjusted PAT", "Adj_EPS": "Adjusted EPS",
    "PAT_Adjusted": "PAT (Adjusted)", "Adjusted_EPS": "Adjusted EPS",
}


def _display_label(key: str) -> str:
    return FIELD_DISPLAY_NAMES.get(key, key.replace("_", " "))


env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
env.filters["display_label"] = _display_label
TEMPLATE = env.get_template("report.html")


def _load_static_content() -> dict:
    return {
        "disclaimer": (STATIC_DIR / "disclaimer.txt").read_text(),
        "rating_criteria": json.loads((STATIC_DIR / "rating_criteria.json").read_text()),
    }


def _summarize_metadata(meta: dict) -> dict:
    """Turns the raw field_sources/missing_fields dict into the small summary
    the trust-strip on the last page shows: how many fields were verified vs
    flagged. This is the visible proof-of-work for the verification pass."""
    if not meta:
        return {}
    sources = meta.get("field_sources", {}) or {}
    missing = meta.get("missing_fields", []) or []
    return {
        "verified_count": len(sources),
        "missing_fields": missing,
    }


def _any_value_present(rows: dict) -> bool:
    """True if any row has at least one non-null value. Used to decide
    whether a whole table section (like Estimates) is worth rendering, vs.
    a full grid of N/A when the source document simply doesn't cover
    forward-looking figures - common for a company's own earnings deck."""
    return any(v is not None for values in (rows or {}).values() for v in values)


def render_report_pdf(extracted: dict, output_path: str) -> str:
    """extracted = the verified JSON from extract.process_document()."""
    estimates_table = extracted.get("estimates_table", {"years": [], "rows": {}})
    context = {
        "meta": extracted.get("meta", {}),
        "rating_block": extracted.get("rating_block", {}),
        "company_data": extracted.get("company_data", {}),
        "shareholding": extracted.get("shareholding", []),
        "narrative": extracted.get("narrative", {}),
        "estimates_table": estimates_table,
        "estimates_table_has_data": _any_value_present(estimates_table.get("rows", {})),
        "change_in_estimates": extracted.get("change_in_estimates"),
        "consolidated_financials": extracted.get("consolidated_financials"),
        "charts": build_all_charts(extracted.get("charts", {})),
        "extraction_metadata": _summarize_metadata(extracted.get("extraction_metadata", {})),
        **_load_static_content(),
    }

    html_str = TEMPLATE.render(**context)
    HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(output_path)
    return output_path


if __name__ == "__main__":
    import sys
    with open(sys.argv[1]) as f:
        data = json.load(f)
    out = render_report_pdf(data, sys.argv[2] if len(sys.argv) > 2 else "output.pdf")
    print(f"Wrote {out}")
