"""
output/report.py — generate a human-readable allocation report.

Reads the latest portfolio weights from the database and writes
a formatted text report to disk.

Pipeline position: runs after optimization, final stage before audit log.
"""

import logging
from datetime import date
from pathlib import Path

import pandas as pd

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db

logger = logging.getLogger(__name__)

REPORTS_DIR = Path("reports")


def generate_report(
    result: dict,
    run_id: int,
    run_date: date = None,
) -> Path:
    """
    Write a human-readable allocation report to disk.

    Args:
        result:   Output dict from optimizer.optimize().
        run_id:   Database run_id for this optimization.
        run_date: Date label for the report filename.

    Returns:
        Path to the written report file.
    """
    if run_date is None:
        run_date = date.today()

    REPORTS_DIR.mkdir(exist_ok=True)
    report_path = REPORTS_DIR / f"allocation_{run_date.isoformat()}.txt"

    weights   = result["weights"].sort_values(ascending=False)
    exp_ret   = result["expected_return"]
    exp_vol   = result["expected_vol"]
    sharpe    = result["sharpe"]
    status    = result["status"]

    lines = [
        "=" * 56,
        f"  PORTFLOW — ALLOCATION REPORT",
        f"  Run date : {run_date.isoformat()}",
        f"  Run ID   : {run_id}",
        f"  Status   : {status}",
        "=" * 56,
        "",
        "  TARGET WEIGHTS",
        "  " + "-" * 40,
    ]

    for ticker, weight in weights.items():
        bar   = "█" * int(weight * 40)
        lines.append(f"  {ticker:<6}  {weight:>6.2%}  {bar}")

    lines += [
        "",
        "  PORTFOLIO STATISTICS",
        "  " + "-" * 40,
        f"  Expected return  : {exp_ret:>8.2%}  (momentum-based)",
        f"  Expected vol     : {exp_vol:>8.2%}  (annualised)",
        f"  Sharpe ratio     : {sharpe:>8.2f}  (rf = 0)",
        "",
        "  NOTE: Sharpe is overstated — momentum signal is a",
        "  12-month cumulative return, not an annualised forecast.",
        "  Treat as a relative ranking, not an absolute figure.",
        "",
        "=" * 56,
    ]

    report_path.write_text("\n".join(lines))
    logger.info("Report written to %s", report_path)
    return report_path


def fetch_latest_weights(run_date: date = None) -> pd.DataFrame:
    """
    Pull the most recent weight vector from the database.
    Used for display and downstream consumption.
    """
    if run_date is None:
        run_date = date.today()

    sql = """
        SELECT ticker, weight, expected_return
        FROM portfolio_weights
        WHERE run_date = %(run_date)s
        ORDER BY weight DESC
    """

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"run_date": run_date})
            rows = cur.fetchall()

    if not rows:
        raise ValueError(f"No weights found for run_date={run_date}")

    return pd.DataFrame(rows)