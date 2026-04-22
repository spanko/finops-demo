"""Commercial ingest — Software Assurance entitlement, EA price sheet."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from gt_finops.ingest.utils import read_tabular


def ingest_sa_entitlement(conn: duckdb.DuckDBPyConnection, path: Path) -> int:
    """Ingest client's Software Assurance entitlement spreadsheet."""
    df = read_tabular(path)
    if df.empty:
        return 0

    rename = {
        "License Family": "license_family",
        "Edition": "edition",
        "Core Count": "core_count_entitled",
        "Cores": "core_count_entitled",
        "SA Active": "sa_active",
        "SAActive": "sa_active",
        "Expiration Date": "expiration_date",
        "Agreement Number": "agreement_number",
        "Notes": "notes",
    }
    df = df.rename(columns=rename)

    required = ["license_family", "edition", "core_count_entitled",
                "sa_active", "expiration_date", "agreement_number", "notes"]
    for c in required:
        if c not in df.columns:
            df[c] = None

    df["core_count_entitled"] = pd.to_numeric(df["core_count_entitled"], errors="coerce").fillna(0).astype(int)

    def _bool(v):
        if isinstance(v, bool):
            return v
        if pd.isna(v):
            return False
        s = str(v).strip().lower()
        return s in ("true", "yes", "y", "1", "active")
    df["sa_active"] = df["sa_active"].apply(_bool)
    df["expiration_date"] = pd.to_datetime(df["expiration_date"], errors="coerce").dt.date

    df["source_file"] = path.name
    df = df[required + ["source_file"]]

    conn.execute("DELETE FROM sa_entitlement")
    conn.register("df_sa", df)
    conn.execute("INSERT INTO sa_entitlement SELECT * FROM df_sa")
    conn.unregister("df_sa")
    conn.commit()
    return len(df)


def ingest_price_sheet(conn: duckdb.DuckDBPyConnection, path: Path) -> int:
    """Ingest EA price sheet overrides (optional)."""
    df = read_tabular(path)
    if df.empty:
        return 0

    rename = {
        "SKU Code": "sku_code",
        "SkuCode": "sku_code",
        "Product": "sku_code",
        "SKU Family": "sku_family",
        "Family": "sku_family",
        "Unit Price": "unit_price_monthly_usd",
        "Monthly Price (USD)": "unit_price_monthly_usd",
        "Price": "unit_price_monthly_usd",
        "Currency": "currency",
    }
    df = df.rename(columns=rename)

    required = ["sku_code", "sku_family", "unit_price_monthly_usd", "currency"]
    for c in required:
        if c not in df.columns:
            df[c] = None

    df["unit_price_monthly_usd"] = pd.to_numeric(df["unit_price_monthly_usd"], errors="coerce")
    df = df.dropna(subset=["sku_code", "unit_price_monthly_usd"])

    if "currency" not in df.columns or df["currency"].isna().all():
        df["currency"] = "USD"

    df["source_file"] = path.name
    df = df[required + ["source_file"]]
    df = df.drop_duplicates(subset=["sku_code"])

    conn.execute("DELETE FROM sku_price_overrides")
    conn.register("df_ps", df)
    conn.execute("INSERT INTO sku_price_overrides SELECT * FROM df_ps")
    conn.unregister("df_ps")
    conn.commit()
    return len(df)
