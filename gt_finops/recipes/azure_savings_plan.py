"""Recipe 5.3 — Savings Plan coverage for stable compute."""

from __future__ import annotations

import duckdb

from gt_finops.pricing import SAVINGS_PLAN_DISCOUNT_PERCENT
from gt_finops.recipes.base import Finding, Recipe


STABILITY_WINDOW_MONTHS = 6
STABILITY_STDDEV_THRESHOLD = 0.15   # coef of variation below this = stable
UNDERBUY_FACTOR = 0.75              # size SP at 75% of stable baseline


class SavingsPlanCoverage(Recipe):

    id = "5.3"
    name = "Savings Plan coverage"
    category = "Commitments"
    sources = ["azure_cost_focus", "azure_savings_plans"]

    def run(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:

        # Compute uncovered compute spend per month over the last N months
        # Note: DuckDB doesn't support `INTERVAL ? MONTH` parameter binding;
        # inline the integer literal (module constant — safe)
        rows = conn.execute(
            f"""
            WITH monthly AS (
                SELECT
                    DATE_TRUNC('month', charge_period_start) AS month,
                    SUM(CASE WHEN service_category = 'Compute'
                             AND (commitment_discount_id IS NULL
                                  OR commitment_discount_id = '')
                             THEN billed_cost ELSE 0 END) AS uncovered_cost
                FROM azure_cost_focus
                WHERE charge_period_start >= CURRENT_DATE - INTERVAL {STABILITY_WINDOW_MONTHS} MONTH
                GROUP BY DATE_TRUNC('month', charge_period_start)
            )
            SELECT
                COUNT(*) AS month_count,
                AVG(uncovered_cost) AS avg_monthly,
                STDDEV(uncovered_cost) AS stddev_monthly,
                MIN(uncovered_cost) AS min_monthly,
                MAX(uncovered_cost) AS max_monthly
            FROM monthly
            """
        ).fetchone()

        if rows is None:
            return []

        month_count, avg_monthly, stddev_monthly, min_monthly, max_monthly = rows

        if month_count is None or month_count < STABILITY_WINDOW_MONTHS:
            return []
        if avg_monthly is None or avg_monthly <= 0:
            return []

        avg_monthly = float(avg_monthly)
        stddev_monthly = float(stddev_monthly or 0)
        cov = stddev_monthly / avg_monthly if avg_monthly > 0 else 1.0

        if cov > STABILITY_STDDEV_THRESHOLD:
            return []  # not stable enough to commit

        # Size SP at 75% of the stable baseline to leave headroom
        sp_monthly_commit = avg_monthly * UNDERBUY_FACTOR
        # Conservative: use 1-year discount
        discount = SAVINGS_PLAN_DISCOUNT_PERCENT["P1Y"]
        monthly_savings = sp_monthly_commit * discount
        annual_savings = round(monthly_savings * 12, 2)

        # Skip if SP already covers substantial portion
        existing_sp_count = conn.execute(
            "SELECT COUNT(*) FROM azure_savings_plans"
        ).fetchone()[0]
        # If any SPs exist, still worth flagging gap, but reduce capturable
        capturable = 0.80 if existing_sp_count == 0 else 0.60

        return [
            self.make_finding(
                entity_id="tenant-savings-plan-coverage",
                entity_name="Tenant-wide Compute Savings Plan opportunity",
                entity_type="tenant",
                current_state=f"${avg_monthly:,.0f}/mo uncovered compute, stable over {month_count} months",
                recommended_state=f"Purchase 1-yr Compute SP at ${sp_monthly_commit:,.0f}/hr equivalent",
                gross_annual_savings_usd=annual_savings,
                capturable_factor=capturable,
                confidence="Medium",  # always Medium - forecast dependent
                days_to_capture=14,
                risk_level="Medium",
                suggested_owner="FinOps / Finance",
                dependencies=[
                    "Apply AHB first before sizing (SP applies to post-AHB spend)",
                    "Confirm 12-month minimum commitment is acceptable",
                    "Identify payment terms preference (upfront vs monthly)",
                ],
                evidence={
                    "months_analyzed": month_count,
                    "avg_monthly_uncovered_cost": round(avg_monthly, 2),
                    "stddev_monthly": round(stddev_monthly, 2),
                    "coefficient_of_variation": round(cov, 3),
                    "min_monthly": round(float(min_monthly), 2) if min_monthly else 0,
                    "max_monthly": round(float(max_monthly), 2) if max_monthly else 0,
                    "recommended_sp_monthly": round(sp_monthly_commit, 2),
                    "discount_rate": discount,
                    "existing_sp_count": existing_sp_count,
                },
            )
        ]
