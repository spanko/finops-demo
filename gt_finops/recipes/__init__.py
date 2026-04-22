"""
Recipe registry.

All recipes are registered here so the CLI and orchestrator can discover them
without hardcoding the list. Add new recipes by importing and appending to
ALL_RECIPES.
"""

from __future__ import annotations

from gt_finops.recipes.base import Recipe

# M365 Licensing
from gt_finops.recipes.m365_e5_to_e3 import E5ToE3Downgrade
from gt_finops.recipes.m365_e3_to_f3 import E3ToF3Downgrade
from gt_finops.recipes.m365_disabled import DisabledButLicensed
from gt_finops.recipes.m365_copilot_reclaim import CopilotReclaim
from gt_finops.recipes.m365_teams_phone import TeamsPhoneUnused

# Microsoft Security
from gt_finops.recipes.sec_defender_p2_p1 import DefenderP2ToP1
from gt_finops.recipes.sec_sentinel_tier import SentinelTierOptimization

# Azure Commitments
from gt_finops.recipes.azure_ahb_audit import AHBAudit
from gt_finops.recipes.azure_ri_utilization import ReservationUtilization
from gt_finops.recipes.azure_savings_plan import SavingsPlanCoverage
from gt_finops.recipes.azure_devtest_pricing import DevTestPricing

# Azure Waste
from gt_finops.recipes.azure_orphans import OrphanResources
from gt_finops.recipes.azure_autoshutdown import NonProdAutoShutdown
from gt_finops.recipes.azure_storage_tiering import StorageTiering


ALL_RECIPES: list[type[Recipe]] = [
    E5ToE3Downgrade,
    E3ToF3Downgrade,
    DisabledButLicensed,
    CopilotReclaim,
    TeamsPhoneUnused,
    DefenderP2ToP1,
    SentinelTierOptimization,
    AHBAudit,
    ReservationUtilization,
    SavingsPlanCoverage,
    DevTestPricing,
    OrphanResources,
    NonProdAutoShutdown,
    StorageTiering,
]


RECIPE_BY_ID: dict[str, type[Recipe]] = {r.id: r for r in ALL_RECIPES}


def get_recipe(recipe_id: str) -> type[Recipe]:
    """Look up a recipe class by ID. Raises KeyError if not found."""
    if recipe_id not in RECIPE_BY_ID:
        raise KeyError(f"Unknown recipe '{recipe_id}'. Available: {sorted(RECIPE_BY_ID)}")
    return RECIPE_BY_ID[recipe_id]
