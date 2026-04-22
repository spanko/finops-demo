"""
Base class and data model for optimization recipes.

Each of the 14 playbook recipes is implemented as a subclass of Recipe.
Recipes are pure functions of the DuckDB state - they read from conformed
tables, compute findings, and return a list of Finding objects.

Key design choices:
- Recipes are classes, not functions, so they can carry metadata and state
- Finding is a dataclass with a fixed shape - every recipe emits the same
  type regardless of category
- run() returns findings; save_findings() persists them to the findings table
- Recipes never modify client data tables; they only read
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

import duckdb


# ---------------------------------------------------------------------------
# Finding data model
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """A single optimization finding - one row in the findings table."""

    recipe_id: str
    recipe_name: str
    category: str                         # 'M365', 'Security', 'Commitments', 'Waste'
    entity_id: str                        # resource_id or UPN
    entity_name: str
    entity_type: str                      # 'user', 'vm', 'disk', etc.
    current_state: str
    recommended_state: str
    gross_annual_savings_usd: float
    capturable_factor: float              # 0-1
    confidence: str                       # 'High', 'Medium', 'Low'
    days_to_capture: int
    risk_level: str                       # 'Low', 'Medium', 'High'
    suggested_owner: str
    dependencies: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    # Derived
    finding_id: str = field(init=False)
    capturable_annual_savings_usd: float = field(init=False)

    def __post_init__(self) -> None:
        # Stable finding_id for dedup and tracking
        material = f"{self.recipe_id}|{self.entity_id}".encode()
        self.finding_id = hashlib.sha256(material).hexdigest()[:16]
        self.capturable_annual_savings_usd = round(
            self.gross_annual_savings_usd * self.capturable_factor, 2
        )

    def to_row(self) -> dict[str, Any]:
        """Convert to a dict suitable for DuckDB insertion."""
        d = asdict(self)
        d["dependencies"] = json.dumps(self.dependencies)
        d["evidence"] = json.dumps(self.evidence, default=str)
        d["detected_at"] = datetime.utcnow()
        return d


# ---------------------------------------------------------------------------
# Recipe base class
# ---------------------------------------------------------------------------


class Recipe(ABC):
    """
    Abstract base class for optimization recipes.

    Subclasses must define:
    - id:       playbook recipe ID (e.g. '3.1')
    - name:     human-readable name
    - category: 'M365' | 'Security' | 'Commitments' | 'Waste'
    - sources:  list of required source table names
    - run():    method that returns list[Finding]

    Subclasses may override:
    - preflight(): sanity checks before run (e.g. required tables populated)
    """

    id: str = ""
    name: str = ""
    category: str = ""
    sources: list[str] = []

    def __init__(self) -> None:
        if not self.id or not self.name or not self.category:
            raise ValueError(
                f"{self.__class__.__name__} must define id, name, category as class attributes"
            )

    # -------------------------------------------------------------
    # Subclass hooks
    # -------------------------------------------------------------

    @abstractmethod
    def run(self, conn: duckdb.DuckDBPyConnection) -> list[Finding]:
        """Execute the recipe against the DuckDB connection and return findings."""
        ...

    def preflight(self, conn: duckdb.DuckDBPyConnection) -> list[str]:
        """
        Check prerequisites. Return a list of problems (empty list = OK to run).
        Default implementation verifies required source tables are *present*.
        Empty tables are allowed — recipes must handle them gracefully (many
        recipes, like Defender P2→P1, surface findings precisely *because*
        certain tables are empty, e.g. when no JIT policies are configured).
        """
        problems = []
        for src in self.sources:
            try:
                conn.execute(f"SELECT COUNT(*) FROM {src}").fetchone()
            except duckdb.Error as e:
                problems.append(f"source table '{src}' is missing ({e})")
        return problems

    # -------------------------------------------------------------
    # Convenience builders
    # -------------------------------------------------------------

    def make_finding(self, **kwargs: Any) -> Finding:
        """
        Convenience constructor that fills in recipe-level fields automatically.
        Subclasses pass only the per-finding fields.
        """
        kwargs.setdefault("recipe_id", self.id)
        kwargs.setdefault("recipe_name", self.name)
        kwargs.setdefault("category", self.category)
        return Finding(**kwargs)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def save_findings(conn: duckdb.DuckDBPyConnection, findings: list[Finding]) -> int:
    """
    Insert findings into the findings table. Returns count inserted.
    Uses INSERT OR REPLACE so rerunning a recipe updates existing findings
    rather than duplicating them (finding_id is stable per entity+recipe).
    """
    if not findings:
        return 0

    # Prepare data as list of tuples in column order
    columns = [
        "finding_id", "recipe_id", "recipe_name", "category",
        "entity_id", "entity_name", "entity_type",
        "current_state", "recommended_state",
        "gross_annual_savings_usd", "capturable_factor",
        "capturable_annual_savings_usd", "confidence",
        "days_to_capture", "risk_level", "suggested_owner",
        "dependencies", "evidence", "detected_at",
    ]
    rows = [tuple(f.to_row()[c] for c in columns) for f in findings]

    # Delete existing findings for this recipe to ensure clean re-run
    recipe_id = findings[0].recipe_id
    conn.execute("DELETE FROM findings WHERE recipe_id = ?", [recipe_id])

    placeholders = ", ".join(["?"] * len(columns))
    col_list = ", ".join(columns)
    conn.executemany(
        f"INSERT INTO findings ({col_list}) VALUES ({placeholders})",
        rows,
    )
    conn.commit()
    return len(findings)


def clear_findings(conn: duckdb.DuckDBPyConnection, recipe_id: str | None = None) -> int:
    """Clear findings - all or by recipe. Returns rows deleted."""
    if recipe_id:
        result = conn.execute(
            "DELETE FROM findings WHERE recipe_id = ?", [recipe_id]
        )
    else:
        result = conn.execute("DELETE FROM findings")
    conn.commit()
    return result.rowcount if hasattr(result, "rowcount") else 0
