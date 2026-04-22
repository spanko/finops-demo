"""
Canonical DuckDB schema for gt-finops.

This module defines the conformed tables that ingest modules write to and
recipe modules read from. It's the contract that decouples the two layers.

Design principles:
- Every table has a stable primary key (entity_id)
- Every table has a source_file column for traceability back to raw input
- Cost is always in USD; utilization is always in percent (0-100)
- Date columns are DATE; timestamp columns are TIMESTAMP
- FOCUS 1.2 column names are preserved where they exist
- Recipes never query raw source files - only these tables
"""

from __future__ import annotations

import duckdb


SCHEMA_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Schema definitions grouped by pillar
# ---------------------------------------------------------------------------

M365_SCHEMA = """
-- M365 subscribed SKUs (what's paid for)
CREATE TABLE IF NOT EXISTS m365_subscribed_skus (
    sku_id                      VARCHAR NOT NULL,      -- GUID from Graph
    sku_part_number             VARCHAR NOT NULL,      -- e.g. 'ENTERPRISEPREMIUM' (E5)
    sku_display_name            VARCHAR,               -- human-readable
    prepaid_units_enabled       INTEGER NOT NULL,
    prepaid_units_suspended     INTEGER,
    prepaid_units_warning       INTEGER,
    consumed_units              INTEGER NOT NULL,
    service_plans               VARCHAR,               -- JSON array of service plan GUIDs
    unit_price_monthly_usd      DOUBLE,                -- populated from price sheet or defaults
    source_file                 VARCHAR NOT NULL,
    PRIMARY KEY (sku_id)
);

-- M365 users with license assignments and sign-in
CREATE TABLE IF NOT EXISTS m365_users (
    user_id                     VARCHAR NOT NULL,      -- Entra object ID
    user_principal_name         VARCHAR NOT NULL,
    display_name                VARCHAR,
    account_enabled             BOOLEAN NOT NULL,
    department                  VARCHAR,
    job_title                   VARCHAR,
    assigned_license_skus       VARCHAR,               -- JSON array of sku_ids
    last_sign_in_datetime       TIMESTAMP,
    last_non_interactive_sign_in TIMESTAMP,
    created_datetime            TIMESTAMP,
    deleted_datetime            TIMESTAMP,             -- null if not deleted
    usage_location              VARCHAR,
    source_file                 VARCHAR NOT NULL,
    PRIMARY KEY (user_id)
);

-- Per-service activity, normalized across all reports
CREATE TABLE IF NOT EXISTS m365_activity (
    user_principal_name         VARCHAR NOT NULL,
    service                     VARCHAR NOT NULL,      -- 'exchange', 'teams', 'sharepoint',
                                                       -- 'onedrive', 'powerbi', 'yammer', 'copilot'
    last_activity_date          DATE,                  -- null means no activity in window
    activity_count_30d          INTEGER,               -- measure depends on service
    metadata                    VARCHAR,               -- JSON for service-specific fields
    source_file                 VARCHAR NOT NULL,
    PRIMARY KEY (user_principal_name, service)
);

-- Desktop Office activation detail (for F3 candidacy)
CREATE TABLE IF NOT EXISTS m365_office_activations (
    user_principal_name         VARCHAR NOT NULL,
    activated_on_any_device     BOOLEAN NOT NULL,
    device_count                INTEGER,
    last_activation_date        DATE,
    source_file                 VARCHAR NOT NULL,
    PRIMARY KEY (user_principal_name)
);

-- PSTN call records (aggregated per user, 90-day window)
CREATE TABLE IF NOT EXISTS m365_pstn_calls (
    user_principal_name         VARCHAR NOT NULL,
    outbound_pstn_calls_90d     INTEGER NOT NULL,
    inbound_pstn_calls_90d      INTEGER NOT NULL,
    last_pstn_call_date         DATE,
    source_file                 VARCHAR NOT NULL,
    PRIMARY KEY (user_principal_name)
);
"""

AZURE_SCHEMA = """
-- FOCUS 1.2 cost data (partial columns most relevant for recipes)
CREATE TABLE IF NOT EXISTS azure_cost_focus (
    charge_period_start         TIMESTAMP NOT NULL,
    charge_period_end           TIMESTAMP NOT NULL,
    billing_period_start        TIMESTAMP,
    billed_cost                 DOUBLE NOT NULL,       -- USD
    effective_cost              DOUBLE,                -- post-discount USD
    list_cost                   DOUBLE,                -- pre-negotiated
    pricing_quantity            DOUBLE,
    pricing_unit                VARCHAR,
    consumed_quantity           DOUBLE,
    consumed_unit               VARCHAR,
    service_category            VARCHAR,               -- 'Compute', 'Storage', etc.
    service_name                VARCHAR,
    service_subcategory         VARCHAR,
    resource_id                 VARCHAR,               -- canonical Azure resource ID
    resource_name               VARCHAR,
    resource_type               VARCHAR,
    region                      VARCHAR,
    sub_account_id              VARCHAR,               -- Azure subscription ID
    sub_account_name            VARCHAR,
    commitment_discount_id      VARCHAR,               -- RI or SP that covered this usage
    commitment_discount_type    VARCHAR,               -- 'Reservation', 'Savings Plan', null
    tags                        VARCHAR,               -- JSON
    source_file                 VARCHAR NOT NULL
);

-- Full Azure resource inventory (from Resource Graph)
CREATE TABLE IF NOT EXISTS azure_resources (
    resource_id                 VARCHAR NOT NULL,      -- /subscriptions/.../resourceGroups/.../...
    resource_name               VARCHAR,
    resource_type               VARCHAR NOT NULL,
    subscription_id             VARCHAR NOT NULL,
    subscription_name           VARCHAR,
    resource_group              VARCHAR,
    location                    VARCHAR,
    sku_name                    VARCHAR,
    sku_tier                    VARCHAR,
    properties                  VARCHAR,               -- JSON - full resource properties
    tags                        VARCHAR,               -- JSON
    created_time                TIMESTAMP,
    source_file                 VARCHAR NOT NULL,
    PRIMARY KEY (resource_id)
);

-- Reservation inventory
CREATE TABLE IF NOT EXISTS azure_reservations (
    reservation_id              VARCHAR NOT NULL,
    reservation_order_id        VARCHAR NOT NULL,
    display_name                VARCHAR,
    sku_name                    VARCHAR,
    region                      VARCHAR,
    quantity                    INTEGER,
    term                        VARCHAR,               -- 'P1Y' or 'P3Y'
    scope                       VARCHAR,               -- 'Shared' or 'Single'
    scope_id                    VARCHAR,               -- subscription or management group
    applied_scopes              VARCHAR,               -- JSON
    purchase_date               DATE,
    expiration_date             DATE,
    effective_cost_monthly_usd  DOUBLE,
    source_file                 VARCHAR NOT NULL,
    PRIMARY KEY (reservation_id)
);

-- Reservation utilization (daily, 90-day window)
CREATE TABLE IF NOT EXISTS azure_reservation_utilization (
    reservation_id              VARCHAR NOT NULL,
    usage_date                  DATE NOT NULL,
    utilization_percentage      DOUBLE NOT NULL,       -- 0-100
    source_file                 VARCHAR NOT NULL,
    PRIMARY KEY (reservation_id, usage_date)
);

-- Savings Plan inventory
CREATE TABLE IF NOT EXISTS azure_savings_plans (
    savings_plan_id             VARCHAR NOT NULL,
    display_name                VARCHAR,
    sku_name                    VARCHAR,               -- e.g. 'Compute_Savings_Plan'
    term                        VARCHAR,               -- 'P1Y' or 'P3Y'
    hourly_commitment_usd       DOUBLE,
    applied_scopes              VARCHAR,               -- JSON
    purchase_date               DATE,
    expiration_date             DATE,
    source_file                 VARCHAR NOT NULL,
    PRIMARY KEY (savings_plan_id)
);

-- Advisor cost recommendations (Microsoft's baseline)
CREATE TABLE IF NOT EXISTS azure_advisor_cost (
    recommendation_id           VARCHAR NOT NULL,
    resource_id                 VARCHAR,
    recommendation_type         VARCHAR,
    impact                      VARCHAR,               -- 'High'/'Medium'/'Low'
    annual_savings_usd          DOUBLE,
    short_description           VARCHAR,
    source_file                 VARCHAR NOT NULL,
    PRIMARY KEY (recommendation_id)
);

-- VM utilization metrics for top spenders
-- Keyed by resource_id + datetime; hourly granularity
CREATE TABLE IF NOT EXISTS azure_vm_utilization (
    resource_id                 VARCHAR NOT NULL,
    time_bucket                 TIMESTAMP NOT NULL,
    cpu_avg_pct                 DOUBLE,
    cpu_max_pct                 DOUBLE,
    memory_avg_pct              DOUBLE,
    memory_max_pct              DOUBLE,
    network_in_bytes            DOUBLE,
    network_out_bytes           DOUBLE,
    source_file                 VARCHAR NOT NULL,
    PRIMARY KEY (resource_id, time_bucket)
);
"""

SECURITY_SCHEMA = """
-- Defender for Cloud pricing inventory
CREATE TABLE IF NOT EXISTS defender_pricing (
    subscription_id             VARCHAR NOT NULL,
    plan_name                   VARCHAR NOT NULL,      -- 'VirtualMachines', 'SqlServers', etc.
    pricing_tier                VARCHAR NOT NULL,      -- 'Free', 'Standard' (P1), 'Premium' (P2)
    sub_plan                    VARCHAR,               -- for granular tiers
    resource_count              INTEGER,
    source_file                 VARCHAR NOT NULL,
    PRIMARY KEY (subscription_id, plan_name)
);

-- JIT VM access policies (tells us if P2 features are in use)
CREATE TABLE IF NOT EXISTS defender_jit_policies (
    policy_id                   VARCHAR NOT NULL,
    subscription_id             VARCHAR NOT NULL,
    policy_name                 VARCHAR,
    vm_count                    INTEGER,
    location                    VARCHAR,
    source_file                 VARCHAR NOT NULL,
    PRIMARY KEY (policy_id)
);

-- Sentinel / Log Analytics ingestion (90-day daily summary per workspace)
CREATE TABLE IF NOT EXISTS sentinel_usage (
    workspace_id                VARCHAR NOT NULL,
    usage_date                  DATE NOT NULL,
    data_type                   VARCHAR NOT NULL,      -- table name
    gb_ingested                 DOUBLE NOT NULL,
    is_billable                 BOOLEAN,
    source_file                 VARCHAR NOT NULL,
    PRIMARY KEY (workspace_id, usage_date, data_type)
);

-- Sentinel workspace commitment tier
CREATE TABLE IF NOT EXISTS sentinel_commitment (
    workspace_id                VARCHAR NOT NULL,
    workspace_name              VARCHAR,
    pricing_tier                VARCHAR NOT NULL,      -- 'PerGB2018', 'CapacityReservation', 'Free', ...
    capacity_reservation_level  INTEGER,               -- GB/day committed (null for PerGB)
    daily_cap_gb                DOUBLE,
    source_file                 VARCHAR NOT NULL,
    PRIMARY KEY (workspace_id)
);
"""

COMMERCIAL_SCHEMA = """
-- Software Assurance entitlement (from client VLSC/MCRA export)
CREATE TABLE IF NOT EXISTS sa_entitlement (
    license_family              VARCHAR NOT NULL,      -- 'Windows Server', 'SQL Server', ...
    edition                     VARCHAR,               -- 'Standard', 'Enterprise', ...
    core_count_entitled         INTEGER,
    sa_active                   BOOLEAN NOT NULL,
    expiration_date             DATE,
    agreement_number            VARCHAR,
    notes                       VARCHAR,
    source_file                 VARCHAR NOT NULL
);

-- SKU price overrides from client's EA price sheet
-- Optional - defaults ship with the analyzer
CREATE TABLE IF NOT EXISTS sku_price_overrides (
    sku_code                    VARCHAR NOT NULL,
    sku_family                  VARCHAR,
    unit_price_monthly_usd      DOUBLE NOT NULL,
    currency                    VARCHAR DEFAULT 'USD',
    source_file                 VARCHAR NOT NULL,
    PRIMARY KEY (sku_code)
);
"""

FINDINGS_SCHEMA = """
-- Unified findings table - what every recipe emits
-- This is the single table the report layer reads from
CREATE TABLE IF NOT EXISTS findings (
    finding_id                  VARCHAR NOT NULL,      -- recipe_id + entity_id hash
    recipe_id                   VARCHAR NOT NULL,      -- e.g. '3.1'
    recipe_name                 VARCHAR NOT NULL,
    category                    VARCHAR NOT NULL,      -- 'M365', 'Security', 'Commitments', 'Waste'
    entity_id                   VARCHAR NOT NULL,      -- resource_id or user_principal_name
    entity_name                 VARCHAR,
    entity_type                 VARCHAR NOT NULL,      -- 'user', 'vm', 'disk', etc.
    current_state               VARCHAR NOT NULL,      -- description of current config
    recommended_state           VARCHAR NOT NULL,      -- description of recommended config
    gross_annual_savings_usd    DOUBLE NOT NULL,       -- full savings if implemented
    capturable_factor           DOUBLE NOT NULL,       -- 0-1; realistic capture rate
    capturable_annual_savings_usd DOUBLE NOT NULL,     -- gross * factor
    confidence                  VARCHAR NOT NULL,      -- 'High', 'Medium', 'Low'
    days_to_capture             INTEGER,               -- estimated days to realize
    risk_level                  VARCHAR,               -- 'Low', 'Medium', 'High'
    suggested_owner             VARCHAR,               -- 'IT Operations', 'Finance', etc.
    dependencies                VARCHAR,               -- JSON array of prerequisite conditions
    evidence                    VARCHAR,               -- JSON blob with supporting data
    detected_at                 TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (finding_id)
);

-- Engagement metadata
CREATE TABLE IF NOT EXISTS engagement_metadata (
    key                         VARCHAR NOT NULL,
    value                       VARCHAR,
    PRIMARY KEY (key)
);
"""

ALL_SCHEMAS = [M365_SCHEMA, AZURE_SCHEMA, SECURITY_SCHEMA, COMMERCIAL_SCHEMA, FINDINGS_SCHEMA]


# ---------------------------------------------------------------------------
# Schema management
# ---------------------------------------------------------------------------

def initialize_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create all tables if they don't exist. Safe to call on an existing DB."""
    for ddl in ALL_SCHEMAS:
        conn.execute(ddl)
    conn.execute(
        """
        INSERT OR REPLACE INTO engagement_metadata (key, value)
        VALUES ('schema_version', ?)
        """,
        [SCHEMA_VERSION],
    )
    conn.commit()


def tables(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """Return a sorted list of table names in the database."""
    result = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name"
    ).fetchall()
    return [row[0] for row in result]


def table_counts(conn: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Return a dict mapping table name -> row count. Useful for ingest diagnostics."""
    counts = {}
    for table in tables(conn):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        counts[table] = count
    return counts
