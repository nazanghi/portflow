"""
AI Generated.

db.py — database connection and schema management for portflow.

Responsibilities:
  - Provide a connection factory (get_connection)
  - Define and create all tables via init_db()
  - Own the schema so every other module imports from here
"""

import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def get_connection():
    """
    Return a psycopg2 connection using environment variables.

    Expected env vars:
        PORTFLOW_DB_HOST    default: localhost
        PORTFLOW_DB_PORT    default: 5432
        PORTFLOW_DB_NAME    default: portflow
        PORTFLOW_DB_USER    default: current OS user
        PORTFLOW_DB_PASS    default: (empty)
    """
    return psycopg2.connect(
        host=os.getenv("PORTFLOW_DB_HOST", "localhost"),
        port=int(os.getenv("PORTFLOW_DB_PORT", 5432)),
        dbname=os.getenv("PORTFLOW_DB_NAME", "portflow"),
        user=os.getenv("PORTFLOW_DB_USER", os.getenv("USER", "postgres")),
        password=os.getenv("PORTFLOW_DB_PASS", ""),
        cursor_factory=RealDictCursor,
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
-- Daily OHLCV price data ingested from yfinance.
-- Primary key: one row per (ticker, date) pair.
CREATE TABLE IF NOT EXISTS prices (
    ticker          TEXT        NOT NULL,
    price_date      DATE        NOT NULL,
    open            NUMERIC(12, 4),
    high            NUMERIC(12, 4),
    low             NUMERIC(12, 4),
    close           NUMERIC(12, 4)   NOT NULL,
    adj_close       NUMERIC(12, 4)   NOT NULL,
    volume          BIGINT,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (ticker, price_date)
);

CREATE INDEX IF NOT EXISTS idx_prices_date
    ON prices (price_date DESC);

CREATE INDEX IF NOT EXISTS idx_prices_ticker_date
    ON prices (ticker, price_date DESC);


-- Target portfolio weights produced by each optimizer run.
-- One row per (run_id, ticker): a full weight vector per run.
CREATE TABLE IF NOT EXISTS portfolio_weights (
    run_id          BIGSERIAL,
    run_date        DATE        NOT NULL,
    ticker          TEXT        NOT NULL,
    weight          NUMERIC(8, 6)   NOT NULL
                        CHECK (weight >= 0 AND weight <= 1),
    expected_return NUMERIC(8, 6),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (run_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_weights_run_date
    ON portfolio_weights (run_date DESC);


-- Audit log for every pipeline execution.
-- One row per run: captures timing, status, and failure context.
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              BIGSERIAL   PRIMARY KEY,
    run_date        DATE        NOT NULL,
    stage           TEXT        NOT NULL,
    status          TEXT        NOT NULL
                        CHECK (status IN ('started', 'success', 'failed')),
    rows_affected   INTEGER,
    error_message   TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_runs_date_stage
    ON pipeline_runs (run_date DESC, stage);
"""


def init_db():
    """
    Create all tables and indexes if they do not already exist.
    Safe to call on every startup — uses IF NOT EXISTS throughout.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        conn.commit()
    logger.info("Schema initialised (or already current).")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log_run(stage: str, status: str, run_date=None,
            rows_affected: int = None, error_message: str = None,
            started_at=None, finished_at=None) -> int:
    """
    Insert a row into pipeline_runs and return its id.
    Called by each pipeline stage to record what happened.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pipeline_runs
                    (run_date, stage, status, rows_affected,
                     error_message, started_at, finished_at)
                VALUES
                    (%(run_date)s, %(stage)s, %(status)s, %(rows_affected)s,
                     %(error_message)s, %(started_at)s, %(finished_at)s)
                RETURNING id
                """,
                {
                    "run_date":      run_date,
                    "stage":         stage,
                    "status":        status,
                    "rows_affected": rows_affected,
                    "error_message": error_message,
                    "started_at":    started_at,
                    "finished_at":   finished_at,
                },
            )
            row = cur.fetchone()
        conn.commit()
    return row["id"]