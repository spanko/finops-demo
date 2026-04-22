"""
Ingest layer — reads client data files and writes to conformed DuckDB tables.

Each submodule handles one category of data. The orchestrator in `runner.py`
walks an expected folder layout and dispatches files to the right ingester.
"""

from gt_finops.ingest.runner import ingest_folder, IngestReport

__all__ = ["ingest_folder", "IngestReport"]
