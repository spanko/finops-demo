"""Shared ingest utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def read_json_file(path: Path) -> Any:
    """Read a JSON file; accept both dict and list at the root."""
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_jsonlines(path: Path) -> list[dict]:
    """Read a JSON-lines file."""
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def read_tabular(path: Path) -> pd.DataFrame:
    """Read csv/parquet/xlsx uniformly, returning a DataFrame."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".tsv":
        return pd.read_csv(path, sep="\t")
    if suffix in (".parquet", ".pq"):
        return pd.read_parquet(path)
    if suffix in (".xlsx", ".xlsm"):
        return pd.read_excel(path)
    if suffix == ".json":
        data = read_json_file(path)
        if isinstance(data, list):
            return pd.DataFrame(data)
        if isinstance(data, dict) and "value" in data:
            # Graph API response shape
            return pd.DataFrame(data["value"])
        raise ValueError(f"Cannot coerce JSON {path} to DataFrame")
    raise ValueError(f"Unsupported file extension: {path}")


def normalize_columns(df: pd.DataFrame, column_map: dict[str, str]) -> pd.DataFrame:
    """Rename columns in df according to column_map; drop unknown columns."""
    renamed = df.rename(columns=column_map)
    keep = [c for c in column_map.values() if c in renamed.columns]
    return renamed[keep]


def first_existing(parent: Path, candidates: list[str]) -> Path | None:
    """Return the first file from candidates that exists in parent."""
    for c in candidates:
        p = parent / c
        if p.exists():
            return p
    return None


def ensure_df_columns(df: pd.DataFrame, columns: list[str], defaults: dict | None = None) -> pd.DataFrame:
    """Ensure every column in `columns` exists in df; fill missing with defaults."""
    defaults = defaults or {}
    for col in columns:
        if col not in df.columns:
            df[col] = defaults.get(col, None)
    return df[columns]
