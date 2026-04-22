"""Recipe 5.1 — Azure Hybrid Benefit audit."""

from __future__ import annotations

import json
import duckdb

from gt_finops.pricing import (
    AHB_DISCOUNT_PERCENT,
    SQL_LICENSE_PORTION_OF_VM_COST,
    WINDOWS_LICENSE_PORTION_OF_VM_COST,
)
from gt_finops.recipes.base import Finding, Recipe


class AHBAudit(Recipe):

    id = "5.1"
    name = "Azure Hybrid Benefit audit"
    category = "Commitments"
    sources = ["azure_resources", "azure_cost_focus"]

    def run(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:

        findings: list[Finding] = []
        findings.extend(self._audit_windows_vms(conn))
        findings.extend(self._audit_sql_vms(conn))
        findings.extend(self._audit_azure_sql(conn))
        return findings

    # -------------------------------------------------------------
    # Windows VMs not claiming AHB
    # -------------------------------------------------------------
    def _audit_windows_vms(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:
        vms = conn.execute(
            """
            SELECT
                r.resource_id,
                r.resource_name,
                r.subscription_id,
                r.resource_group,
                r.location,
                r.sku_name,
                r.properties,
                r.tags
            FROM azure_resources r
            WHERE r.resource_type ILIKE 'microsoft.compute/virtualmachines'
            """
        ).fetchall()

        windows_candidates: list[tuple] = []
        for resource_id, name, sub_id, rg, loc, sku, props_json, tags in vms:
            try:
                props = json.loads(props_json) if props_json else {}
            except (json.JSONDecodeError, TypeError):
                continue

            os_type = (
                props.get("storageProfile", {}).get("osDisk", {}).get("osType", "")
                or ""
            ).lower()
            if os_type != "windows":
                continue

            license_type = (props.get("licenseType") or "").lower()
            # AHB applied if licenseType is 'windows_server' (Windows AHB)
            if license_type == "windows_server":
                continue  # already claiming

            windows_candidates.append(
                (resource_id, name, sub_id, rg, loc, sku)
            )

        # Cost lookup: last 30 days of billed_cost per resource
        findings: list[Finding] = []
        for resource_id, name, sub_id, rg, loc, sku in windows_candidates:
            monthly_cost = self._recent_monthly_cost(conn, resource_id)
            if monthly_cost <= 0:
                continue

            # AHB savings ≈ (windows license portion) × (AHB discount)
            monthly_savings = (
                monthly_cost
                * WINDOWS_LICENSE_PORTION_OF_VM_COST
                * AHB_DISCOUNT_PERCENT["windows_vm"]
            )
            annual_savings = round(monthly_savings * 12, 2)

            findings.append(
                self.make_finding(
                    entity_id=resource_id,
                    entity_name=name or resource_id.split("/")[-1],
                    entity_type="vm_windows",
                    current_state=f"Windows VM, no AHB applied (${monthly_cost:.2f}/mo)",
                    recommended_state="Apply Windows Server AHB (licenseType=Windows_Server)",
                    gross_annual_savings_usd=annual_savings,
                    capturable_factor=0.90,
                    confidence="Medium",  # contingent on SA entitlement
                    days_to_capture=14,
                    risk_level="Low",
                    suggested_owner="IT — Azure Admin / Licensing",
                    dependencies=[
                        "Verify Windows Server SA entitlement has sufficient cores",
                        "Apply via portal or Set-AzVM -LicenseType Windows_Server",
                    ],
                    evidence={
                        "subscription_id": sub_id,
                        "resource_group": rg,
                        "location": loc,
                        "sku": sku,
                        "monthly_cost": round(monthly_cost, 2),
                    },
                )
            )

        return findings

    # -------------------------------------------------------------
    # SQL IaaS VMs not claiming AHB
    # -------------------------------------------------------------
    def _audit_sql_vms(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:
        sql_vms = conn.execute(
            """
            SELECT
                resource_id, resource_name, subscription_id, resource_group,
                location, properties
            FROM azure_resources
            WHERE resource_type ILIKE 'microsoft.sqlvirtualmachine/sqlvirtualmachines'
            """
        ).fetchall()

        findings: list[Finding] = []
        for resource_id, name, sub_id, rg, loc, props_json in sql_vms:
            try:
                props = json.loads(props_json) if props_json else {}
            except (json.JSONDecodeError, TypeError):
                continue
            sql_license = (props.get("sqlServerLicenseType") or "").upper()
            if sql_license == "AHUB":
                continue

            monthly_cost = self._recent_monthly_cost(conn, resource_id)
            if monthly_cost <= 0:
                continue

            monthly_savings = (
                monthly_cost
                * SQL_LICENSE_PORTION_OF_VM_COST
                * AHB_DISCOUNT_PERCENT["sql_vm"]
            )
            annual_savings = round(monthly_savings * 12, 2)

            findings.append(
                self.make_finding(
                    entity_id=resource_id,
                    entity_name=name or resource_id.split("/")[-1],
                    entity_type="vm_sql",
                    current_state=f"SQL IaaS VM, no AHB (${monthly_cost:.2f}/mo)",
                    recommended_state="Apply SQL Server AHB (sqlServerLicenseType=AHUB)",
                    gross_annual_savings_usd=annual_savings,
                    capturable_factor=0.85,
                    confidence="Medium",
                    days_to_capture=14,
                    risk_level="Low",
                    suggested_owner="IT — Azure Admin / Licensing",
                    dependencies=[
                        "Verify SQL Server SA entitlement has sufficient cores",
                    ],
                    evidence={
                        "subscription_id": sub_id,
                        "resource_group": rg,
                        "location": loc,
                        "monthly_cost": round(monthly_cost, 2),
                    },
                )
            )
        return findings

    # -------------------------------------------------------------
    # Azure SQL DB / Managed Instance not claiming AHB
    # -------------------------------------------------------------
    def _audit_azure_sql(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:
        sql = conn.execute(
            """
            SELECT
                resource_id, resource_name, subscription_id, resource_group,
                location, resource_type, properties
            FROM azure_resources
            WHERE resource_type ILIKE 'microsoft.sql/servers/databases'
               OR resource_type ILIKE 'microsoft.sql/managedinstances'
            """
        ).fetchall()

        findings: list[Finding] = []
        for resource_id, name, sub_id, rg, loc, rtype, props_json in sql:
            try:
                props = json.loads(props_json) if props_json else {}
            except (json.JSONDecodeError, TypeError):
                continue

            # licenseType=LicenseIncluded means NOT claiming AHB
            # licenseType=BasePrice means claiming AHB
            license_type = (props.get("licenseType") or "").lower()
            if license_type != "licenseincluded":
                continue

            monthly_cost = self._recent_monthly_cost(conn, resource_id)
            if monthly_cost <= 0:
                continue

            # Azure SQL AHB discount is on the license portion of the price
            monthly_savings = (
                monthly_cost * 0.30  # typical license portion for Azure SQL
                * AHB_DISCOUNT_PERCENT["sql_database"]
            )
            annual_savings = round(monthly_savings * 12, 2)

            entity_type = ("sql_mi" if "managedinstances" in rtype.lower()
                           else "sql_database")

            findings.append(
                self.make_finding(
                    entity_id=resource_id,
                    entity_name=name or resource_id.split("/")[-1],
                    entity_type=entity_type,
                    current_state=f"Azure SQL {entity_type} on LicenseIncluded (${monthly_cost:.2f}/mo)",
                    recommended_state="Switch licenseType to BasePrice (AHB)",
                    gross_annual_savings_usd=annual_savings,
                    capturable_factor=0.85,
                    confidence="Medium",
                    days_to_capture=14,
                    risk_level="Low",
                    suggested_owner="IT — Azure Admin / Licensing",
                    dependencies=[
                        "Verify SQL Server SA core entitlement",
                    ],
                    evidence={
                        "subscription_id": sub_id,
                        "resource_group": rg,
                        "monthly_cost": round(monthly_cost, 2),
                    },
                )
            )
        return findings

    # -------------------------------------------------------------
    # Utility: average monthly cost from recent FOCUS data
    # -------------------------------------------------------------
    def _recent_monthly_cost(
        self, conn: duckdb.DuckDBPyConnection, resource_id: str,
    ) -> float:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(billed_cost), 0) AS total_cost,
                   COUNT(DISTINCT DATE_TRUNC('day', charge_period_start)) AS days
            FROM azure_cost_focus
            WHERE resource_id = ?
              AND charge_period_start >= CURRENT_DATE - INTERVAL 30 DAY
            """,
            [resource_id],
        ).fetchone()
        if row is None or row[1] == 0:
            return 0.0
        # Scale to monthly
        total_cost, days = float(row[0]), int(row[1])
        return (total_cost / days) * 30 if days > 0 else 0.0
