"""Recipe 3.5 — Teams Phone without PSTN usage."""

from __future__ import annotations

import json
import duckdb

from gt_finops.pricing import M365_SKU_MONTHLY
from gt_finops.recipes.base import Finding, Recipe


# Calling Plan SKU part numbers (various regional variants)
CALLING_PLAN_SKU_PARTS = [
    "MCOPSTNC",    # Domestic
    "MCOPSTN5",    # Domestic + International
    "MCOPSTNEAU",  # Regional
    "MCOPSTNEAU2",
]


class TeamsPhoneUnused(Recipe):

    id = "3.5"
    name = "Teams Phone without PSTN usage"
    category = "M365"
    sources = ["m365_subscribed_skus", "m365_users", "m365_pstn_calls"]

    def run(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:

        # Resolve Calling Plan SKU GUIDs and prices
        placeholders = ", ".join(["?"] * len(CALLING_PLAN_SKU_PARTS))
        sku_rows = conn.execute(
            f"""
            SELECT sku_id, sku_part_number, unit_price_monthly_usd
            FROM m365_subscribed_skus
            WHERE sku_part_number IN ({placeholders})
            """,
            CALLING_PLAN_SKU_PARTS,
        ).fetchall()

        if not sku_rows:
            return []

        cp_sku_map: dict[str, tuple[str, float]] = {}
        for sku_id, part, price in sku_rows:
            effective = price if price else M365_SKU_MONTHLY.get(part, 10.0)
            cp_sku_map[sku_id] = (part, effective)

        # Users with any calling plan assigned
        # assigned_license_skus is stored as JSON array; match any membership
        rows = conn.execute(
            """
            SELECT
                u.user_id,
                u.user_principal_name,
                u.display_name,
                u.assigned_license_skus,
                COALESCE(p.outbound_pstn_calls_90d, 0) AS outbound_90d,
                COALESCE(p.inbound_pstn_calls_90d, 0) AS inbound_90d,
                p.last_pstn_call_date
            FROM m365_users u
            LEFT JOIN m365_pstn_calls p
                ON p.user_principal_name = u.user_principal_name
            WHERE u.account_enabled = TRUE
            """
        ).fetchall()

        findings: list[Finding] = []

        for row in rows:
            user_id, upn, display_name, licenses_json, outbound, inbound, last_call = row

            try:
                sku_ids = json.loads(licenses_json) if licenses_json else []
            except (json.JSONDecodeError, TypeError):
                continue

            # Find any Calling Plan SKUs assigned
            user_cp_skus = [sku_id for sku_id in sku_ids if sku_id in cp_sku_map]
            if not user_cp_skus:
                continue

            # Criterion: zero outbound PSTN in 90 days
            if outbound > 0:
                continue

            # Sum the monthly value of their Calling Plan subscriptions
            monthly_total = sum(cp_sku_map[s][1] for s in user_cp_skus)
            parts_held = [cp_sku_map[s][0] for s in user_cp_skus]
            annual_savings = monthly_total * 12

            # If they still receive inbound, flag as Medium confidence (may
            # intentionally be a receive-only setup, like reception desk)
            confidence = "Medium" if inbound > 0 else "High"
            risk = "Medium" if inbound > 0 else "Low"

            deps = ["Verify E911 compliance doesn't require Calling Plan"]
            if inbound > 0:
                deps.append(
                    f"User received {inbound} inbound PSTN calls in 90 days — "
                    "confirm outbound plan isn't needed for callbacks"
                )

            findings.append(
                self.make_finding(
                    entity_id=user_id,
                    entity_name=upn,
                    entity_type="user",
                    current_state=f"Calling Plan ({', '.join(parts_held)}) - "
                                  f"0 outbound PSTN calls in 90 days",
                    recommended_state="Remove Calling Plan (keep Teams Phone Standard for VoIP)",
                    gross_annual_savings_usd=annual_savings,
                    capturable_factor=0.60,
                    confidence=confidence,
                    days_to_capture=14,
                    risk_level=risk,
                    suggested_owner="IT — Telephony Admin",
                    dependencies=deps,
                    evidence={
                        "display_name": display_name,
                        "calling_plans": parts_held,
                        "outbound_90d": outbound,
                        "inbound_90d": inbound,
                        "last_pstn_call": str(last_call) if last_call else None,
                        "monthly_value": round(monthly_total, 2),
                    },
                )
            )

        return findings
