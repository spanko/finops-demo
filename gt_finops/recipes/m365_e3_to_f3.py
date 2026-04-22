"""Recipe 3.2 — E3 → F3 for frontline workers."""

from __future__ import annotations

import duckdb

from gt_finops.pricing import DOWNGRADE_SAVINGS_MONTHLY, M365_SKU_MONTHLY
from gt_finops.recipes.base import Finding, Recipe


E3_SKU_PART = "ENTERPRISEPACK"
F3_SKU_PART = "DESKLESSPACK"

# Thresholds from playbook
ONEDRIVE_F3_GB_LIMIT = 2.0
MAILBOX_F3_GB_LIMIT = 2.0


class E3ToF3Downgrade(Recipe):

    id = "3.2"
    name = "E3 → F3 for frontline workers"
    category = "M365"
    sources = ["m365_subscribed_skus", "m365_users", "m365_activity",
               "m365_office_activations"]

    def run(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:

        e3_row = conn.execute(
            "SELECT sku_id FROM m365_subscribed_skus WHERE sku_part_number = ?",
            [E3_SKU_PART],
        ).fetchone()
        if e3_row is None:
            return []
        e3_sku_id = e3_row[0]

        # Candidates: E3 users who match all four F3 signals
        # (no desktop Office, OneDrive <= 2GB, no SP ownership, small mailbox)
        query = """
            WITH e3_users AS (
                SELECT
                    u.user_id, u.user_principal_name, u.display_name,
                    u.department, u.job_title
                FROM m365_users u
                WHERE u.account_enabled = TRUE
                  AND u.assigned_license_skus LIKE '%' || ? || '%'
            ),
            activation_check AS (
                SELECT user_principal_name, activated_on_any_device
                FROM m365_office_activations
            ),
            onedrive_storage AS (
                SELECT
                    user_principal_name,
                    -- Extract OneDrive storage from activity metadata
                    TRY_CAST(
                        JSON_EXTRACT_STRING(metadata, '$.storage_used_gb') AS DOUBLE
                    ) AS storage_gb
                FROM m365_activity
                WHERE service = 'onedrive'
            ),
            mailbox_size AS (
                SELECT
                    user_principal_name,
                    TRY_CAST(
                        JSON_EXTRACT_STRING(metadata, '$.mailbox_gb') AS DOUBLE
                    ) AS mailbox_gb
                FROM m365_activity
                WHERE service = 'exchange'
            ),
            sp_ownership AS (
                SELECT
                    user_principal_name,
                    TRY_CAST(
                        JSON_EXTRACT_STRING(metadata, '$.owned_site_count') AS INTEGER
                    ) AS owned_sites
                FROM m365_activity
                WHERE service = 'sharepoint'
            )
            SELECT
                e3.user_id,
                e3.user_principal_name,
                e3.display_name,
                e3.department,
                e3.job_title,
                COALESCE(ac.activated_on_any_device, FALSE) AS has_desktop_activation,
                COALESCE(os.storage_gb, 0) AS onedrive_gb,
                COALESCE(mb.mailbox_gb, 0) AS mailbox_gb,
                COALESCE(sp.owned_sites, 0) AS sp_sites_owned
            FROM e3_users e3
            LEFT JOIN activation_check ac ON ac.user_principal_name = e3.user_principal_name
            LEFT JOIN onedrive_storage os ON os.user_principal_name = e3.user_principal_name
            LEFT JOIN mailbox_size mb ON mb.user_principal_name = e3.user_principal_name
            LEFT JOIN sp_ownership sp ON sp.user_principal_name = e3.user_principal_name
        """
        rows = conn.execute(query, [e3_sku_id]).fetchall()

        monthly_savings = DOWNGRADE_SAVINGS_MONTHLY.get(
            (E3_SKU_PART, F3_SKU_PART), 28.00
        )
        annual_savings_per_user = monthly_savings * 12

        findings: list[Finding] = []

        for row in rows:
            (user_id, upn, display_name, dept, title,
             has_desktop, onedrive_gb, mailbox_gb, sp_sites) = row

            # Rule out any disqualifier
            if has_desktop:
                continue
            if onedrive_gb > ONEDRIVE_F3_GB_LIMIT:
                continue
            if mailbox_gb > MAILBOX_F3_GB_LIMIT:
                continue
            if sp_sites > 0:
                continue

            # Optional strengthening signal: job title matches frontline pattern
            title_l = (title or "").lower()
            is_likely_frontline = any(
                kw in title_l for kw in
                ["retail", "associate", "cashier", "warehouse", "field tech",
                 "nurse", "driver", "technician", "clerk", "floor", "stock"]
            )
            confidence = "High" if is_likely_frontline else "Medium"

            findings.append(
                self.make_finding(
                    entity_id=user_id,
                    entity_name=upn,
                    entity_type="user",
                    current_state=f"M365 E3 ({M365_SKU_MONTHLY.get(E3_SKU_PART, 36):.0f}/month)",
                    recommended_state=f"M365 F3 ({M365_SKU_MONTHLY.get(F3_SKU_PART, 8):.0f}/month)",
                    gross_annual_savings_usd=annual_savings_per_user,
                    capturable_factor=0.65,
                    confidence=confidence,
                    days_to_capture=21,
                    risk_level="Medium",
                    suggested_owner="BU Liaison / HR",
                    dependencies=[
                        "BU liaison confirms user does not need desktop Office",
                        "Not a supervisor role (supervisors typically need E3)",
                        "User's device pattern matches shared/mobile frontline",
                    ],
                    evidence={
                        "has_desktop_activation": has_desktop,
                        "onedrive_gb": round(onedrive_gb, 2),
                        "mailbox_gb": round(mailbox_gb, 2),
                        "sharepoint_sites_owned": sp_sites,
                        "job_title": title,
                        "department": dept,
                        "frontline_title_match": is_likely_frontline,
                    },
                )
            )

        return findings
