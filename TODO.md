# TODO.md

Prioritized next actions for `portflow`. Organized by urgency and interview
impact. Fix bugs before adding features.

---

## Fix immediately — documented bugs

These are already logged in `AI_USAGE.md`. Fix before the next push.

- [ ] **Fix log ordering bug in `task_optimize`** (`pipeline.py`)
      Move `db.log_run(status="success")` to after `store_weights()` returns.
      Currently records success even if the weight write fails.

- [ ] **Remove dead code in `validate.py`**
      `all_equal()` is defined inside `_check_stale_prices` but never called.
      Either pass it to `.apply()` or delete it.

- [ ] **Add all-negative momentum pre-check** (`optimizer.py`)
      Log a warning before hitting the solver when all momentum values are
      negative. Makes the min-variance fallback explicit rather than silent.

---

## Production hardening — high interview value

Do these together as a single commit after the bug fixes.

- [ ] **Normalize momentum to annualized units** (`signals/compute.py`)
      The 12-month cumulative return fed directly into Sharpe produces an
      inflated ratio (~3.5). Divide by the lookback period in years so the
      units are consistent with annualized volatility.

- [ ] **Exponentially weighted covariance matrix** (`signals/compute.py`)
      Replace `log_returns.cov()` with `log_returns.ewm(span=120).cov()`.
      Gives recent observations higher weight, adapts to regime changes
      without manual intervention. One line, high impact.

- [ ] **Alert threshold on ticker validation failures** (`ingestion/fetch.py`, `config.py`)
      Add `MAX_FAILED_TICKERS = 2` to `config.py`. If more tickers than
      this fail validation in a single run, raise rather than continue on
      a dangerously concentrated universe.

- [ ] **Add `.env` support** (`db.py`)
      Add `python-dotenv` to load connection config from a `.env` file.
      Create `.env.example` with variable names and no values. Add `.env`
      to `.gitignore`.

- [ ] **Add `requirements.txt`**
      ```bash
      pip freeze > requirements.txt
      ```

---

## Meaningful extensions — reference in interviews as known next steps

These are additive scope. Implement if time allows; reference by name even
if not — "here's what I'd do next and why" is a complete interview answer.

- [ ] **Persist signals to database** (`signals/compute.py`, `db.py`)
      Add a `signals` table keyed on `(run_date, ticker)`. Write log returns,
      volatility, and momentum after each computation run. Closes the
      auditability gap — lets you inspect exactly what signal values fed
      any historical optimization.

- [ ] **Ledoit-Wolf shrinkage on covariance matrix** (`signals/compute.py`)
      Replace the sample covariance with a shrinkage estimator from
      `sklearn.covariance.LedoitWolf`. Reduces estimation error in small
      universes. Standard in production quant systems.

- [ ] **Replace `executemany` with COPY for bulk ingest** (`ingestion/fetch.py`)
      Use `psycopg2.copy_expert` with a StringIO buffer. Only matters at
      scale but demonstrates awareness of the performance boundary.

- [ ] **Add a Prefect deployment with a real schedule**
      ```bash
      prefect deploy pipeline.py:portflow_pipeline --cron "0 18 * * 1-5"
      ```
      Makes the scheduling concrete rather than theoretical.

- [ ] **Backtest harness**
      Run the optimizer over a rolling window of historical dates. Compute
      realized Sharpe on the resulting weight series. Turns the pipeline
      from a point-in-time tool into something that can be evaluated and
      compared. Largest scope item — highest signal for a quant role.

---

## Suggested commit sequence

1. Fix the three documented bugs → `fix: documented bugs from AI review`
2. Hardening items (momentum normalization, ewm covariance, alert threshold,
   dotenv, requirements.txt) → `feat: production hardening pass`
3. Signals persistence + Ledoit-Wolf → `feat: signal auditability and covariance shrinkage`
4. Backtest harness → `feat: rolling backtest`