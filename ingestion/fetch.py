"""
ingestion/fetch.py — pull daily OHLCV data from yfinance and write to postgres.

Design decisions:
  - Pulls the full configured universe in a single yfinance call (batched).
  - Uses INSERT ... ON CONFLICT DO UPDATE so reruns are idempotent.
  - Validates data before writing; bad tickers are logged and skipped.
  - Returns a summary dict for the pipeline audit log.
"""

import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
from ingestion.validate import validate_ticker_df

logger = logging.getLogger(__name__)

# How many calendar days back to fetch on a normal run.
DEFAULT_LOOKBACK_DAYS = 365 * 2


def fetch_and_store(
    tickers: list[str],
    start_date: date = None,
    end_date: date = None,
) -> dict:
    """
    Pull OHLCV data for all tickers, validate, and upsert into prices table.

    Args:
        tickers:    List of ticker symbols, e.g. ['SPY', 'AGG', 'GLD'].
        start_date: First date to fetch. Defaults to DEFAULT_LOOKBACK_DAYS ago.
        end_date:   Last date to fetch. Defaults to today.

    Returns:
        Summary dict with keys: tickers_ok, tickers_failed, rows_written.
    """
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    logger.info(
        "Fetching %d tickers from %s to %s", len(tickers), start_date, end_date
    )

    # yfinance accepts a space-separated string for multi-ticker pulls.
    # This is more efficient than one HTTP request per ticker.
    raw = yf.download(
        tickers=" ".join(tickers),
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        auto_adjust=False,   # keep raw + adj_close both visible
        progress=False,
    )

    if raw.empty:
        logger.error("yfinance returned empty DataFrame for universe %s", tickers)
        return {"tickers_ok": [], "tickers_failed": tickers, "rows_written": 0}

    tickers_ok = []
    tickers_failed = []
    total_rows = 0

    for ticker in tickers:
        try:
            df = _extract_ticker(raw, ticker, len(tickers))
            errors = validate_ticker_df(df, ticker)
            if errors:
                for e in errors:
                    logger.warning("Validation failure [%s]: %s", ticker, e)
                tickers_failed.append(ticker)
                continue

            rows = _upsert_prices(df, ticker)
            total_rows += rows
            tickers_ok.append(ticker)
            logger.info("Upserted %d rows for %s", rows, ticker)

        except Exception as exc:
            logger.exception("Failed to process %s: %s", ticker, exc)
            tickers_failed.append(ticker)

    return {
        "tickers_ok": tickers_ok,
        "tickers_failed": tickers_failed,
        "rows_written": total_rows,
    }


def _extract_ticker(raw: pd.DataFrame, ticker: str, n_tickers: int) -> pd.DataFrame:
    """
    Slice one ticker out of the multi-ticker yfinance DataFrame.

    yfinance returns a MultiIndex column structure when multiple tickers
    are requested: (field, ticker). For a single ticker it returns flat
    columns. We normalise both cases to a flat DataFrame.
    """
    if n_tickers == 1:
        df = raw.copy()
    else:
        df = raw.xs(ticker, axis=1, level=1).copy()

    df.index.name = "price_date"
    df = df.reset_index()
    df["price_date"] = pd.to_datetime(df["price_date"]).dt.date

    # Normalise column names to lowercase
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]

    # yfinance column is 'adj_close' — ensure it's present
    if "adj_close" not in df.columns:
        raise ValueError(f"adj_close column missing for {ticker}")

    return df[["price_date", "open", "high", "low", "close", "adj_close", "volume"]]


def _upsert_prices(df: pd.DataFrame, ticker: str) -> int:
    """
    Insert rows into prices, updating on conflict (ticker, price_date).
    Returns number of rows written.
    """
    rows = [
        {
            "ticker":     ticker,
            "price_date": row.price_date,
            "open":       _safe_float(row.open),
            "high":       _safe_float(row.high),
            "low":        _safe_float(row.low),
            "close":      _safe_float(row.close),
            "adj_close":  _safe_float(row.adj_close),
            "volume":     int(row.volume) if pd.notna(row.volume) else None,
        }
        for row in df.itertuples()
    ]

    sql = """
        INSERT INTO prices
            (ticker, price_date, open, high, low, close, adj_close, volume)
        VALUES
            (%(ticker)s, %(price_date)s, %(open)s, %(high)s, %(low)s,
             %(close)s, %(adj_close)s, %(volume)s)
        ON CONFLICT (ticker, price_date) DO UPDATE SET
            open        = EXCLUDED.open,
            high        = EXCLUDED.high,
            low         = EXCLUDED.low,
            close       = EXCLUDED.close,
            adj_close   = EXCLUDED.adj_close,
            volume      = EXCLUDED.volume,
            ingested_at = NOW()
    """

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()

    return len(rows)


def _safe_float(val) -> float | None:
    """Return float or None — guards against numpy NaN leaking into postgres."""
    if pd.isna(val):
        return None
    return float(val)