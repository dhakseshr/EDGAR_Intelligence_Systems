"""Weekly PDF research report generator using Jinja2 + WeasyPrint."""
import os
import re
from datetime import date, datetime
from pathlib import Path
import markdown
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _severity_counts(filings: list[dict]) -> dict:
    counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    for f in filings:
        sev = f.get("severity", "Low")
        counts[sev] = counts.get(sev, 0) + 1
    return counts


def _thesis_counts(filings: list[dict]) -> dict:
    counts = {"Bullish": 0, "Neutral": 0, "Bearish": 0}
    for f in filings:
        t = f.get("thesis", "Neutral")
        counts[t] = counts.get(t, 0) + 1
    return counts


def _group_by_sector(filings: list[dict]) -> dict:
    sectors: dict[str, list] = {}
    for f in filings:
        sector = f.get("sector", "General")
        for evt in f.get("events", []):
            sectors.setdefault(sector, []).append({
                "company": f["company"],
                "event_type": evt["event_type"],
                "summary": evt["summary"][:120],
            })
    return sectors


def generate_weekly_report(
    filings: list[dict],
    week_start: date,
    week_end: date,
    output_path: str,
) -> str:
    """
    Build a PDF report for the given week.

    Each filing dict expected keys:
        company, filing_date, sector, score, severity,
        thesis, thesis_confidence, thesis_reasoning,
        key_factors, events (list of {event_type, summary, confidence}),
        memo (markdown string)
    Returns path to generated PDF.
    """
    sev = _severity_counts(filings)
    thesis = _thesis_counts(filings)
    sectors = _group_by_sector(filings)

    filings_ranked = sorted(filings, key=lambda f: f.get("score", 0), reverse=True)

    # Convert memo markdown → HTML
    memos_with_html = []
    for f in filings_ranked:
        memo_html = markdown.markdown(f.get("memo", ""), extensions=["tables"])
        memos_with_html.append({**f, "memo_html": memo_html})

    thesis_matrix = [
        {
            "company": f["company"],
            "thesis": f.get("thesis", "Neutral"),
            "confidence": f.get("thesis_confidence", 0.5),
            "key_factors": f.get("key_factors", []),
            "reasoning": f.get("thesis_reasoning", ""),
        }
        for f in filings_ranked
    ]

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=False)
    template = env.get_template("report.html")
    html_content = template.render(
        week_start=week_start.strftime("%B %d, %Y"),
        week_end=week_end.strftime("%B %d, %Y"),
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        total_filings=len(filings),
        critical_count=sev["Critical"],
        high_count=sev["High"],
        medium_count=sev["Medium"],
        low_count=sev["Low"],
        bullish_count=thesis["Bullish"],
        neutral_count=thesis["Neutral"],
        bearish_count=thesis["Bearish"],
        filings_ranked=filings_ranked,
        events_by_sector=sectors,
        memos=memos_with_html,
        thesis_matrix=thesis_matrix,
    )

    css_path = TEMPLATES_DIR / "style.css"
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    HTML(string=html_content, base_url=str(TEMPLATES_DIR)).write_pdf(
        output_path,
        stylesheets=[CSS(filename=str(css_path))],
    )
    return output_path
