from datetime import date
from typing import Dict, Any, List, Tuple, Optional
import pandas as pd
from pandas import DataFrame

from .data_loader import load_json_file, get_fund_by_ticker
from .constants import DATA_FILES
from .calculator_utils import compute_contribution_pct_for_year

"""
401k Retirement Plan - Age-Based Phase Projections

Phase 1 (Up to 50):  70% US Stock / 30% Foreign Stock
Phase 2 (50 to 65):  60% US Stock / 20% Foreign Stock / 20% Bonds
Phase 3 (65+):       40% US Stock / 20% Foreign Stock / 40% Bonds

US Stock:     S&P 500 Mutual Funds
Foreign Stock: Ex-US Mutual Funds
Bonds:        Total Bond Market Funds

Steven → Fidelity funds (FXAIX, FSGGX, FXNAX)
Alyssa → Vanguard Admiral funds (VFIAX, VTIAX, VBTLX)
"""

# ---------------------------------------------------------------------------
# Fund provider → ticker mapping (used by custom plan)
# ---------------------------------------------------------------------------
FUND_TICKERS = {
    "fidelity": {"us": "FXAIX", "intl": "FSGGX", "bond": "FXNAX"},
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


def _get_fund_yield_and_appreciation(ticker: str) -> Tuple[float, float]:
    """
    Get dividend/coupon yield and price appreciation components separately.
    
    Returns:
        (yield_pct, appreciation_pct) as decimals
        
    For example, a stock fund with 10.2% total return and 1.6% dividend yield
    would return (0.016, 0.086)
    """
    for source_name, source_file in [("stocks", DATA_FILES["STOCKS"]), ("bonds", DATA_FILES["BONDS"])]:
        try:
            fund = get_fund_by_ticker(source_file, ticker)
            total_return = fund["projected_annual_return_pct"] / 100.0
            
            if source_name == "stocks":
                # For stocks, use dividend_yield_pct
                yield_pct = fund.get("dividend_yield_pct", 0) / 100.0
            else:
                # For bonds, use current_yield_pct
                yield_pct = fund.get("current_yield_pct", 0) / 100.0
            
            # Price appreciation = total return - yield
            appreciation_pct = total_return - yield_pct
            
            return yield_pct, appreciation_pct
        except (ValueError, KeyError):
            continue
    
    raise ValueError(f"Fund '{ticker}' not found in stocks.json or bonds.json")


def _calculate_blended_yield_and_appreciation(allocation: Dict[str, Dict]) -> Tuple[float, float]:
    """
    Calculate weighted average yield and appreciation across all funds in an allocation.
    
    Returns:
        (blended_yield, blended_appreciation) as decimals
    """
    blended_yield = 0.0
    blended_appreciation = 0.0
    
    for key, cfg in allocation.items():
        pct = cfg["pct"]
        ticker = cfg["ticker"]
        yield_pct, appreciation_pct = _get_fund_yield_and_appreciation(ticker)
        
        blended_yield += pct * yield_pct
        blended_appreciation += pct * appreciation_pct
    
    return blended_yield, blended_appreciation


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


def calculate_annualized_return(projection_df: DataFrame) -> float:
    """
    Calculate the average annualized return (CAGR) from a projection DataFrame.
    
    Uses the Compound Annual Growth Rate formula:
    CAGR = (Ending Value / Beginning Value)^(1/n) - 1
    where n is the number of years
    
    Args:
        projection_df: DataFrame from _project_phase or similar projection function
        
    Returns:
        Annualized return rate as a decimal (e.g. 0.1105 for 11.05%)
    """
    if projection_df.empty or len(projection_df) < 2:
        return 0.0
    
    # Get starting balance (first year balance minus contributions and growth added that year)
    first_row = projection_df.iloc[0]
    starting_balance = first_row["balance"] - first_row["total_contribution"] - first_row["growth"]
    
    # Get ending balance
    ending_balance = projection_df.iloc[-1]["balance"]
    
    # Number of years
    num_years = len(projection_df)
    
    if starting_balance <= 0 or num_years <= 0:
        return 0.0
    
    cagr = (ending_balance / starting_balance) ** (1 / num_years) - 1
    return cagr


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
    match_basis: str = "salary",
    contribution_details: Optional[Dict[str, Any]] = None,
    contribution_pct_boost: float = 0.0,
) -> Tuple[DataFrame, float, float]:
    """
    Project 401k balance year-by-year for a single phase with dividend/yield reinvestment.

    Separates dividend/coupon yields from price appreciation and reinvests yields.
    Rebalances portfolio every 2 years.

    Args:
        start_balance:      Balance at beginning of phase
        start_age:          Age at start of phase
        end_age:            Age at end of phase (exclusive)
        start_year:         Calendar year the phase begins
        salary:             Annual salary at phase start
        contribution_pct:   Employee contribution rate (decimal)
        match_pct:          Employer match rate (decimal)
        match_basis:        'salary' => % of salary; 'employee' => % of employee contribution
        salary_increase_pct: Annual salary growth rate (decimal)
        allocation:         Dict of asset_class → {pct, ticker}
        beneficiary:        Name for labeling rows
        phase_label:        e.g. 'Phase 1'

    Returns:
        (DataFrame of projections, ending balance, ending salary)
    """
    blended_yield, blended_appreciation = _calculate_blended_yield_and_appreciation(allocation)
    alloc_label = _format_allocation_label(allocation)

    rows: List[Dict[str, Any]] = []
    balance = start_balance
    current_salary = salary
    years_since_rebalance = 0

    for i in range(end_age - start_age + 1):
        year = start_year + i
        age = start_age + i

        effective_contribution_pct = compute_contribution_pct_for_year(
            contribution_details or {},
            year,
            base_pct_override=contribution_pct,
            pct_boost=contribution_pct_boost,
        )

        employee_contrib = current_salary * effective_contribution_pct
        if match_basis == "employee":
            employer_match = employee_contrib * match_pct
        else:
            effective_match_pct = min(match_pct, effective_contribution_pct)
            employer_match = current_salary * effective_match_pct
        total_contrib = employee_contrib + employer_match

        # Model periodic contributions through the year instead of an upfront lump sum.
        # Use a mid-year convention so contributions receive ~half-year growth on average.
        growth_base = balance + (total_contrib / 2)

        # Calculate separate components of growth
        # 1. Dividend/coupon yield (reinvested)
        dividend_income = growth_base * blended_yield

        # 2. Price appreciation
        price_appreciation = growth_base * blended_appreciation
        
        # Total growth
        growth = dividend_income + price_appreciation
        balance += total_contrib + growth
        
        # Track years since last rebalance for metadata
        years_since_rebalance += 1
        is_rebalance_year = (years_since_rebalance % 2 == 0)
        if is_rebalance_year:
            years_since_rebalance = 0

        rows.append({
            "beneficiary": beneficiary,
            "year": year,
            "age": age,
            "phase": phase_label,
            "salary": round(current_salary, 2),
            "employee_contribution": round(employee_contrib, 2),
            "employer_match": round(employer_match, 2),
            "total_contribution": round(total_contrib, 2),
            "dividend_income": round(dividend_income, 2),
            "price_appreciation": round(price_appreciation, 2),
            "growth": round(growth, 2),
            "balance": round(balance, 2),
            "allocation": alloc_label,
            "rebalanced": is_rebalance_year,
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
    phase_cfg = user["401k_phases"]["phase_1"]
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
            contribution_details=contrib,
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
    phase_cfg = user["401k_phases"]["phase_2"]
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
        contribution_details=contrib,
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
    phase_cfg = user["401k_phases"]["phase_3"]
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
        contribution_details=contrib,
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
    post_retirement_years: int = 0,
    withdrawal_pct: float = None,
    match_pct_override: float = None,
    match_basis: str = "salary",
    contribution_pct_override: float = None,
    contribution_pct_boost: float = 0.0,
) -> DataFrame:
    """
    Run a complete 3-phase 401k projection for a stored user.

    Chains Phase 1 → Phase 2 → Phase 3, carrying balance and salary forward.
    Optionally continues 'Post-Retirement' using Phase 3 allocation and zero contributions.

    Args:
        beneficiary:           Name of user in users.json
        current_year:          Override starting calendar year
        post_retirement_years: Number of years to project after retirement (0 contributions)
        withdrawal_pct:        Override withdrawal rate (uses user's setting if None)
        match_pct_override:    Override employer match rate (decimal, e.g. 0.03 for 3%)
        match_basis:           'salary' => % of salary; 'employee' => % of employee contribution
        contribution_pct_override: Override employee contribution rate (decimal, e.g. 0.07)

    Returns:
        Single DataFrame spanning all phases from current age to retirement (+ post-retirement)
        Includes withdrawal tracking in Phase 3
    """
    if current_year is None:
        current_year = date.today().year

    user = _load_user_data(beneficiary)
    contrib = user["contribution_details"]
    retirement_age = user.get("retirement_age", 65)
    
    # Use provided withdrawal_pct or get from user data, default to 6%
    if withdrawal_pct is None:
        withdrawal_pct = user.get("withdrawal_pct") or 0.06

    balance = user["current_401k_balance"]
    salary = contrib["annual_salary"]
    age = user["age"]
    year = current_year
    frames: List[DataFrame] = []

    # 1. Active working phases (1, 2, 3)
    for phase_key, label in [
        ("phase_1", "Phase 1"),
        ("phase_2", "Phase 2"),
        ("phase_3", "Phase 3"),
    ]:
        phase_cfg = user["401k_phases"][phase_key]
        end_age = phase_cfg["end_age"] if phase_cfg["end_age"] is not None else retirement_age
        end_age = min(end_age, retirement_age)

        if age >= end_age:
            continue

        effective_match_pct = match_pct_override if match_pct_override is not None else contrib["company_match_pct"]
        effective_contribution_pct = (
            contribution_pct_override
            if contribution_pct_override is not None
            else contrib["annual_contribution_pct"]
        )

        df, balance, salary = _project_phase(
            start_balance=balance,
            start_age=age,
            end_age=end_age,
            start_year=year,
            salary=salary,
            contribution_pct=effective_contribution_pct,
            match_pct=effective_match_pct,
            match_basis=match_basis,
            salary_increase_pct=contrib["salary_increase_pct"],
            allocation=phase_cfg["allocation"],
            beneficiary=beneficiary,
            phase_label=label,
            contribution_details=contrib,
            contribution_pct_boost=contribution_pct_boost,
        )

        frames.append(df)
        age = end_age
        year += len(df)

    # 2. Post-Retirement Phase (Optional)
    if post_retirement_years > 0:
        # Use Phase 3 allocation (conservative/safe)
        phase_cfg = user["401k_phases"]["phase_3"]
        
        df, balance, _ = _project_phase(
            start_balance=balance,
            start_age=age,
            end_age=age + post_retirement_years,
            start_year=year,
            salary=0,  # No salary in retirement
            contribution_pct=0,  # No contributions
            match_pct=0,
            match_basis="salary",
            salary_increase_pct=0,
            allocation=phase_cfg["allocation"],
            beneficiary=beneficiary,
            phase_label="Phase 3",
            contribution_details=contrib,
            contribution_pct_boost=contribution_pct_boost,
        )
        frames.append(df)

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
    post_retirement_years: int = 0,
    withdrawal_pct: float = 0.06,
) -> DataFrame:
    """
    Run a 401k projection with manually-supplied inputs.

    Uses the same 3-phase glide path as stored users, but allows any parameter
    to be provided by the caller (e.g. from an interactive CLI).
    Optionally continues 'Post-Retirement' using Phase 3 allocation and zero contributions.

    Args:
        name:                  Display name for rows
        age:                   Current age
        salary:                Current annual salary
        contribution_pct:      Employee contribution rate (decimal, e.g. 0.15)
        match_pct:             Employer match rate (decimal, e.g. 0.05)
        salary_increase_pct:   Annual salary growth rate (decimal, e.g. 0.03)
        retirement_age:        Age to project through
        starting_balance:      Current 401k balance (default 0)
        fund_provider:         'Vanguard' or 'Fidelity'
        current_year:          Override starting calendar year
        post_retirement_years: Number of years to project after retirement (0 contributions)
        withdrawal_pct:        Withdrawal rate in retirement (default 6%)

    Returns:
        DataFrame with year-by-year projections across all phases
        Includes withdrawal tracking for Phase 3
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

    # 1. Active working phases (1, 2, 3)
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

    # 2. Post-Retirement Phase (Optional)
    if post_retirement_years > 0:
        # Use Phase 3 (safest) allocation
        phase_cfg = phases["phase_3"]
        
        df, balance, _ = _project_phase(
            start_balance=balance,
            start_age=current_age,
            end_age=current_age + post_retirement_years,
            start_year=year,
            salary=0,  # No salary
            contribution_pct=0,  # No contributions
            match_pct=0,
            salary_increase_pct=0,
            allocation=phase_cfg["allocation"],
            beneficiary=name,
            phase_label="Phase 3",
        )
        frames.append(df)

    if not frames:
        return DataFrame()
    return pd.concat(frames, ignore_index=True)
