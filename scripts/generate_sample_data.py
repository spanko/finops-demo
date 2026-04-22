"""
Generate realistic synthetic client data for end-to-end testing.

Creates a folder matching the EXPECTED_LAYOUT with data that will produce
non-trivial findings across all 14 recipes.

Design: fixed random seed so runs are reproducible. Deliberately includes
known patterns each recipe should detect — if the findings summary drops
below expected levels, something in the code has regressed.
"""

from __future__ import annotations

import csv
import json
import random
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path

rng = random.Random(42)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("sample_data")

# Well-known SKU GUIDs (stable across all tenants)
E5_SKU_ID    = str(uuid.UUID("c7df2760-2c81-4ef7-b578-5b5392b571df"))
E3_SKU_ID    = str(uuid.UUID("6fd2c87f-b296-42f0-b197-1e91e994b900"))
F3_SKU_ID    = str(uuid.UUID("66b55226-6b4f-492c-910c-a3b7a3c9d993"))
COPILOT_SKU  = str(uuid.UUID("639dec6b-bb19-468b-871c-c5c441c4b0cb"))
CALLPLAN_SKU = str(uuid.UUID("0dab259f-bf13-4952-b7f8-7db8f131b28d"))

SUBSCRIPTION_IDS = [
    "11111111-1111-1111-1111-111111111111",  # prod
    "22222222-2222-2222-2222-222222222222",  # dev
    "33333333-3333-3333-3333-333333333333",  # test
]

TODAY = date.today()


# ---------------------------------------------------------------------------
# M365
# ---------------------------------------------------------------------------

def write_subscribed_skus(target: Path):
    skus = [
        {"skuId": E5_SKU_ID,   "skuPartNumber": "ENTERPRISEPREMIUM",
         "prepaidUnits": {"enabled": 200, "suspended": 0, "warning": 0},
         "consumedUnits": 180},
        {"skuId": E3_SKU_ID,   "skuPartNumber": "ENTERPRISEPACK",
         "prepaidUnits": {"enabled": 300, "suspended": 0, "warning": 0},
         "consumedUnits": 260},
        {"skuId": F3_SKU_ID,   "skuPartNumber": "DESKLESSPACK",
         "prepaidUnits": {"enabled": 50, "suspended": 0, "warning": 0},
         "consumedUnits": 40},
        {"skuId": COPILOT_SKU, "skuPartNumber": "Microsoft_365_Copilot",
         "prepaidUnits": {"enabled": 100, "suspended": 0, "warning": 0},
         "consumedUnits": 80},
        {"skuId": CALLPLAN_SKU, "skuPartNumber": "MCOPSTNC",
         "prepaidUnits": {"enabled": 50, "suspended": 0, "warning": 0},
         "consumedUnits": 45},
    ]
    target.write_text(json.dumps({"value": skus}, indent=2))


def write_users(target: Path):
    """Generate 500 users with varied license/activity patterns."""
    users = []

    # Bucket 1: E5 users, 40 of which are E5-active (keep), 60 inactive (downgrade candidates)
    for i in range(100):
        is_active_e5 = i < 40
        users.append({
            "id": str(uuid.uuid4()),
            "userPrincipalName": f"e5-user{i:03d}@acme.example",
            "displayName": f"E5 User {i:03d}",
            "accountEnabled": True,
            "department": "Engineering" if i % 2 == 0 else "Sales",
            "jobTitle": "Senior Engineer" if i % 3 == 0 else "Account Executive",
            "assignedLicenses": [{"skuId": E5_SKU_ID}],
            "signInActivity": {
                "lastSignInDateTime": (datetime.utcnow() - timedelta(days=rng.randint(1, 10))).isoformat() + "Z",
            },
            "createdDateTime": (datetime.utcnow() - timedelta(days=rng.randint(100, 800))).isoformat() + "Z",
            "_is_active_e5": is_active_e5,   # carried for activity gen
        })

    # Bucket 2: E3 users - 80 frontline candidates, 120 legitimate E3
    for i in range(200):
        is_frontline = i < 80
        users.append({
            "id": str(uuid.uuid4()),
            "userPrincipalName": f"e3-user{i:03d}@acme.example",
            "displayName": f"E3 User {i:03d}",
            "accountEnabled": True,
            "department": "Retail Ops" if is_frontline else "Finance",
            "jobTitle": "Retail Associate" if is_frontline else "Analyst",
            "assignedLicenses": [{"skuId": E3_SKU_ID}],
            "signInActivity": {
                "lastSignInDateTime": (datetime.utcnow() - timedelta(days=rng.randint(1, 15))).isoformat() + "Z",
            },
            "createdDateTime": (datetime.utcnow() - timedelta(days=rng.randint(100, 800))).isoformat() + "Z",
            "_is_frontline": is_frontline,
        })

    # Bucket 3: 25 disabled users still holding licenses
    for i in range(25):
        users.append({
            "id": str(uuid.uuid4()),
            "userPrincipalName": f"disabled-user{i:03d}@acme.example",
            "displayName": f"Disabled User {i:03d}",
            "accountEnabled": False,
            "department": "Former",
            "jobTitle": "",
            "assignedLicenses": [{"skuId": rng.choice([E3_SKU_ID, E5_SKU_ID])}],
            "signInActivity": {
                "lastSignInDateTime": (datetime.utcnow() - timedelta(days=rng.randint(60, 300))).isoformat() + "Z",
            },
            "createdDateTime": (datetime.utcnow() - timedelta(days=rng.randint(500, 1500))).isoformat() + "Z",
        })

    # Bucket 4: 100 Copilot-licensed, 35 inactive
    for i in range(100):
        is_inactive_copilot = i < 35
        users.append({
            "id": str(uuid.uuid4()),
            "userPrincipalName": f"copilot-user{i:03d}@acme.example",
            "displayName": f"Copilot User {i:03d}",
            "accountEnabled": True,
            "department": "Marketing",
            "jobTitle": "Manager",
            "assignedLicenses": [
                {"skuId": E3_SKU_ID},
                {"skuId": COPILOT_SKU},
            ],
            "signInActivity": {
                "lastSignInDateTime": (datetime.utcnow() - timedelta(days=rng.randint(1, 20))).isoformat() + "Z",
            },
            "createdDateTime": (datetime.utcnow() - timedelta(days=rng.randint(60, 500))).isoformat() + "Z",
            "_copilot_inactive": is_inactive_copilot,
        })

    # Bucket 5: 50 Calling Plan assignees, 20 with no PSTN usage
    for i in range(50):
        zero_pstn = i < 20
        users.append({
            "id": str(uuid.uuid4()),
            "userPrincipalName": f"phone-user{i:03d}@acme.example",
            "displayName": f"Phone User {i:03d}",
            "accountEnabled": True,
            "department": "Support",
            "jobTitle": "Support Specialist",
            "assignedLicenses": [
                {"skuId": E3_SKU_ID},
                {"skuId": CALLPLAN_SKU},
            ],
            "signInActivity": {
                "lastSignInDateTime": (datetime.utcnow() - timedelta(days=rng.randint(1, 10))).isoformat() + "Z",
            },
            "createdDateTime": (datetime.utcnow() - timedelta(days=rng.randint(60, 500))).isoformat() + "Z",
            "_zero_pstn": zero_pstn,
        })

    target.write_text(json.dumps({"value": users}, indent=2))
    return users


def write_activity_reports(target_dir: Path, users: list[dict]):
    """Per-service activity CSVs. The ingester normalizes these into m365_activity."""

    # Use last-activity dates computed from user metadata
    def upn_for(u): return u["userPrincipalName"]
    def last_date_recent(days_ago_max=10):
        return (TODAY - timedelta(days=rng.randint(1, days_ago_max))).isoformat()
    def last_date_old():
        return (TODAY - timedelta(days=rng.randint(60, 150))).isoformat()

    # Office365 Active Users (exchange proxy)
    rows = []
    for u in users:
        has_active = u.get("accountEnabled", True)
        rows.append({
            "User Principal Name": upn_for(u),
            "Last Activity Date": last_date_recent() if has_active else last_date_old(),
            "Mailbox Storage Used (Byte)":
                (400 if u.get("_is_frontline") else 4000) * 1024 * 1024,
        })
    _write_csv(target_dir / "office365_active_users.csv", rows)

    # Teams
    rows = []
    for u in users:
        rows.append({
            "User Principal Name": upn_for(u),
            "Last Activity Date": last_date_recent(),
            "Team Chat Message Count": rng.randint(0, 200),
        })
    _write_csv(target_dir / "teams_user_activity.csv", rows)

    # SharePoint (owned site count metadata)
    rows = []
    for u in users:
        owned = 0 if u.get("_is_frontline") else rng.randint(0, 3)
        rows.append({
            "User Principal Name": upn_for(u),
            "Last Activity Date": last_date_recent() if not u.get("_is_frontline") else "",
            "Owned Site Count": owned,
        })
    _write_csv(target_dir / "sharepoint_site_usage.csv", rows)

    # OneDrive
    rows = []
    for u in users:
        # Frontline users have tiny OneDrive (<2GB), others larger
        storage_gb = 0.5 if u.get("_is_frontline") else rng.uniform(3, 15)
        rows.append({
            "Owner Principal Name": upn_for(u),
            "Last Activity Date": last_date_recent(),
            "Storage Used (Byte)": int(storage_gb * 1024**3),
        })
    _write_csv(target_dir / "onedrive_account_detail.csv", rows)

    # Power BI (only a few users actively use Power BI Pro)
    rows = []
    for u in users:
        sku_ids = [lic["skuId"] for lic in u.get("assignedLicenses", [])]
        is_active_e5 = u.get("_is_active_e5")
        # Only E5-active users use Power BI
        active_pbi = bool(is_active_e5 and E5_SKU_ID in sku_ids)
        rows.append({
            "User Principal Name": upn_for(u),
            "Last Activity Date": last_date_recent() if active_pbi else "",
            "Viewed or Edited Report Count": rng.randint(1, 50) if active_pbi else 0,
        })
    _write_csv(target_dir / "powerbi_activity.csv", rows)

    # Yammer (rarely used - emit some zeros)
    rows = []
    for u in users[:50]:
        rows.append({
            "User Principal Name": upn_for(u),
            "Last Activity Date": "",
            "Posted Count": 0,
        })
    _write_csv(target_dir / "yammer_activity.csv", rows)

    # Copilot
    rows = []
    for u in users:
        sku_ids = [lic["skuId"] for lic in u.get("assignedLicenses", [])]
        if COPILOT_SKU not in sku_ids:
            continue
        inactive = u.get("_copilot_inactive")
        rows.append({
            "User Principal Name": upn_for(u),
            "Last Activity Date": "" if inactive else last_date_recent(),
            "Copilot Chat Count": 0 if inactive else rng.randint(5, 100),
        })
    _write_csv(target_dir / "copilot_usage.csv", rows)


def write_office_activations(target: Path, users: list[dict]):
    """Frontline users have no desktop Office activations; others do."""
    rows = []
    for u in users:
        is_frontline = u.get("_is_frontline", False)
        rows.append({
            "User Principal Name": u["userPrincipalName"],
            "Activated On Any Device": "No" if is_frontline else "Yes",
            "Activation Count": 0 if is_frontline else rng.randint(1, 3),
            "Last Activation Date": "" if is_frontline else
                (TODAY - timedelta(days=rng.randint(1, 30))).isoformat(),
        })
    _write_csv(target, rows)


def write_pstn_calls(target: Path, users: list[dict]):
    """Only Calling Plan users get entries; zero_pstn users show 0 outbound."""
    rows = []
    for u in users:
        sku_ids = [lic["skuId"] for lic in u.get("assignedLicenses", [])]
        if CALLPLAN_SKU not in sku_ids:
            continue
        if u.get("_zero_pstn"):
            outbound, inbound = 0, 0
        else:
            outbound, inbound = rng.randint(20, 200), rng.randint(10, 100)
        rows.append({
            "user_principal_name": u["userPrincipalName"],
            "outbound_pstn_calls_90d": outbound,
            "inbound_pstn_calls_90d": inbound,
            "last_pstn_call_date": "" if outbound == 0 and inbound == 0 else
                (TODAY - timedelta(days=rng.randint(1, 80))).isoformat(),
        })
    _write_csv(target, rows)


# ---------------------------------------------------------------------------
# Azure
# ---------------------------------------------------------------------------

def write_resource_inventory(target: Path) -> list[dict]:
    """Mix of resources: some orphans, AHB candidates, empty plans, old snapshots."""
    resources = []

    def rid(resource_type, name, sub=None):
        sub = sub or SUBSCRIPTION_IDS[0]
        return f"/subscriptions/{sub}/resourceGroups/rg-demo/providers/{resource_type}/{name}"

    # 30 Windows VMs — 20 without AHB, 10 with
    for i in range(30):
        has_ahb = i >= 20
        resources.append({
            "id": rid("Microsoft.Compute/virtualMachines", f"win-vm-{i:02d}"),
            "name": f"win-vm-{i:02d}",
            "type": "microsoft.compute/virtualmachines",
            "subscriptionId": SUBSCRIPTION_IDS[0],
            "resourceGroup": "rg-demo",
            "location": "eastus",
            "sku": {"name": "Standard_D4s_v5"},
            "properties": {
                "storageProfile": {"osDisk": {"osType": "Windows"}},
                "hardwareProfile": {"vmSize": "Standard_D4s_v5"},
                "licenseType": "Windows_Server" if has_ahb else "",
            },
            "tags": {"env": "prod"},
        })

    # 15 SQL IaaS VMs - 10 without AHB, 5 with
    for i in range(15):
        has_ahb = i >= 10
        resources.append({
            "id": rid("Microsoft.SqlVirtualMachine/sqlVirtualMachines", f"sql-vm-{i:02d}"),
            "name": f"sql-vm-{i:02d}",
            "type": "microsoft.sqlvirtualmachine/sqlvirtualmachines",
            "subscriptionId": SUBSCRIPTION_IDS[0],
            "resourceGroup": "rg-demo",
            "location": "eastus",
            "properties": {"sqlServerLicenseType": "AHUB" if has_ahb else "PAYG"},
            "tags": {"env": "prod"},
        })

    # 30 unattached disks - 20 unattached (orphan), 10 attached
    for i in range(30):
        is_unattached = i < 20
        is_premium = i < 5
        size_gb = 1024 if is_premium else 256
        resources.append({
            "id": rid("Microsoft.Compute/disks", f"orphan-disk-{i:02d}"),
            "name": f"orphan-disk-{i:02d}",
            "type": "microsoft.compute/disks",
            "subscriptionId": SUBSCRIPTION_IDS[0],
            "resourceGroup": "rg-demo",
            "location": "eastus",
            "sku": {"name": "Premium_LRS" if is_premium else "Standard_LRS"},
            "properties": {
                "diskState": "Unattached" if is_unattached else "Attached",
                "diskSizeGB": size_gb,
            },
            "tags": {},
        })

    # 15 NICs - 10 orphaned, 5 attached; created well in past so they clear MIN_AGE_DAYS
    for i in range(15):
        is_orphan = i < 10
        resources.append({
            "id": rid("Microsoft.Network/networkInterfaces", f"nic-{i:02d}"),
            "name": f"nic-{i:02d}",
            "type": "microsoft.network/networkinterfaces",
            "subscriptionId": SUBSCRIPTION_IDS[0],
            "resourceGroup": "rg-demo",
            "location": "eastus",
            "properties": {
                "virtualMachine": None if is_orphan else {"id": "some-vm-id"},
            },
            "tags": {},
            "createdTime": (datetime.utcnow() - timedelta(days=60)).isoformat() + "Z",
        })

    # 10 static public IPs - 8 unassociated, 2 associated
    for i in range(10):
        is_unassoc = i < 8
        resources.append({
            "id": rid("Microsoft.Network/publicIPAddresses", f"pip-{i:02d}"),
            "name": f"pip-{i:02d}",
            "type": "microsoft.network/publicipaddresses",
            "subscriptionId": SUBSCRIPTION_IDS[0],
            "resourceGroup": "rg-demo",
            "location": "eastus",
            "sku": {"name": "Standard"},
            "properties": {
                "publicIPAllocationMethod": "Static",
                "ipConfiguration": None if is_unassoc else {"id": "some-nic-ipconfig"},
            },
            "tags": {},
        })

    # 10 App Service plans - 4 empty, 6 with sites
    for i in range(10):
        num_sites = 0 if i < 4 else rng.randint(1, 3)
        resources.append({
            "id": rid("Microsoft.Web/serverFarms", f"asp-{i:02d}"),
            "name": f"asp-{i:02d}",
            "type": "microsoft.web/serverfarms",
            "subscriptionId": SUBSCRIPTION_IDS[0],
            "resourceGroup": "rg-demo",
            "location": "eastus",
            "sku": {"name": "P1v2"},
            "properties": {"numberOfSites": num_sites},
            "tags": {},
        })

    # 15 snapshots - 10 old (>90d), 5 recent
    for i in range(15):
        age_days = rng.randint(120, 200) if i < 10 else rng.randint(5, 30)
        created = (datetime.utcnow() - timedelta(days=age_days)).isoformat() + "Z"
        resources.append({
            "id": rid("Microsoft.Compute/snapshots", f"snap-{i:02d}"),
            "name": f"snap-{i:02d}",
            "type": "microsoft.compute/snapshots",
            "subscriptionId": SUBSCRIPTION_IDS[0],
            "resourceGroup": "rg-demo",
            "location": "eastus",
            "properties": {"timeCreated": created, "diskSizeGB": 512},
            "tags": {},
            "createdTime": created,
        })

    # 5 storage accounts mostly in Hot tier
    for i in range(5):
        tier = "Hot" if i < 4 else "Cool"
        resources.append({
            "id": rid("Microsoft.Storage/storageAccounts", f"storage{i:02d}"),
            "name": f"storage{i:02d}",
            "type": "microsoft.storage/storageaccounts",
            "subscriptionId": SUBSCRIPTION_IDS[0],
            "resourceGroup": "rg-demo",
            "location": "eastus",
            "sku": {"name": "Standard_LRS"},
            "properties": {"accessTier": tier},
            "tags": {},
        })

    # Write as flat CSV for the ingester
    # CSV with columns: resource_id, name, type, subscription_id, resource_group,
    # location, sku_name, properties(JSON), tags(JSON), created_time
    rows = []
    for r in resources:
        rows.append({
            "id": r["id"],
            "name": r["name"],
            "type": r["type"],
            "subscriptionId": r["subscriptionId"],
            "resourceGroup": r["resourceGroup"],
            "location": r["location"],
            "sku_name": r.get("sku", {}).get("name", ""),
            "properties": json.dumps(r["properties"]),
            "tags": json.dumps(r.get("tags", {})),
            "createdTime": r.get("createdTime", ""),
        })
    _write_csv(target, rows)
    return resources


def write_focus_cost(target_dir: Path, resources: list[dict]):
    """Generate 30 days of FOCUS cost records referencing the resources."""
    target_dir.mkdir(parents=True, exist_ok=True)
    rows = []

    # Cost per resource type (monthly estimate we'll divide into days)
    type_monthly = {
        "microsoft.compute/virtualmachines": 500.0,
        "microsoft.sqlvirtualmachine/sqlvirtualmachines": 1500.0,
        "microsoft.compute/disks": 40.0,
        "microsoft.network/networkinterfaces": 0.0,
        "microsoft.network/publicipaddresses": 3.65,
        "microsoft.web/serverfarms": 75.0,
        "microsoft.compute/snapshots": 25.0,
        "microsoft.storage/storageaccounts": 200.0,
    }

    for r in resources:
        monthly = type_monthly.get(r["type"], 0)
        if monthly == 0:
            continue
        daily = monthly / 30.0
        # 30 days of daily charges
        for d in range(30):
            charge_date = TODAY - timedelta(days=30 - d)
            rows.append({
                "ChargePeriodStart": f"{charge_date}T00:00:00Z",
                "ChargePeriodEnd":   f"{charge_date}T23:59:59Z",
                "BilledCost":        f"{daily:.4f}",
                "EffectiveCost":     f"{daily * 0.9:.4f}",
                "ListCost":          f"{daily * 1.1:.4f}",
                "PricingQuantity":   "1",
                "PricingUnit":       "unit",
                "ConsumedQuantity":  "1",
                "ConsumedUnit":      "unit",
                "ServiceCategory":   _service_category(r["type"]),
                "ServiceName":       _service_name(r["type"]),
                "ResourceId":        r["id"],
                "ResourceName":      r["name"],
                "ResourceType":      r["type"],
                "Region":            r["location"],
                "SubAccountId":      r["subscriptionId"],
                "SubAccountName":    "prod-sub",
                "CommitmentDiscountId":   "",
                "CommitmentDiscountType": "",
                "Tags": json.dumps(r.get("tags", {})),
            })

    _write_csv(target_dir / "cost_2026-03.csv", rows)


def _service_category(resource_type: str) -> str:
    t = resource_type.lower()
    if "compute" in t or "sqlvirtualmachine" in t or "serverfarms" in t:
        return "Compute"
    if "storage" in t:
        return "Storage"
    if "network" in t:
        return "Networking"
    return "Other"


def _service_name(resource_type: str) -> str:
    mapping = {
        "microsoft.compute/virtualmachines": "Virtual Machines",
        "microsoft.sqlvirtualmachine/sqlvirtualmachines": "SQL Server VM",
        "microsoft.compute/disks": "Managed Disks",
        "microsoft.network/publicipaddresses": "Public IP",
        "microsoft.web/serverfarms": "App Service",
        "microsoft.compute/snapshots": "Snapshots",
        "microsoft.storage/storageaccounts": "Storage",
    }
    return mapping.get(resource_type, resource_type.split("/")[-1])


def write_reservations_and_utilization(ri_path: Path, util_path: Path):
    """3 RIs with varied utilization: one healthy, one low-single-scope, one very low."""
    reservations = []
    util_rows = []

    presets = [
        # (id, name, scope, util_pct)
        ("ri-healthy-001",   "Healthy RI",   "Shared",  92.0),
        ("ri-rescope-001",   "Rescope RI",   "Single",  55.0),
        ("ri-exchange-001",  "Exchange RI",  "Shared",  30.0),
    ]

    for rid, name, scope, util in presets:
        reservations.append({
            "id": f"/providers/Microsoft.Capacity/reservationOrders/ord-001/reservations/{rid}",
            "reservationOrderId": "ord-001",
            "displayName": name,
            "skuName": "Standard_D4s_v5",
            "location": "eastus",
            "quantity": 10,
            "term": "P1Y",
            "scope": scope,
            "scopeId": SUBSCRIPTION_IDS[0],
            "appliedScopes": [],
            "purchaseDate": (TODAY - timedelta(days=180)).isoformat(),
            "expirationDate": (TODAY + timedelta(days=185)).isoformat(),
            "effectiveCostMonthlyUsd": 2500.0,
        })
        # 90 daily util rows
        for d in range(90):
            util_rows.append({
                "reservationId": rid,
                "usageDate": (TODAY - timedelta(days=90 - d)).isoformat(),
                "utilizationPercentage": util + rng.uniform(-5, 5),
            })

    ri_path.write_text(json.dumps({"value": reservations}, indent=2))
    util_path.write_text(json.dumps({"value": util_rows}, indent=2))


def write_savings_plans(target: Path):
    """Empty SP inventory - creates headroom for Recipe 5.3 to fire."""
    target.write_text(json.dumps({"value": []}, indent=2))


def write_advisor_cost(target: Path):
    rows = [
        {"recommendationId": "adv-001",
         "resourceId": "/subscriptions/sub/rg/demo/vm/v1",
         "recommendationType": "Shutdown",
         "impact": "High",
         "annualSavingsUsd": 3600,
         "shortDescription": "Shut down idle VM"}
    ]
    _write_csv(target, rows)


def write_vm_utilization(target: Path, resources: list[dict]):
    """Utilization for dev/test VMs - low idle hours => auto-shutdown candidates."""
    # Pick first 10 VMs as "top spenders" with utilization data
    vm_resources = [r for r in resources if "virtualmachines" in r["type"]][:10]
    rows = []
    for r in vm_resources:
        for d in range(30):
            t = TODAY - timedelta(days=30 - d)
            for h in range(24):
                # Business hours 7am-7pm weekdays get 30%, off-hours 2%
                is_business = 7 <= h <= 19 and t.weekday() < 5
                cpu = rng.uniform(25, 45) if is_business else rng.uniform(1, 4)
                rows.append({
                    "resourceId": r["id"],
                    "timeBucket": f"{t}T{h:02d}:00:00Z",
                    "cpuAvgPct": round(cpu, 2),
                    "cpuMaxPct": round(cpu + 5, 2),
                    "memoryAvgPct": round(cpu + 10, 2),
                    "memoryMaxPct": round(cpu + 15, 2),
                    "networkInBytes": rng.randint(1000, 10000),
                    "networkOutBytes": rng.randint(1000, 10000),
                })
    _write_csv(target, rows)


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

def write_defender_pricing(target: Path):
    plans = []
    for sub_id in SUBSCRIPTION_IDS:
        plans.append({
            "subscriptionId": sub_id,
            "name": "VirtualMachines",
            "pricingTier": "Standard",
            "subPlan": "P2",
            "freeTrialRemainingTime": "0",
        })
        plans.append({
            "subscriptionId": sub_id,
            "name": "SqlServers",
            "pricingTier": "Standard",
            "subPlan": "",
        })
    target.write_text(json.dumps({"value": plans}, indent=2))


def write_jit_policies(target: Path):
    """No JIT policies => Recipe 4.1 fires."""
    target.write_text(json.dumps({"value": []}, indent=2))


def write_sentinel_usage(target: Path):
    """Workspace with average 70 GB/day but committed at 100 GB/day (over-committed)."""
    rows = []
    for d in range(90):
        date_str = (TODAY - timedelta(days=90 - d)).isoformat()
        tables = [
            ("SecurityEvent", 25),
            ("Syslog", 20),
            ("AzureActivity", 15),
            ("AppEvents", 10),
        ]
        for tbl_name, base_gb in tables:
            rows.append({
                "workspaceId": "ws-001",
                "usageDate": date_str,
                "dataType": tbl_name,
                "gbIngested": base_gb + rng.uniform(-3, 3),
                "isBillable": True,
            })
    _write_csv(target, rows)


def write_sentinel_commitment(target: Path):
    commitment = [{
        "workspaceId": "ws-001",
        "workspaceName": "acme-sec-ws",
        "pricingTier": "CapacityReservation",
        "capacityReservationLevel": 100,  # 100 GB/day committed, avg ~70 = over-committed
        "dailyCapGb": None,
    }]
    target.write_text(json.dumps({"value": commitment}, indent=2))


# ---------------------------------------------------------------------------
# Commercial
# ---------------------------------------------------------------------------

def write_sa_entitlement(target: Path):
    """Client has SA entitlement; makes Recipe 5.1 relevant."""
    try:
        import openpyxl
    except ImportError:
        # Fallback: skip this if openpyxl isn't here
        return
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "SA Entitlement"
    ws.append([
        "License Family", "Edition", "Cores Entitled", "SA Active",
        "Expiration Date", "Agreement Number",
    ])
    ws.append(["Windows Server", "Datacenter", 800, True,
               (TODAY + timedelta(days=365)).isoformat(), "EA-123456"])
    ws.append(["SQL Server", "Enterprise", 400, True,
               (TODAY + timedelta(days=365)).isoformat(), "EA-123456"])
    wb.save(target)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate(output_dir: Path = OUTPUT_DIR) -> None:
    print(f"Generating synthetic data in {output_dir}")

    m365_dir = output_dir / "m365"
    azure_dir = output_dir / "azure"
    security_dir = output_dir / "security"
    commercial_dir = output_dir / "commercial"

    for d in (m365_dir, azure_dir, security_dir, commercial_dir):
        d.mkdir(parents=True, exist_ok=True)

    # M365
    write_subscribed_skus(m365_dir / "subscribedskus.json")
    users = write_users(m365_dir / "users.json")
    write_activity_reports(m365_dir, users)
    write_office_activations(m365_dir / "office365_activations.csv", users)
    write_pstn_calls(m365_dir / "call_records.csv", users)

    # Azure
    resources = write_resource_inventory(azure_dir / "resource_inventory.csv")
    write_focus_cost(azure_dir / "focus_cost_export", resources)
    write_reservations_and_utilization(
        azure_dir / "reservations.json",
        azure_dir / "reservation_utilization.json",
    )
    write_savings_plans(azure_dir / "savings_plans.json")
    write_advisor_cost(azure_dir / "advisor_cost.csv")
    write_vm_utilization(azure_dir / "vm_utilization.csv", resources)

    # Security
    write_defender_pricing(security_dir / "defender_pricing.json")
    write_jit_policies(security_dir / "jit_policies.json")
    write_sentinel_usage(security_dir / "sentinel_usage.csv")
    write_sentinel_commitment(security_dir / "sentinel_commitment.json")

    # Commercial
    write_sa_entitlement(commercial_dir / "sa_entitlement.xlsx")

    print(f"Done. {len(users)} users, {len(resources)} resources.")


if __name__ == "__main__":
    generate()
