# OwnerLens

OwnerLens turns raw SEC filings into trustworthy, owner-oriented financial intelligence. It retrieves SEC
Company Facts, normalizes them into canonical facts with full provenance, derives deterministic
owner-economics and capital-efficiency metrics, and produces an Economic Value Lens — all as reproducible,
testable Python.

See [docs/PRD.md](docs/PRD.md) for product context and [ROADMAP.md](ROADMAP.md) for the slice history.

## Architecture

OwnerLens separates data providers from its deterministic financial logic with a canonical boundary:

```text
providers (SEC today)
   ↓  provider adapter (owner_lens.sec_adapter)
canonical facts (owner_lens.canonical.CanonicalFinancialHistory)
   ↓
OwnerLens deterministic logic (owner economics, capital efficiency, Economic Value Lens, coverage)
```

Provider-specific concepts, such as SEC XBRL tags, stay above the boundary and survive below it only as
provenance on each canonical fact. See
[Feature 5: Provider Boundary](docs/feature_docs/feature_05_canonical_provider_boundary.md) for the
model, the boundary rule, and how it is enforced.

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
