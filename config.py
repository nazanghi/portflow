"""
config.py — universe definition and pipeline parameters.

Single source of truth for all configurable values.
Every other module imports from here rather than hardcoding.
"""

# Asset universe
TICKERS = [
    "SPY",  # US large cap equity
    "AGG",  # US aggregate bonds
    "GLD",  # Gold
    "EFA",  # International developed equity
    "IEF",  # US intermediate treasuries
    "VNQ",  # Real estate
    "GSG",  # Commodities
]

# Optimization constraints
OPTIMIZATION_PARAMS = {
    "max_position_size":    0.40,
    "min_position_size":    0.00,
    "weight_sum_tolerance": 1e-4,
}

# Pipeline schedule — daily at 18:00 ET
PIPELINE_SCHEDULE_CRON = "0 18 * * 1-5"  # weekdays only