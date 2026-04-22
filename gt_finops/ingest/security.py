"""Security ingest — Defender for Cloud, Sentinel / Log Analytics."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from gt_finops.ingest.utils import read_json_file, read_tabular


def ingest_defender_pricing(conn: duckdb.DuckDBPyConnection, path: Path) -> int:
    data = read_json_file(path)
    records = data.get("value", data) if isinstance(data, dict) else data
    if not records:
        return 0

    rows = []
    for r in records:
        # az security pricing list output structure:
        # { "id": "/subscriptions/xxx/.../pricings/VirtualMachines",
        #   "name": "VirtualMachines",
        #   "properties": { "pricingTier": "Standard", "subPlan": "P2", ... } }
        rid = r.get("id", "")
        subscription_id = ""
        if "/subscriptions/" in rid:
            parts = rid.split("/")
            try:
                subscription_id = parts[parts.index("subscriptions") + 1]
            except (ValueError, IndexError):
                subscription_id = ""
        subscription_id = subscription_id or r.get("subscriptionId", "")
        plan_name = r.get("name") or r.get("planName", "")
        props = r.get("properties") or r
        pricing_tier = props.get("pricingTier", "Free")
        sub_plan = props.get("subPlan")

        rows.append({
            "subscription_id": subscription_id,
            "plan_name": plan_name,
            "pricing_tier": pricing_tier,
            "sub_plan": sub_plan,
            "resource_count": props.get("resourceCount") or props.get("resource_count"),
            "source_file": path.name,
        })

    if not rows:
        return 0

    # Deduplicate on (subscription_id, plan_name) - keep first
    df = pd.DataFrame(rows).drop_duplicates(subset=["subscription_id", "plan_name"])

    conn.execute("DELETE FROM defender_pricing")
    conn.register("df_def", df)
    conn.execute("INSERT INTO defender_pricing SELECT * FROM df_def")
    conn.unregister("df_def")
    conn.commit()
    return len(df)


def ingest_jit_policies(conn: duckdb.DuckDBPyConnection, path: Path) -> int:
    data = read_json_file(path)
    records = data.get("value", data) if isinstance(data, dict) else data
    if not records:
        return 0

    rows = []
    for r in records:
        pid = r.get("id") or r.get("policyId")
        if not pid:
            continue
        subscription_id = ""
        if "/subscriptions/" in pid:
            parts = pid.split("/")
            try:
                subscription_id = parts[parts.index("subscriptions") + 1]
            except (ValueError, IndexError):
                pass

        props = r.get("properties") or r
        vms = props.get("virtualMachines") or []
        rows.append({
            "policy_id": pid,
            "subscription_id": subscription_id,
            "policy_name": r.get("name"),
            "vm_count": len(vms) if isinstance(vms, list) else 0,
            "location": r.get("location"),
            "source_file": path.name,
        })

    if not rows:
        return 0

    df = pd.DataFrame(rows).drop_duplicates(subset=["policy_id"])

    conn.execute("DELETE FROM defender_jit_policies")
    conn.register("df_jit", df)
    conn.execute("INSERT INTO defender_jit_policies SELECT * FROM df_jit")
    conn.unregister("df_jit")
    conn.commit()
    return len(df)


def ingest_sentinel_usage(conn: duckdb.DuckDBPyConnection, path: Path) -> int:
    df = read_tabular(path)
    if df.empty:
        return 0

    # Kusto output column names + generator/export variants
    rename = {
        "WorkspaceId": "workspace_id",
        "workspaceId": "workspace_id",
        "TimeGenerated": "usage_date",
        "UsageDate": "usage_date",
        "usageDate": "usage_date",
        "DataType": "data_type",
        "dataType": "data_type",
        "Quantity": "gb_ingested",
        "gb": "gb_ingested",
        "GbIngested": "gb_ingested",
        "gbIngested": "gb_ingested",
        "IsBillable": "is_billable",
        "isBillable": "is_billable",
    }
    df = df.rename(columns=rename)

    required = ["workspace_id", "usage_date", "data_type", "gb_ingested", "is_billable"]
    for c in required:
        if c not in df.columns:
            df[c] = None

    df["usage_date"] = pd.to_datetime(df["usage_date"], errors="coerce").dt.date
    df["gb_ingested"] = pd.to_numeric(df["gb_ingested"], errors="coerce").fillna(0)
    if "is_billable" in df.columns:
        df["is_billable"] = df["is_billable"].astype(bool) if df["is_billable"].notna().any() else True

    df["source_file"] = path.name
    df = df.dropna(subset=["workspace_id", "usage_date", "data_type"])
    df = df.drop_duplicates(subset=["workspace_id", "usage_date", "data_type"])
    df = df[required + ["source_file"]]

    conn.execute("DELETE FROM sentinel_usage")
    conn.register("df_sent", df)
    conn.execute("INSERT INTO sentinel_usage SELECT * FROM df_sent")
    conn.unregister("df_sent")
    conn.commit()
    return len(df)


def ingest_sentinel_commitment(conn: duckdb.DuckDBPyConnection, path: Path) -> int:
    data = read_json_file(path)
    records = data.get("value", data) if isinstance(data, dict) else data
    if not records:
        return 0

    rows = []
    for r in records:
        wid = r.get("workspaceId") or r.get("id", "").split("/")[-1]
        if not wid:
            continue
        props = r.get("properties") or r
        sku = props.get("sku") or {}

        # Accept multiple shapes: top-level pricingTier (flattened),
        # properties.pricingTier (Azure API), or sku.name (legacy)
        pricing_tier = (
            r.get("pricingTier")
            or props.get("pricingTier")
            or (sku.get("name") if isinstance(sku, dict) else None)
            or "PerGB2018"
        )
        capacity_level = (
            r.get("capacityReservationLevel")
            or props.get("capacityReservationLevel")
            or (sku.get("capacityReservationLevel") if isinstance(sku, dict) else None)
        )
        daily_cap = r.get("dailyCapGb") or r.get("dailyQuotaGb")
        if daily_cap is None and isinstance(props.get("workspaceCapping"), dict):
            daily_cap = props["workspaceCapping"].get("dailyQuotaGb")

        rows.append({
            "workspace_id": wid,
            "workspace_name": r.get("name") or r.get("workspaceName"),
            "pricing_tier": pricing_tier,
            "capacity_reservation_level": capacity_level,
            "daily_cap_gb": daily_cap,
            "source_file": path.name,
        })

    if not rows:
        return 0

    df = pd.DataFrame(rows).drop_duplicates(subset=["workspace_id"])

    conn.execute("DELETE FROM sentinel_commitment")
    conn.register("df_sc", df)
    conn.execute("INSERT INTO sentinel_commitment SELECT * FROM df_sc")
    conn.unregister("df_sc")
    conn.commit()
    return len(df)
