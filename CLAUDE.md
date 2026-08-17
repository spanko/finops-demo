# finops-demo (gt-finops)

A local, file-based analyzer for Microsoft cost-optimization engagements. Point it at a folder of
client data; it runs 14 deterministic optimization recipes and produces a report. Python package
`gt-finops`, installed from `pyproject.toml`, with a `gt-finops` console script.

**Local and file-based on purpose** — client cost data never leaves the machine and no cloud
service is called. Keep it that way: an "upload to X" convenience would change what this tool is.

## Commands

| Task | Command |
|---|---|
| install (editable) | `pip install -e .` |
| run the analyzer | `gt-finops` |
| test | `pytest` |

The interpreter is **`python`, not `python3`**.

## Layout

| Path | What it is |
|---|---|
| `gt_finops/` | the package — the 14 recipes and the report writer |
| `tests/`, `tests/fixtures/` | fixture-driven tests; recipes are pure over their inputs |
| `sample_data/` | a safe input folder to run against |
| `notebooks/` | exploration only — never the source of truth for a recipe |
| `scripts/` | helper entry points |
| `GETTING_STARTED.md` | the engagement walkthrough |

## What makes this repo unusual

The recipes are **deterministic** — same input folder, same report. That is the product promise
for an engagement deliverable, so a recipe must not depend on wall-clock time, network state, or
dict ordering. If a recipe needs "now", it takes it as a parameter.

Numbers in a report are estimates from list prices, never invoice-grade. Say so wherever a figure
reaches a client-facing surface.

## Shared conventions

<!-- Unified memory (~/claude-memory). Global standards + rules load automatically via ~/.claude/. -->
@~/claude-memory/shared-context/testing-strategy.md

## Gotchas

- Client data in `sample_data/` or an engagement folder is **not** committed — check before adding
  anything under a data directory.
- FOCUS is the cost fact; usage is a separate fact. Don't write estimated allocations back into a
  conformant cost dataset.
