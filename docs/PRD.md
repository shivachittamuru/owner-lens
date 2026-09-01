# OwnerLens — Product Requirements Document

**Repository:** `owner-lens`
**Status:** Initial
**Primary user:** Individual long-term fundamental investor and developer

---

## 1. Vision

OwnerLens is a deterministic fundamental-intelligence layer for understanding the economics of public businesses.

It converts trustworthy financial data into normalized fundamentals, derived economic metrics, and eventually transparent investment scores that can be consumed by humans, notebooks, screeners, valuation systems, and AI agents.

OwnerLens is not intended to replicate a full consumer product such as Stock Unlock.

Its purpose is to provide a small, trustworthy foundation for answering questions such as:

* How is this business economically performing?
* Is economic value per share compounding?
* Is the business becoming stronger or weaker?
* How efficiently is capital being deployed?
* How attractive is the current valuation?
* Which businesses deserve deeper research?
* How do these characteristics aggregate at portfolio level?

---

## 2. Core Philosophy

OwnerLens separates four layers that must never be confused.

### Facts

Reported financial information obtained from authoritative or trusted data providers.

Examples:

* revenue
* operating income
* cash flow from operations
* capital expenditures
* diluted shares

### Metrics

Deterministic calculations derived from facts.

Examples:

* FCF
* FCF margin
* revenue CAGR
* FCF/share
* ROIC
* share-count growth

### Scores

Transparent deterministic transformations of metrics.

Examples:

* Business Quality Score
* Growth Quality Score
* Financial Health Score
* Valuation Score
* Economic Value Score

### Judgment

Qualitative interpretation requiring business, industry, competitive, technological, or probabilistic reasoning.

Judgment may eventually be performed or assisted by AI agents, but it must remain distinguishable from reported facts and deterministic calculations.

---

## 3. Initial Scope

OwnerLens begins intentionally narrow.

### Company universe

Initially:

* Adobe (`ADBE`)

Subsequently:

* selected U.S.-listed companies
* primarily conventional U.S. GAAP operating companies
* potentially the S&P 500 over time

Initial versions do not need universal company coverage.

### Data source

Initial fundamental data will come from SEC EDGAR structured XBRL APIs.

OwnerLens will define a provider abstraction so another normalized financial-data provider can replace or supplement SEC data later without changing downstream metric logic.

### Initial period

Approximately five annual fiscal years.

Quarterly and TTM calculations will be introduced only after annual-period handling is trustworthy.

---

## 4. v0.1 User Story

As an investor,

I want to provide a ticker such as `ADBE`

and receive a trustworthy five-year financial history

so that I can understand the basic economic development of the business without manually collecting financial statements.

---

## 5. v0.1 Fundamental Facts

OwnerLens should retrieve or derive enough information to represent:

### Income Statement

* Revenue
* Gross Profit
* Operating Income
* Net Income

### Cash Flow Statement

* Operating Cash Flow
* Capital Expenditures
* Share-Based Compensation
* Share Repurchases
* Dividends

### Balance Sheet

* Cash and short-term investments
* Total Debt
* Total Assets
* Total Equity

### Ownership

* Diluted weighted-average shares

Not every future metric needs to be supported in v0.1.

---

## 6. v0.1 Derived Metrics

OwnerLens should deterministically calculate:

* Free Cash Flow
* Revenue Growth
* Revenue CAGR
* Operating Margin
* FCF Margin
* FCF/share
* FCF/share Growth
* Share-count Growth

Definitions must be explicit and testable.

OwnerLens should never silently substitute alternative metric definitions.

---

## 7. Data Provenance

Every reported financial fact should retain enough metadata to explain where it came from.

At minimum:

* ticker
* metric
* value
* unit
* fiscal period
* fiscal year
* source
* source concept/tag when available
* filing/accession identifier when available

A user or future agent should be able to answer:

> Where did this number come from?

---

## 8. Reliability Principles

### Deterministic before probabilistic

Financial calculations that can be performed reliably in code must not be delegated to an LLM.

### Explicit definitions

Metrics such as FCF and ROIC must have documented definitions.

### Traceability

Reported facts should retain source provenance.

### Fail loudly

Missing or ambiguous financial facts should be surfaced rather than silently guessed.

### Narrow correctness over broad coverage

Correct support for a handful of companies is more valuable than unreliable support for thousands.

### Human-verifiable

Outputs should initially be easy to compare against SEC filings and Stock Unlock.

---

## 9. Initial Validation Standard

Adobe will serve as the first golden company.

OwnerLens output will be compared against:

1. Adobe's reported filings
2. SEC Company Facts
3. Stock Unlock financial history

Differences must be understood rather than dismissed.

v0.1 succeeds when the supported Adobe metrics reconcile within expected reporting/rounding differences.

---

## 10. Non-Goals

The initial project will NOT build:

* a consumer investing website
* mobile applications
* brokerage integration
* portfolio tracking
* authentication
* notifications
* interactive charting infrastructure
* real-time market data
* universal international company support
* automatic investment recommendations
* AI agents
* vector databases
* RAG
* complex valuation engines
* hundreds of financial ratios
* complete US-GAAP taxonomy normalization

These capabilities may be considered only when an actual downstream use case requires them.

---

## 11. Future Capability Layers

OwnerLens may eventually evolve through independent layers.

### Fundamental Layer

Normalized company financial history.

### Metrics Layer

Deterministic economic and financial calculations.

### Scoring Layer

Transparent measures of:

* business quality
* profitability
* growth quality
* financial health
* capital allocation
* valuation
* economic-value creation

### Screening Layer

Search company universes using metrics and scores.

### Economic Value Layer

Measure how underlying economic value per ownership unit evolves over time.

### Valuation Layer

Support bear/base/bull intrinsic-value distributions.

### Portfolio Layer

Aggregate company economics, valuation, quality, and risk characteristics across holdings.

### Agent Layer

Expose OwnerLens functionality as deterministic tools to research, valuation, portfolio, and risk-management agents.

---

## 12. Azure Strategy

OwnerLens should remain Azure-compatible from the beginning without provisioning infrastructure before it is needed.

Azure services should be introduced when they solve a real requirement.

Potential future services include:

* Azure Blob Storage for raw filing/document snapshots
* Azure Database for PostgreSQL for normalized fundamentals, metrics, scores, and historical snapshots
* Azure Key Vault for secrets
* Azure Monitor / Application Insights for telemetry
* Azure AI Search or Foundry knowledge capabilities for filing and document retrieval
* Microsoft Foundry for models, evaluations, tracing, and future agent workloads
* Azure Container Apps or another appropriate Azure compute service when OwnerLens requires a deployed API/service

The architecture should not require Azure infrastructure for basic local development.

---

## 13. AI Architecture Principle

Future AI agents must consume deterministic OwnerLens tools rather than independently inventing financial facts.

Example future interfaces might include:

* `get_company_financials(ticker)`
* `get_metric_history(ticker, metric)`
* `compare_companies(tickers)`
* `get_company_scores(ticker)`
* `screen_companies(criteria)`
* `calculate_economic_value(ticker)`
* `get_valuation_inputs(ticker)`

Agent reasoning should focus primarily on interpretation and judgment.

---

## 14. Development Principles

OwnerLens should favor:

* Python
* `uv`
* `src/` package layout
* typed domain models
* focused unit tests
* small incremental releases
* educational notebooks
* explicit financial definitions
* provider abstraction
* reproducible calculations
* minimal dependencies
* architecture that grows only when justified

Each meaningful release should ideally leave behind:

1. working production code
2. focused tests
3. a runnable educational notebook
4. a small architecture or decision note where necessary

---

## 15. Success Criteria

OwnerLens is successful if it eventually becomes a trusted reusable foundation that allows the user to spend less time collecting and calculating financial data and more time thinking about:

* business economics
* competitive advantage
* economic-value creation
* valuation
* probability distributions
* portfolio construction
* risk
* investment judgment

The project should improve both investing capability and understanding of robust AI/agent system architecture.

It should not become an exercise in rebuilding financial-data infrastructure for its own sake.
