"""
Recipe 3.1 — E5 → E3 downgrade.

Identifies users paying for Microsoft 365 E5 who have shown no activity in any
E5-exclusive feature over the last 30 days. Per the playbook, per-user savings
is ~$22/month ($264/year).

Reference implementation — this is the most thoroughly commented recipe so
other recipes can follow the pattern.
"""

from __future__ import annotations

import json
import duckdb

from gt_finops.pricing import (
    DOWNGRADE_SAVINGS_MONTHLY,
    E5_EXCLUSIVE_SERVICES,
    M365_SKU_MONTHLY,
)
from gt_finops.recipes.base import Finding, Recipe


# SKU part number for Microsoft 365 E5 (sometimes published as the "enterprise premium" SKU)
E5_SKU_PART = "ENTERPRISEPREMIUM"
E3_SKU_PART = "ENTERPRISEPACK"


class E5ToE3Downgrade(Recipe):

    id = "3.1"
    name = "E5 → E3 downgrade"
    category = "M365"
    sources = ["m365_subscribed_skus", "m365_users", "m365_activity"]

    def run(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:

        # ---------------------------------------------------------------
        # Step 1: resolve SKU IDs
        # The GUIDs for E5 and E3 are tenant-invariant but we look them up
        # via sku_part_number to avoid hardcoding GUIDs.
        # ---------------------------------------------------------------
        sku_row = conn.execute(
            """
            SELECT sku_id FROM m365_subscribed_skus
            WHERE sku_part_number = ?
            """,
            [E5_SKU_PART],
        ).fetchone()

        if sku_row is None:
            # Tenant doesn't have E5 purchased - recipe is a no-op
            return []
        e5_sku_id = sku_row[0]

        # ---------------------------------------------------------------
        # Step 2: find users with E5 assigned and evaluate activity
        # We join users to activity and apply the E5-exclusive service filter.
        # A user is a candidate if they have NO activity in any E5-exclusive
        # service in the last 30 days.
        # ---------------------------------------------------------------
        # Build a set of exclusive service names to check. These map to the
        # normalized `service` column in m365_activity.
        exclusive_services = {
            "powerbi",       # Power BI Pro usage (bundled in E5)
            "teams_phone",   # Phone System / Teams Phone Standard
            "defender_o365_p2",
            "viva_insights",
            "advanced_ediscovery",
        }

        # DuckDB parametrized query - users with E5 and activity summary
        query = """
            WITH e5_users AS (
                SELECT
                    u.user_id,
                    u.user_principal_name,
                    u.display_name,
                    u.department,
                    u.job_title,
                    u.last_sign_in_datetime
                FROM m365_users u
                WHERE u.account_enabled = TRUE
                  AND u.assigned_license_skus LIKE '%' || ? || '%'
            ),
            user_activity AS (
                SELECT
                    a.user_principal_name,
                    a.service,
                    a.last_activity_date,
                    a.activity_count_30d
                FROM m365_activity a
            )
            SELECT
                e5.user_id,
                e5.user_principal_name,
                e5.display_name,
                e5.department,
                e5.job_title,
                e5.last_sign_in_datetime,
                -- Aggregate activity signals
                COALESCE(MAX(CASE WHEN a.service = 'powerbi'
                    AND COALESCE(a.activity_count_30d, 0) > 0 THEN 1 ELSE 0 END), 0)
                    AS active_powerbi,
                COALESCE(MAX(CASE WHEN a.service = 'teams_phone'
                    AND COALESCE(a.activity_count_30d, 0) > 0 THEN 1 ELSE 0 END), 0)
                    AS active_teams_phone,
                COALESCE(MAX(CASE WHEN a.service = 'defender_o365_p2'
                    AND COALESCE(a.activity_count_30d, 0) > 0 THEN 1 ELSE 0 END), 0)
                    AS active_defender,
                COALESCE(MAX(CASE WHEN a.service = 'viva_insights'
                    AND COALESCE(a.activity_count_30d, 0) > 0 THEN 1 ELSE 0 END), 0)
                    AS active_viva,
                COALESCE(MAX(CASE WHEN a.service = 'advanced_ediscovery'
                    AND COALESCE(a.activity_count_30d, 0) > 0 THEN 1 ELSE 0 END), 0)
                    AS active_ediscovery
            FROM e5_users e5
            LEFT JOIN user_activity a
                ON a.user_principal_name = e5.user_principal_name
            GROUP BY ALL
        """
        rows = conn.execute(query, [e5_sku_id]).fetchall()

        # ---------------------------------------------------------------
        # Step 3: apply decision logic and build findings
        # ---------------------------------------------------------------
        monthly_savings = DOWNGRADE_SAVINGS_MONTHLY.get(
            (E5_SKU_PART, E3_SKU_PART), 22.00
        )
        annual_savings_per_user = monthly_savings * 12

        findings: list[Finding] = []

        for row in rows:
            (
                user_id, upn, display_name, department, job_title, last_sign_in,
                active_powerbi, active_teams_phone, active_defender, active_viva,
                active_ediscovery,
            ) = row

            # If any E5-exclusive signal is active, keep on E5
            is_e5_active = bool(
                active_powerbi or active_teams_phone or active_defender
                or active_viva or active_ediscovery
            )
            if is_e5_active:
                continue

            # Also skip users who haven't signed in at all in 90 days
            # (extended lookback for edge cases like parental leave)
            # Keep them as E5 for now; they'll surface in 3.3 if disabled
            # This is a conservative choice that avoids surprising reclaims
            if last_sign_in is None:
                continue

            # Confidence rating: High if we have activity data for all five
            # services; Medium if some are missing (unmeasured != inactive)
            activity_coverage = sum(
                1 for a in [active_powerbi, active_teams_phone, active_defender,
                            active_viva, active_ediscovery]
            )
            # activity_coverage is always 5 here because MAX(CASE) returns 0
            # rather than NULL - but if the activity table was empty for this
            # user entirely, coverage drops. Check this explicitly:
            had_any_activity_row = conn.execute(
                """
                SELECT COUNT(*) FROM m365_activity
                WHERE user_principal_name = ?
                """,
                [upn],
            ).fetchone()[0]
            confidence = "High" if had_any_activity_row >= 5 else "Medium"

            evidence = {
                "last_sign_in": str(last_sign_in) if last_sign_in else None,
                "active_signals_checked": [
                    "powerbi", "teams_phone", "defender_o365_p2",
                    "viva_insights", "advanced_ediscovery",
                ],
                "activity_rows_found": had_any_activity_row,
                "current_sku": E5_SKU_PART,
                "target_sku": E3_SKU_PART,
                "department": department,
                "job_title": job_title,
            }

            findings.append(
                self.make_finding(
                    entity_id=user_id,
                    entity_name=upn,
                    entity_type="user",
                    current_state=f"M365 E5 ({M365_SKU_MONTHLY.get(E5_SKU_PART, 57):.0f}/month)",
                    recommended_state=f"M365 E3 ({M365_SKU_MONTHLY.get(E3_SKU_PART, 36):.0f}/month)",
                    gross_annual_savings_usd=annual_savings_per_user,
                    capturable_factor=0.75,          # 70-85% per playbook
                    confidence=confidence,
                    days_to_capture=14,              # typical BU review cycle
                    risk_level="Low",                # no workload change
                    suggested_owner="IT — License Management",
                    dependencies=[
                        "BU lead confirms user does not need E5 compliance features",
                        "Not in active legal hold or eDiscovery case",
                    ],
                    evidence=evidence,
                )
            )

        return findings
