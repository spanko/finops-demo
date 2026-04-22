"""Recipe 4.1 — Defender for Servers P2 → P1 downgrade."""

from __future__ import annotations

import duckdb

from gt_finops.pricing import DEFENDER_P2_TO_P1_SAVINGS_MONTHLY, DEFENDER_PRICING_MONTHLY
from gt_finops.recipes.base import Finding, Recipe


class DefenderP2ToP1(Recipe):

    id = "4.1"
    name = "Defender for Servers P2 → P1"
    category = "Security"
    sources = ["defender_pricing", "defender_jit_policies", "azure_resources"]

    def run(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:

        # Subscriptions on VirtualMachines plan = P2
        p2_subs = conn.execute(
            """
            SELECT subscription_id, pricing_tier, sub_plan, resource_count
            FROM defender_pricing
            WHERE plan_name = 'VirtualMachines'
              AND (pricing_tier = 'Standard' OR sub_plan = 'P2')
            """
        ).fetchall()

        findings: list[Finding] = []

        for subscription_id, pricing_tier, sub_plan, resource_count in p2_subs:
            # Only P2 (Standard tier without a P1 sub_plan override) qualifies
            # for this recipe. "Standard" tier = P2 unless sub_plan says P1.
            is_p2 = (sub_plan is None or sub_plan == "P2") and pricing_tier == "Standard"
            if not is_p2:
                continue

            # Check whether any P2-exclusive feature is in use.
            # Simplest signal: presence of JIT policies in the subscription.
            jit_count = conn.execute(
                """
                SELECT COUNT(*) FROM defender_jit_policies
                WHERE subscription_id = ?
                """,
                [subscription_id],
            ).fetchone()[0]

            if jit_count > 0:
                continue  # P2 in active use

            # Count VMs protected in this subscription to size the savings
            vm_count = conn.execute(
                """
                SELECT COUNT(*) FROM azure_resources
                WHERE subscription_id = ?
                  AND resource_type ILIKE 'microsoft.compute/virtualmachines'
                """,
                [subscription_id],
            ).fetchone()[0]

            # Fall back to the defender_pricing resource_count if inventory absent
            vms_protected = vm_count if vm_count > 0 else (resource_count or 0)
            if vms_protected == 0:
                continue

            annual_savings = vms_protected * DEFENDER_P2_TO_P1_SAVINGS_MONTHLY * 12

            findings.append(
                self.make_finding(
                    entity_id=subscription_id,
                    entity_name=f"Subscription {subscription_id[:8]}...",
                    entity_type="subscription",
                    current_state=f"Defender for Servers P2 — ${DEFENDER_PRICING_MONTHLY['VirtualMachines']['P2']:.2f}/VM/mo",
                    recommended_state=f"Defender for Servers P1 — ${DEFENDER_PRICING_MONTHLY['VirtualMachines']['P1']:.2f}/VM/mo",
                    gross_annual_savings_usd=annual_savings,
                    capturable_factor=0.70,
                    confidence="Medium",  # always Medium: security owner must sign off
                    days_to_capture=21,
                    risk_level="Medium",
                    suggested_owner="Security Operations",
                    dependencies=[
                        "Security team confirms JIT, FIM, and adaptive controls are not planned",
                        "Free 500 MB/day log ingestion not otherwise being relied on",
                        "Compliance framework does not mandate P2 features",
                    ],
                    evidence={
                        "subscription_id": subscription_id,
                        "vms_protected": vms_protected,
                        "jit_policies_found": jit_count,
                        "monthly_savings_per_vm": DEFENDER_P2_TO_P1_SAVINGS_MONTHLY,
                    },
                )
            )

        return findings
