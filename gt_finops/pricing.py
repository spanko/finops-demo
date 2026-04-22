"""
Pricing defaults for cost estimation.

These are public list prices as of the playbook publication date. Client EA
agreements usually carry meaningful discounts off list; the `sku_price_overrides`
table captures client-specific pricing when a price sheet is provided.

When a finding has access to override pricing, it should use the override.
Otherwise these defaults are used and the finding is marked with
confidence='Medium' to reflect pricing uncertainty.

Prices are monthly, USD, per-unit (per user for M365, per server for Defender,
per VM for Azure compute, etc.).

Update this file quarterly or when Microsoft announces price changes.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# M365 SKUs
# ---------------------------------------------------------------------------
# sku_part_number -> monthly per-user list price (USD)

M365_SKU_MONTHLY = {
    # Enterprise
    "ENTERPRISEPREMIUM":      57.00,  # Microsoft 365 E5
    "ENTERPRISEPACK":         36.00,  # Microsoft 365 E3
    "ENTERPRISEPACK_B_PILOT": 36.00,  # E3 variants
    "DESKLESSPACK":            8.00,  # Microsoft 365 F3 (frontline)
    "FRONTLINE":               8.00,  # F3 alias

    # Office 365 (distinct from Microsoft 365)
    "OFFICESUBSCRIPTION":     12.00,  # Office 365 E1
    "STANDARDPACK":           10.00,  # Office 365 E1 alt
    "STANDARDWOFFPACK":       23.00,  # Office 365 E3
    "ENTERPRISEPREMIUM_NOPSTNCONF": 38.00,  # Office 365 E5 w/o PSTN conf

    # Copilot
    "Microsoft_365_Copilot":  30.00,  # M365 Copilot per user per month

    # Teams Phone add-ons
    "MCOCAP":                 12.00,  # Microsoft Teams Phone Standard
    "MCOMEETADV":              4.00,  # Audio Conferencing add-on
    "MCOPSTNC":               12.00,  # Calling Plan - Domestic
    "MCOPSTN5":               24.00,  # Calling Plan - Domestic + International
    "MCOPSTNEAU":             12.00,  # Calling Plan variants by region
    "MCOPSTNEAU2":            24.00,

    # Power BI
    "POWER_BI_PRO":           14.00,
    "POWER_BI_PREMIUM_PER_USER": 24.00,
}

# Service plans that identify E5-exclusive features
# If a user is active in any of these, they should stay on E5
E5_EXCLUSIVE_SERVICES = {
    "THREAT_INTELLIGENCE",       # Defender for O365 P2
    "THREAT_INTELLIGENCE_P2",
    "ADV_COMMS_COMPLIANCE",      # Advanced Communications Compliance
    "BPOS_S_DlpAddOn",           # Data Loss Prevention advanced
    "MICROSOFTENDPOINTDLP",
    "MCOEV",                     # Phone System (Teams Phone Standard)
    "POWER_BI_PRO_CE",           # Power BI Pro (bundled in E5)
    "EQUIVIO_ANALYTICS",         # Advanced eDiscovery
    "LOCKBOX_ENTERPRISE",        # Customer Lockbox
    "INFORMATION_BARRIERS",
    "PREMIUM_ENCRYPTION",
    "MICROSOFT_ANALYTICS_INSIGHTS",  # MyAnalytics / Viva Insights
    "VIVA_INSIGHTS",
}

# Downgrade target prices for recipe 3.1 (E5 -> E3) and 3.2 (E3 -> F3)
DOWNGRADE_SAVINGS_MONTHLY = {
    ("ENTERPRISEPREMIUM", "ENTERPRISEPACK"):  22.00,   # E5 -> E3
    ("ENTERPRISEPACK",   "DESKLESSPACK"):     28.00,   # E3 -> F3
}


# ---------------------------------------------------------------------------
# Microsoft Security - Defender for Cloud plan pricing
# ---------------------------------------------------------------------------
# Per protected resource per month (USD)

DEFENDER_PRICING_MONTHLY = {
    "VirtualMachines": {
        "P1":  7.50,   # Defender for Servers P1
        "P2": 15.00,   # Defender for Servers P2
    },
    "SqlServers": {
        "Standard": 15.00,   # per SQL instance
    },
    "StorageAccounts": {
        "Standard": 10.00,   # per storage account
    },
    "AppServices": {
        "Standard": 15.00,   # per App Service Plan
    },
    "KeyVaults": {
        "Standard":  2.00,   # per 10K transactions
    },
    "Arm": {
        "Standard":  4.00,   # per subscription per month
    },
    "Dns": {
        "Standard":  0.70,   # per million queries
    },
    "Containers": {
        "Standard":  7.00,   # per vCore per month
    },
    "CloudPosture": {
        "Standard":  4.00,   # CSPM per billable resource
    },
    "Api": {
        "Standard":  2.50,   # per API
    },
    "CosmosDbs": {
        "Standard": 15.00,   # per 100 RU/s provisioned
    },
}

# Defender P2 -> P1 savings per VM/month
DEFENDER_P2_TO_P1_SAVINGS_MONTHLY = (
    DEFENDER_PRICING_MONTHLY["VirtualMachines"]["P2"]
    - DEFENDER_PRICING_MONTHLY["VirtualMachines"]["P1"]
)


# ---------------------------------------------------------------------------
# Sentinel / Log Analytics tier pricing
# ---------------------------------------------------------------------------
# Pay-as-you-go and commitment tier prices (USD per GB ingested)
# Sentinel pricing = Log Analytics + Sentinel surcharge; these are combined rates

SENTINEL_PAYG_USD_PER_GB = 4.30  # Combined LA + Sentinel PAYG rate

SENTINEL_COMMITMENT_TIERS = [
    # Each entry: (gb_per_day, usd_per_gb_effective, monthly_total_cost_usd)
    {"gb_per_day": 100,  "usd_per_gb": 3.70, "monthly_total_usd": 11_155},
    {"gb_per_day": 200,  "usd_per_gb": 3.50, "monthly_total_usd": 21_108},
    {"gb_per_day": 300,  "usd_per_gb": 3.38, "monthly_total_usd": 30_564},
    {"gb_per_day": 400,  "usd_per_gb": 3.30, "monthly_total_usd": 39_820},
    {"gb_per_day": 500,  "usd_per_gb": 3.25, "monthly_total_usd": 49_015},
    {"gb_per_day": 1000, "usd_per_gb": 3.05, "monthly_total_usd": 91_957},
    {"gb_per_day": 2000, "usd_per_gb": 2.90, "monthly_total_usd": 174_935},
    {"gb_per_day": 5000, "usd_per_gb": 2.80, "monthly_total_usd": 422_350},
]

# Basic Logs tier - roughly 90% cheaper for ingestion
SENTINEL_BASIC_LOGS_USD_PER_GB = 0.55


# ---------------------------------------------------------------------------
# Azure Hybrid Benefit discount rates
# ---------------------------------------------------------------------------
# AHB discount varies by SKU and workload; these are industry-average rates

AHB_DISCOUNT_PERCENT = {
    "windows_vm":       0.40,  # 40% off Windows license portion of VM cost
    "sql_vm":           0.55,  # 55% off SQL license portion of SQL IaaS VM
    "sql_database":     0.55,  # 55% off Azure SQL DB license-included portion
    "sql_managed_instance": 0.55,
}

# Rough Windows licensing portion of total VM cost by VM category
# Used to estimate AHB savings when detailed pricing is unavailable
WINDOWS_LICENSE_PORTION_OF_VM_COST = 0.35  # ~35% of Windows VM cost is licensing

# SQL licensing portion of total SQL IaaS VM cost
SQL_LICENSE_PORTION_OF_VM_COST = 0.60  # ~60% of SQL VM cost is SQL licensing


# ---------------------------------------------------------------------------
# Reserved Instance and Savings Plan discount rates
# ---------------------------------------------------------------------------

RI_DISCOUNT_PERCENT = {
    "P1Y": 0.30,  # ~30% off PAYG for 1-year RI
    "P3Y": 0.55,  # ~55% off PAYG for 3-year RI
}

SAVINGS_PLAN_DISCOUNT_PERCENT = {
    "P1Y": 0.13,  # ~13% off PAYG for 1-year CSP
    "P3Y": 0.28,  # ~28% off PAYG for 3-year CSP
}


# ---------------------------------------------------------------------------
# Dev/Test pricing discount
# ---------------------------------------------------------------------------

DEVTEST_DISCOUNT_PERCENT = 0.55  # ~55% off compute and SQL for eligible subs

# Subscription name patterns that indicate non-prod
NONPROD_NAME_PATTERNS = [
    r"\bdev\b",
    r"\btest\b",
    r"\bqa\b",
    r"\bstag(e|ing)\b",
    r"\bnonprod\b",
    r"\buat\b",
    r"\bsandbox\b",
    r"\bsbx\b",
]


# ---------------------------------------------------------------------------
# Storage tiering savings
# ---------------------------------------------------------------------------
# Hot -> Cool -> Archive relative savings

STORAGE_TIER_SAVINGS_PERCENT = {
    "hot_to_cool":     0.50,   # ~50% less than Hot
    "cool_to_archive": 0.80,   # ~80% less than Cool (94% less than Hot)
    "hot_to_archive":  0.94,
}


def get_sku_price(sku_part_number: str, overrides: dict[str, float] | None = None) -> float | None:
    """Return monthly USD price for a SKU; checks overrides first."""
    if overrides and sku_part_number in overrides:
        return overrides[sku_part_number]
    return M365_SKU_MONTHLY.get(sku_part_number)


def find_sentinel_tier_for_volume(avg_daily_gb: float) -> dict | None:
    """
    Return the best commitment tier for a given average daily ingestion.
    Rule: use the largest tier whose threshold <= avg daily ingestion.
    """
    eligible = [t for t in SENTINEL_COMMITMENT_TIERS if t["gb_per_day"] <= avg_daily_gb]
    return eligible[-1] if eligible else None
