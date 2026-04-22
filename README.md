# gt-finops-analyzer

**Grant Thornton · FinOps Quick-Wins Analyzer**

A local, file-based analyzer for Microsoft cost optimization engagements. Ingests a folder of client data, runs 14 deterministic optimization recipes, and produces a findings HTML report, evidence workbook, and populated findings deck.

Designed for the 30-day quick-wins engagement pattern described in the *FinOps Quick-Wins Playbook*. Library-first architecture — the same recipes can be hosted by the CLI for one-time engagements, or by ADF pipelines and the agentic AI orchestrator for continuous operation.

---

## Principles

- **Local execution.** No credentials to the client tenant. No cloud services required. Runs on a consultant laptop.
- **File-based ingest.** Client drops a folder of files into shared storage. Analyzer reads the folder. That's it.
- **Deterministic recipes.** Every recommendation is reproducible from the source data — no LLM in the analysis path.
- **Ephemeral.** Nothing persists beyond the engagement. DuckDB file is engagement-scoped.
- **Library first, CLI second.** The recipes are a library. The CLI is one of several possible hosts.

## Quick start

```bash
# Install in editable mode
pip install -e ".[dev]"

# Ingest client data to local DuckDB
gt-finops ingest \
  --source-dir ./client-data \
  --output ./engagement.duckdb

# Run all 14 recipes
gt-finops analyze \
  --db ./engagement.duckdb \
  --recipes all

# Produce findings artifacts
gt-finops report \
  --db ./engagement.duckdb \
  --client-name "Acme Corp" \
  --output ./findings/
```

## Engagement flow

1. **Pre-engagement** — send client the data-pull checklist (separate GT artifact). Client pulls data, drops it in shared OneDrive/SharePoint folder.
2. **Day 1** — `gt-finops ingest`. Missing or malformed files surface immediately.
3. **Days 1–3** — `gt-finops analyze`. Consultant reviews HTML report, flags edge cases, reruns with exclusions.
4. **Days 3–10** — consultant works through high-value findings, has BU conversations.
5. **Days 10–15** — commercial conversation with Microsoft rep, findings deck finalization.
6. **Day 15** — present findings.

This compresses the 30-day playbook to 15 days without reducing quality.

## Recipes

See `gt_finops/recipes/` for all 14. Each is a self-contained class implementing `Recipe` with a single `run(db)` method returning findings.

| ID  | Recipe                               | Category          |
| --- | ------------------------------------ | ----------------- |
| 3.1 | E5 → E3 downgrade                    | M365 Licensing    |
| 3.2 | E3 → F3 for frontline workers        | M365 Licensing    |
| 3.3 | Disabled-but-licensed accounts       | M365 Licensing    |
| 3.4 | Copilot reclaim                      | M365 Licensing    |
| 3.5 | Teams Phone without PSTN             | M365 Licensing    |
| 4.1 | Defender for Servers P2 → P1         | Microsoft Security|
| 4.2 | Sentinel commitment tier             | Microsoft Security|
| 5.1 | Azure Hybrid Benefit audit           | Azure Commitments |
| 5.2 | Reservation utilization              | Azure Commitments |
| 5.3 | Savings Plan coverage                | Azure Commitments |
| 5.4 | Dev/Test pricing eligibility         | Azure Commitments |
| 6.1 | Orphan resources                     | Azure Waste       |
| 6.2 | Non-prod auto-shutdown               | Azure Waste       |
| 6.3 | Storage tiering                      | Azure Waste       |

## Data inputs

Expected folder layout in `--source-dir`:

```
client-data/
├── m365/
│   ├── subscribedskus.json
│   ├── users.json
│   ├── office365_active_users.csv
│   ├── teams_user_activity.csv
│   ├── sharepoint_site_usage.csv
│   ├── onedrive_account_detail.csv
│   ├── powerbi_activity.csv
│   ├── yammer_activity.csv
│   ├── copilot_usage.csv
│   ├── office365_activations.csv
│   └── call_records.csv
├── azure/
│   ├── focus_cost_export/           # Parquet or CSV, 13 months
│   ├── resource_inventory.csv
│   ├── reservations.json
│   ├── reservation_utilization.json
│   ├── savings_plans.json
│   ├── advisor_cost.csv
│   └── vm_utilization.csv
├── security/
│   ├── defender_pricing.json
│   ├── jit_policies.json
│   ├── sentinel_usage.csv
│   └── sentinel_commitment.json
└── commercial/
    ├── sa_entitlement.xlsx
    └── price_sheet.xlsx  (optional)
```

## Security model

- All client data stays on the consultant laptop
- DuckDB file is deleted at engagement close
- Findings artifacts (HTML, XLSX, PPTX) move to engagement-scoped GT SharePoint
- Auto-purge at 90 days post-delivery

## License

Proprietary. Internal Grant Thornton consulting use only.
