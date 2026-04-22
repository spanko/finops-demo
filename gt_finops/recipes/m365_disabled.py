"""Recipe 3.3 — Disabled-but-licensed accounts."""

from __future__ import annotations

import json
import duckdb

from gt_finops.pricing import M365_SKU_MONTHLY
from gt_finops.recipes.base import Finding, Recipe


class DisabledButLicensed(Recipe):

    id = "3.3"
    name = "Disabled-but-licensed accounts"
    category = "M365"
    sources = ["m365_subscribed_skus", "m365_users"]

    def run(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:

        # SKU GUID -> (part_number, monthly_price)
        sku_rows = conn.execute(
            """
            SELECT sku_id, sku_part_number, unit_price_monthly_usd
            FROM m365_subscribed_skus
            """
        ).fetchall()
        sku_lookup: dict[str, tuple[str, float]] = {}
        for sku_id, part, price in sku_rows:
            # Fall back to defaults if price not populated
            effective_price = price if price else M365_SKU_MONTHLY.get(part, 0.0)
            sku_lookup[sku_id] = (part, effective_price)

        # Disabled users still holding licenses
        rows = conn.execute(
            """
            SELECT user_id, user_principal_name, display_name,
                   assigned_license_skus, deleted_datetime
            FROM m365_users
            WHERE account_enabled = FALSE
              AND assigned_license_skus IS NOT NULL
              AND assigned_license_skus != '[]'
              AND assigned_license_skus != ''
            """
        ).fetchall()

        findings: list[Finding] = []

        for user_id, upn, display_name, licenses_json, deleted_at in rows:
            try:
                sku_ids = json.loads(licenses_json) if licenses_json else []
            except (json.JSONDecodeError, TypeError):
                sku_ids = []
            if not sku_ids:
                continue

            # Sum the monthly value of all licenses this user holds
            monthly_total = 0.0
            sku_parts = []
            for sku_id in sku_ids:
                if sku_id in sku_lookup:
                    part, price = sku_lookup[sku_id]
                    monthly_total += price
                    sku_parts.append(part)

            if monthly_total == 0:
                continue  # nothing to save

            annual_savings = monthly_total * 12

            # deleted_datetime - if set, the account is in soft-delete window
            # Reclaim is slightly riskier because the account may be restored
            if deleted_at:
                confidence = "Medium"
                risk = "Medium"
                deps = ["Confirm user will not be restored from soft-delete"]
            else:
                confidence = "High"
                risk = "Low"
                deps = ["HR confirms account is permanently disabled",
                        "Not in active legal hold or eDiscovery case"]

            findings.append(
                self.make_finding(
                    entity_id=user_id,
                    entity_name=upn,
                    entity_type="user",
                    current_state=f"Disabled account holding licenses (${monthly_total:.0f}/mo)",
                    recommended_state="Unassign all licenses",
                    gross_annual_savings_usd=annual_savings,
                    capturable_factor=0.95,  # very high - just need HR confirmation
                    confidence=confidence,
                    days_to_capture=7,
                    risk_level=risk,
                    suggested_owner="IT — License Management",
                    dependencies=deps,
                    evidence={
                        "display_name": display_name,
                        "license_skus": sku_parts,
                        "monthly_value": round(monthly_total, 2),
                        "deleted_datetime": str(deleted_at) if deleted_at else None,
                    },
                )
            )

        return findings
