"""Recipe 3.4 — Copilot reclaim."""

from __future__ import annotations

from datetime import date, timedelta
import duckdb

from gt_finops.pricing import M365_SKU_MONTHLY
from gt_finops.recipes.base import Finding, Recipe


COPILOT_SKU_PART = "Microsoft_365_Copilot"
COPILOT_MONTHLY_USD = M365_SKU_MONTHLY.get(COPILOT_SKU_PART, 30.00)


class CopilotReclaim(Recipe):

    id = "3.4"
    name = "Copilot reclaim"
    category = "M365"
    sources = ["m365_subscribed_skus", "m365_users", "m365_activity"]

    def run(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:

        copilot = conn.execute(
            "SELECT sku_id FROM m365_subscribed_skus WHERE sku_part_number = ?",
            [COPILOT_SKU_PART],
        ).fetchone()
        if copilot is None:
            return []
        copilot_sku_id = copilot[0]

        # Users with Copilot assigned + Copilot activity
        rows = conn.execute(
            """
            SELECT
                u.user_id,
                u.user_principal_name,
                u.display_name,
                u.department,
                u.created_datetime,
                a.last_activity_date,
                a.activity_count_30d
            FROM m365_users u
            LEFT JOIN m365_activity a
                ON a.user_principal_name = u.user_principal_name
               AND a.service = 'copilot'
            WHERE u.account_enabled = TRUE
              AND u.assigned_license_skus LIKE '%' || ? || '%'
            """,
            [copilot_sku_id],
        ).fetchall()

        threshold_date = date.today() - timedelta(days=30)
        # Exclude users within 14-day ramp window
        ramp_cutoff = date.today() - timedelta(days=14)

        annual_savings = COPILOT_MONTHLY_USD * 12
        findings: list[Finding] = []

        for row in rows:
            (user_id, upn, display_name, dept, created, last_activity, count_30d) = row

            # Ramp exclusion
            if created is not None:
                created_date = created.date() if hasattr(created, "date") else created
                if created_date > ramp_cutoff:
                    continue

            has_any_activity = (
                last_activity is not None
                and last_activity >= threshold_date
                and (count_30d or 0) > 0
            )
            if has_any_activity:
                continue

            findings.append(
                self.make_finding(
                    entity_id=user_id,
                    entity_name=upn,
                    entity_type="user",
                    current_state=f"Copilot licensed, no activity in 30 days",
                    recommended_state="Reclaim and reassign to waitlisted user (or drop)",
                    gross_annual_savings_usd=annual_savings,
                    capturable_factor=0.70,
                    confidence="High" if last_activity is None else "Medium",
                    days_to_capture=7,
                    risk_level="Low",
                    suggested_owner="IT — License Management",
                    dependencies=[
                        "Verify user is not currently ramping up (<30 days)",
                        "Check waitlist for reassignment candidate",
                    ],
                    evidence={
                        "display_name": display_name,
                        "department": dept,
                        "last_copilot_activity_date":
                            str(last_activity) if last_activity else None,
                        "activity_count_30d": count_30d,
                        "account_created_date":
                            str(created.date() if hasattr(created, "date") else created)
                            if created else None,
                    },
                )
            )

        return findings
