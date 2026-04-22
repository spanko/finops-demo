"""HTML report generator."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb
from jinja2 import Environment, FileSystemLoader, select_autoescape

from gt_finops import __version__
from gt_finops.aggregate import summarize, top_findings, all_findings


def write_html_report(
    conn: duckdb.DuckDBPyConnection,
    output_path: Path,
    client_name: str,
) -> Path:
    """Render the findings HTML report and return the output path."""

    templates_dir = Path(__file__).parent.parent / "templates"
    env = Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report.html.j2")

    summary = summarize(conn)
    top = top_findings(conn, limit=25)

    # Group all findings by recipe for the per-recipe detail section
    all_df = all_findings(conn)
    recipe_findings: dict = {}
    if not all_df.empty:
        for rid, group in all_df.groupby("recipe_id"):
            recipe_findings[rid] = group.to_dict("records")

    # Get schema version
    version_row = conn.execute(
        "SELECT value FROM engagement_metadata WHERE key = 'schema_version'"
    ).fetchone()
    schema_version = version_row[0] if version_row else "0.1.0"

    rendered = template.render(
        client_name=client_name,
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        summary=summary,
        top_findings=top.to_dict("records"),
        recipe_findings=recipe_findings,
        version=__version__,
        schema_version=schema_version,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    return output_path
