# portflow

A production-grade systematic portfolio construction pipeline targeting the
infrastructure patterns used in quantitative asset management.

Built as a portfolio project demonstrating the research-to-production gap
that quant dev roles exist to close, while serving as an exercise in GAI iteration.

---

## What it does

`portflow` runs a daily pipeline that:

1. Pulls OHLCV price data for a 7-ETF universe from Yahoo Finance
2. Validates data quality (nulls, gaps, outliers, stale prices)
3. Computes log returns, rolling volatility, and a momentum signal
4. Runs mean-variance optimization via CVXPY to produce target weights
5. Writes weights to PostgreSQL and generates a human-readable report

The result is a target allocation like this, produced every trading day:

```
  AGG     40.00%  ███████████████
  SPY     22.95%  █████████
  GSG     18.32%  ███████
  IEF     18.00%  ███████
  GLD      0.73%
```

---

## Asset universe

| Ticker | Description |
|--------|-------------|
| SPY    | US large cap equity |
| AGG    | US aggregate bonds |
| GLD    | Gold |
| EFA    | International developed equity |
| IEF    | US intermediate treasuries |
| VNQ    | Real estate |
| GSG    | Commodities |

These ETFs were chosen for low pairwise correlation — diversification in the
mathematical sense, not just the colloquial one.

---

## Stack

| Component | Technology |
|-----------|------------|
| Data      | yfinance, PostgreSQL, psycopg2 |
| Compute   | pandas, NumPy, CVXPY (CLARABEL solver) |
| Orchestration | Prefect 3 |
| Language  | Python 3.13 |

---

## Project structure

```
portflow/
├── ingestion/
│   ├── fetch.py          # yfinance pull + upsert
│   └── validate.py       # data quality checks
├── signals/
│   └── compute.py        # returns, volatility, momentum, covariance
├── optimization/
│   └── optimizer.py      # mean-variance via CVXPY
├── output/
│   └── report.py         # allocation report generation
├── pipeline.py           # Prefect flow wiring all stages
├── db.py                 # schema, connection, audit logging
├── config.py             # universe and parameters
├── ARCHITECTURE.md       # design decisions and tradeoffs
├── AI_USAGE.md           # AI usage log with mistake tracking
└── INTERVIEW_PREP.md     # technical Q&A for this project
```

---

## Setup

**Prerequisites**: Python 3.13+, PostgreSQL 14+

```bash
# Clone and create virtual environment
git clone <repo>
cd portflow
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install yfinance cvxpy prefect pandas numpy psycopg2-binary

# Create database
createdb portflow

# Initialise schema
python3 -c "import db; db.init_db()"

# Run the pipeline
python3 pipeline.py
```

Report is written to `reports/allocation_YYYY-MM-DD.txt`.

---

## Design philosophy

Three decisions define this project:

**Separation of concerns.** Each module owns exactly one stage. `db.py`
owns the schema. `validate.py` owns data quality. `optimizer.py` owns
the math. Nothing bleeds across boundaries.

**Auditability over convenience.** Every pipeline run writes to
`pipeline_runs` with start time, finish time, rows affected, and any
error message. A failure at 6am is debuggable without reading logs.

**Known limitations documented, not hidden.** The Sharpe ratio is
overstated because momentum is a cumulative return, not an annualized
forecast. The covariance matrix uses full history and is regime-sensitive.
These are in `ARCHITECTURE.md` with production fixes identified.

---

## Development approach

This project was built in collaboration with Claude (Anthropic). All
architectural decisions, schema designs, and implementation choices were
specified and reviewed by me. AI-generated code is tracked in `AI_USAGE.md`
with notes on what was accepted, what was corrected, and why — including
bugs caught in review that would have shipped undetected.