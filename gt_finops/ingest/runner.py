"""Ingest orchestrator — walks the expected client-data folder layout."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from gt_finops.ingest import m365, azure, security, commercial


@dataclass
class IngestReport:
    """Summary of what got ingested from a client data folder."""

    tables_populated: dict[str, int] = field(default_factory=dict)
    files_processed: list[str] = field(default_factory=list)
    files_missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return sum(self.tables_populated.values())


# ---------------------------------------------------------------------------
# Expected file map (relative to source_dir)
# ---------------------------------------------------------------------------

EXPECTED_LAYOUT = {
    # M365
    "m365/subscribedskus.json":       "m365_subscribed_skus",
    "m365/users.json":                "m365_users",
    "m365/office365_activations.csv": "m365_office_activations",
    "m365/call_records.csv":          "m365_pstn_calls",
    # M365 activity reports handled as a group
    "m365/office365_active_users.csv":  "m365_activity (exchange)",
    "m365/teams_user_activity.csv":     "m365_activity (teams)",
    "m365/sharepoint_site_usage.csv":   "m365_activity (sharepoint)",
    "m365/onedrive_account_detail.csv": "m365_activity (onedrive)",
    "m365/powerbi_activity.csv":        "m365_activity (powerbi)",
    "m365/yammer_activity.csv":         "m365_activity (yammer)",
    "m365/copilot_usage.csv":           "m365_activity (copilot)",

    # Azure
    "azure/focus_cost_export":        "azure_cost_focus",
    "azure/resource_inventory.csv":   "azure_resources",
    "azure/reservations.json":        "azure_reservations",
    "azure/reservation_utilization.json": "azure_reservation_utilization",
    "azure/savings_plans.json":       "azure_savings_plans",
    "azure/advisor_cost.csv":         "azure_advisor_cost",
    "azure/vm_utilization.csv":       "azure_vm_utilization",

    # Security
    "security/defender_pricing.json":    "defender_pricing",
    "security/jit_policies.json":        "defender_jit_policies",
    "security/sentinel_usage.csv":       "sentinel_usage",
    "security/sentinel_commitment.json": "sentinel_commitment",

    # Commercial
    "commercial/sa_entitlement.xlsx":    "sa_entitlement",
    "commercial/price_sheet.xlsx":       "sku_price_overrides",
}


def ingest_folder(
    conn: duckdb.DuckDBPyConnection, source_dir: Path,
) -> IngestReport:
    """
    Walk the expected client data layout and ingest each file into its
    conformed table. Missing files are logged but not errors.
    """
    report = IngestReport()
    src = Path(source_dir)

    # ----------------------------------------------------------------
    # M365
    # ----------------------------------------------------------------
    m365_dir = src / "m365"
    if m365_dir.exists():
        for fname, ingest_fn in [
            ("subscribedskus.json", m365.ingest_subscribed_skus),
            ("users.json", m365.ingest_users),
            ("office365_activations.csv", m365.ingest_office_activations),
            ("call_records.csv", m365.ingest_pstn_calls),
        ]:
            fpath = m365_dir / fname
            if fpath.exists():
                try:
                    count = ingest_fn(conn, fpath)
                    # Table name comes from the ingest function — look up via ingest_fn
                    target = _table_for_fn(ingest_fn)
                    report.tables_populated[target] = count
                    report.files_processed.append(str(fpath.relative_to(src)))
                except Exception as e:
                    report.errors.append(f"{fpath.name}: {e}")
            else:
                report.files_missing.append(f"m365/{fname}")

        # Per-service activity reports — batched
        try:
            count = m365.ingest_activity_reports(conn, m365_dir)
            if count > 0:
                report.tables_populated["m365_activity"] = count
        except Exception as e:
            report.errors.append(f"m365_activity: {e}")
    else:
        report.files_missing.append("m365/ (directory)")

    # ----------------------------------------------------------------
    # Azure
    # ----------------------------------------------------------------
    azure_dir = src / "azure"
    if azure_dir.exists():
        # FOCUS cost export (directory or file)
        focus_path = azure_dir / "focus_cost_export"
        if not focus_path.exists():
            focus_path = azure_dir / "focus_cost_export.parquet"
        if focus_path.exists():
            try:
                count = azure.ingest_focus_cost(conn, focus_path)
                report.tables_populated["azure_cost_focus"] = count
                report.files_processed.append(f"azure/{focus_path.name}")
            except Exception as e:
                report.errors.append(f"focus_cost_export: {e}")
        else:
            report.files_missing.append("azure/focus_cost_export")

        for fname, ingest_fn in [
            ("resource_inventory.csv", azure.ingest_resources),
            ("resource_inventory.json", azure.ingest_resources),
            ("reservations.json", azure.ingest_reservations),
            ("reservation_utilization.json", azure.ingest_reservation_utilization),
            ("reservation_utilization.csv", azure.ingest_reservation_utilization),
            ("savings_plans.json", azure.ingest_savings_plans),
            ("advisor_cost.csv", azure.ingest_advisor_cost),
            ("vm_utilization.csv", azure.ingest_vm_utilization),
        ]:
            fpath = azure_dir / fname
            if fpath.exists():
                try:
                    count = ingest_fn(conn, fpath)
                    target = _table_for_fn(ingest_fn)
                    if target not in report.tables_populated:
                        report.tables_populated[target] = count
                    report.files_processed.append(f"azure/{fname}")
                except Exception as e:
                    report.errors.append(f"{fname}: {e}")
    else:
        report.files_missing.append("azure/ (directory)")

    # ----------------------------------------------------------------
    # Security
    # ----------------------------------------------------------------
    sec_dir = src / "security"
    if sec_dir.exists():
        for fname, ingest_fn in [
            ("defender_pricing.json", security.ingest_defender_pricing),
            ("jit_policies.json", security.ingest_jit_policies),
            ("sentinel_usage.csv", security.ingest_sentinel_usage),
            ("sentinel_commitment.json", security.ingest_sentinel_commitment),
        ]:
            fpath = sec_dir / fname
            if fpath.exists():
                try:
                    count = ingest_fn(conn, fpath)
                    target = _table_for_fn(ingest_fn)
                    report.tables_populated[target] = count
                    report.files_processed.append(f"security/{fname}")
                except Exception as e:
                    report.errors.append(f"{fname}: {e}")
            else:
                report.files_missing.append(f"security/{fname}")
    else:
        report.files_missing.append("security/ (directory)")

    # ----------------------------------------------------------------
    # Commercial
    # ----------------------------------------------------------------
    com_dir = src / "commercial"
    if com_dir.exists():
        for fname, ingest_fn in [
            ("sa_entitlement.xlsx", commercial.ingest_sa_entitlement),
            ("sa_entitlement.csv", commercial.ingest_sa_entitlement),
            ("price_sheet.xlsx", commercial.ingest_price_sheet),
        ]:
            fpath = com_dir / fname
            if fpath.exists():
                try:
                    count = ingest_fn(conn, fpath)
                    target = _table_for_fn(ingest_fn)
                    report.tables_populated[target] = count
                    report.files_processed.append(f"commercial/{fname}")
                except Exception as e:
                    report.errors.append(f"{fname}: {e}")

    return report


def _table_for_fn(fn) -> str:
    """Map an ingest function to its target table name."""
    mapping = {
        m365.ingest_subscribed_skus: "m365_subscribed_skus",
        m365.ingest_users: "m365_users",
        m365.ingest_office_activations: "m365_office_activations",
        m365.ingest_pstn_calls: "m365_pstn_calls",
        azure.ingest_focus_cost: "azure_cost_focus",
        azure.ingest_resources: "azure_resources",
        azure.ingest_reservations: "azure_reservations",
        azure.ingest_reservation_utilization: "azure_reservation_utilization",
        azure.ingest_savings_plans: "azure_savings_plans",
        azure.ingest_advisor_cost: "azure_advisor_cost",
        azure.ingest_vm_utilization: "azure_vm_utilization",
        security.ingest_defender_pricing: "defender_pricing",
        security.ingest_jit_policies: "defender_jit_policies",
        security.ingest_sentinel_usage: "sentinel_usage",
        security.ingest_sentinel_commitment: "sentinel_commitment",
        commercial.ingest_sa_entitlement: "sa_entitlement",
        commercial.ingest_price_sheet: "sku_price_overrides",
    }
    return mapping.get(fn, "unknown")
