# ARCHITECTURE.md

Documents significant design decisions made during the construction of
`portflow`, the tradeoffs involved, and what would change in a production
hardening pass. Updated incrementally as each session adds new components.

---

## System overview

`portflow` is a scheduled portfolio construction pipeline with four stages:

    prices (postgres) → signals (in-memory) → weights (postgres) → report (file)

Each stage is a discrete Python module with a single responsibility. The
pipeline is orchestrated by Prefect, which handles scheduling, logging,
and failure alerting.

---

## Decision log

### 1. Three-table schema instead of a flat log

**Decision**: Separate tables for `prices`, `portfolio_weights`, and
`pipeline_runs` rather than a single wide table or a flat audit log.

**Rationale**: Each table owns exactly one stage of the pipeline's state.
`prices` is immutable observed data. `portfolio_weights` is optimizer
output — derived, but worth persisting for auditability and backtesting.
`pipeline_runs` is the operational log, decoupled from both so it can
record failures even when the other tables aren't written to.

**Tradeoff**: Three connections per pipeline run minimum. Acceptable at
this data volume. At higher frequency, a connection pool
(e.g. SQLAlchemy) would replace the per-call `get_connection()` factory.

---

### 2. Upsert on ingest (ON CONFLICT DO UPDATE)

**Decision**: Price rows are upserted rather than inserted. A rerun on
the same day overwrites rather than errors or duplicates.

**Rationale**: Makes the ingestion stage idempotent. Scheduled pipelines
fail and retry — idempotency means retries are safe. `ingested_at`
timestamp is updated on each upsert so you can always tell when a row
was last written.

**Tradeoff**: A bug that writes incorrect prices will silently overwrite
correct ones. Mitigation: validation runs before the upsert, and
`ingested_at` provides a trail.

---

### 3. Signals computed in memory, not persisted

**Decision**: Log returns, volatility, momentum, and the covariance
matrix are computed fresh on each run and passed directly to the
optimizer. They are not written to the database.

**Rationale**: Signals are derived data — they can always be recomputed
from `prices`, which is the source of truth. Persisting derived data
creates a synchronization risk: if prices are corrected, stored signals
become stale without a recomputation trigger.

**Tradeoff**: No auditability of signal values. If the optimizer produces
a surprising weight vector, you cannot easily inspect what signal values
fed it without rerunning the computation. 

**Production fix**: A `signals` table keyed on `(run_date, ticker)` would
close this gap. Deferred — completing the end-to-end pipeline takes
priority over optimizing intermediate persistence.

---

### 4. Full-history covariance matrix

**Decision**: The covariance matrix is estimated from the full available
price history (up to 400 days).

**Rationale**: More data generally means a more stable estimate. For a
7-asset universe, the matrix is small enough that estimation error is
not a severe problem.

**Known limitation**: Markets move through regimes. A covariance matrix
estimated across pre- and post-2020 data treats both periods as equally
informative, which they are not. SPY/AGG correlation behaved very
differently in the rate-hiking cycle than before it.

**Production fix**: Exponentially weighted covariance (`ewm().cov()` in
pandas) gives recent observations higher weight without requiring manual
regime flagging. Ledoit-Wolf shrinkage is the standard academic fix for
ill-conditioned matrices in small universes.

---

### 5. Validation as a gate, not a quarantine

**Decision**: Validation failures cause a ticker to be skipped entirely
for that run. Bad data is logged and the pipeline continues with the
remaining tickers.

**Rationale**: A single bad ticker (e.g. Yahoo returning stale data for
GSG) should not abort the entire portfolio construction run. The
optimizer can work with 6 of 7 assets.

**Tradeoff**: Silent partial runs. If enough tickers fail validation, the
optimizer runs on an unintentionally concentrated universe. 

**Production fix**: Alert if more than N tickers fail validation in a
single run. Configurable threshold — for a 7-asset universe, failing
2+ tickers should trigger an alert.

---

## Known limitations and deferred improvements

| Item | Severity | Fix |
|---|---|---|
| No connection pooling | Low (dev), Medium (prod) | SQLAlchemy connection pool |
| Signals not persisted | Medium | signals table keyed on (run_date, ticker) |
| Full-history covariance | Medium | Exponentially weighted covariance or Ledoit-Wolf shrinkage |
| Validation is warn-not-quarantine | Medium | Alert threshold on ticker failure count |
| No second data source | High (prod) | Cross-validate Yahoo prices against a secondary feed |
| executemany for upsert | Low | COPY for bulk loads at higher data volume |

---