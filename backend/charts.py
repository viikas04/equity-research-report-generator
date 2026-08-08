"""
charts.py — renders the bar+line combo charts (bars = absolute value,
line = growth/margin %) matching the Geojit sample's Revenue / GOV / EBITDA /
PAT charts. Returns base64 PNG strings ready to drop straight into the HTML
template's <img src="data:image/png;base64,...">.
"""

import base64
import io

import matplotlib
matplotlib.use("Agg")  # no display backend needed on a server
import matplotlib.pyplot as plt

TEAL = "#0e9488"
ORANGE = "#e8833a"

CHART_TITLES = {
    "revenue_trend": "Revenue",
    "gross_order_value": "Gross Order Value",
    "ebitda_margin": "EBITDA",
    "pat_margin": "PAT",
}


def render_combo_chart(quarters: list[str], bar_values: list[float], line_pct: list[float], chart_key: str) -> str:
    """One bar+line chart -> base64 PNG. chart_key picks the title/labels."""
    fig, ax1 = plt.subplots(figsize=(4.2, 2.6), dpi=150)

    ax1.bar(quarters, bar_values, color=TEAL, width=0.55, zorder=2)
    ax1.set_ylabel("", fontsize=8)
    ax1.tick_params(axis="x", labelsize=7, rotation=45)
    ax1.tick_params(axis="y", labelsize=7)
    ax1.spines[["top", "right"]].set_visible(False)

    ax2 = ax1.twinx()
    ax2.plot(quarters, line_pct, color=ORANGE, marker="o", markersize=3, linewidth=1.5, zorder=3)
    for x, y in zip(quarters, line_pct):
        ax2.annotate(f"{y:.1f}%", (x, y), textcoords="offset points", xytext=(0, 6),
                      ha="center", fontsize=6, color=ORANGE)
    ax2.tick_params(axis="y", labelsize=7)
    ax2.spines[["top"]].set_visible(False)

    ax1.set_title(CHART_TITLES.get(chart_key, chart_key), fontsize=10, fontweight="bold",
                   color="#1a5c56", loc="left")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def render_price_performance_chart(dates: list[str], stock_series: list[float], index_series: list[float]) -> str:
    """The small line chart on page 1 (stock vs benchmark, rebased)."""
    fig, ax = plt.subplots(figsize=(4.5, 1.8), dpi=150)
    ax.plot(dates, stock_series, color=TEAL, linewidth=1.3, label="Stock")
    ax.plot(dates, index_series, color="#999999", linewidth=1.0, linestyle="--", label="Index (rebased)")
    ax.tick_params(axis="both", labelsize=6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(fontsize=6, frameon=False, loc="upper left")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def build_all_charts(extracted_charts: dict) -> dict:
    """
    extracted_charts is the `charts` block from extract.py's output, e.g.:
      {"revenue_trend": {"quarters": [...], "values": [...], "growth_pct": [...]}, ...}
    Returns {chart_key: base64_png_str} for every chart that had data.
    Gracefully skips any chart type the source document didn't have data for —
    this is the "handles missing fields gracefully" behavior applied to charts.
    """
    rendered = {}
    for key, data in (extracted_charts or {}).items():
        if not data or not data.get("quarters") or not data.get("values"):
            continue
        values = data["values"]
        growth = data.get("growth_pct")
        if not growth or all(g in (0, 0.0, None) for g in growth):
            # The extraction step didn't supply a growth series (or supplied
            # an all-zero placeholder) even though we have the raw values to
            # compute it from. Rather than plot a flat, misleading 0% line,
            # derive quarter-over-quarter growth ourselves.
            growth = _derive_qoq_growth(values)
        rendered[key] = render_combo_chart(data["quarters"], values, growth, key)
    return rendered


def _derive_qoq_growth(values: list[float]) -> list[float]:
    """First point has no prior quarter to compare to, so it's 0 by
    definition (not a placeholder, an actual "no prior data" 0)."""
    growth = [0.0]
    for prev, curr in zip(values, values[1:]):
        pct = ((curr - prev) / prev * 100) if prev else 0.0
        growth.append(round(pct, 1))
    return growth
