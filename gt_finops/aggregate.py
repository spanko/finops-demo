"""
Findings aggregation — rollup, dedup, and summary statistics.

The raw findings table has one row per (recipe, entity) pair. This module
provides the views consultants and the report layer need.
"""

from __future__ import annotations

from dataclasses import dataclass
import duckdb
import pandas as pd


@dataclass
class FindingsSummary:
    total_findings: int
    total_gross_usd: float
    total_capturable_usd: float
    by_category: dict[str, dict[str, float]]     # category → {count, gross, capturable}
    by_recipe: dict[str, dict[str, float]]       # recipe_id → {name, count, gross, capturable}
    by_confidence: dict[str, int]


def summarize(conn: duckdb.DuckDBPyConnection) -> FindingsSummary:
    """Compute the top-level summary of all findings."""

    total_row = conn.execute(
        """
        SELECT
            COUNT(*) AS n,
            COALESCE(SUM(gross_annual_savings_usd), 0) AS gross,
            COALESCE(SUM(capturable_annual_savings_usd), 0) AS capturable
        FROM findings
        """
    ).fetchone()
    total_findings, gross, capturable = total_row

    by_cat_rows = conn.execute(
        """
        SELECT
            category,
            COUNT(*) AS n,
            COALESCE(SUM(gross_annual_savings_usd), 0) AS gross,
            COALESCE(SUM(capturable_annual_savings_usd), 0) AS capturable
        FROM findings
        GROUP BY category
        ORDER BY capturable DESC
        """
    ).fetchall()
    by_category = {
        row[0]: {
            "count": int(row[1]),
            "gross": float(row[2]),
            "capturable": float(row[3]),
        }
        for row in by_cat_rows
    }

    by_recipe_rows = conn.execute(
        """
        SELECT
            recipe_id, recipe_name,
            COUNT(*) AS n,
            COALESCE(SUM(gross_annual_savings_usd), 0) AS gross,
            COALESCE(SUM(capturable_annual_savings_usd), 0) AS capturable
        FROM findings
        GROUP BY recipe_id, recipe_name
        ORDER BY recipe_id
        """
    ).fetchall()
    by_recipe = {
        row[0]: {
            "name": row[1],
            "count": int(row[2]),
            "gross": float(row[3]),
            "capturable": float(row[4]),
        }
        for row in by_recipe_rows
    }

    by_conf_rows = conn.execute(
        """
        SELECT confidence, COUNT(*) FROM findings GROUP BY confidence
        """
    ).fetchall()
    by_confidence = {row[0]: int(row[1]) for row in by_conf_rows}

    return FindingsSummary(
        total_findings=int(total_findings),
        total_gross_usd=float(gross),
        total_capturable_usd=float(capturable),
        by_category=by_category,
        by_recipe=by_recipe,
        by_confidence=by_confidence,
    )


def top_findings(
    conn: duckdb.DuckDBPyConnection, limit: int = 25,
) -> pd.DataFrame:
    """Return top-N findings ranked by capturable savings."""
    return conn.execute(
        """
        SELECT
            recipe_id, recipe_name, category,
            entity_name, entity_type,
            current_state, recommended_state,
            gross_annual_savings_usd,
            capturable_annual_savings_usd,
            confidence, risk_level, suggested_owner
        FROM findings
        ORDER BY capturable_annual_savings_usd DESC
        LIMIT ?
        """,
        [limit],
    ).df()


def findings_for_recipe(
    conn: duckdb.DuckDBPyConnection, recipe_id: str,
) -> pd.DataFrame:
    """All findings for a specific recipe, as a DataFrame."""
    return conn.execute(
        """
        SELECT * FROM findings
        WHERE recipe_id = ?
        ORDER BY capturable_annual_savings_usd DESC
        """,
        [recipe_id],
    ).df()


def all_findings(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return conn.execute(
        "SELECT * FROM findings ORDER BY capturable_annual_savings_usd DESC"
    ).df()
