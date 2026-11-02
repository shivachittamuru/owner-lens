---
title: OwnerLens
description: "Local owner-oriented financial evidence, economics, screening, and research."
---

## OwnerLens

OwnerLens turns raw SEC filings into trustworthy, owner-oriented financial intelligence. It retrieves SEC
Company Facts, normalizes them into canonical facts with full provenance, derives deterministic
owner-economics and capital-efficiency metrics, produces an Economic Value Lens, screens a company
universe for research priority, and presents all of it in a local research workbench — all as
reproducible, testable Python.

See [docs/PRD.md](docs/PRD.md) for product context and [ROADMAP.md](ROADMAP.md) for the slice history.

## Architecture

OwnerLens separates data providers from its deterministic financial logic with a canonical boundary:

```text
SEC Company Facts ─→ owner_lens.sec_adapter ─┐
                                            ├─→ canonical facts (CanonicalFinancialHistory)
FMP statements    ─→ owner_lens.fmp_adapter ─┘        ↓
                              OwnerLens deterministic logic (owner economics, capital
                              efficiency, Economic Value Lens, coverage, screening)
```

SEC is the default and the regression/audit provider. FMP is an optional second provider that needs
`OWNER_LENS_FMP_API_KEY`. Provider-specific concepts, such as SEC XBRL tags or FMP field names, stay
above the boundary and survive below it only as provenance on each canonical fact. A reconciliation layer
(`owner_lens.reconciliation`, run with `uv run python scripts/reconcile_providers.py`) compares SEC-backed
and FMP-backed histories fact by fact; its current evidence keeps SEC as the primary provider.

A coverage survey (`uv run python scripts/survey_universe.py`) runs the SEC-first pipeline across a
24-company universe and diagnoses every blocker. SEC concept selection is recency-aware, mechanical
restatements (precision re-roundings and stock splits) resolve deterministically, current debt is
composed from its reported components, and alternative SEC concepts are adopted only when they are
economically equivalent. Companies that cannot produce a metric stay explicitly unsupported rather
than being approximated. See
[Feature 6: Universe Coverage](docs/feature_docs/feature_06_universe_coverage.md). See
[Feature 5: Provider Boundary](docs/feature_docs/feature_05_canonical_provider_boundary.md) for the
model, the boundary rule, and how it is enforced.

## Opportunity screening

Above the metrics sits the first investing-decision layer: a deterministic screen that narrows a
universe to the companies worth expensive underwriting. It bands six interpretable dimensions
(business quality, capital efficiency, per-share compounding, balance-sheet strength, capital
allocation, economic momentum), applies survival gates, and assigns a research-priority bucket with
structured reasons.

```powershell
uv run owner-lens screen                      # every persisted company, no network call
uv run owner-lens screen ADBE MSFT --detail   # full per-company justification
uv run owner-lens screen --provider fmp       # current persisted S&P 500 annual histories
uv run python scripts/screen_universe.py      # the 24-company universe
```

Three properties are load bearing. Margin *levels* are never scored across companies, so a 3%-margin
retailer is not penalized for its business model. ROIC level and ROIC trend are separated, so a
company whose invested capital grew as its cash pile shrank is not mistaken for a broken one. A
dimension OwnerLens cannot see is `NOT_EVALUABLE` — excluded from the score and capped by a coverage
ceiling — so missing negative evidence never becomes an advantage.

A bucket communicates **research priority, not investment advice**. The layer contains no price,
multiple, intrinsic value, expected return, or LLM call. See
[Feature 7: Opportunity Screening](docs/feature_docs/feature_07_opportunity_screening.md).

## Requirements

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/) for environment and dependency management

## Setup

```powershell
uv sync
Copy-Item .env.example .env    # then edit .env with your SEC user agent
```

Run the checks:

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## Using OwnerLens

One command opens everything:

```powershell
uv run owner-lens workbench
uv run owner-lens workbench --provider fmp   # persisted S&P 500 evidence and screening
```

The workbench is a local Streamlit interface over the persisted store, with ten
views: **Overview** (coverage, the opportunity funnel, the research queue),
**Screener** (the filterable screening table), **Company** (owner economics,
capital efficiency, capital allocation, Economic Value Lens, screening
dimensions), **Compare** (2–5 companies side by side), **Opportunity Comparison**
(2–5 exact completed underwriting versions), **Decisions** (append-only investor
judgments and history), **Shadow Portfolio** (frozen independent counterfactual
starts), **Portfolio Context / Position Sizing** (explicit downside budgets and
immutable manual holdings context), **What Changed?** (manual evidence events and
approved re-underwriting triggers), and **Data Quality**
(exactly which metrics are missing and why).

It reads persisted data only — opening or navigating it never calls SEC or FMP.
To add a company, or refresh one, use the CLI and then reload in the sidebar:

```powershell
uv run owner-lens ingest ADBE                        # fetch and persist
uv run owner-lens workbench --db data/universe_6a.db # browse another store
```

See [Feature 7D: Workbench](docs/feature_docs/feature_07d_workbench.md). The
other commands remain available for scripting:

```powershell
uv run owner-lens show ADBE         # persisted summary, coverage, screening
uv run owner-lens screen --detail   # ranked screen with full justifications
```

For the persisted S&P 500 universe, explicitly select FMP in the CLI or the
workbench sidebar. SEC remains the default and authoritative filed-fact source.
FMP annual histories remain isolated from SEC. Quarterly statements, EOD prices,
and Market Expectations are separate Company-page evidence, not annual screening
inputs. See [Feature 8A3](docs/feature_docs/feature_08a3_universe_workbench.md)
for the offline workflow and coverage inspection.

## Local persistence

Manually capture immutable, semantically typed underwriting snapshots with
`uv run owner-lens underwriting create ADBE --file .\data\underwriting\ADBE.json`.
See [Feature 8B](docs/feature_docs/feature_08b_immutable_underwriting.md) for the
input template, version history, and offline validation workflow.

Run deterministic five-year scenario valuation from an exact underwriting
version with `uv run owner-lens valuation run ADBE --version 1`. See
[Feature 8C](docs/feature_docs/feature_08c_scenario_valuation.md) for the
Bear/Base/Bull contract, equations, and illustrative manual input.

Compare captured consensus with BASE assumptions offline using
`uv run owner-lens variant show ADBE --version 1`. See
[Feature 8D](docs/feature_docs/feature_08d_variant_perception.md) for matched
revenue horizons, manual disagreement rationales, and deterministic sensitivity.

Complete the offline loop with
`uv run owner-lens underwriting summary ADBE --version 1 --required-return 0.12`
and `uv run owner-lens challenger run ADBE --version 1`. See
[Feature 8E](docs/feature_docs/feature_08e_underwriting_loop.md) for manually
approved probabilities, transparent hurdle bands and the advisory rules-only
challenger. Neither command is a buy/sell recommendation.

Compare completed immutable underwriting versions without an aggregate score:

```powershell
uv run owner-lens compare-underwriting ADBE:7 MSFT:3 GOOGL:2
uv run owner-lens compare-underwriting ADBE:7 MSFT:3 GOOGL:2 --json
```

Use exact versions present in your store. **Opportunity Comparison** in the
Workbench provides the same read-only comparison with explicit version selection.
Research attention is separate from conditional capital economics; missing
dimensions remain missing. Feature 7 context is reused only when frozen in the
selected snapshot, never recomputed during comparison. See
[Feature 9A](docs/feature_docs/feature_09a_opportunity_comparison.md) for flags,
conservative dominance, reproducibility, examples and manual PowerShell checks.

Record an explicit judgment against an exact completed underwriting version:

```powershell
uv run owner-lens decision create ADBE --version 7 --file .\data\decisions\ADBE.json --json
uv run owner-lens decision show ADBE
uv run owner-lens decision history ADBE --json
uv run owner-lens shadow show --json
```

Use the reviewed [decision input example](docs/examples/adbe_decision.sample.json)
with exact versions present in your store. **Company > Underwriting** and
**Opportunity Comparison** can open the same explicit-save decision workflow.
Changed minds create new records; considered alternatives and optional $100
shadow starts retain their decision-time state. Outcomes are not decision
quality. No trades, sizing, weights or returns are inferred. See
[Feature 9B](docs/feature_docs/feature_09b_decision_shadow.md) for schemas,
immutability, benchmark placeholders and manual validation commands.

Evaluate cash-funded position-size bounds over explicit, immutable manual holdings:

```powershell
uv run owner-lens portfolio snapshot create --file .\data\portfolio\portfolio.json --json
uv run owner-lens position-size ADBE --version 7 --portfolio <snapshot-id> --policy .\data\portfolio\policy.json --json
```

Review the synthetic [portfolio](docs/examples/portfolio_context.sample.json) and
[policy](docs/examples/sizing_policy.sample.json) examples before supplying your
own inputs. There are no hidden policy defaults, inferred shadow holdings,
automatic decisions or trades. **Portfolio Context / Position Sizing** provides
the same preview and explicit-save workflow. See
[Feature 9C](docs/feature_docs/feature_09c_portfolio_sizing.md) for formulas,
quality caps, missing-data constraints, schemas and manual PowerShell validation.

Record new information without rewriting the underwriting that preceded it:

```powershell
uv run owner-lens change create ADBE --version 7 --file .\data\changes\adbe-q4.json --json
uv run owner-lens change assess <event-id>
uv run owner-lens change approve <event-id> --classification THESIS_UPDATE --rationale "Revisit growth persistence."
uv run owner-lens change history ADBE
uv run owner-lens change summary ADBE
```

Use the [synthetic event example](docs/examples/adbe_change.sample.json) only after
editing its dates, source, condition ID and affected-belief pointers to match your
exact snapshot. **What Changed?** reviews deterministic candidates and requires
explicit investor approval. Approved updates/breaks offer **Start from latest
underwriting**, opening a draft without saving or changing a decision/sizing
record. See [Feature 9D](docs/feature_docs/feature_09d_what_changed.md) for literal
metric/unit matching, approval authority, immutable history and manual commands.

For new underwriting, use the consolidated
[canonical contract](docs/feature_docs/feature_08f1_underwriting_contract.md) and
[version-2 authoring example](docs/examples/adbe_consolidated_underwriting.sample.json).
OwnerLens supplies FACT/EXPECTATION; you author ASSUMPTION/JUDGMENT.
Existing immutable versions remain unchanged.

The Company page now shows saved underwriting and offers **Copy Research Context**
with Markdown/JSON downloads. See
[Feature 8F2](docs/feature_docs/feature_08f2_company_underwriting.md) for the
read-only workflow and manual inspection checklist.

Use **Company → Underwriting → Create New Underwriting** to author assumptions
and judgments without JSON editing. Explicit presets, live probability totals
and a required review precede immutable save; old versions remain unchanged.
See [Feature 8F4](docs/feature_docs/feature_08f4_underwriting_authoring.md).

OwnerLens persists its outputs to a **local-first** store (Slice 4A). Two backends implement the storage
boundary and are composed from configuration:

- `SqliteStore` — a local SQLite database holding companies, source snapshots, canonical reported facts,
  derived metrics, Feature 2 analysis outputs, and coverage states.
- `FilesystemRawSnapshotStore` — immutable raw SEC Company Facts payloads on the local filesystem, addressed
  by content hash.

### Where runtime data lives

Everything is written under `data/`, which is **local runtime state** and is gitignored (only `.gitkeep`
scaffolding is committed — the SQLite database and SEC payloads are never committed):

```text
data/
├── ownerlens.db                         # SQLite database
└── raw/
    └── sec/
        └── company_facts/
            └── <CIK>/
                └── <content-hash>.json  # immutable raw SEC payload
```

Raw snapshots keep the Slice 4A identity `<CIK>/<content-hash>.json` — the content hash is the identity and
the CIK (not the mutable ticker) anchors the path.

### Configuration

Configuration comes from environment variables (a local `.env` is loaded for convenience; see
[.env.example](.env.example)):

| Variable | Default | Purpose |
|----------|---------|---------|
| `OWNER_LENS_SEC_USER_AGENT` | — | SEC User-Agent (app + contact) for live retrieval |
| `OWNER_LENS_DB_PATH` | `data/ownerlens.db` | SQLite database path |
| `OWNER_LENS_RAW_DATA_PATH` | `data/raw/sec/company_facts` | Raw SEC payload root |

Compose the local store from settings:

```python
from owner_lens import load_settings, build_local_store

store = build_local_store(load_settings())
store.initialize()
```

### Azure persistence

Cloud persistence (Azure Blob + PostgreSQL) is **intentionally deferred**. The persistence boundary
(`OwnerLensStore` / `RawSnapshotStore`) is designed so a cloud backend can be added later without changing
the financial layers; that work lives on a separate branch and is not part of the local-first `main`.
