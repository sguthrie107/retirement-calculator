"""
IRA Retirement Plan - Age-Based Phase Projections

Supports Traditional / Roth IRA contribution modeling with annual lump-sum
deposits at the maximum allowed limit.

Phase 1 (Up to 50):  60% FZROX / 30% FZILX / 10% us_large_cap
                       (Steven → FLCOX, Alyssa → FSPGX)
Phase 2 (51 to 65):  60% FZROX / 20% FZILX / 20% FUAMX
Phase 3 (65+):       40% FZROX / 20% FZILX / 15% FUAMX / 15% FNAX / 10% FIPDX

Contribution logic:
  - 2026 max contribution: $7,500
  - Every 3 years the max increases by $500
  - Contributions are lump-sum at beginning of each year
"""

from datetime import date
from typing import Dict, Any, List, Tuple
import pandas as pd
from pandas import DataFrame

from .data_loader import load_json_file
from .constants import DATA_FILES
from .plan_by_age import (
    _calculate_blended_yield_and_appreciation,
)


# ---------------------------------------------------------------------------
# IRA contribution constants
# ---------------------------------------------------------------------------
IRA_BASE_YEAR = 2026
IRA_BASE_LIMIT = 7500
IRA_INCREASE_INTERVAL = 3   # years between increases
IRA_INCREASE_AMOUNT = 500   # dollar increase per interval


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_ira_contribution_limit(year: int) -> float:
    """
    Calculate the maximum IRA contribution limit for a given year.

    Starting from $7,500 in 2026, the limit increases by $500 every 3 years.

    Args:
        year: Calendar year

    Returns:
        Maximum annual IRA contribution in dollars

    Examples:
        2026-2028: $7,500
        2029-2031: $8,000
        2032-2034: $8,500
    """
    if year < IRA_BASE_YEAR:
        return float(IRA_BASE_LIMIT)

    years_elapsed = year - IRA_BASE_YEAR
    increases = years_elapsed // IRA_INCREASE_INTERVAL
    return float(IRA_BASE_LIMIT + increases * IRA_INCREASE_AMOUNT)


def calculate_ira_annualized_return(projection_df: DataFrame) -> float:
    """
    Calculate the average annualized return (CAGR) for an IRA projection.

    Uses the Compound Annual Growth Rate formula:
    CAGR = (Ending Value / Beginning Value)^(1/n) - 1

    Args:
        projection_df: DataFrame from _project_ira_phase

    Returns:
        Annualized return rate as a decimal (e.g. 0.0950 for 9.50%)
    """
    if projection_df.empty or len(projection_df) < 2:
        return 0.0

    first_row = projection_df.iloc[0]
    starting_balance = (
        first_row["ira_balance"]
        - first_row["ira_contribution"]
        - first_row["growth"]
    )
    ending_balance = projection_df.iloc[-1]["ira_balance"]
    num_years = len(projection_df)

    if starting_balance <= 0 or num_years <= 0:
        return 0.0

    return (ending_balance / starting_balance) ** (1 / num_years) - 1


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_user_ira_data(beneficiary: str) -> Dict[str, Any]:
    """
    Load user-specific IRA configuration from users.json.

    Args:
        beneficiary: User name (e.g. 'Steven' or 'Alyssa')

    Returns:
        User data dictionary (must contain ira_phases and current_ira_balance)

    Raises:
        ValueError: If user not found or IRA data missing
    """
    data = load_json_file(DATA_FILES["USERS"])

    for user in data.get("users", []):
        if user.get("name") == beneficiary:
            if "current_ira_balance" not in user:
                raise ValueError(f"No IRA data found for '{beneficiary}'")
            return user

    raise ValueError(f"Beneficiary '{beneficiary}' not found in users.json")


def _format_ira_allocation_label(allocation: Dict[str, Dict]) -> str:
    """
    Human-readable IRA allocation string using the label field from config.

    Falls back to the asset class key if no label is provided.
    """
    parts = []
    for key, cfg in allocation.items():
        pct_str = f"{int(cfg['pct'] * 100)}%"
        label = cfg.get("label", key.replace("_", " ").title())
        parts.append(f"{pct_str} {label}")
    return " / ".join(parts)


def _project_ira_phase(
    start_balance: float,
    start_age: int,
    end_age: int,
    start_year: int,
    allocation: Dict[str, Dict],
    beneficiary: str,
    phase_label: str,
    contribute: bool = True,
) -> Tuple[DataFrame, float]:
    """
    Project IRA balance year-by-year for a single phase.

    Contributions are lump-sum at the beginning of each year at the
    maximum allowed limit.  Dividend/coupon yields and price appreciation
    are calculated separately and reinvested.

    Args:
        start_balance:  Balance at beginning of phase
        start_age:      Age at start of phase
        end_age:        Age at end of phase (exclusive)
        start_year:     Calendar year the phase begins
        allocation:     Dict of asset_class -> {pct, ticker, label}
        beneficiary:    Name for labeling rows
        phase_label:    e.g. 'Phase 1'
        contribute:     Whether to make annual contributions (default True)

    Returns:
        (DataFrame of projections, ending balance)
    """
    blended_yield, blended_appreciation = _calculate_blended_yield_and_appreciation(
        allocation
    )
    alloc_label = _format_ira_allocation_label(allocation)

    rows: List[Dict[str, Any]] = []
    balance = start_balance

    for i in range(end_age - start_age + 1):
        year = start_year + i
        age = start_age + i

        # Lump-sum contribution at beginning of year (if enabled)
        contribution = get_ira_contribution_limit(year) if contribute else 0.0
        balance += contribution

        # Separate growth components
        dividend_income = balance * blended_yield
        price_appreciation = balance * blended_appreciation
        growth = dividend_income + price_appreciation
        balance += growth

        rows.append({
            "beneficiary": beneficiary,
            "year": year,
            "age": age,
            "phase": phase_label,
            "ira_contribution": round(contribution, 2),
            "dividend_income": round(dividend_income, 2),
            "price_appreciation": round(price_appreciation, 2),
            "growth": round(growth, 2),
            "ira_balance": round(balance, 2),
            "allocation": alloc_label,
        })

    return DataFrame(rows), balance


# ---------------------------------------------------------------------------
# Full multi-phase IRA plan
# ---------------------------------------------------------------------------

def retirement_ira_full_plan(
    beneficiary: str,
    current_year: int = None,
    post_retirement_years: int = 0,
    withdrawal_pct: float = None,
) -> DataFrame:
    """
    Run a complete 3-phase IRA projection for a stored user.

    Chains Phase 1 -> Phase 2 -> Phase 3, carrying balance forward.
    Optionally extends projection into 'Post-Retirement' with zero contributions.

    Args:
        beneficiary:           Name of user in users.json
        current_year:          Override starting calendar year
        post_retirement_years: Number of years to project after retirement (0 contributions)
        withdrawal_pct:        Override withdrawal rate (uses user's setting if None)

    Returns:
        Single DataFrame spanning all phases from current age to retirement (+ post-retirement)
    """
    if current_year is None:
        current_year = date.today().year

    user = _load_user_ira_data(beneficiary)
    retirement_age = user.get("retirement_age", 65)
    
    # Use provided withdrawal_pct or get from user data, default to 6%
    if withdrawal_pct is None:
        withdrawal_pct = user.get("withdrawal_pct") or 0.06

    balance = user["current_ira_balance"]
    age = user["age"]
    year = current_year
    frames: List[DataFrame] = []

    # 1. Active working phases (1, 2, 3)
    for phase_key, label in [
        ("phase_1", "Phase 1"),
        ("phase_2", "Phase 2"),
        ("phase_3", "Phase 3"),
    ]:
        phase_cfg = user["ira_phases"][phase_key]
        end_age = (
            phase_cfg["end_age"]
            if phase_cfg["end_age"] is not None
            else retirement_age
        )
        end_age = min(end_age, retirement_age)

        if age >= end_age:
            continue

        df, balance = _project_ira_phase(
            start_balance=balance,
            start_age=age,
            end_age=end_age,
            start_year=year,
            allocation=phase_cfg["allocation"],
            beneficiary=beneficiary,
            phase_label=label,
        )

        frames.append(df)
        age = end_age
        year += len(df)

    # 2. Post-Retirement Phase (Optional)
    if post_retirement_years > 0:
        # Use Phase 3 (safest) allocation for retirement phase
        phase_cfg = user["ira_phases"]["phase_3"]
        
        df, balance = _project_ira_phase(
            start_balance=balance,
            start_age=age,
            end_age=age + post_retirement_years,
            start_year=year,
            allocation=phase_cfg["allocation"],
            beneficiary=beneficiary,
            phase_label="Phase 3",
            contribute=False,  # No contributions in retirement
        )
        frames.append(df)

    if not frames:
        return DataFrame()
    return pd.concat(frames, ignore_index=True)
