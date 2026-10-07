# Feature 7D — Local Research Workbench

## Purpose

OwnerLens's capabilities had accumulated across a CLI, four scripts, sixteen
notebooks, a SQLite store, and a screening report. Using the system meant
remembering which one produced what. Feature 7D adds a single local interface
that becomes the one place to inspect, trust, compare, and act on everything
OwnerLens already knows.

It is a **thin UI over the deterministic engine**. No financial logic moved into
it. Every band, bucket, classification, and coverage state the workbench shows
is read from Features 1, 2, 6, and 7, so the UI can never disagree with the CLI
or the tests.

**Status: closed.** Five pages, one launch command, 62 tests, no network call on
open or navigation.

## Architecture

```text
SEC Company Facts (persisted raw snapshots)
        ↓
Canonical OwnerLens engine
        ↓
Owner economics · Capital efficiency · Economic Value · Coverage · Screening
        ↓
owner_lens.workbench.data        ← all workbench logic, no Streamlit, testable
        ↓
owner_lens.workbench.cache       ← the only place caching is applied
        ↓
owner_lens.workbench.views.*     ← rendering only
        ↓
owner_lens.workbench.app         ← navigation and orchestration
```

```text
src/owner_lens/workbench/
    __init__.py      re-exports the data layer; imports no Streamlit
    data.py          every model and loader; the whole of the logic
    cache.py         Streamlit caching, keyed on snapshot content hashes
    app.py           page navigation, sidebar, session state
    views/
        _common.py       shared rendering helpers
        overview.py      universe summary, funnel, research queue
        screener.py      filterable screening table and per-company detail
        company.py       one company's full research picture
        compare.py       side-by-side table for 2-5 companies
        data_quality.py  coverage, blockers, and technical provenance
```

The split is deliberate: `data.py` imports no Streamlit, so the entire behaviour
of the workbench is unit-testable without a browser, and a script or notebook
can use the same loaders. A test asserts that importing `data.py` with Streamlit
blocked still succeeds.

## How to launch

```powershell
uv run owner-lens workbench
```

That is the only command needed. It opens the store configured by
`OWNER_LENS_DB_PATH` (default `data/ownerlens.db`).

To browse the full 24-company survey universe:

```powershell
uv run owner-lens workbench --db data/universe_6a.db
```

Other options: `--port` (default 8501) and `--no-browser`.

Streamlit lives in the `workbench` dependency group, which `uv sync` installs by
default, so it never becomes a runtime dependency of the `owner_lens` package.
If it is missing, the command says exactly how to fix it and exits 2.

## Pages

### 1. Overview

The landing page. Compact metric cards for companies tracked and the
`FULL` / `PARTIAL` / `FAILED` coverage split, then one card per screening
bucket, then the setup-type breakdown.

The **opportunity funnel** shows the narrowing from tracked to screenable to
worth deeper underwriting. Every count is derived from the active store on each
load; nothing is hard-coded. Against the 24-company universe it currently reads
24 → 17 → 7.

The **research queue** lists the `HIGH_PRIORITY` and `WORTH_UNDERWRITING`
companies in Feature 7 ranking order with their setup type, score, coverage,
strongest reason, and main limitation, and offers one click through to the
Company view.

Companies that are tracked but have no readable raw snapshot get their own
section rather than being quietly dropped.

### 2. Screener

The full screening table, filterable by priority bucket, setup type, coverage
class, limiting factor, and the band of any chosen dimension; sortable by the
Feature 7 ranking (the default), by score, or by ticker.

Selecting a company exposes the three Feature 7 reason categories unchanged —
*Why it surfaced*, *What holds it back*, *What we cannot see* — plus an
expandable panel with each dimension's evidence lines.

### 3. Company

Header: coverage, research priority, setup type, latest fiscal year, and how
many of the six dimensions were evaluable, with the snapshot hash and fetch time
beneath.

Three tabs:

* **Fundamentals** — owner economics (revenue, operating income, operating
  margin, net income, operating cash flow, CapEx, FCF, FCF margin, diluted
  shares, FCF/share), capital efficiency (ROIC, ROA, ROE, invested capital,
  total debt, net cash/debt), capital allocation (repurchases, SBC, dividends,
  the ratios to FCF, retained FCF, share-count change, buyback effectiveness,
  classification), and the Economic Value Lens (annual classifications, both
  compounding windows, the company summary with its positive/watch/negative
  drivers).
* **Screening** — the six dimensions with text labels and their evidence.
* **Future: Valuation · Edge** — a deliberately empty tab naming what comes next
  and why it is not here.

Where a layer is unavailable, the Feature 6 coverage reason appears in place of
an empty chart. ServiceNow, for example, shows the exact concept list that was
tried for current debt instead of a blank capital-efficiency table.

### 4. Compare

Two to five companies side by side across standing, compounding, economics,
capital allocation, and all six screening dimensions. Unavailable metrics render
as `N/A` and a dimension that could not be evaluated renders as `NOT EVALUABLE`;
neither is ever normalized to zero.

Compounding rates are read from the Feature 2B view and are never re-derived
here, so a company whose compounding view the engine refused to build reports
`N/A` rather than a rate computed over some other window. The window itself is a
row, so two companies measured over different spans cannot be silently compared.
Where the rate is absent, the screening-dimension rows still carry the engine's
own verdict for that company.

### 5. Data Quality

The trust model made visible. A grid of every company's coverage standing,
unusable metrics, and primary blocker — including the `FAILED` ones, which stay
listed with their reason.

For a selected company: each canonical metric marked available, structurally
absent, unsupported, or invalid, with the reason and whether it blocks a layer;
each analytical layer's state and reason; and, behind an expander, the technical
provenance — which SEC concept was selected, what else was tried, the catalog
candidates, the diagnosis category, and any conflict the normalizer resolved.
Raw XBRL payloads are never rendered.

## Trust rules

The workbench preserves every semantic the engine guarantees.

| Rule | How it is enforced |
|---|---|
| `None` never becomes zero | Comparison values hold raw types; `format_*` returns `N/A` for `None`; charts drop missing years rather than plotting them |
| A `NOT_EVALUABLE` dimension stays visible | Rendered with its text label, never a blank or a filled band |
| `PARTIAL` coverage is never hidden | Coverage class appears in the header, the screener, the queue, and the comparison |
| `FAILED` companies are never dropped | They appear in the Overview counts, the screener, and the data-quality grid |
| Screening is never recomputed | Views read `ScreeningResult` objects produced by `owner_lens.screening` |
| No valuation is inferred | No price, multiple, intrinsic value, expected return, scenario, or position size appears anywhere |
| No buy/sell language | Buckets are labelled research priority, with that stated on the page |
| No network call on open | Every loader reads the store and the content-addressed snapshot store only |

Text labels are always shown; colour is never the only carrier of meaning.

## Performance and caching

Streamlit reruns the script on nearly every interaction, so caching is applied in
`cache.py` and nowhere else.

* **The company list is deliberately not cached.** It is re-read from the store
  on every run, so a re-ingested company's new content hash appears immediately.
  Caching it would have frozen the fingerprint every other key is built from and
  reduced the invalidation guarantee to "until the user presses Reload".
* **Everything expensive is keyed on content hashes.** Screening, company detail,
  comparison, and coverage diagnosis are keyed on a fingerprint of
  `(ticker, content_hash)` pairs. A new hash is a new key, so a stale result is
  never served. If the store changes under a cached entry, the loader raises and
  tells the reader to reload rather than attributing a value to a payload it was
  not derived from.
* **No live handle is cached.** Cached functions take hashable scalars and return
  plain data. This is not stylistic: a `WorkbenchSource` owns a SQLite
  connection, SQLite connections are bound to their creating thread, and
  Streamlit reruns on whichever thread is free. Each cached function opens a
  short-lived source and closes it, which is affordable precisely because the
  expensive results are what gets cached.
* **No hidden global mutable state.** `WorkbenchSource` is a context manager,
  every use site closes it, and a failed `initialize()` closes the half-open
  connection before the error propagates.

The sidebar's **Reload persisted data** button drops every cached entry.

## Failure handling

The workbench degrades one row at a time rather than blanking a page.

| Failure | Behaviour |
|---|---|
| Company has no raw snapshot | Listed on Overview and in the coverage grid with its reason; skipped by screening |
| Snapshot is unreadable or not valid JSON | Becomes a `WorkbenchError`; that company drops out of screening and reads `ERROR` in the coverage grid; every page still renders |
| OwnerLens refuses to derive a history | The `CanonicalDataError` is shown as a message explaining that it refused rather than approximated |
| Store cannot be opened at all | A titled page with the error and the command to point at another store |
| Store is empty | A titled page naming the ingest command |

Each of these is a test in `tests/test_workbench_pages.py` or
`tests/test_workbench.py`.

## Refresh and ingestion

Fetching is deliberately left to the CLI. The sidebar states the distinction and
names the command:

```powershell
uv run owner-lens ingest TICKER   # fetches fresh SEC data
# then press "Reload persisted data" in the workbench
```

Putting a fetch button in the UI would have blurred the one guarantee that makes
the workbench safe to leave open: nothing it does reaches the network. This is
recorded as a possible future enhancement rather than an omission.

## Testing

`tests/test_workbench.py` (42 tests) covers the data layer against a real
temporary store built from the offline golden payloads: persisted-company
discovery including a company with no readable snapshot, canonical-history
reconstruction, screening-universe loading, dynamically derived overview counts,
the company detail model, the comparison model including the rule that
compounding rates come from the engine view or not at all, `None` preservation
through both the model and the formatters, `FAILED` companies staying visible,
`PARTIAL` companies retaining their missing dimensions and their ceiling, the
absence of any network call, corrupt-snapshot containment, connection hygiene on
a failed open, cache fingerprints changing with the content hash, the refusal to
compute against a payload a key does not name, CLI argv and environment
restoration, and — the contract that matters most — the workbench reporting
exactly the verdict `screen_company_from_facts` produces.

`tests/test_workbench_pages.py` (20 tests) runs the real Streamlit script through
`AppTest`, with no browser, asserting that each of the five pages renders without
raising and that the headline content is present, that the rendered Compare table
shows `N/A` where the engine refused a rate and `NOT EVALUABLE` where a dimension
could not be scored, that a corrupt snapshot blanks no page, and that an empty or
unopenable store explains itself instead of failing.

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## Where future features attach

The workbench creates the obvious seams without building anything behind them.

| Future feature | Where it lands |
|---|---|
| Valuation, intrinsic value | Company → the `Future: Valuation · Edge` tab |
| Expected return, edge | Company → the same tab; a Screener column once it exists |
| Scenarios, distributions | Company → a new tab beside Screening |
| Portfolio construction | A sixth page, beside Data Quality |
| A second provider | Data Quality → the technical-provenance expander already names the provider concept |

Each would add a view module and a loader in `data.py`. None requires changing
the engine, the trust rules, or any existing page.

## What Feature 7D Deliberately Did Not Build

- valuation, intrinsic value, prices, multiples, scenarios, probability
  distributions, expected return, edge, position sizing, or portfolio
  construction,
- news, LLM analysis, or any non-deterministic content,
- authentication, accounts, cloud deployment, or a frontend build step,
- a second database or any duplicated financial calculation,
- an in-UI SEC or FMP fetch,
- a generic UI framework: five pages, one data module, no abstraction layer
  beyond what those five pages needed.
