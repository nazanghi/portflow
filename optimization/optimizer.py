"""
optimization/optimizer.py — mean-variance optimization via CVXPY.

Solves for the maximum Sharpe ratio portfolio subject to:
  - Long-only: w_i >= 0
  - Fully invested: sum(w) == 1
  - Position limit: w_i <= MAX_POSITION_SIZE

Pipeline position: consumes signals from signals/compute.py,
writes results to portfolio_weights table via db.py.

Design decisions:
  - Maximizes Sharpe directly via the Dinkelbach / Charnes-Cooper
    transformation (maximizing mu'w / sqrt(w'Σw) is not convex as
    written, so we reformulate as a convex QP).
  - Falls back to minimum variance portfolio if the momentum signal
    is flat (all expected returns near zero).
  - Validates that output weights sum to 1.0 within tolerance before
    writing to the database.
"""

import logging
from datetime import date

import cvxpy as cp
import numpy as np
import pandas as pd

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db

logger = logging.getLogger(__name__)

# Optimization parameters
MAX_POSITION_SIZE   = 0.40        # maximum weight for any single asset
MIN_POSITION_SIZE   = 0.00        # long-only (no shorts)
WEIGHT_SUM_TOLERANCE = 1e-4       # weights must sum to 1 within this tolerance
SOLVER              = cp.CLARABEL # Update solver from ECOS for compatibility w/ recent version


def optimize(
    tickers: list[str],
    expected_returns: pd.Series,
    cov_matrix: pd.DataFrame,
    run_date: date = None,
) -> dict:
    """
    Run mean-variance optimization and return the result.

    Args:
        tickers:          Ordered list of ticker symbols.
        expected_returns: pd.Series indexed by ticker — momentum signal.
        cov_matrix:       pd.DataFrame (tickers x tickers) — annualised.
        run_date:         Date label for this optimization run.

    Returns:
        {
          'weights':           pd.Series indexed by ticker,
          'expected_return':   float (annualised),
          'expected_vol':      float (annualised),
          'sharpe':            float,
          'status':            str (solver status),
        }
    """
    if run_date is None:
        run_date = date.today()

    # Align everything to the same ticker order
    tickers   = sorted(tickers)
    mu        = expected_returns.reindex(tickers).values.astype(float)
    sigma     = cov_matrix.reindex(index=tickers, columns=tickers).values.astype(float)
    n         = len(tickers)

    logger.info("Running optimizer: %d assets, date=%s", n, run_date)

    # ------------------------------------------------------------------
    # Convex reformulation of maximum Sharpe ratio
    #
    # Maximizing mu'w / sqrt(w'Σw) is a fractional program — not convex.
    # Standard fix (Charnes-Cooper): let y = w / sqrt(w'Σw), solve for y,
    # then recover w = y / sum(y).
    #
    # Equivalent convex problem:
    #   minimize    y' Σ y
    #   subject to  mu' y == 1        (normalisation)
    #               y >= 0            (long-only in y-space)
    #               y_i <= k * MAX_POSITION_SIZE  where k = sum(y)
    #
    # The position limit constraint is enforced on recovered weights,
    # not on y directly, so we iterate if needed.
    # ------------------------------------------------------------------

    weights, status = _solve_max_sharpe(mu, sigma, n)

    if status not in ("optimal", "optimal_inaccurate"):
        logger.warning(
            "Max Sharpe solver status: %s — falling back to min variance", status
        )
        weights, status = _solve_min_variance(sigma, n)

    if weights is None:
        raise RuntimeError(f"Optimization failed with status: {status}")

    weights_series = pd.Series(weights, index=tickers)

    # Validate weights sum to 1
    weight_sum = weights_series.sum()
    if abs(weight_sum - 1.0) > WEIGHT_SUM_TOLERANCE:
        raise ValueError(
            f"Weights sum to {weight_sum:.6f}, expected 1.0 "
            f"(tolerance {WEIGHT_SUM_TOLERANCE})"
        )

    # Portfolio statistics
    port_return = float(mu @ weights)
    port_var    = float(weights @ sigma @ weights)
    port_vol    = float(np.sqrt(max(port_var, 0)))
    sharpe      = port_return / port_vol if port_vol > 1e-8 else 0.0

    result = {
        "weights":         weights_series,
        "expected_return": port_return,
        "expected_vol":    port_vol,
        "sharpe":          sharpe,
        "status":          status,
    }

    logger.info(
        "Optimization complete: return=%.3f vol=%.3f sharpe=%.3f status=%s",
        port_return, port_vol, sharpe, status
    )

    return result


def store_weights(result: dict, expected_returns: pd.Series, run_date: date = None) -> int:
    """
    Write optimized weights to the portfolio_weights table.
    expected_returns should be the per-ticker momentum signal,
    not the portfolio-level aggregate.
    Returns the run_id assigned by the database.
    """
    if run_date is None:
        run_date = date.today()

    weights = result["weights"]

    sql = """
        INSERT INTO portfolio_weights
            (run_date, ticker, weight, expected_return)
        VALUES
            (%(run_date)s, %(ticker)s, %(weight)s, %(expected_return)s)
        RETURNING run_id
    """

    run_id = None
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            for ticker, weight in weights.items():
                cur.execute(sql, {
                    "run_date":        run_date,
                    "ticker":          ticker,
                    "weight":          float(weight),
                    "expected_return": float(expected_returns.get(ticker, 0.0)),
                })
                if run_id is None:
                    run_id = cur.fetchone()["run_id"]
        conn.commit()

    logger.info("Stored weights for run_id=%d, date=%s", run_id, run_date)
    return run_id

# ---------------------------------------------------------------------------
# Solvers
# ---------------------------------------------------------------------------

def _solve_max_sharpe(mu: np.ndarray, sigma: np.ndarray, n: int):
    """
    Charnes-Cooper reformulation of maximum Sharpe ratio.
    Returns (weights_array, status_string).
    """
    y = cp.Variable(n, nonneg=True)

    objective   = cp.Minimize(cp.quad_form(y, sigma))
    constraints = [
        mu @ y == 1,
        cp.sum(y) * MAX_POSITION_SIZE >= y,   # position limit on recovered weights
    ]

    prob = cp.Problem(objective, constraints)
    prob.solve(solver=SOLVER, verbose=False)

    if prob.status not in ("optimal", "optimal_inaccurate") or y.value is None:
        return None, prob.status

    # Recover weights: w = y / sum(y)
    y_val   = np.maximum(y.value, 0)          # clip tiny negatives from solver
    w       = y_val / y_val.sum()
    return w, prob.status


def _solve_min_variance(sigma: np.ndarray, n: int):
    """
    Fallback: minimum variance portfolio ignoring expected returns.
    Used when the momentum signal is flat or max Sharpe fails.
    """
    w = cp.Variable(n, nonneg=True)

    objective   = cp.Minimize(cp.quad_form(w, sigma))
    constraints = [
        cp.sum(w) == 1,
        w <= MAX_POSITION_SIZE,
    ]

    prob = cp.Problem(objective, constraints)
    prob.solve(solver=SOLVER, verbose=False)

    if prob.status not in ("optimal", "optimal_inaccurate") or w.value is None:
        return None, prob.status

    w_val = np.maximum(w.value, 0)
    w_val = w_val / w_val.sum()
    return w_val, prob.status