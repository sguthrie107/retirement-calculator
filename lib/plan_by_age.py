from datetime import date
from typing import Dict, Any, List, Tuple, Optional
import pandas as pd
from pandas import DataFrame

from .data_loader import load_json_file, get_fund_by_ticker
from .constants import DATA_FILES

"""
401k Retirement Plan - Age-Based Phase Projections

Phase 1 (Up to 50):  70% US Stock / 30% Foreign Stock
Phase 2 (50 to 65):  60% US Stock / 20% Foreign Stock / 20% Bonds
Phase 3 (65+):       40% US Stock / 20% Foreign Stock / 40% Bonds

US Stock:     S&P 500 Mutual Funds
Foreign Stock: Ex-US Mutual Funds
Bonds:        Total Bond Market Funds

Steven → Fidelity funds (FXAIX, FZILX, FXNAX)
Alyssa → Vanguard Admiral funds (VFIAX, VTIAX, VBTLX)
"""

# ---------------------------------------------------------------------------
# Fund provider → ticker mapping (used by custom plan)
# ---------------------------------------------------------------------------
FUND_TICKERS = {
    "fidelity": {"us": "FXAIX", "intl": "FZILX", "bond": "FXNAX"},
    "vanguard": {"us": "VFIAX", "intl": "VTIAX", "bond": "VBTLX"},
}

# Phase allocation percentages
PHASE_ALLOCATIONS = {
    "phase_1": {"us_stock": 0.70, "foreign_stock": 0.30},
    "phase_2": {"us_stock": 0.60, "foreign_stock": 0.20, "bonds": 0.20},
    "phase_3": {"us_stock": 0.40, "foreign_stock": 0.20, "bonds": 0.40},
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_user_data(beneficiary: str) -> Dict[str, Any]:
    """
    Load user-specific 401k configuration from users.json.

    Args:
        beneficiary: User name (e.g. 'Steven' or 'Alyssa')

    Returns:
        User data dictionary

    Raises:
        ValueError: If user not found in users.json
    """
    data = load_json_file(DATA_FILES["USERS"])

    for user in data.get("users", []):
        if user.get("name") == beneficiary:
            return user

    raise ValueError(f"Beneficiary '{beneficiary}' not found in users.json")


def _get_fund_projected_return(ticker: str) -> float:
    """
    Look up a fund's projected annual return from stocks.json or bonds.json.

    Returns the rate as a decimal (e.g. 0.102 for 10.2%).
    """
    for source in [DATA_FILES["STOCKS"], DATA_FILES["BONDS"]]:
        try:
            fund = get_fund_by_ticker(source, ticker)
            return fund["projected_annual_return_pct"] / 100.0
        except (ValueError, KeyError):
            continue
    raise ValueError(f"Fund '{ticker}' not found in stocks.json or bonds.json")


def _calculate_blended_return(allocation: Dict[str, Dict]) -> float:
    """Weighted average annual return across all funds in an allocation."""
    return sum(
        cfg["pct"] * _get_fund_projected_return(cfg["ticker"])
        for cfg in allocation.values()
    )


def _format_allocation_label(allocation: Dict[str, Dict]) -> str:
    """Human-readable allocation string, e.g. '70% US Stock / 30% Intl Stock'."""
    labels = {
        "us_stock": "US Stock",
        "foreign_stock": "Intl Stock",
        "bonds": "Bonds",
    }
    return " / ".join(
        f"{int(cfg['pct'] * 100)}% {labels.get(key, key)}"
        for key, cfg in allocation.items()
    )


def _project_phase(
    start_balance: float,
    start_age: int,
    end_age: int,
    start_year: int,
    salary: float,
    contribution_pct: float,
    match_pct: float,
    salary_increase_pct: float,
    allocation: Dict[str, Dict],
    beneficiary: str,
    phase_label: str,
) -> Tuple[DataFrame, float, float]:
    """
    Project 401k balance year-by-year for a single phase.

    Args:
        start_balance:      Balance at beginning of phase
        start_age:          Age at start of phase
        end_age:            Age at end of phase (exclusive)
        start_year:         Calendar year the phase begins
        salary:             Annual salary at phase start
        contribution_pct:   Employee contribution rate (decimal)
        match_pct:          Employer match rate (decimal)
        salary_increase_pct: Annual salary growth rate (decimal)
        allocation:         Dict of asset_class → {pct, ticker}
        beneficiary:        Name for labeling rows
        phase_label:        e.g. 'Phase 1'

    Returns:
        (DataFrame of projections, ending balance, ending salary)
    """
    blended_return = _calculate_blended_return(allocation)
    alloc_label = _format_allocation_label(allocation)

    rows: List[Dict[str, Any]] = []
    balance = start_balance
    current_salary = salary

    for i in range(end_age - start_age):
        year = start_year + i
        age = start_age + i + 1

        employee_contrib = current_salary * contribution_pct
        employer_match = current_salary * match_pct
        total_contrib = employee_contrib + employer_match

        balance += total_contrib
        growth = balance * blended_return
        balance += growth

        rows.append({
            "beneficiary": beneficiary,
            "year": year,
            "age": age,
            "phase": phase_label,
            "salary": round(current_salary, 2),
            "employee_contribution": round(employee_contrib, 2),
            "employer_match": round(employer_match, 2),
            "total_contribution": round(total_contrib, 2),
            "growth": round(growth, 2),
            "balance": round(balance, 2),
            "allocation": alloc_label,
        })

        current_salary *= (1 + salary_increase_pct)

    return DataFrame(rows), balance, current_salary


# ---------------------------------------------------------------------------
# Phase controller functions
# ---------------------------------------------------------------------------

def retirement_401k_age_based_plan_phase_1(
    beneficiary: str,
    age: int,
    current_year: int = None,
    portfolio: DataFrame = None,
) -> DataFrame:
    """
    Phase 1 of the 401k plan — current age through age 50.

    Allocation: 70% US Stock (S&P 500), 30% Foreign Stock (Ex-US).

    Args:
        beneficiary:  Name of user ('Steven' or 'Alyssa')
        age:          Current age (must be < phase 1 end age)
        current_year: Override starting calendar year
        portfolio:    Existing DataFrame to append to

    Returns:
        DataFrame with year-by-year projections through age 50
    """
    if current_year is None:
        current_year = date.today().year

    user = _load_user_data(beneficiary)
    contrib = user["contribution_details"]
    phase_cfg = user["phases"]["phase_1"]
    end_age = phase_cfg["end_age"]

    if age >= end_age:
        raise ValueError(f"Age {age} is not valid for Phase 1 (must be < {end_age})")

    df, _, _ = _project_phase(
        start_balance=user["current_401k_balance"],
        start_age=age,
        end_age=end_age,
        start_year=current_year,
        salary=contrib["annual_salary"],
        contribution_pct=contrib["annual_contribution_pct"],
        match_pct=contrib["company_match_pct"],
        salary_increase_pct=contrib["salary_increase_pct"],
        allocation=phase_cfg["allocation"],
        beneficiary=beneficiary,
        phase_label="Phase 1",
    )

    if portfolio is not None and not portfolio.empty:
        return pd.concat([portfolio, df], ignore_index=True)
    return df


def retirement_401k_age_based_plan_phase_2(
    beneficiary: str,
    age: int,
    current_year: int = None,
    portfolio: DataFrame = None,
    starting_balance: float = None,
    starting_salary: float = None,
) -> DataFrame:
    """
    Phase 2 of the 401k plan — age 50 through 65.

    Allocation: 60% US Stock, 20% Foreign Stock, 20% Bonds.

    Args:
        beneficiary:      Name of user
        age:              Age at start of phase (typically 50)
        current_year:     Override starting calendar year
        portfolio:        Existing DataFrame to append to
        starting_balance: Override starting balance (e.g. from Phase 1 ending)
        starting_salary:  Override starting salary (e.g. from Phase 1 ending)

    Returns:
        DataFrame with year-by-year projections through age 65
    """
    if current_year is None:
        current_year = date.today().year

    user = _load_user_data(beneficiary)
    contrib = user["contribution_details"]
    phase_cfg = user["phases"]["phase_2"]
    end_age = phase_cfg["end_age"]

    balance = starting_balance if starting_balance is not None else user["current_401k_balance"]
    salary = starting_salary if starting_salary is not None else contrib["annual_salary"]

    if age >= end_age:
        raise ValueError(f"Age {age} is not valid for Phase 2 (must be < {end_age})")

    df, _, _ = _project_phase(
        start_balance=balance,
        start_age=age,
        end_age=end_age,
        start_year=current_year,
        salary=salary,
        contribution_pct=contrib["annual_contribution_pct"],
        match_pct=contrib["company_match_pct"],
        salary_increase_pct=contrib["salary_increase_pct"],
        allocation=phase_cfg["allocation"],
        beneficiary=beneficiary,
        phase_label="Phase 2",
    )

    if portfolio is not None and not portfolio.empty:
        return pd.concat([portfolio, df], ignore_index=True)
    return df


def retirement_401k_age_based_plan_phase_3(
    beneficiary: str,
    age: int,
    retirement_age: int = None,
    current_year: int = None,
    portfolio: DataFrame = None,
    starting_balance: float = None,
    starting_salary: float = None,
) -> DataFrame:
    """
    Phase 3 of the 401k plan — age 65 through retirement.

    Allocation: 40% US Stock, 20% Foreign Stock, 40% Bonds.

    Args:
        beneficiary:      Name of user
        age:              Age at start of phase (typically 65)
        retirement_age:   When to stop projecting (defaults to user config)
        current_year:     Override starting calendar year
        portfolio:        Existing DataFrame to append to
        starting_balance: Override starting balance
        starting_salary:  Override starting salary

    Returns:
        DataFrame with year-by-year projections through retirement age
    """
    if current_year is None:
        current_year = date.today().year

    user = _load_user_data(beneficiary)
    contrib = user["contribution_details"]
    phase_cfg = user["phases"]["phase_3"]
    end_age = retirement_age or user.get("retirement_age", 70)

    balance = starting_balance if starting_balance is not None else user["current_401k_balance"]
    salary = starting_salary if starting_salary is not None else contrib["annual_salary"]

    if age >= end_age:
        raise ValueError(f"Age {age} is not valid for Phase 3 (must be < {end_age})")

    df, _, _ = _project_phase(
        start_balance=balance,
        start_age=age,
        end_age=end_age,
        start_year=current_year,
        salary=salary,
        contribution_pct=contrib["annual_contribution_pct"],
        match_pct=contrib["company_match_pct"],
        salary_increase_pct=contrib["salary_increase_pct"],
        allocation=phase_cfg["allocation"],
        beneficiary=beneficiary,
        phase_label="Phase 3",
    )

    if portfolio is not None and not portfolio.empty:
        return pd.concat([portfolio, df], ignore_index=True)
    return df


# ---------------------------------------------------------------------------
# Full multi-phase plan
# ---------------------------------------------------------------------------

def retirement_401k_full_plan(
    beneficiary: str,
    current_year: int = None,
) -> DataFrame:
    """
    Run a complete 3-phase 401k projection for a stored user.

    Chains Phase 1 → Phase 2 → Phase 3, carrying balance and salary forward.

    Args:
        beneficiary:  Name of user in users.json
        current_year: Override starting calendar year

    Returns:
        Single DataFrame spanning all phases from current age to retirement
    """
    if current_year is None:
        current_year = date.today().year

    user = _load_user_data(beneficiary)
    contrib = user["contribution_details"]
    retirement_age = user.get("retirement_age", 65)

    balance = user["current_401k_balance"]
    salary = contrib["annual_salary"]
    age = user["age"]
    year = current_year
    frames: List[DataFrame] = []

    for phase_key, label in [
        ("phase_1", "Phase 1"),
        ("phase_2", "Phase 2"),
        ("phase_3", "Phase 3"),
    ]:
        phase_cfg = user["phases"][phase_key]
        end_age = phase_cfg["end_age"] if phase_cfg["end_age"] is not None else retirement_age
        end_age = min(end_age, retirement_age)

        if age >= end_age:
            continue

        df, balance, salary = _project_phase(
            start_balance=balance,
            start_age=age,
            end_age=end_age,
            start_year=year,
            salary=salary,
            contribution_pct=contrib["annual_contribution_pct"],
            match_pct=contrib["company_match_pct"],
            salary_increase_pct=contrib["salary_increase_pct"],
            allocation=phase_cfg["allocation"],
            beneficiary=beneficiary,
            phase_label=label,
        )

        frames.append(df)
        age = end_age
        year += len(df)

    if not frames:
        return DataFrame()
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Custom plan (for interactive / manual input)
# ---------------------------------------------------------------------------

def retirement_401k_custom_plan(
    name: str,
    age: int,
    salary: float,
    contribution_pct: float,
    match_pct: float,
    salary_increase_pct: float,
    retirement_age: int,
    starting_balance: float = 0.0,
    fund_provider: str = "Vanguard",
    current_year: int = None,
) -> DataFrame:
    """
    Run a 401k projection with manually-supplied inputs.

    Uses the same 3-phase glide path as stored users, but allows any parameter
    to be provided by the caller (e.g. from an interactive CLI).

    Args:
        name:                Display name for rows
        age:                 Current age
        salary:              Current annual salary
        contribution_pct:    Employee contribution rate (decimal, e.g. 0.15)
        match_pct:           Employer match rate (decimal, e.g. 0.05)
        salary_increase_pct: Annual salary growth rate (decimal, e.g. 0.03)
        retirement_age:      Age to project through
        starting_balance:    Current 401k balance (default 0)
        fund_provider:       'Vanguard' or 'Fidelity'
        current_year:        Override starting calendar year

    Returns:
        DataFrame with year-by-year projections across all phases
    """
    if current_year is None:
        current_year = date.today().year

    provider = fund_provider.lower()
    if provider not in FUND_TICKERS:
        raise ValueError(f"Unsupported provider '{fund_provider}'. Use 'Vanguard' or 'Fidelity'.")

    t = FUND_TICKERS[provider]

    # Build phase allocation configs using the standard percentages
    phases = {
        "phase_1": {
            "end_age": 50,
            "allocation": {
                "us_stock": {"pct": 0.70, "ticker": t["us"]},
                "foreign_stock": {"pct": 0.30, "ticker": t["intl"]},
            },
        },
        "phase_2": {
            "end_age": 65,
            "allocation": {
                "us_stock": {"pct": 0.60, "ticker": t["us"]},
                "foreign_stock": {"pct": 0.20, "ticker": t["intl"]},
                "bonds": {"pct": 0.20, "ticker": t["bond"]},
            },
        },
        "phase_3": {
            "end_age": None,
            "allocation": {
                "us_stock": {"pct": 0.40, "ticker": t["us"]},
                "foreign_stock": {"pct": 0.20, "ticker": t["intl"]},
                "bonds": {"pct": 0.40, "ticker": t["bond"]},
            },
        },
    }

    balance = starting_balance
    current_salary = salary
    current_age = age
    year = current_year
    frames: List[DataFrame] = []

    for phase_key, label in [
        ("phase_1", "Phase 1"),
        ("phase_2", "Phase 2"),
        ("phase_3", "Phase 3"),
    ]:
        cfg = phases[phase_key]
        end_age = cfg["end_age"] if cfg["end_age"] is not None else retirement_age
        end_age = min(end_age, retirement_age)

        if current_age >= end_age:
            continue

        df, balance, current_salary = _project_phase(
            start_balance=balance,
            start_age=current_age,
            end_age=end_age,
            start_year=year,
            salary=current_salary,
            contribution_pct=contribution_pct,
            match_pct=match_pct,
            salary_increase_pct=salary_increase_pct,
            allocation=cfg["allocation"],
            beneficiary=name,
            phase_label=label,
        )

        frames.append(df)
        current_age = end_age
        year += len(df)

    if not frames:
        return DataFrame()
    return pd.concat(frames, ignore_index=True)
