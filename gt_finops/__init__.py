"""
gt-finops — Grant Thornton FinOps Quick-Wins Analyzer.

Local, file-based recipe engine for Microsoft cost optimization engagements.
See README.md for usage and the accompanying playbook for recipe details.
"""

__version__ = "0.1.0"
__author__ = "Grant Thornton"

from gt_finops.schema import initialize_schema, table_counts
from gt_finops.recipes.base import Finding, Recipe, save_findings

__all__ = [
    "__version__",
    "initialize_schema",
    "table_counts",
    "Finding",
    "Recipe",
    "save_findings",
]
