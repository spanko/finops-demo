"""M365 ingest — Graph API exports."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from gt_finops.ingest.utils import (
    first_existing, read_json_file, read_tabular,
)
from gt_finops.pricing import M365_SKU_MONTHLY


def ingest_subscribed_skus(conn: duckdb.DuckDBPyConnection, path: Path) -> int:
    """Ingest /subscribedSkus. Accepts Graph API shape or Get-MgSubscribedSku shape."""
    data = read_json_file(path)
    # Normalize to a list
    if isinstance(data, dict):
        records = data.get("value", [data] if "skuId" in data else [])
    else:
        records = data

    if not records:
        return 0

    rows = []
    for r in records:
        sku_id = r.get("skuId") or r.get("SkuId")
        sku_part = r.get("skuPartNumber") or r.get("SkuPartNumber") or ""
        display = r.get("displayName") or r.get("DisplayName") or sku_part

        prepaid = r.get("prepaidUnits") or r.get("PrepaidUnits") or {}
        enabled = prepaid.get("enabled", 0)
        suspended = prepaid.get("suspended", 0)
        warning = prepaid.get("warning", 0)
        consumed = r.get("consumedUnits") or r.get("ConsumedUnits") or 0

        service_plans = r.get("servicePlans") or r.get("ServicePlans") or []
        sp_json = json.dumps(service_plans)

        price = M365_SKU_MONTHLY.get(sku_part)

        rows.append({
            "sku_id": sku_id,
            "sku_part_number": sku_part,
            "sku_display_name": display,
            "prepaid_units_enabled": enabled,
            "prepaid_units_suspended": suspended,
            "prepaid_units_warning": warning,
            "consumed_units": consumed,
            "service_plans": sp_json,
            "unit_price_monthly_usd": price,
            "source_file": path.name,
        })

    df = pd.DataFrame(rows)
    conn.execute("DELETE FROM m365_subscribed_skus")
    conn.register("df_skus", df)
    conn.execute("INSERT INTO m365_subscribed_skus SELECT * FROM df_skus")
    conn.unregister("df_skus")
    conn.commit()
    return len(rows)


def ingest_users(conn: duckdb.DuckDBPyConnection, path: Path) -> int:
    """Ingest /users with assignedLicenses and signInActivity."""
    data = read_json_file(path)
    if isinstance(data, dict):
        records = data.get("value", [data] if "id" in data else [])
    else:
        records = data

    if not records:
        return 0

    rows = []
    for r in records:
        user_id = r.get("id") or r.get("Id")
        upn = r.get("userPrincipalName") or r.get("UserPrincipalName")
        if not upn or not user_id:
            continue

        # assignedLicenses is a list of {skuId, disabledPlans} - we just keep skuIds
        assigned = r.get("assignedLicenses") or r.get("AssignedLicenses") or []
        sku_ids = [al.get("skuId") for al in assigned if al.get("skuId")]

        sia = r.get("signInActivity") or r.get("SignInActivity") or {}
        last_sign_in = sia.get("lastSignInDateTime")
        last_non_int = sia.get("lastNonInteractiveSignInDateTime")

        rows.append({
            "user_id": user_id,
            "user_principal_name": upn,
            "display_name": r.get("displayName") or r.get("DisplayName"),
            "account_enabled": bool(r.get("accountEnabled", True)),
            "department": r.get("department") or r.get("Department"),
            "job_title": r.get("jobTitle") or r.get("JobTitle"),
            "assigned_license_skus": json.dumps(sku_ids),
            "last_sign_in_datetime": last_sign_in,
            "last_non_interactive_sign_in": last_non_int,
            "created_datetime": r.get("createdDateTime") or r.get("CreatedDateTime"),
            "deleted_datetime": r.get("deletedDateTime") or r.get("DeletedDateTime"),
            "usage_location": r.get("usageLocation") or r.get("UsageLocation"),
            "source_file": path.name,
        })

    df = pd.DataFrame(rows)
    # Coerce datetime columns
    for col in ["last_sign_in_datetime", "last_non_interactive_sign_in",
                "created_datetime", "deleted_datetime"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)

    conn.execute("DELETE FROM m365_users")
    conn.register("df_users", df)
    conn.execute("INSERT INTO m365_users SELECT * FROM df_users")
    conn.unregister("df_users")
    conn.commit()
    return len(rows)


def ingest_activity_reports(
    conn: duckdb.DuckDBPyConnection, m365_dir: Path,
) -> int:
    """Ingest all per-service activity reports, normalizing to m365_activity."""

    # Map filename → (service name, metadata extraction callable)
    activity_files = {
        "office365_active_users.csv":  ("exchange", _extract_exchange_metadata),
        "teams_user_activity.csv":     ("teams", _extract_teams_metadata),
        "sharepoint_site_usage.csv":   ("sharepoint", _extract_sharepoint_metadata),
        "onedrive_account_detail.csv": ("onedrive", _extract_onedrive_metadata),
        "powerbi_activity.csv":        ("powerbi", _no_metadata),
        "yammer_activity.csv":         ("yammer", _no_metadata),
        "copilot_usage.csv":           ("copilot", _no_metadata),
    }

    total = 0
    conn.execute("DELETE FROM m365_activity")

    for fname, (service, extract_meta) in activity_files.items():
        path = m365_dir / fname
        if not path.exists():
            continue

        try:
            df = read_tabular(path)
        except Exception:
            continue

        if df.empty:
            continue

        # Graph reports CSVs use "User Principal Name" or similar
        upn_col = _find_column(df, [
            "user_principal_name", "User Principal Name",
            "userPrincipalName", "UPN",
        ])
        last_activity_col = _find_column(df, [
            "last_activity_date", "Last Activity Date",
            "lastActivityDate",
        ])
        if upn_col is None:
            continue

        rows = []
        for _, row in df.iterrows():
            upn = row.get(upn_col)
            if pd.isna(upn) or not upn:
                continue
            last_activity = row.get(last_activity_col) if last_activity_col else None
            if pd.isna(last_activity):
                last_activity = None
            metadata = extract_meta(row) or {}
            # Attempt to find an activity-count column
            count_30d = None
            for count_col in ["activity_count_30d", "Activity Count",
                              "Team Chat Messages", "Message Count"]:
                if count_col in df.columns and not pd.isna(row.get(count_col)):
                    try:
                        count_30d = int(row[count_col])
                        break
                    except (ValueError, TypeError):
                        pass

            rows.append({
                "user_principal_name": str(upn),
                "service": service,
                "last_activity_date": last_activity,
                "activity_count_30d": count_30d,
                "metadata": json.dumps(metadata, default=str),
                "source_file": path.name,
            })

        if not rows:
            continue

        act_df = pd.DataFrame(rows)
        act_df["last_activity_date"] = pd.to_datetime(
            act_df["last_activity_date"], errors="coerce"
        ).dt.date
        conn.register("df_act", act_df)
        conn.execute("INSERT INTO m365_activity SELECT * FROM df_act")
        conn.unregister("df_act")
        total += len(rows)

    conn.commit()
    return total


def ingest_office_activations(conn: duckdb.DuckDBPyConnection, path: Path) -> int:
    df = read_tabular(path)
    if df.empty:
        return 0

    upn_col = _find_column(df, ["user_principal_name", "User Principal Name", "UPN"])
    if upn_col is None:
        return 0

    # Heuristic: if any device activation column is truthy, user has desktop activation
    device_cols = [c for c in df.columns if "activated" in c.lower() or "activation" in c.lower()]

    rows = []
    for _, row in df.iterrows():
        upn = row.get(upn_col)
        if pd.isna(upn):
            continue
        activated = False
        device_count = 0
        for c in device_cols:
            val = row.get(c)
            try:
                if not pd.isna(val) and (val is True or int(val) > 0):
                    activated = True
                    device_count += int(val) if val is not True else 1
            except (ValueError, TypeError):
                pass
        rows.append({
            "user_principal_name": str(upn),
            "activated_on_any_device": activated,
            "device_count": device_count,
            "last_activation_date": None,
            "source_file": path.name,
        })

    if not rows:
        return 0

    conn.execute("DELETE FROM m365_office_activations")
    act_df = pd.DataFrame(rows)
    conn.register("df_oa", act_df)
    conn.execute("INSERT INTO m365_office_activations SELECT * FROM df_oa")
    conn.unregister("df_oa")
    conn.commit()
    return len(rows)


def ingest_pstn_calls(conn: duckdb.DuckDBPyConnection, path: Path) -> int:
    df = read_tabular(path)
    if df.empty:
        return 0

    upn_col = _find_column(df, ["user_principal_name", "User Principal Name",
                                 "caller_upn", "UPN"])
    if upn_col is None:
        return 0

    # Aggregate calls per user (input may be call-level records or pre-aggregated)
    df_norm = df.copy()
    if "direction" in df_norm.columns:
        # Call-level records: count by direction
        outbound = df_norm[df_norm["direction"].str.lower() == "outbound"].groupby(upn_col).size()
        inbound = df_norm[df_norm["direction"].str.lower() == "inbound"].groupby(upn_col).size()
        last_call = df_norm.groupby(upn_col)["start_time"].max() if "start_time" in df_norm else None
    else:
        # Pre-aggregated
        outbound_col = _find_column(df_norm, ["outbound_pstn_calls_90d", "outbound_calls"])
        inbound_col = _find_column(df_norm, ["inbound_pstn_calls_90d", "inbound_calls"])
        if outbound_col is None:
            return 0
        outbound = df_norm.set_index(upn_col)[outbound_col]
        inbound = df_norm.set_index(upn_col)[inbound_col] if inbound_col else None
        last_col = _find_column(df_norm, ["last_pstn_call_date"])
        last_call = df_norm.set_index(upn_col)[last_col] if last_col else None

    # Union of users
    users = set(outbound.index.tolist())
    if inbound is not None:
        users.update(inbound.index.tolist())

    rows = []
    for user in users:
        rows.append({
            "user_principal_name": str(user),
            "outbound_pstn_calls_90d": int(outbound.get(user, 0)) if user in outbound.index else 0,
            "inbound_pstn_calls_90d": int(inbound.get(user, 0)) if inbound is not None and user in inbound.index else 0,
            "last_pstn_call_date": (
                last_call.get(user) if last_call is not None and user in last_call.index else None
            ),
            "source_file": path.name,
        })

    if not rows:
        return 0

    conn.execute("DELETE FROM m365_pstn_calls")
    pstn_df = pd.DataFrame(rows)
    pstn_df["last_pstn_call_date"] = pd.to_datetime(
        pstn_df["last_pstn_call_date"], errors="coerce"
    ).dt.date
    conn.register("df_pstn", pstn_df)
    conn.execute("INSERT INTO m365_pstn_calls SELECT * FROM df_pstn")
    conn.unregister("df_pstn")
    conn.commit()
    return len(rows)


# -----------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------

def _find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    # Case-insensitive match
    lowered = {col.lower(): col for col in df.columns}
    for c in candidates:
        if c.lower() in lowered:
            return lowered[c.lower()]
    # Normalize: strip spaces, underscores, hyphens
    def _norm(s: str) -> str:
        return "".join(ch for ch in s.lower() if ch.isalnum())
    normalized = {_norm(col): col for col in df.columns}
    for c in candidates:
        if _norm(c) in normalized:
            return normalized[_norm(c)]
    return None


def _no_metadata(row) -> dict:
    return {}


def _extract_exchange_metadata(row) -> dict:
    meta = {}
    for col in ["mailbox_gb", "Storage Used (MB)", "storage_used_mb",
                "Mailbox Storage (GB)"]:
        val = row.get(col) if col in row.index else None
        if val is not None and not pd.isna(val):
            try:
                if "MB" in col or "mb" in col:
                    meta["mailbox_gb"] = float(val) / 1024
                else:
                    meta["mailbox_gb"] = float(val)
                break
            except (ValueError, TypeError):
                pass
    return meta


def _extract_teams_metadata(row) -> dict:
    return {}


def _extract_sharepoint_metadata(row) -> dict:
    meta = {}
    for col in ["owned_site_count", "Site Count"]:
        val = row.get(col) if col in row.index else None
        if val is not None and not pd.isna(val):
            try:
                meta["owned_site_count"] = int(val)
                break
            except (ValueError, TypeError):
                pass
    return meta


def _extract_onedrive_metadata(row) -> dict:
    meta = {}
    for col in ["storage_used_gb", "Storage Used (GB)",
                "Storage Used (Bytes)", "storage_used_bytes"]:
        val = row.get(col) if col in row.index else None
        if val is not None and not pd.isna(val):
            try:
                num = float(val)
                if "Bytes" in col or "bytes" in col:
                    meta["storage_used_gb"] = num / (1024 ** 3)
                else:
                    meta["storage_used_gb"] = num
                break
            except (ValueError, TypeError):
                pass
    return meta
