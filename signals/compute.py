"""
signals/compute.py — compute return series, rolling volatility, and momentum
signals from stored price data.

Pipeline position: runs after ingestion, feeds the optimizer.

Outputs (all written to caller as DataFrames):
  - log_returns:  daily log returns, shape (dates, tickers)
  - volatility:   rolling annualised volatility, shape (dates, tickers)
  - momentum:     12-1 month momentum signal, shape (tickers,) — latest values only

Design decisions:
  - All computation is in-memory on DataFrames pulled from postgres.
  - No intermediate writes to the database — signals are transient inputs
    to the optimizer, not persisted state.
  - Uses adj_close exclusively for all return calculations.
"""

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db

logger = logging.getLogger(__name__)

# Signal parameters
TRADING_DAYS_PER_YEAR = 252
VOL_LOOKBACK_DAYS     = 60    # rolling window for volatility estimate
MOM_LONG_DAYS         = 252   # 12-month lookback for momentum
MOM_SHORT_DAYS        = 21    # 1-month exclusion (skip most recent month)


def load_prices(tickers: list[str], lookback_days: int = 400) -> pd.DataFrame:
    """
    Pull adj_close from postgres for the given tickers.

    Returns a DataFrame indexed by price_date, one column per ticker.
    Missing dates (holidays) appear as NaN — forward-filled before return.
    """
    cutoff = date.today() - timedelta(days=lookback_days)

    sql = """
        SELECT ticker, price_date, adj_close
        FROM prices
        WHERE ticker = ANY(%(tickers)s)
          AND price_date >= %(cutoff)s
        ORDER BY price_date ASC
    """

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"tickers": tickers, "cutoff": cutoff})
            rows = cur.fetchall()

    if not rows:
        raise ValueError(f"No price data found for {tickers} since {cutoff}")

    df = pd.DataFrame(rows, columns=["ticker", "price_date", "adj_close"])
    pivot = df.pivot(index="price_date", columns="ticker", values="adj_close")
    pivot.index = pd.to_datetime(pivot.index)
    pivot = pivot.sort_index()

    # Forward-fill over holidays/weekends, then drop any leading NaNs
    pivot = pivot.ffill().dropna(how="all")
    pivot = pivot.astype(float) # AI Mistake: adding fix for pandas 3.x compatibility

    missing = [t for t in tickers if t not in pivot.columns]
    if missing:
        logger.warning("No data found for tickers: %s", missing)

    return pivot


def compute_log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """
    Compute daily log returns from a prices DataFrame.

    log_return_t = ln(P_t / P_{t-1})

    First row is dropped (NaN from diff).
    """
    log_returns = np.log(prices / prices.shift(1)).dropna(how="all")
    return log_returns


def compute_rolling_volatility(
    log_returns: pd.DataFrame,
    window: int = VOL_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """
    Compute rolling annualised volatility.

    vol_t = std(log_returns over window) * sqrt(TRADING_DAYS_PER_YEAR)

    Rows with fewer than (window / 2) observations are dropped to avoid
    unreliable estimates at the start of the series.
    """
    rolling_vol = (
        log_returns
        .rolling(window=window, min_periods=window // 2)
        .std()
        * np.sqrt(TRADING_DAYS_PER_YEAR)
    )
    return rolling_vol.dropna(how="all")


def compute_momentum(prices: pd.DataFrame) -> pd.Series:
    """
    Compute 12-1 month momentum signal for each ticker.

    momentum = cumulative log return from (today - MOM_LONG_DAYS)
               to (today - MOM_SHORT_DAYS)

    Excludes the most recent month to avoid short-term reversal.
    Returns a Series indexed by ticker with the latest momentum value.
    """
    if len(prices) < MOM_LONG_DAYS:
        logger.warning(
            "Price history (%d days) shorter than momentum lookback (%d days). "
            "Signal will be based on available history only.",
            len(prices), MOM_LONG_DAYS
        )

    long_prices  = prices.iloc[-MOM_LONG_DAYS]  if len(prices) >= MOM_LONG_DAYS  else prices.iloc[0]
    short_prices = prices.iloc[-MOM_SHORT_DAYS] if len(prices) >= MOM_SHORT_DAYS else prices.iloc[-1]

    momentum = np.log(short_prices / long_prices)
    momentum.name = "momentum"
    return momentum


def compute_all(tickers: list[str]) -> dict:
    """
    Run the full signal computation pipeline for the given tickers.

    Returns:
        {
          'prices':     pd.DataFrame  — adj_close, dates x tickers
          'log_returns': pd.DataFrame — daily log returns, dates x tickers
          'volatility': pd.DataFrame — rolling annualised vol, dates x tickers
          'momentum':   pd.Series    — 12-1 month momentum, indexed by ticker
          'cov_matrix': pd.DataFrame — annualised covariance matrix, tickers x tickers
        }
    """
    logger.info("Loading prices for %d tickers", len(tickers))
    prices = load_prices(tickers)

    logger.info("Computing log returns")
    log_returns = compute_log_returns(prices)

    logger.info("Computing rolling volatility (window=%d)", VOL_LOOKBACK_DAYS)
    volatility = compute_rolling_volatility(log_returns)

    logger.info("Computing momentum signal")
    momentum = compute_momentum(prices)

    logger.info("Computing covariance matrix")
    cov_matrix = _compute_covariance(log_returns)

    logger.info("Signal computation complete")
    return {
        "prices":      prices,
        "log_returns": log_returns,
        "volatility":  volatility,
        "momentum":    momentum,
        "cov_matrix":  cov_matrix,
    }


def _compute_covariance(log_returns: pd.DataFrame) -> pd.DataFrame:
    """
    Compute the annualised covariance matrix from log returns.

    Uses the full available history. Annualised by multiplying by
    TRADING_DAYS_PER_YEAR (valid because log returns are additive).

    The covariance matrix is the core input to the optimizer — it
    captures how assets move together, not just how volatile each is.
    """
    cov = log_returns.cov() * TRADING_DAYS_PER_YEAR
    return cov