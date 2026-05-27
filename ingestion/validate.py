"""
ingestion/validate.py — data quality checks for ingested price data.

Each check returns a list of error strings (empty = clean).
validate_ticker_df() runs all checks and aggregates results.

Design decisions:
  - Checks are pure functions: no database access, no side effects.
  - Returns strings rather than raising — caller decides whether to skip
    or abort based on error count and severity.
  - Thresholds are module-level constants so they're easy to find and tune.
"""

import logging
from datetime import date

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Validation thresholds
MIN_ROWS              = 20        # fewer rows than this = insufficient history
MAX_NULL_FRACTION     = 0.02      # more than 2% nulls in adj_close = fail
MAX_DAILY_RETURN      = 0.30      # single-day move > 30% flagged as outlier
MIN_PRICE             = 0.01      # prices at or below this are invalid
MAX_STALE_STREAK      = 5         # this many consecutive identical closes = stale


def validate_ticker_df(df: pd.DataFrame, ticker: str) -> list[str]:
    """
    Run all validation checks on a single-ticker price DataFrame.

    Args:
        df:     DataFrame with columns: price_date, open, high, low,
                close, adj_close, volume.
        ticker: Ticker symbol — used in error messages only.

    Returns:
        List of error strings. Empty list means data is clean.
    """
    errors = []
    errors += _check_min_rows(df, ticker)
    errors += _check_nulls(df, ticker)
    errors += _check_price_sanity(df, ticker)
    errors += _check_outlier_returns(df, ticker)
    errors += _check_stale_prices(df, ticker)
    return errors


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_min_rows(df: pd.DataFrame, ticker: str) -> list[str]:
    if len(df) < MIN_ROWS:
        return [f"{ticker}: only {len(df)} rows, minimum is {MIN_ROWS}"]
    return []


def _check_nulls(df: pd.DataFrame, ticker: str) -> list[str]:
    null_count = df["adj_close"].isna().sum()
    null_frac  = null_count / len(df)
    if null_frac > MAX_NULL_FRACTION:
        return [
            f"{ticker}: {null_count} null adj_close values "
            f"({null_frac:.1%} > threshold {MAX_NULL_FRACTION:.1%})"
        ]
    return []


def _check_price_sanity(df: pd.DataFrame, ticker: str) -> list[str]:
    errors = []
    bad = df[df["adj_close"].notna() & (df["adj_close"] <= MIN_PRICE)]
    if not bad.empty:
        errors.append(
            f"{ticker}: {len(bad)} rows with adj_close <= {MIN_PRICE}: "
            f"{bad['price_date'].tolist()}"
        )
    return errors


def _check_outlier_returns(df: pd.DataFrame, ticker: str) -> list[str]:
    errors = []
    prices = df["adj_close"].dropna()
    if len(prices) < 2:
        return []

    returns = prices.pct_change().dropna()
    outliers = returns[returns.abs() > MAX_DAILY_RETURN]
    if not outliers.empty:
        errors.append(
            f"{ticker}: {len(outliers)} daily return(s) exceed "
            f"{MAX_DAILY_RETURN:.0%}: dates {df.loc[outliers.index, 'price_date'].tolist()}"
        )
    return errors


def _check_stale_prices(df: pd.DataFrame, ticker: str) -> list[str]:
    errors = []
    prices = df["adj_close"].dropna().reset_index(drop=True)
    if len(prices) < MAX_STALE_STREAK:
        return []

    # AI erroneously added a dead function here to do what the lambda does below, then never used it. Deleted, switched to Lambda.  

    stale = (
        prices
        .rolling(MAX_STALE_STREAK)
        .apply(lambda w: 1 if len(set(w)) == 1 else 0, raw=True) # rolling check to see if any window of MAX_STALE_STREAK vals are all equal 
        .eq(1)
        .any()
    )
    if stale:
        errors.append(
            f"{ticker}: found streak of {MAX_STALE_STREAK}+ identical "
            f"adj_close values — possible stale data"
        )
    return errors