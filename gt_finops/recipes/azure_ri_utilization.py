"""Recipe 5.2 — Reservation scope and utilization."""

from __future__ import annotations

from datetime import date, timedelta
import duckdb

from gt_finops.recipes.base import Finding, Recipe


UTILIZATION_WINDOW_DAYS = 90
HEALTHY_THRESHOLD = 0.70       # >= 70% = healthy
RESCOPE_THRESHOLD = 0.70       # < 70% & single scope = rescope candidate
EXCHANGE_THRESHOLD = 0.40      # < 40% = exchange or cancel


class ReservationUtilization(Recipe):

    id = "5.2"
    name = "Reservation scope and utilization"
    category = "Commitments"
    sources = ["azure_reservations", "azure_reservation_utilization"]

    def run(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:

        # Per-reservation average utilization over the window
        # Note: DuckDB doesn't support `INTERVAL ? DAY` parameter binding,
        # so we inline the integer literal (safe since it's a module constant)
        rows = conn.execute(
            f"""
            SELECT
                r.reservation_id,
                r.display_name,
                r.sku_name,
                r.region,
                r.quantity,
                r.term,
                r.scope,
                r.effective_cost_monthly_usd,
                r.expiration_date,
                COALESCE(AVG(u.utilization_percentage), 0) AS avg_util,
                COUNT(DISTINCT u.usage_date) AS days_of_data
            FROM azure_reservations r
            LEFT JOIN azure_reservation_utilization u
                ON u.reservation_id = r.reservation_id
               AND u.usage_date >= CURRENT_DATE - INTERVAL {UTILIZATION_WINDOW_DAYS} DAY
            GROUP BY ALL
            """
        ).fetchall()

        findings: list[Finding] = []

        for row in rows:
            (reservation_id, display_name, sku, region, qty, term, scope,
             monthly_cost, expiration, avg_util, days_of_data) = row

            if days_of_data < 30:
                continue  # insufficient data

            util_ratio = float(avg_util) / 100.0
            monthly_cost = float(monthly_cost or 0)

            if util_ratio >= HEALTHY_THRESHOLD:
                continue  # healthy, nothing to do

            # Determine the right action
            scope_is_single = (scope or "").lower() in ("single", "singleresourcegroup",
                                                        "singlesubscription")

            # Case A: low util with single scope — rescope (free)
            if scope_is_single and util_ratio < RESCOPE_THRESHOLD:
                # Estimate recovered utilization - assume rescope brings +20pts
                potential_additional_util = min(0.25, HEALTHY_THRESHOLD - util_ratio)
                monthly_savings = monthly_cost * potential_additional_util
                annual_savings = round(monthly_savings * 12, 2)

                findings.append(
                    self.make_finding(
                        entity_id=reservation_id,
                        entity_name=display_name or reservation_id[:12],
                        entity_type="reservation",
                        current_state=f"RI at single scope, {avg_util:.0f}% avg utilization",
                        recommended_state="Re-scope to Shared (free, reversible)",
                        gross_annual_savings_usd=annual_savings,
                        capturable_factor=0.80,
                        confidence="High",
                        days_to_capture=3,
                        risk_level="Low",
                        suggested_owner="FinOps / Azure Admin",
                        dependencies=[
                            "Client chargeback rules permit shared-scope RIs",
                        ],
                        evidence={
                            "sku": sku, "region": region, "quantity": qty,
                            "term": term, "avg_utilization": round(float(avg_util), 2),
                            "days_of_data": days_of_data,
                            "current_scope": scope,
                            "monthly_cost": round(monthly_cost, 2),
                            "expiration_date": str(expiration),
                        },
                    )
                )
                continue

            # Case B: very low util regardless of scope — exchange or cancel
            if util_ratio < EXCHANGE_THRESHOLD:
                # Savings estimate: waste portion that's recoverable via exchange
                waste_ratio = max(0, 1.0 - util_ratio)
                monthly_waste = monthly_cost * waste_ratio
                annual_waste = round(monthly_waste * 12, 2)

                findings.append(
                    self.make_finding(
                        entity_id=reservation_id,
                        entity_name=display_name or reservation_id[:12],
                        entity_type="reservation",
                        current_state=f"RI at {avg_util:.0f}% utilization — mostly wasted",
                        recommended_state="Exchange for different SKU/region, or cancel",
                        gross_annual_savings_usd=annual_waste,
                        capturable_factor=0.60,
                        confidence="Medium",
                        days_to_capture=30,
                        risk_level="Medium",
                        suggested_owner="FinOps / Azure Admin",
                        dependencies=[
                            "Verify 12-month exchange window still open",
                            "Identify the right replacement SKU before cancelling",
                            "Cancellation has 12%/yr penalty on remaining value",
                        ],
                        evidence={
                            "sku": sku, "region": region, "quantity": qty,
                            "term": term, "avg_utilization": round(float(avg_util), 2),
                            "days_of_data": days_of_data,
                            "current_scope": scope,
                            "monthly_cost": round(monthly_cost, 2),
                            "expiration_date": str(expiration),
                        },
                    )
                )
                continue

            # Case C: low-but-not-dire util with already-shared scope
            # Recommend monitoring + exchange planning
            if not scope_is_single:
                waste_ratio = max(0, HEALTHY_THRESHOLD - util_ratio)
                monthly_waste = monthly_cost * waste_ratio
                annual_waste = round(monthly_waste * 12, 2)

                findings.append(
                    self.make_finding(
                        entity_id=reservation_id,
                        entity_name=display_name or reservation_id[:12],
                        entity_type="reservation",
                        current_state=f"Shared-scope RI at {avg_util:.0f}% — underutilized",
                        recommended_state="Evaluate exchange for different SKU",
                        gross_annual_savings_usd=annual_waste,
                        capturable_factor=0.50,
                        confidence="Medium",
                        days_to_capture=30,
                        risk_level="Medium",
                        suggested_owner="FinOps / Azure Admin",
                        dependencies=[
                            "Match a different SKU that client actively runs at scale",
                        ],
                        evidence={
                            "sku": sku, "region": region, "quantity": qty,
                            "term": term, "avg_utilization": round(float(avg_util), 2),
                            "monthly_cost": round(monthly_cost, 2),
                            "expiration_date": str(expiration),
                        },
                    )
                )

        return findings
