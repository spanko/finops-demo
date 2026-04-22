"""Azure ingest — Cost Management, Resource Graph, RIs, SPs, Advisor, VM metrics."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from gt_finops.ingest.utils import read_json_file, read_tabular


# -----------------------------------------------------------------
# FOCUS 1.2 cost export (parquet or csv, may be directory of files)
# -----------------------------------------------------------------

# Map from common FOCUS column names to our schema
FOCUS_COLUMN_MAP = {
    # FOCUS canonical → schema
    "ChargePeriodStart": "charge_period_start",
    "ChargePeriodEnd": "charge_period_end",
    "BillingPeriodStart": "billing_period_start",
    "BilledCost": "billed_cost",
    "EffectiveCost": "effective_cost",
    "ListCost": "list_cost",
    "PricingQuantity": "pricing_quantity",
    "PricingUnit": "pricing_unit",
    "ConsumedQuantity": "consumed_quantity",
    "ConsumedUnit": "consumed_unit",
    "ServiceCategory": "service_category",
    "ServiceName": "service_name",
    "ServiceSubcategory": "service_subcategory",
    "ResourceId": "resource_id",
    "ResourceName": "resource_name",
    "ResourceType": "resource_type",
    "RegionName": "region",
    "SubAccountId": "sub_account_id",
    "SubAccountName": "sub_account_name",
    "CommitmentDiscountId": "commitment_discount_id",
    "CommitmentDiscountType": "commitment_discount_type",
    "Tags": "tags",
}


def ingest_focus_cost(conn: duckdb.DuckDBPyConnection, source: Path) -> int:
    """Ingest FOCUS cost data. `source` can be a file or a directory."""
    files: list[Path] = []
    if source.is_dir():
        for ext in ("*.parquet", "*.pq", "*.csv"):
            files.extend(source.glob(ext))
    elif source.is_file():
        files = [source]
    else:
        return 0

    if not files:
        return 0

    conn.execute("DELETE FROM azure_cost_focus")
    total = 0

    for fp in files:
        try:
            df = read_tabular(fp)
        except Exception:
            continue
        if df.empty:
            continue

        # Rename FOCUS columns
        renamed = df.rename(columns=FOCUS_COLUMN_MAP)

        # Ensure every required column exists
        required = list(FOCUS_COLUMN_MAP.values())
        for col in required:
            if col not in renamed.columns:
                renamed[col] = None

        # Coerce datetimes
        for col in ["charge_period_start", "charge_period_end", "billing_period_start"]:
            if col in renamed.columns:
                renamed[col] = pd.to_datetime(renamed[col], errors="coerce", utc=True)
                # DuckDB prefers naive timestamps for TIMESTAMP columns
                renamed[col] = renamed[col].dt.tz_localize(None)

        # Coerce numeric
        for col in ["billed_cost", "effective_cost", "list_cost",
                    "pricing_quantity", "consumed_quantity"]:
            if col in renamed.columns:
                renamed[col] = pd.to_numeric(renamed[col], errors="coerce")

        # Tags: if it's a dict, serialize to JSON string
        if "tags" in renamed.columns:
            renamed["tags"] = renamed["tags"].apply(
                lambda v: json.dumps(v) if isinstance(v, dict) else (v if isinstance(v, str) else None)
            )

        renamed["source_file"] = fp.name

        keep = required + ["source_file"]
        renamed = renamed[keep]

        conn.register("df_cost", renamed)
        conn.execute("INSERT INTO azure_cost_focus SELECT * FROM df_cost")
        conn.unregister("df_cost")
        total += len(renamed)

    conn.commit()
    return total


# -----------------------------------------------------------------
# Resource inventory (from Resource Graph)
# -----------------------------------------------------------------

def ingest_resources(conn: duckdb.DuckDBPyConnection, path: Path) -> int:
    """Ingest Resource Graph output. Accepts JSON or CSV."""
    if path.suffix.lower() == ".json":
        data = read_json_file(path)
        if isinstance(data, dict):
            records = data.get("data", data.get("value", []))
        else:
            records = data
        if not records:
            return 0
        df = pd.DataFrame(records)
    else:
        df = read_tabular(path)

    if df.empty:
        return 0

    # Column name normalization
    rename = {
        "id": "resource_id",
        "ResourceId": "resource_id",
        "name": "resource_name",
        "ResourceName": "resource_name",
        "type": "resource_type",
        "ResourceType": "resource_type",
        "subscriptionId": "subscription_id",
        "SubscriptionId": "subscription_id",
        "subscriptionName": "subscription_name",
        "resourceGroup": "resource_group",
        "ResourceGroup": "resource_group",
        "location": "location",
        "Location": "location",
    }
    df = df.rename(columns=rename)

    # SKU can arrive as a dict under "sku" or as sku_name directly
    if "sku" in df.columns and "sku_name" not in df.columns:
        df["sku_name"] = df["sku"].apply(
            lambda v: v.get("name") if isinstance(v, dict) else v
        )
        df["sku_tier"] = df["sku"].apply(
            lambda v: v.get("tier") if isinstance(v, dict) else None
        )

    # properties arrives as dict → serialize
    if "properties" in df.columns:
        df["properties"] = df["properties"].apply(
            lambda v: json.dumps(v, default=str) if isinstance(v, (dict, list))
            else (v if isinstance(v, str) else None)
        )
    else:
        df["properties"] = None

    # tags
    if "tags" in df.columns:
        df["tags"] = df["tags"].apply(
            lambda v: json.dumps(v) if isinstance(v, dict) else (v if isinstance(v, str) else None)
        )
    else:
        df["tags"] = None

    # created_time
    if "createdTime" in df.columns and "created_time" not in df.columns:
        df["created_time"] = df["createdTime"]
    if "created_time" in df.columns:
        df["created_time"] = pd.to_datetime(df["created_time"], errors="coerce", utc=True).dt.tz_localize(None)
    else:
        df["created_time"] = None

    # Ensure all schema columns exist
    required = ["resource_id", "resource_name", "resource_type", "subscription_id",
                "subscription_name", "resource_group", "location", "sku_name",
                "sku_tier", "properties", "tags", "created_time"]
    for col in required:
        if col not in df.columns:
            df[col] = None

    df["source_file"] = path.name

    # Deduplicate on resource_id
    df = df.dropna(subset=["resource_id"]).drop_duplicates(subset=["resource_id"])

    df = df[required + ["source_file"]]

    conn.execute("DELETE FROM azure_resources")
    conn.register("df_res", df)
    conn.execute("INSERT INTO azure_resources SELECT * FROM df_res")
    conn.unregister("df_res")
    conn.commit()
    return len(df)


# -----------------------------------------------------------------
# Reservations
# -----------------------------------------------------------------

def ingest_reservations(conn: duckdb.DuckDBPyConnection, path: Path) -> int:
    data = read_json_file(path)
    records = data.get("value", data) if isinstance(data, dict) else data
    if not records:
        return 0

    rows = []
    for r in records:
        rid = r.get("id", "").split("/")[-1] if r.get("id") else r.get("reservationId")
        if not rid:
            continue

        props = r.get("properties") or r
        rows.append({
            "reservation_id": rid,
            "reservation_order_id": r.get("reservationOrderId") or props.get("reservationOrderId", ""),
            "display_name": props.get("displayName"),
            "sku_name": (props.get("sku") or {}).get("name") if isinstance(props.get("sku"), dict) else props.get("skuName"),
            "region": props.get("location") or props.get("region"),
            "quantity": props.get("quantity"),
            "term": props.get("term"),
            "scope": props.get("appliedScopeType") or props.get("scope"),
            "scope_id": None,
            "applied_scopes": json.dumps(props.get("appliedScopes", [])),
            "purchase_date": props.get("purchaseDate") or props.get("startDate"),
            "expiration_date": props.get("expiryDate") or props.get("expirationDate"),
            "effective_cost_monthly_usd": props.get("effectiveCostMonthlyUsd"),
            "source_file": path.name,
        })

    if not rows:
        return 0

    df = pd.DataFrame(rows)
    for col in ["purchase_date", "expiration_date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.date

    conn.execute("DELETE FROM azure_reservations")
    conn.register("df_ri", df)
    conn.execute("INSERT INTO azure_reservations SELECT * FROM df_ri")
    conn.unregister("df_ri")
    conn.commit()
    return len(rows)


def ingest_reservation_utilization(conn: duckdb.DuckDBPyConnection, path: Path) -> int:
    """Ingest per-reservation daily utilization."""
    if path.suffix.lower() == ".json":
        data = read_json_file(path)
        records = data.get("value", data) if isinstance(data, dict) else data
        df = pd.DataFrame(records) if records else pd.DataFrame()
    else:
        df = read_tabular(path)

    if df.empty:
        return 0

    # Normalize column names
    rename_map = {
        "reservationId": "reservation_id",
        "ReservationId": "reservation_id",
        "usageDate": "usage_date",
        "UsageDate": "usage_date",
        "utilizationPercentage": "utilization_percentage",
        "UtilizationPercentage": "utilization_percentage",
    }
    df = df.rename(columns=rename_map)

    required = ["reservation_id", "usage_date", "utilization_percentage"]
    if not all(c in df.columns for c in required):
        return 0

    df["usage_date"] = pd.to_datetime(df["usage_date"], errors="coerce").dt.date
    df["utilization_percentage"] = pd.to_numeric(df["utilization_percentage"], errors="coerce")
    df["source_file"] = path.name
    df = df.dropna(subset=["reservation_id", "usage_date"])
    df = df.drop_duplicates(subset=["reservation_id", "usage_date"])

    keep = required + ["source_file"]
    df = df[keep]

    conn.execute("DELETE FROM azure_reservation_utilization")
    conn.register("df_util", df)
    conn.execute("INSERT INTO azure_reservation_utilization SELECT * FROM df_util")
    conn.unregister("df_util")
    conn.commit()
    return len(df)


# -----------------------------------------------------------------
# Savings Plans
# -----------------------------------------------------------------

def ingest_savings_plans(conn: duckdb.DuckDBPyConnection, path: Path) -> int:
    data = read_json_file(path)
    records = data.get("value", data) if isinstance(data, dict) else data
    if not records:
        return 0

    rows = []
    for r in records:
        rid = r.get("id", "").split("/")[-1] if r.get("id") else r.get("savingsPlanId")
        if not rid:
            continue
        props = r.get("properties") or r
        rows.append({
            "savings_plan_id": rid,
            "display_name": props.get("displayName"),
            "sku_name": (props.get("sku") or {}).get("name") if isinstance(props.get("sku"), dict) else props.get("skuName"),
            "term": props.get("term"),
            "hourly_commitment_usd": props.get("commitment", {}).get("amount") if isinstance(props.get("commitment"), dict) else props.get("hourlyCommitmentUsd"),
            "applied_scopes": json.dumps(props.get("appliedScopes", [])),
            "purchase_date": props.get("purchaseDate") or props.get("startDate"),
            "expiration_date": props.get("expiryDate") or props.get("expirationDate"),
            "source_file": path.name,
        })

    if not rows:
        return 0

    df = pd.DataFrame(rows)
    for col in ["purchase_date", "expiration_date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.date

    conn.execute("DELETE FROM azure_savings_plans")
    conn.register("df_sp", df)
    conn.execute("INSERT INTO azure_savings_plans SELECT * FROM df_sp")
    conn.unregister("df_sp")
    conn.commit()
    return len(rows)


# -----------------------------------------------------------------
# Advisor cost recommendations
# -----------------------------------------------------------------

def ingest_advisor_cost(conn: duckdb.DuckDBPyConnection, path: Path) -> int:
    df = read_tabular(path)
    if df.empty:
        return 0

    rename = {
        "recommendationId": "recommendation_id",
        "id": "recommendation_id",
        "resourceId": "resource_id",
        "recommendationTypeId": "recommendation_type",
        "category": "category",
        "impact": "impact",
        "annualSavingsAmount": "annual_savings_usd",
        "annual_savings": "annual_savings_usd",
        "shortDescription": "short_description",
        "description": "short_description",
    }
    df = df.rename(columns=rename)

    required = ["recommendation_id", "resource_id", "recommendation_type",
                "impact", "annual_savings_usd", "short_description"]
    for c in required:
        if c not in df.columns:
            df[c] = None

    df["annual_savings_usd"] = pd.to_numeric(df["annual_savings_usd"], errors="coerce").fillna(0)
    df["source_file"] = path.name
    df = df.dropna(subset=["recommendation_id"]).drop_duplicates(subset=["recommendation_id"])
    df = df[required + ["source_file"]]

    conn.execute("DELETE FROM azure_advisor_cost")
    conn.register("df_adv", df)
    conn.execute("INSERT INTO azure_advisor_cost SELECT * FROM df_adv")
    conn.unregister("df_adv")
    conn.commit()
    return len(df)


# -----------------------------------------------------------------
# VM utilization
# -----------------------------------------------------------------

def ingest_vm_utilization(conn: duckdb.DuckDBPyConnection, path: Path) -> int:
    df = read_tabular(path)
    if df.empty:
        return 0

    rename = {
        "ResourceId": "resource_id",
        "resourceId": "resource_id",
        "TimeGenerated": "time_bucket",
        "timestamp": "time_bucket",
        "timeBucket": "time_bucket",
        "TimeBucket": "time_bucket",
        "cpuAvgPct": "cpu_avg_pct",
        "CpuAvgPct": "cpu_avg_pct",
        "cpuMaxPct": "cpu_max_pct",
        "CpuMaxPct": "cpu_max_pct",
        "memoryAvgPct": "memory_avg_pct",
        "MemoryAvgPct": "memory_avg_pct",
        "memoryMaxPct": "memory_max_pct",
        "MemoryMaxPct": "memory_max_pct",
        "networkInBytes": "network_in_bytes",
        "NetworkInBytes": "network_in_bytes",
        "networkOutBytes": "network_out_bytes",
        "NetworkOutBytes": "network_out_bytes",
    }
    df = df.rename(columns=rename)

    required = ["resource_id", "time_bucket", "cpu_avg_pct", "cpu_max_pct",
                "memory_avg_pct", "memory_max_pct", "network_in_bytes",
                "network_out_bytes"]
    for c in required:
        if c not in df.columns:
            df[c] = None

    df["time_bucket"] = pd.to_datetime(df["time_bucket"], errors="coerce", utc=True).dt.tz_localize(None)
    for col in ["cpu_avg_pct", "cpu_max_pct", "memory_avg_pct",
                "memory_max_pct", "network_in_bytes", "network_out_bytes"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["source_file"] = path.name
    df = df.dropna(subset=["resource_id", "time_bucket"])
    df = df.drop_duplicates(subset=["resource_id", "time_bucket"])
    df = df[required + ["source_file"]]

    conn.execute("DELETE FROM azure_vm_utilization")
    conn.register("df_vm", df)
    conn.execute("INSERT INTO azure_vm_utilization SELECT * FROM df_vm")
    conn.unregister("df_vm")
    conn.commit()
    return len(df)
