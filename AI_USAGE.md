# AI_USAGE.md

Tracks every instance of AI-generated code in this project: what was
generated, what decisions were implicit, what was caught and corrected,
and what category of AI failure each entry represents.

The goal is not to justify using AI — it's to demonstrate that every
line was understood, reviewed, and owned.

---

## Failure categories

| Category | Description |
|---|---|
| Instruction drift | AI ignored or drifted from an explicit requirement |
| Convention blindness | AI applied a common pattern that didn't fit this context |
| Brittle success | Code works for the happy path but breaks on edge cases |
| Confident wrongness | AI stated something incorrect without flagging uncertainty |
| Scope creep | AI added unrequested complexity |
| Error recovery failure | AI's error handling was absent or misleading |
| Grader gaming | AI optimised for looking correct rather than being correct |
| Ambiguity without disclosure | AI resolved ambiguity silently instead of flagging it |

---

## Log

### Session 1 — Schema and connection layer

**Module**: `db.py`
**What was generated**: Full schema (3 tables), connection factory,
`init_db()`, `log_run()` helper

**Implicit decisions**:
- `NUMERIC(12,4)` for prices and `NUMERIC(8,6)` for weights — precision
  chosen without discussion. Weight precision to 6 decimal places is
  finer than any real portfolio needs.
- `RealDictCursor` chosen as default cursor factory — returns dicts
  instead of tuples. Convenient but slightly higher memory overhead.
  Not discussed before generation.
- `log_run()` opens its own connection per call — separate connection
  open/close cycle for every audit write. Connection exhaustion risk
  at scale, not flagged.
- `adj_close` vs `close` both stored — correct decision, but the reason
  (split/dividend adjustment, not latency) was not explained before
  code was generated.

**Review outcome**: Accepted with noted caveats. All implicit decisions
caught in three-question review.
**Failure category**: Ambiguity without disclosure.

---

### Session 2 — Data ingestion

**Module**: `ingestion/fetch.py`
**What was generated**: yfinance pull, ticker extraction, upsert logic

**Implicit decisions**:
- `DEFAULT_LOOKBACK_DAYS = 365 * 2` — two years chosen without
  discussion. Covariance estimation quality depends on this window.
- `executemany` used for upsert — correct for moderate row counts,
  not optimal for bulk loads (COPY faster at scale).
- `auto_adjust=False` passed to yfinance — correct decision to keep
  both raw and adjusted columns, not explained before generation.

**Review outcome**: Accepted. Implicit decisions understood.
**Failure category**: Ambiguity without disclosure.

---

**Module**: `ingestion/validate.py`
**What was generated**: Five validation checks, thresholds as constants

**Implicit decisions**:
- `MAX_STALE_STREAK = 5` maps to a trading week — correct but undisclosed.
- `MAX_DAILY_RETURN = 0.30` would incorrectly flag delayed split
  adjustments from Yahoo — should be a warning, not a hard failure.

**Bug caught in review**:
- `all_equal()` defined inside `_check_stale_prices` but never called.
  Lambda in `.apply()` does the same work. Dead code.
- Detection: three-question review, indentation inspection.
- Correct approach: use `all_equal` in the apply or remove the definition.
- **Failure category: Scope creep.**

---

### Session 3 — Signal computation

**Module**: `signals/compute.py`
**What was generated**: price loading, log returns, rolling vol,
momentum, covariance matrix

**Implicit decisions**:
- `VOL_LOOKBACK_DAYS = 60` — two months chosen without discussion.
- `lookback_days = 400` in `load_prices` — implicit buffer beyond
  momentum lookback. Not discussed.
- Signals not persisted to database — deliberate tradeoff noted:
  avoids storing derived data that could desync from prices.
  Auditability gap acknowledged. Deferred.
- Covariance uses full history — regime dependence problem noted.
  Exponentially weighted covariance identified as production fix.
  Deferred.

**Bug caught in review**:
- `np.log()` failed on Decimal types returned by `RealDictCursor`.
  Fixed by adding `pivot.astype(float)` in `load_prices`.
- Detection: runtime error on first execution.
- **Failure category: Convention blindness** — assumed float dtype
  without accounting for psycopg2 Decimal return types.

---

### Session 4 — Optimization

**Module**: `optimization/optimizer.py`
**What was generated**: Charnes-Cooper max Sharpe reformulation,
min variance fallback, weight storage

**Implicit decisions**:
- `SOLVER = cp.ECOS` — ECOS removed from CVXPY defaults in recent
  versions. Caught immediately on first run. Fixed to CLARABEL.
- `MAX_POSITION_SIZE = 0.40` — AGG immediately hit this cap, meaning
  the constraint is actively binding. Not discussed before generation.
- Sharpe ratio of 3.5 is an artifact of using 12-month cumulative
  momentum as the return input against annualized volatility. Units
  are inconsistent. Documented in report output and ARCHITECTURE.md.

**Bug caught in review**:
- `store_weights` wrote portfolio-level expected return into every
  per-ticker row. Column name implies per-ticker semantics. Semantically
  wrong. Fixed to store per-ticker momentum value.
- Detection: three-question review.
- **Failure category: Confident wrongness.**

---

### Session 5 — Output and orchestration

**Module**: `pipeline.py`
**What was generated**: Prefect flow, four tasks, audit logging per stage

**Implicit decisions**:
- Prefect spins up a temporary local server on each run — fine for
  development, requires a dedicated server or Prefect Cloud for
  production deployment.
- Flow name `portflow` hardcoded — not discussed before generation.

**Bug caught in review (pre-run)**:
- `db.log_run(status="success")` called before `store_weights()` in
  `task_optimize`. If `store_weights` fails, audit log records success
  with no failure entry. Fix: move success log to after `store_weights`
  returns.
- Detection: three-question review.
- **Failure category: Error recovery failure.**

**Bug caught on first run**:
- `tickers: list[str] = None` rejected by Prefect 3's Pydantic
  validation. Fixed to `tickers: list[str] = TICKERS`.
- Detection: runtime error on first execution.
- **Failure category: Convention blindness** — common Python default
  pattern incompatible with Prefect 3's strict parameter validation.

---

## Summary

| Session | Bugs caught in review | Bugs caught on run | Implicit decisions flagged |
|---|---|---|---|
| 1 — Schema | 0 | 0 | 4 |
| 2 — Ingestion | 1 (dead code) | 0 | 3 |
| 3 — Signals | 0 | 1 (Decimal dtype) | 4 |
| 4 — Optimization | 1 (wrong column) | 1 (missing solver) | 3 |
| 5 — Orchestration | 1 (log ordering) | 1 (Pydantic default) | 2 |
| **Total** | **3** | **3** | **16** |

Six bugs caught across five sessions. Three caught before code ran —
by reading carefully. Three caught on first execution. Zero shipped
silently. The review discipline is the point.