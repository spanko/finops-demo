"""Recipe 5.4 — Dev/Test pricing eligibility."""

from __future__ import annotations

import json
import re
import duckdb

from gt_finops.pricing import DEVTEST_DISCOUNT_PERCENT, NONPROD_NAME_PATTERNS
from gt_finops.recipes.base import Finding, Recipe


class DevTestPricing(Recipe):

    id = "5.4"
    name = "Dev/Test pricing eligibility"
    category = "Commitments"
    sources = ["azure_resources", "azure_cost_focus"]

    def run(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:

        # ResourceContainers style subscription records in the inventory
        subs = conn.execute(
            """
            SELECT DISTINCT
                subscription_id, subscription_name, properties
            FROM azure_resources
            WHERE subscription_id IS NOT NULL
            """
        ).fetchall()

        if not subs:
            # Fall back to cost data for subscription IDs if inventory is thin
            subs = conn.execute(
                """
                SELECT DISTINCT sub_account_id, sub_account_name, NULL
                FROM azure_cost_focus
                WHERE sub_account_id IS NOT NULL
                """
            ).fetchall()

        patterns = [re.compile(p, re.IGNORECASE) for p in NONPROD_NAME_PATTERNS]

        findings: list[Finding] = []

        for sub_id, sub_name, props_json in subs:
            if not sub_name:
                continue

            matches_nonprod = any(p.search(sub_name) for p in patterns)
            if not matches_nonprod:
                continue

            # Check offer type from properties (if available); absence implies
            # non-DevTest
            offer_type = ""
            if props_json:
                try:
                    props = json.loads(props_json)
                    offer_type = (props.get("quotaId") or "").lower()
                except (json.JSONDecodeError, TypeError):
                    pass

            if "devtest" in offer_type:
                continue  # already on Dev/Test pricing

            # Compute monthly spend in this subscription
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(billed_cost), 0),
                    COUNT(DISTINCT DATE_TRUNC('day', charge_period_start)) AS days
                FROM azure_cost_focus
                WHERE sub_account_id = ?
                  AND charge_period_start >= CURRENT_DATE - INTERVAL 30 DAY
                  AND (service_category = 'Compute' OR service_name LIKE '%SQL%')
                """,
                [sub_id],
            ).fetchone()
            if row is None:
                continue

            total_cost, days = float(row[0]), int(row[1])
            if days == 0 or total_cost <= 0:
                continue

            monthly_cost = (total_cost / days) * 30
            # Dev/Test discount applies to compute + SQL
            monthly_savings = monthly_cost * DEVTEST_DISCOUNT_PERCENT
            annual_savings = round(monthly_savings * 12, 2)

            findings.append(
                self.make_finding(
                    entity_id=sub_id,
                    entity_name=sub_name,
                    entity_type="subscription",
                    current_state=f"Subscription '{sub_name}' on non-Dev/Test offer, ${monthly_cost:,.0f}/mo compute+SQL",
                    recommended_state="Convert to EA Dev/Test subscription",
                    gross_annual_savings_usd=annual_savings,
                    capturable_factor=0.70,
                    confidence="Medium",
                    days_to_capture=14,
                    risk_level="Medium",
                    suggested_owner="Microsoft account team + IT Procurement",
                    dependencies=[
                        "Confirm no production workloads run in this subscription",
                        "All users accessing sub must have Visual Studio subscriptions",
                        "Not internet-facing with end users",
                        "Microsoft rep must initiate offer conversion",
                    ],
                    evidence={
                        "subscription_name": sub_name,
                        "monthly_cost": round(monthly_cost, 2),
                        "name_matched_pattern": matches_nonprod,
                        "current_offer": offer_type or "(unknown)",
                    },
                )
            )

        return findings
