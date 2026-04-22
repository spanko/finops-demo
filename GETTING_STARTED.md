# Getting started with gt-finops-analyzer

Short guide for GT engineers picking up this repository. For the full architecture and recipe catalog, see `README.md`.

## What this is

A local Python tool that runs the 14 quick-wins recipes from the *FinOps Quick-Wins Playbook* against a folder of client data. Produces three deliverables:

- **Findings HTML report** — browseable by consultant
- **Evidence Excel workbook** — per-recipe tabs, one row per finding (what you hand the client)
- **Findings PowerPoint** — auto-populated deck matching the Section 8 template

No client-tenant credentials. No cloud services. Runs on a laptop.

## Setup

```bash
# From the repo root
pip install -e ".[dev]"

# Verify
gt-finops --help
gt-finops list-recipes
```

Python 3.10+. The tool is tested on 3.12.

## Try it against synthetic data

The repo ships with a sample-data generator that produces a realistic fake client dataset. Useful for onboarding, demos, and smoke-testing after changes.

```bash
# 1. Generate synthetic client data
python scripts/generate_sample_data.py
# → writes ./sample_data/ with ~20 files across m365/, azure/, security/, commercial/

# 2. Ingest into a local DuckDB engagement database
gt-finops ingest \
  --source-dir sample_data \
  --output engagement.duckdb

# 3. Run all 14 recipes
gt-finops analyze \
  --db engagement.duckdb \
  --recipes all

# 4. Generate findings artifacts
gt-finops report \
  --db engagement.duckdb \
  --client-name "Acme Corp" \
  --output findings/
```

On the synthetic data you should see ~415 findings totaling ~$179K capturable across 10 of the 14 recipes. (The other 4 recipes need specific data patterns the synthetic set doesn't fully cover — they fire normally on real client data.)

## For a real engagement

1. Get the client to drop their data pull into a shared folder matching the layout in `README.md`. The *FinOps Data Pull Checklist* (separate GT artifact) tells them what to produce and how.
2. Copy or mount the folder locally as `client-data/`.
3. Run the three CLI commands above, pointing at `client-data/` and `client-findings/`.
4. Review the HTML report to flag edge cases, then re-run specific recipes if you need to exclude resources.
5. Hand off the Excel workbook and PowerPoint to the client. Edit slides 2, 9, and 10 of the deck for client-specific narrative.

## Repository layout

```
gt-finops/
├── pyproject.toml
├── README.md                  # architecture, recipes, data layout
├── GETTING_STARTED.md         # this file
├── gt_finops/                 # library package
│   ├── cli.py                 # `gt-finops` entry point
│   ├── schema.py              # DuckDB table definitions
│   ├── pricing.py             # Microsoft SKU prices and discount rates
│   ├── aggregate.py           # findings rollup + summary helpers
│   ├── ingest/                # client data → DuckDB
│   │   ├── m365.py
│   │   ├── azure.py
│   │   ├── security.py
│   │   ├── commercial.py
│   │   └── runner.py          # orchestrator (walks folder layout)
│   ├── recipes/               # 14 optimization recipes
│   │   ├── base.py            # Recipe base class, Finding dataclass
│   │   ├── m365_e5_to_e3.py   # ← reference implementation (fully commented)
│   │   └── … 13 others
│   ├── report/
│   │   ├── html_report.py     # Jinja template → HTML
│   │   ├── excel_workbook.py  # openpyxl workbook builder
│   │   └── pptx_findings.py   # python-pptx deck builder
│   └── templates/
│       └── report.html.j2     # GT-branded HTML template
├── scripts/
│   └── generate_sample_data.py  # synthetic dataset for testing
└── sample_data/               # gets created by the generator
```

## Adding a new recipe

1. Copy `gt_finops/recipes/m365_e5_to_e3.py` as a starting point — it's the most thoroughly commented recipe.
2. Subclass `Recipe` with a unique `id`, `name`, `category`, and list of `sources` (conformed table names).
3. Implement `run(conn)` — return a list of `Finding` objects. Use `self.make_finding(...)` to avoid repeating recipe-level fields.
4. Register the class in `gt_finops/recipes/__init__.py` by adding it to `ALL_RECIPES`.

That's it. The CLI auto-discovers it, the aggregator picks up its findings, and all three reports include it.

## Adding a new data source

1. Define the conformed table in `gt_finops/schema.py` (add DDL to the appropriate schema block).
2. Write an ingest function in the right `ingest/*.py` module — takes a DuckDB connection and a Path, returns row count.
3. Wire the file into `ingest/runner.py`: add to `EXPECTED_LAYOUT` and to the dispatch logic.
4. Use the new table in recipes that need it — add it to the recipe's `sources` list.

## Field-name defensiveness

Real client data comes in different shapes. The tool handles:

- camelCase (`resourceId`, `usageDate`) — Microsoft Graph and Azure SDK outputs
- PascalCase (`ResourceId`, `UsageDate`) — Kusto query outputs
- snake_case (`resource_id`, `usage_date`) — analyst-normalized data
- Title-case with spaces (`User Principal Name`) — admin center CSV exports

The `_find_column()` helper in `gt_finops/ingest/m365.py` normalizes across all four. When adding a new ingest module, put your column name variants in the `rename` dict at the top of the ingest function so other format variants are handled transparently.

## Troubleshooting

**"Recipe X skipped"** — check `preflight(conn)` output. Usually means a required table is missing (as opposed to empty). Empty tables are allowed; missing tables block.

**"Parser error: INTERVAL ?"** — DuckDB doesn't parameter-bind INTERVAL literals. Inline the integer with an f-string (see `azure_ri_utilization.py`).

**Ingest returns 0 rows** — check field-name alignment. Run the generator's output against the ingester's rename dict. Most zero-row ingests are case/punctuation mismatches.

**PPTX category colors wrong** — the GT palette lives in `CATEGORY_COLORS` at the top of `report/pptx_findings.py`. Keep HTML `report.html.j2` `.pill.*` rules in sync.

## What the tool deliberately doesn't do

- Connect to the client tenant via API. Findings come from file ingest only.
- Architecture optimization (VM → Container Apps, etc.). That's the second view, needs VM Insights + Dependency Agent data, different engagement.
- Execute optimizations. Strictly read-only analysis.
- Persist data across engagements. Every engagement is a fresh DuckDB.

These are intentional — they keep the tool within the trust posture of the quick-wins engagement model.
