"""Recipe 6.1 — Orphan resources (unattached disks, NICs, public IPs, empty ASPs, old snapshots)."""

from __future__ import annotations

import json
from datetime import date, timedelta
import duckdb

from gt_finops.recipes.base import Finding, Recipe


MIN_AGE_DAYS = 7


class OrphanResources(Recipe):

    id = "6.1"
    name = "Orphan resources"
    category = "Waste"
    sources = ["azure_resources", "azure_cost_focus"]

    def run(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._unattached_disks(conn))
        findings.extend(self._unused_nics(conn))
        findings.extend(self._unassociated_public_ips(conn))
        findings.extend(self._empty_app_service_plans(conn))
        findings.extend(self._old_snapshots(conn))
        return findings

    def _unattached_disks(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:
        rows = conn.execute(
            """
            SELECT resource_id, resource_name, subscription_id, resource_group,
                   location, sku_name, properties, tags
            FROM azure_resources
            WHERE resource_type ILIKE 'microsoft.compute/disks'
            """
        ).fetchall()

        findings: list[Finding] = []
        for resource_id, name, sub_id, rg, loc, sku, props_json, tags_json in rows:
            try:
                props = json.loads(props_json) if props_json else {}
                tags = json.loads(tags_json) if tags_json else {}
            except (json.JSONDecodeError, TypeError):
                continue

            disk_state = (props.get("diskState") or "").lower()
            if disk_state != "unattached":
                continue
            if self._is_protected_by_tag(tags):
                continue

            size_gb = props.get("diskSizeGB") or 0
            monthly_cost = self._recent_monthly_cost(conn, resource_id)
            if monthly_cost == 0:
                monthly_cost = self._estimate_disk_cost(sku, size_gb)
            if monthly_cost <= 0:
                continue

            is_premium = "premium" in (sku or "").lower()
            annual_savings = round(monthly_cost * 12, 2)

            findings.append(
                self.make_finding(
                    entity_id=resource_id,
                    entity_name=name or resource_id.split("/")[-1],
                    entity_type="disk",
                    current_state=f"Unattached {sku} disk, {size_gb} GB (${monthly_cost:.2f}/mo)",
                    recommended_state="Snapshot then delete",
                    gross_annual_savings_usd=annual_savings,
                    capturable_factor=0.95,
                    confidence="High",
                    days_to_capture=5,
                    risk_level="Low",
                    suggested_owner="IT — Azure Admin",
                    dependencies=[
                        "Snapshot disk before delete (recovery path)",
                        "Verify no retention tag or compliance hold",
                    ],
                    evidence={
                        "subscription_id": sub_id,
                        "resource_group": rg,
                        "location": loc,
                        "sku": sku,
                        "size_gb": size_gb,
                        "is_premium": is_premium,
                        "monthly_cost": round(monthly_cost, 2),
                    },
                )
            )
        return findings

    def _unused_nics(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:
        rows = conn.execute(
            """
            SELECT resource_id, resource_name, subscription_id, resource_group,
                   location, properties, tags, created_time
            FROM azure_resources
            WHERE resource_type ILIKE 'microsoft.network/networkinterfaces'
            """
        ).fetchall()

        findings: list[Finding] = []
        cutoff = date.today() - timedelta(days=MIN_AGE_DAYS)

        for resource_id, name, sub_id, rg, loc, props_json, tags_json, created in rows:
            try:
                props = json.loads(props_json) if props_json else {}
                tags = json.loads(tags_json) if tags_json else {}
            except (json.JSONDecodeError, TypeError):
                continue

            vm_ref = props.get("virtualMachine")
            if vm_ref and vm_ref.get("id"):
                continue
            if self._is_protected_by_tag(tags):
                continue

            if created:
                created_date = created.date() if hasattr(created, "date") else created
                if created_date > cutoff:
                    continue

            # NICs are free but create hygiene noise — include with $0 savings
            findings.append(
                self.make_finding(
                    entity_id=resource_id,
                    entity_name=name or resource_id.split("/")[-1],
                    entity_type="network_interface",
                    current_state="NIC not attached to any VM",
                    recommended_state="Delete",
                    gross_annual_savings_usd=0.0,
                    capturable_factor=1.0,
                    confidence="High",
                    days_to_capture=3,
                    risk_level="Low",
                    suggested_owner="IT — Network Admin",
                    dependencies=["Verify no pending VM deployment intends to use this NIC"],
                    evidence={
                        "subscription_id": sub_id,
                        "resource_group": rg,
                        "location": loc,
                        "created_time": str(created) if created else None,
                    },
                )
            )
        return findings

    def _unassociated_public_ips(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:
        rows = conn.execute(
            """
            SELECT resource_id, resource_name, subscription_id, resource_group,
                   location, sku_name, properties, tags
            FROM azure_resources
            WHERE resource_type ILIKE 'microsoft.network/publicipaddresses'
            """
        ).fetchall()

        findings: list[Finding] = []
        for resource_id, name, sub_id, rg, loc, sku, props_json, tags_json in rows:
            try:
                props = json.loads(props_json) if props_json else {}
                tags = json.loads(tags_json) if tags_json else {}
            except (json.JSONDecodeError, TypeError):
                continue

            ip_config = props.get("ipConfiguration")
            allocation = (props.get("publicIPAllocationMethod") or "").lower()

            if ip_config is not None:
                continue
            if allocation != "static":
                continue  # dynamic IPs are free when unassigned
            if self._is_protected_by_tag(tags):
                continue

            monthly_cost = self._recent_monthly_cost(conn, resource_id)
            if monthly_cost == 0:
                monthly_cost = 3.65  # default for Standard Static IPv4

            annual_savings = round(monthly_cost * 12, 2)

            findings.append(
                self.make_finding(
                    entity_id=resource_id,
                    entity_name=name or resource_id.split("/")[-1],
                    entity_type="public_ip",
                    current_state=f"Static public IP not associated (${monthly_cost:.2f}/mo)",
                    recommended_state="Delete",
                    gross_annual_savings_usd=annual_savings,
                    capturable_factor=0.95,
                    confidence="High",
                    days_to_capture=3,
                    risk_level="Low",
                    suggested_owner="IT — Network Admin",
                    dependencies=[
                        "Verify no downstream allow-list depends on this IP",
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

    def _empty_app_service_plans(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:
        rows = conn.execute(
            """
            SELECT resource_id, resource_name, subscription_id, resource_group,
                   location, sku_name, properties, tags
            FROM azure_resources
            WHERE resource_type ILIKE 'microsoft.web/serverfarms'
            """
        ).fetchall()

        findings: list[Finding] = []
        for resource_id, name, sub_id, rg, loc, sku, props_json, tags_json in rows:
            try:
                props = json.loads(props_json) if props_json else {}
                tags = json.loads(tags_json) if tags_json else {}
            except (json.JSONDecodeError, TypeError):
                continue

            site_count = props.get("numberOfSites", 0) or 0
            if site_count > 0:
                continue
            if self._is_protected_by_tag(tags):
                continue

            monthly_cost = self._recent_monthly_cost(conn, resource_id)
            if monthly_cost <= 0:
                continue  # Free tier — nothing to save

            annual_savings = round(monthly_cost * 12, 2)

            findings.append(
                self.make_finding(
                    entity_id=resource_id,
                    entity_name=name or resource_id.split("/")[-1],
                    entity_type="app_service_plan",
                    current_state=f"App Service Plan with 0 apps, {sku} tier (${monthly_cost:.2f}/mo)",
                    recommended_state="Delete or downgrade to Free tier",
                    gross_annual_savings_usd=annual_savings,
                    capturable_factor=0.90,
                    confidence="High",
                    days_to_capture=3,
                    risk_level="Low",
                    suggested_owner="IT — Azure Admin",
                    dependencies=[
                        "Confirm no pending deployment intends to use this plan",
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

    def _old_snapshots(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:
        from datetime import datetime
        cutoff = date.today() - timedelta(days=90)
        rows = conn.execute(
            """
            SELECT resource_id, resource_name, subscription_id, resource_group,
                   location, properties, tags, created_time
            FROM azure_resources
            WHERE resource_type ILIKE 'microsoft.compute/snapshots'
            """
        ).fetchall()

        findings: list[Finding] = []
        for resource_id, name, sub_id, rg, loc, props_json, tags_json, created in rows:
            try:
                props = json.loads(props_json) if props_json else {}
                tags = json.loads(tags_json) if tags_json else {}
            except (json.JSONDecodeError, TypeError):
                continue

            created_str = props.get("timeCreated")
            if created_str:
                try:
                    created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass

            if not created:
                continue
            created_date = created.date() if hasattr(created, "date") else created
            if created_date > cutoff:
                continue

            if self._is_protected_by_tag(tags):
                continue

            monthly_cost = self._recent_monthly_cost(conn, resource_id)
            if monthly_cost == 0:
                size_gb = props.get("diskSizeGB") or 0
                monthly_cost = size_gb * 0.05  # typical snapshot rate per GB
            if monthly_cost <= 0:
                continue

            age_days = (date.today() - created_date).days
            annual_savings = round(monthly_cost * 12, 2)

            findings.append(
                self.make_finding(
                    entity_id=resource_id,
                    entity_name=name or resource_id.split("/")[-1],
                    entity_type="snapshot",
                    current_state=f"Snapshot {age_days} days old (${monthly_cost:.2f}/mo)",
                    recommended_state="Delete (or move to Archive tier)",
                    gross_annual_savings_usd=annual_savings,
                    capturable_factor=0.80,
                    confidence="Medium",
                    days_to_capture=7,
                    risk_level="Medium",
                    suggested_owner="IT — Backup Admin",
                    dependencies=[
                        "Confirm snapshot is not a protected recovery point",
                        "Verify no compliance retention requires this snapshot",
                    ],
                    evidence={
                        "subscription_id": sub_id,
                        "age_days": age_days,
                        "created_time": str(created),
                        "monthly_cost": round(monthly_cost, 2),
                    },
                )
            )
        return findings

    @staticmethod
    def _is_protected_by_tag(tags: dict) -> bool:
        protected_keys = {"retain", "backup", "do-not-delete", "donotdelete",
                          "legalhold", "compliance-hold"}
        for key, value in tags.items():
            if key.lower() in protected_keys:
                return True
            if key.lower() in {"retention", "hold"} and str(value).lower() in {"yes", "true", "1"}:
                return True
        return False

    @staticmethod
    def _estimate_disk_cost(sku: str | None, size_gb: int) -> float:
        if not sku or size_gb <= 0:
            return 0.0
        sku_l = sku.lower()
        if "premium" in sku_l:
            return size_gb * 0.15
        if "standardssd" in sku_l or "standard_ssd" in sku_l:
            return size_gb * 0.075
        return size_gb * 0.04

    def _recent_monthly_cost(
        self, conn: duckdb.DuckDBPyConnection, resource_id: str,
    ) -> float:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(billed_cost), 0), 
                   COUNT(DISTINCT DATE_TRUNC('day', charge_period_start))
            FROM azure_cost_focus
            WHERE resource_id = ?
              AND charge_period_start >= CURRENT_DATE - INTERVAL 30 DAY
            """,
            [resource_id],
        ).fetchone()
        if row is None or row[1] == 0:
            return 0.0
        total_cost, days = float(row[0]), int(row[1])
        return (total_cost / days) * 30 if days > 0 else 0.0
