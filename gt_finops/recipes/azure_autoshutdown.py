"""Recipe 6.2 — Non-prod auto-shutdown for dev/test VMs."""

from __future__ import annotations

import json
import re
import duckdb

from gt_finops.pricing import NONPROD_NAME_PATTERNS
from gt_finops.recipes.base import Finding, Recipe


# Business-hours-only savings factor (idle 24/7 vs runs 10h × 5d = ~30% of week)
BUSINESS_HOURS_SAVINGS_FACTOR = 0.65

# CPU threshold below which VM is considered idle in a given hour
IDLE_CPU_THRESHOLD = 5.0


class NonProdAutoShutdown(Recipe):

    id = "6.2"
    name = "Non-prod auto-shutdown"
    category = "Waste"
    sources = ["azure_resources", "azure_vm_utilization", "azure_cost_focus"]

    def run(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:

        patterns = [re.compile(p, re.IGNORECASE) for p in NONPROD_NAME_PATTERNS]

        # Get all VMs with their subscription/resource-group names
        vms = conn.execute(
            """
            SELECT
                resource_id, resource_name, subscription_id, subscription_name,
                resource_group, location, properties, tags
            FROM azure_resources
            WHERE resource_type ILIKE 'microsoft.compute/virtualmachines'
            """
        ).fetchall()

        findings: list[Finding] = []

        for (resource_id, name, sub_id, sub_name, rg, loc,
             props_json, tags_json) in vms:

            # Determine if VM is non-prod based on name/tags/subscription
            is_nonprod = self._is_nonprod(
                vm_name=name, resource_group=rg,
                subscription_name=sub_name, tags_json=tags_json,
                patterns=patterns,
            )
            if not is_nonprod:
                continue

            # Analyze utilization pattern — off-hours idleness
            util_row = conn.execute(
                """
                WITH hourly AS (
                    SELECT
                        HOUR(time_bucket) AS hour_of_day,
                        DAYOFWEEK(time_bucket) AS day_of_week,
                        AVG(cpu_avg_pct) AS avg_cpu
                    FROM azure_vm_utilization
                    WHERE resource_id = ?
                    GROUP BY hour_of_day, day_of_week
                )
                SELECT
                    AVG(CASE WHEN (hour_of_day < 7 OR hour_of_day >= 19)
                             OR day_of_week IN (0, 6)
                             THEN avg_cpu END) AS off_hours_avg_cpu,
                    AVG(CASE WHEN (hour_of_day >= 7 AND hour_of_day < 19)
                             AND day_of_week NOT IN (0, 6)
                             THEN avg_cpu END) AS business_hours_avg_cpu,
                    COUNT(*) AS hour_buckets
                FROM hourly
                """,
                [resource_id],
            ).fetchone()

            if util_row is None or util_row[2] is None or util_row[2] < 24:
                continue  # insufficient util data

            off_hours_cpu = float(util_row[0] or 0)
            business_hours_cpu = float(util_row[1] or 0)

            # Strong signal: off-hours CPU consistently below idle threshold
            # AND business-hours CPU shows some activity (so this VM is used)
            if off_hours_cpu >= IDLE_CPU_THRESHOLD:
                continue
            if business_hours_cpu < 1.0:
                # Totally idle VM - that's a different finding (rightsize/deallocate),
                # not auto-shutdown; skip here
                continue

            # Get monthly cost from FOCUS data
            cost_row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(billed_cost), 0),
                    COUNT(DISTINCT DATE_TRUNC('day', charge_period_start)) AS days
                FROM azure_cost_focus
                WHERE resource_id = ?
                  AND charge_period_start >= CURRENT_DATE - INTERVAL 30 DAY
                """,
                [resource_id],
            ).fetchone()

            total_cost, days = float(cost_row[0]), int(cost_row[1])
            if days == 0 or total_cost <= 0:
                continue
            monthly_cost = (total_cost / days) * 30

            monthly_savings = monthly_cost * BUSINESS_HOURS_SAVINGS_FACTOR
            annual_savings = round(monthly_savings * 12, 2)

            findings.append(
                self.make_finding(
                    entity_id=resource_id,
                    entity_name=name or resource_id.split("/")[-1],
                    entity_type="nonprod_vm",
                    current_state=(
                        f"Non-prod VM running 24/7, off-hours avg CPU {off_hours_cpu:.1f}%, "
                        f"${monthly_cost:.0f}/mo"
                    ),
                    recommended_state="Apply business-hours-only auto-shutdown schedule",
                    gross_annual_savings_usd=annual_savings,
                    capturable_factor=0.75,
                    confidence="High",
                    days_to_capture=10,
                    risk_level="Low",
                    suggested_owner="IT — Azure Admin",
                    dependencies=[
                        "Verify VM not domain-joined with critical heartbeat requirements",
                        "Check for scheduled nightly jobs (builds, ETL)",
                        "Coordinate with developer workstation users",
                    ],
                    evidence={
                        "subscription_name": sub_name,
                        "resource_group": rg,
                        "location": loc,
                        "off_hours_avg_cpu": round(off_hours_cpu, 2),
                        "business_hours_avg_cpu": round(business_hours_cpu, 2),
                        "monthly_cost": round(monthly_cost, 2),
                    },
                )
            )

        return findings

    @staticmethod
    def _is_nonprod(vm_name, resource_group, subscription_name,
                    tags_json, patterns) -> bool:
        # Check tags first - explicit is best
        try:
            tags = json.loads(tags_json) if tags_json else {}
            if isinstance(tags, dict):
                for k, v in tags.items():
                    if k.lower() in ("environment", "env"):
                        env = str(v).lower()
                        if env in ("dev", "test", "qa", "staging", "nonprod", "sandbox"):
                            return True
                        if env in ("prod", "production"):
                            return False
        except (json.JSONDecodeError, TypeError):
            pass

        # Fall back to name pattern matching
        checks = [vm_name or "", resource_group or "", subscription_name or ""]
        for text in checks:
            for p in patterns:
                if p.search(text):
                    return True
        return False
