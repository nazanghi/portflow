"""
pipeline.py — Prefect flow definition for the portflow pipeline.

Stages (in order):
  1. ingest    — fetch prices from yfinance, validate, upsert to postgres
  2. signals   — compute log returns, volatility, momentum, covariance
  3. optimize  — run mean-variance optimization, store weights
  4. report    — write human-readable allocation report to disk

Each stage is a Prefect task. The flow wires them together, handles
failures, and writes to pipeline_runs for every stage outcome.

Scheduling: run daily at 18:00 ET (after US market close + data lag).
"""

import logging
import sys
from datetime import date, datetime, timezone

from prefect import flow, task
from prefect.logging import get_run_logger

import db
from config import TICKERS, OPTIMIZATION_PARAMS
from ingestion.fetch import fetch_and_store
from signals.compute import compute_all
from optimization.optimizer import optimize, store_weights
from output.report import generate_report

# ---------------------------------------------------------------------------
# Tasks — each wraps one pipeline stage
# ---------------------------------------------------------------------------

@task(name="ingest", retries=2, retry_delay_seconds=60)
def task_ingest(tickers: list[str]) -> dict:
    logger = get_run_logger()
    started_at = datetime.now(timezone.utc)

    run_id = db.log_run(
        stage="ingest",
        status="started",
        run_date=date.today(),
        started_at=started_at,
    )

    try:
        summary = fetch_and_store(tickers)
        finished_at = datetime.now(timezone.utc)

        db.log_run(
            stage="ingest",
            status="success",
            run_date=date.today(),
            rows_affected=summary["rows_written"],
            started_at=started_at,
            finished_at=finished_at,
        )

        logger.info(
            "Ingest complete: %d tickers ok, %d failed, %d rows written",
            len(summary["tickers_ok"]),
            len(summary["tickers_failed"]),
            summary["rows_written"],
        )

        if summary["tickers_failed"]:
            logger.warning("Failed tickers: %s", summary["tickers_failed"])

        return summary

    except Exception as exc:
        db.log_run(
            stage="ingest",
            status="failed",
            run_date=date.today(),
            error_message=str(exc),
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
        raise


@task(name="signals")
def task_signals(tickers: list[str]) -> dict:
    logger = get_run_logger()
    started_at = datetime.now(timezone.utc)

    db.log_run(
        stage="signals",
        status="started",
        run_date=date.today(),
        started_at=started_at,
    )

    try:
        signals = compute_all(tickers)
        finished_at = datetime.now(timezone.utc)

        db.log_run(
            stage="signals",
            status="success",
            run_date=date.today(),
            started_at=started_at,
            finished_at=finished_at,
        )

        logger.info("Signals computed for %d tickers", len(tickers))
        return signals

    except Exception as exc:
        db.log_run(
            stage="signals",
            status="failed",
            run_date=date.today(),
            error_message=str(exc),
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
        raise


@task(name="optimize")
def task_optimize(tickers: list[str], signals: dict) -> tuple[dict, int]:
    logger = get_run_logger()
    started_at = datetime.now(timezone.utc)

    db.log_run(
        stage="optimize",
        status="started",
        run_date=date.today(),
        started_at=started_at,
    )

    try:
        result = optimize(
            tickers=tickers,
            expected_returns=signals["momentum"],
            cov_matrix=signals["cov_matrix"],
        )

        run_id = store_weights(
            result=result,
            expected_returns=signals["momentum"],
        )

        finished_at = datetime.now(timezone.utc)
        db.log_run(
            stage="optimize",
            status="success",
            run_date=date.today(),
            rows_affected=len(result["weights"]),
            started_at=started_at,
            finished_at=finished_at,
        )

        logger.info(
            "Optimization complete: sharpe=%.3f vol=%.3f run_id=%d",
            result["sharpe"],
            result["expected_vol"],
            run_id,
        )

        return result, run_id

    except Exception as exc:
        db.log_run(
            stage="optimize",
            status="failed",
            run_date=date.today(),
            error_message=str(exc),
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
        raise


@task(name="report")
def task_report(result: dict, run_id: int) -> str:
    logger = get_run_logger()
    started_at = datetime.now(timezone.utc)

    db.log_run(
        stage="report",
        status="started",
        run_date=date.today(),
        started_at=started_at,
    )

    try:
        report_path = generate_report(result=result, run_id=run_id)
        finished_at = datetime.now(timezone.utc)

        db.log_run(
            stage="report",
            status="success",
            run_date=date.today(),
            started_at=started_at,
            finished_at=finished_at,
        )

        logger.info("Report written to %s", report_path)
        return str(report_path)

    except Exception as exc:
        db.log_run(
            stage="report",
            status="failed",
            run_date=date.today(),
            error_message=str(exc),
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
        raise


# ---------------------------------------------------------------------------
# Flow — wires tasks together
# ---------------------------------------------------------------------------

@flow(name="portflow", log_prints=True)
def portflow_pipeline(tickers: list[str] = TICKERS):
    """
    Full portfolio construction pipeline.

    Runs ingest → signals → optimize → report in sequence.
    Any task failure is logged to pipeline_runs and propagates
    to Prefect, which marks the flow run as failed.
    """

    summary          = task_ingest(tickers)
    signals          = task_signals(tickers)
    result, run_id   = task_optimize(tickers, signals)
    report_path      = task_report(result, run_id)

    return {
        "run_id":      run_id,
        "report_path": report_path,
        "sharpe":      result["sharpe"],
        "weights":     result["weights"].to_dict(),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    portflow_pipeline()