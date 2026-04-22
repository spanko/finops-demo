"""Recipe 4.2 — Sentinel commitment tier optimization."""

from __future__ import annotations

import duckdb

from gt_finops.pricing import (
    SENTINEL_COMMITMENT_TIERS,
    SENTINEL_PAYG_USD_PER_GB,
    find_sentinel_tier_for_volume,
)
from gt_finops.recipes.base import Finding, Recipe


# Thresholds for recommending tier changes
OVER_COMMITTED_RATIO = 0.80   # avg <= 80% of tier threshold = over-committed
UNDER_COMMITTED_RATIO = 1.50  # avg >= 150% of next tier threshold = under-committed


class SentinelTierOptimization(Recipe):

    id = "4.2"
    name = "Sentinel commitment tier optimization"
    category = "Security"
    sources = ["sentinel_usage", "sentinel_commitment"]

    def run(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:

        # Per-workspace: average daily ingestion over window vs. committed tier
        rows = conn.execute(
            """
            WITH daily_totals AS (
                SELECT
                    workspace_id,
                    usage_date,
                    SUM(gb_ingested) AS daily_gb
                FROM sentinel_usage
                WHERE COALESCE(is_billable, TRUE) = TRUE
                GROUP BY workspace_id, usage_date
            ),
            workspace_stats AS (
                SELECT
                    workspace_id,
                    AVG(daily_gb) AS avg_daily_gb,
                    quantile_cont(daily_gb, 0.50) AS p50_gb,
                    quantile_cont(daily_gb, 0.95) AS p95_gb,
                    COUNT(DISTINCT usage_date) AS days_observed
                FROM daily_totals
                GROUP BY workspace_id
            )
            SELECT
                c.workspace_id,
                c.workspace_name,
                c.pricing_tier,
                c.capacity_reservation_level,
                s.avg_daily_gb,
                s.p50_gb,
                s.p95_gb,
                s.days_observed
            FROM sentinel_commitment c
            LEFT JOIN workspace_stats s
                ON s.workspace_id = c.workspace_id
            """
        ).fetchall()

        findings: list[Finding] = []

        for row in rows:
            (workspace_id, workspace_name, current_tier, current_cap,
             avg_daily_gb, p50_gb, p95_gb, days_observed) = row

            if avg_daily_gb is None or days_observed is None or days_observed < 30:
                continue  # insufficient data

            avg_daily_gb = float(avg_daily_gb)
            current_cap = int(current_cap) if current_cap else None

            finding = self._evaluate_workspace(
                workspace_id=workspace_id,
                workspace_name=workspace_name or workspace_id[:8],
                current_tier=current_tier,
                current_cap_gb=current_cap,
                avg_daily_gb=avg_daily_gb,
                p50_gb=float(p50_gb or 0),
                p95_gb=float(p95_gb or 0),
                days_observed=days_observed,
            )
            if finding is not None:
                findings.append(finding)

        return findings

    def _evaluate_workspace(
        self, workspace_id: str, workspace_name: str,
        current_tier: str, current_cap_gb: int | None,
        avg_daily_gb: float, p50_gb: float, p95_gb: float, days_observed: int,
    ) -> Finding | None:

        # Case 1: on PerGB (PAYG) — consider moving to commitment tier
        if current_tier == "PerGB2018":
            best_tier = find_sentinel_tier_for_volume(avg_daily_gb)
            if best_tier is None:
                return None  # volume too low for commitment

            current_monthly_cost = avg_daily_gb * 30 * SENTINEL_PAYG_USD_PER_GB
            new_monthly_cost = best_tier["monthly_total_usd"]
            # PAYG covers overflow; if avg_daily_gb > tier threshold, add overflow cost
            overflow_gb = max(0, avg_daily_gb - best_tier["gb_per_day"])
            overflow_monthly = overflow_gb * 30 * SENTINEL_PAYG_USD_PER_GB

            total_new_cost = new_monthly_cost + overflow_monthly
            monthly_savings = current_monthly_cost - total_new_cost

            if monthly_savings <= 0:
                return None  # no savings

            return self.make_finding(
                entity_id=workspace_id,
                entity_name=workspace_name,
                entity_type="log_analytics_workspace",
                current_state=f"PerGB (PAYG) at {avg_daily_gb:.0f} GB/day avg",
                recommended_state=f"Commitment tier {best_tier['gb_per_day']} GB/day",
                gross_annual_savings_usd=round(monthly_savings * 12, 2),
                capturable_factor=0.95,
                confidence="High",
                days_to_capture=35,  # 31-day lock-in rule
                risk_level="Low",
                suggested_owner="Security Operations / FinOps",
                dependencies=[
                    "Workspace tier change has 31-day minimum hold",
                    "Verify ingestion volatility won't spike above tier cap regularly",
                ],
                evidence={
                    "avg_daily_gb": round(avg_daily_gb, 2),
                    "p50_gb": round(p50_gb, 2),
                    "p95_gb": round(p95_gb, 2),
                    "days_observed": days_observed,
                    "current_monthly_cost": round(current_monthly_cost, 2),
                    "new_monthly_cost": round(total_new_cost, 2),
                },
            )

        # Case 2: on commitment tier — check if over- or under-committed
        if current_cap_gb is None:
            return None

        ratio = avg_daily_gb / current_cap_gb if current_cap_gb > 0 else 0

        # Over-committed: drop a tier
        if ratio <= OVER_COMMITTED_RATIO:
            # Find a smaller tier that still fits avg
            smaller_tiers = [
                t for t in SENTINEL_COMMITMENT_TIERS
                if t["gb_per_day"] < current_cap_gb and t["gb_per_day"] >= avg_daily_gb
            ]
            if not smaller_tiers:
                return None

            target_tier = smaller_tiers[-1]  # largest that still fits
            current_tier_info = next(
                (t for t in SENTINEL_COMMITMENT_TIERS
                 if t["gb_per_day"] == current_cap_gb), None,
            )
            if current_tier_info is None:
                return None

            monthly_savings = current_tier_info["monthly_total_usd"] - target_tier["monthly_total_usd"]

            return self.make_finding(
                entity_id=workspace_id,
                entity_name=workspace_name,
                entity_type="log_analytics_workspace",
                current_state=f"Committed at {current_cap_gb} GB/day, using {avg_daily_gb:.0f} GB/day avg",
                recommended_state=f"Downgrade commitment to {target_tier['gb_per_day']} GB/day",
                gross_annual_savings_usd=round(monthly_savings * 12, 2),
                capturable_factor=0.90,
                confidence="High",
                days_to_capture=35,
                risk_level="Low",
                suggested_owner="Security Operations / FinOps",
                dependencies=[
                    "Workspace tier change has 31-day minimum hold",
                    "Factor in typical spikes; p95 below new tier threshold recommended",
                ],
                evidence={
                    "avg_daily_gb": round(avg_daily_gb, 2),
                    "p95_gb": round(p95_gb, 2),
                    "current_cap_gb": current_cap_gb,
                    "target_cap_gb": target_tier["gb_per_day"],
                    "current_monthly_cost": current_tier_info["monthly_total_usd"],
                    "new_monthly_cost": target_tier["monthly_total_usd"],
                },
            )

        # Under-committed: move up a tier for better per-GB rate
        if ratio >= UNDER_COMMITTED_RATIO:
            larger_tiers = [
                t for t in SENTINEL_COMMITMENT_TIERS
                if t["gb_per_day"] > current_cap_gb and t["gb_per_day"] <= avg_daily_gb
            ]
            if not larger_tiers:
                return None
            target_tier = larger_tiers[-1]
            current_tier_info = next(
                (t for t in SENTINEL_COMMITMENT_TIERS
                 if t["gb_per_day"] == current_cap_gb), None,
            )
            if current_tier_info is None:
                return None

            # Current cost = commitment + PAYG overflow
            overflow = max(0, avg_daily_gb - current_cap_gb)
            current_monthly = (current_tier_info["monthly_total_usd"]
                               + overflow * 30 * SENTINEL_PAYG_USD_PER_GB)
            new_overflow = max(0, avg_daily_gb - target_tier["gb_per_day"])
            new_monthly = (target_tier["monthly_total_usd"]
                           + new_overflow * 30 * SENTINEL_PAYG_USD_PER_GB)
            monthly_savings = current_monthly - new_monthly
            if monthly_savings <= 0:
                return None

            return self.make_finding(
                entity_id=workspace_id,
                entity_name=workspace_name,
                entity_type="log_analytics_workspace",
                current_state=f"Committed at {current_cap_gb} GB/day, using {avg_daily_gb:.0f} GB/day — paying PAYG overflow",
                recommended_state=f"Upgrade commitment to {target_tier['gb_per_day']} GB/day for lower per-GB rate",
                gross_annual_savings_usd=round(monthly_savings * 12, 2),
                capturable_factor=0.90,
                confidence="High",
                days_to_capture=35,
                risk_level="Low",
                suggested_owner="Security Operations / FinOps",
                dependencies=["Workspace tier change has 31-day minimum hold"],
                evidence={
                    "avg_daily_gb": round(avg_daily_gb, 2),
                    "current_cap_gb": current_cap_gb,
                    "target_cap_gb": target_tier["gb_per_day"],
                    "current_monthly_cost": round(current_monthly, 2),
                    "new_monthly_cost": round(new_monthly, 2),
                },
            )

        return None
