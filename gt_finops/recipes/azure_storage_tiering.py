"""Recipe 6.3 — Storage tiering (Hot → Cool → Archive)."""

from __future__ import annotations

import json
import duckdb

from gt_finops.pricing import STORAGE_TIER_SAVINGS_PERCENT
from gt_finops.recipes.base import Finding, Recipe


class StorageTiering(Recipe):

    id = "6.3"
    name = "Storage tiering"
    category = "Waste"
    sources = ["azure_resources", "azure_cost_focus"]

    def run(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:

        # Find storage accounts with their configured tier
        rows = conn.execute(
            """
            SELECT
                resource_id, resource_name, subscription_id, resource_group,
                location, sku_name, properties, tags
            FROM azure_resources
            WHERE resource_type ILIKE 'microsoft.storage/storageaccounts'
            """
        ).fetchall()

        findings: list[Finding] = []

        for (resource_id, name, sub_id, rg, loc, sku_name,
             props_json, tags) in rows:
            try:
                props = json.loads(props_json) if props_json else {}
            except (json.JSONDecodeError, TypeError):
                continue

            access_tier = (props.get("accessTier") or "").lower()
            # Only blob storage accounts have accessTier; skip others
            if access_tier not in ("hot", "cool"):
                continue

            # Check for existing lifecycle management policy
            has_lifecycle = bool(props.get("lifecycleManagementPolicy"))

            # Only recommend if no policy exists - otherwise probably already managed
            if has_lifecycle:
                continue

            # Get 30-day spend
            cost_row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(billed_cost), 0),
                    COUNT(DISTINCT DATE_TRUNC('day', charge_period_start)) AS days
                FROM azure_cost_focus
                WHERE resource_id = ?
                  AND service_category = 'Storage'
                  AND charge_period_start >= CURRENT_DATE - INTERVAL 30 DAY
                """,
                [resource_id],
            ).fetchone()

            total_cost = float(cost_row[0]) if cost_row else 0
            days = int(cost_row[1]) if cost_row and cost_row[1] else 0
            if days == 0 or total_cost <= 0:
                continue

            monthly_cost = (total_cost / days) * 30
            # Below threshold, not worth the effort
            if monthly_cost < 50:
                continue

            # Estimate: ~60% of data typically qualifies to move to Cool
            # Of Cool data, ~40% can subsequently move to Archive
            # Combined effective savings on 60% qualifying cold data ~ 40-50% of storage cost
            if access_tier == "hot":
                # 60% of data * ~50% savings on that portion = 30% overall
                monthly_savings = monthly_cost * 0.30
                target_state = "Hot with lifecycle: Hot→Cool@30d, Cool→Archive@90d"
            else:  # cool
                # 40% of Cool data * 80% savings = 32%
                monthly_savings = monthly_cost * 0.30
                target_state = "Cool with lifecycle: add Cool→Archive@90d"

            annual_savings = round(monthly_savings * 12, 2)

            findings.append(
                self.make_finding(
                    entity_id=resource_id,
                    entity_name=name or resource_id.split("/")[-1],
                    entity_type="storage_account",
                    current_state=f"Storage account on {access_tier.capitalize()} tier, no lifecycle policy — ${monthly_cost:.0f}/mo",
                    recommended_state=target_state,
                    gross_annual_savings_usd=annual_savings,
                    capturable_factor=0.70,
                    confidence="Medium",
                    days_to_capture=14,
                    risk_level="Low",
                    suggested_owner="IT — Storage Admin",
                    dependencies=[
                        "Enable last-access tracking on account",
                        "Verify no compliance rule requires immediate-access tier",
                        "Confirm Archive rehydration latency is acceptable for cold data",
                    ],
                    evidence={
                        "subscription_id": sub_id,
                        "resource_group": rg,
                        "location": loc,
                        "sku_name": sku_name,
                        "current_tier": access_tier,
                        "monthly_cost": round(monthly_cost, 2),
                        "has_lifecycle_policy": has_lifecycle,
                    },
                )
            )

        return findings
