# AI_USAGE.md

Tracks every instance of AI-generated code in this project: what was generated,
what decisions were implicit, what was caught and corrected, and what category
of AI failure (if any) each entry represents.

The goal is not to justify using AI — it's to demonstrate that every line was
understood, reviewed, and owned.

---

## Entry format

**Module**: which file  
**What was generated**: brief description  
**Implicit decisions**: choices the AI made that weren't explicitly specified  
**Review outcome**: accepted / corrected / rejected, and why  
**Failure category** (if applicable): see categories below  

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
**What was generated**: Full schema (3 tables), connection factory, `init_db()`, `log_run()` helper  

**Implicit decisions**:
- Used `NUMERIC(12,4)` for prices and `NUMERIC(8,6)` for weights — precision chosen
  without discussion. Price precision is defensible; weight precision to 6 decimal
  places is finer than any real portfolio needs and was not specified.
- `RealDictCursor` chosen as the default cursor factory — means all query results
  return dicts instead of tuples. Convenient, but slightly higher memory overhead.
  Not discussed before generation.
- `log_run()` opens its own connection rather than accepting one as a parameter —
  means every audit log write is a separate connection open/close cycle. Noted as
  a connection exhaustion risk in the three-question review.
- `adj_close` vs `close` both stored — correct decision (adj_close for returns,
  close for reference), but the reason (split/dividend adjustment) was not
  explained before code was generated.

**Review outcome**: Accepted with noted caveats. Implicit decisions were caught
in the three-question review and are understood.  

**Failure category**: Ambiguity without disclosure — several precision and
cursor choices were made silently.

---

### Session 2 — Data ingestion

**Module**: `ingestion/fetch.py`  
**What was generated**: yfinance pull, ticker extraction, upsert logic  

**Implicit decisions**:
- `DEFAULT_LOOKBACK_DAYS = 365 * 2` — two years chosen without discussion.
  Covariance estimation quality depends on this window. Too short = noisy
  estimates. Too long = older data may not reflect current regime.
- `executemany` used for upsert — correct for moderate row counts but not
  optimal for bulk loads (COPY would be faster at scale).
- `auto_adjust=False` passed to yfinance — correct decision to keep both
  raw and adjusted columns visible, but not explained before generation.

**Review outcome**: Accepted. Implicit decisions understood and documented.  
**Failure category**: Ambiguity without disclosure.

---

**Module**: `ingestion/validate.py`  
**What was generated**: Five validation checks, thresholds as named constants  

**Implicit decisions**:
- `MAX_STALE_STREAK = 5` maps to a trading week — correct but undisclosed.
- `MAX_DAILY_RETURN = 0.30` would incorrectly flag delayed split adjustments
  from Yahoo — should be a warning, not a hard failure.

**Bug caught in review**:
- `all_equal()` defined inside `_check_stale_prices` but never called —
  dead code. Lambda in `.apply()` does the work instead.
- Detection method: three-question review, indentation inspection.
- Correct approach: use `all_equal` in the apply or remove the definition.
- Failure category: Scope creep.

### Session 3 — Signal computation

**Module**: `signals/compute.py`  
**What was generated**: price loading, log returns, rolling vol, momentum, covariance matrix  

**Implicit decisions**:
- `VOL_LOOKBACK_DAYS = 60` — two months chosen without discussion. Shorter
  windows are more responsive but noisier. Not specified before generation.
- `lookback_days = 400` in load_prices — slightly more than MOM_LONG_DAYS (252)
  to ensure enough history. Implicit buffer, not discussed.
- Signals not persisted to database — deliberate tradeoff: avoids storing
  derived data that could get out of sync with prices. Auditability gap
  noted; signals table deferred to post-MVP hardening.
- Covariance uses full history — regime dependence problem noted.
  Exponentially weighted covariance (ewm().cov()) identified as
  production fix. Deferred.

**Bug caught in review**:
- `np.log()` failed on Decimal types returned by RealDictCursor from
  postgres. Fixed by adding `pivot.astype(float)` in load_prices.
- Detection method: runtime error on first execution.
- Failure category: Convention blindness — assumed float dtype without
  accounting for psycopg2 Decimal return types.

  ### Session 4 — Optimization

**Module**: `optimization/optimizer.py`  
**What was generated**: Charnes-Cooper max Sharpe reformulation, min variance
fallback, weight storage  

**Implicit decisions**:
- `SOLVER = cp.ECOS` — ECOS removed from CVXPY defaults in recent versions.
  Caught immediately on first run. Fixed to CLARABEL.
  Failure category: Convention blindness.
- `MAX_POSITION_SIZE = 0.40` — chosen without discussion. AGG immediately
  hit this cap, meaning the constraint is actively binding. A tighter cap
  (0.30) would force more diversification.
- Sharpe ratio of 3.5 is an artifact of using 12-month cumulative momentum
  as the return input against annualized volatility. Units are inconsistent.
  Should normalize momentum to annualized return before computing Sharpe.
  Failure category: Ambiguity without disclosure.

**Bug caught in review**:
- `expected_return` column stores portfolio-level return, not per-ticker
  momentum. Column name implies per-ticker semantics. Semantically wrong.
  Fix: store per-ticker momentum value, or rename column.
  Failure category: Confident wrongness.

  ### Session 5 — Output and orchestration

**Module**: `pipeline.py`  
**What was generated**: Prefect flow, four tasks, audit logging per stage  

**Implicit decisions**:
- Prefect spins up a temporary local server on each run — fine for
  development, not for production. A dedicated Prefect server or
  Prefect Cloud would replace this.
- Flow name 'portflow' is hardcoded — not discussed before generation.

**Bugs caught in review**:
- `tickers: list[str] = None` rejected by Prefect 3's Pydantic validation.
  Fixed to `tickers: list[str] = TICKERS`.
  Detection method: first run error.
  Failure category: Convention blindness.

- `db.log_run(status="success")` called before `store_weights()` in
  task_optimize. If store_weights fails, audit log shows success with
  no corresponding failure entry for that write. Fix: move success log
  to after store_weights returns.
  Detection method: three-question review.
  Failure category: Error recovery failure.