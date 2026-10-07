# OwnerLens

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
```

The workbench is a local Streamlit interface over the persisted store, with five
views: **Overview** (coverage, the opportunity funnel, the research queue),
**Screener** (the filterable screening table), **Company** (owner economics,
capital efficiency, capital allocation, Economic Value Lens, screening
dimensions), **Compare** (2–5 companies side by side), and **Data Quality**
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

## Local persistence

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
