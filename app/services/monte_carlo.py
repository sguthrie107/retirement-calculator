"""Monte Carlo retirement stress testing service.

This module is intentionally separate from deterministic projections to preserve the
existing baseline engine unchanged.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from lib.calculator_utils import load_users_data, load_user_profile as _load_user_profile
from lib.data_loader import load_json_file
from ..models import Account, ActualBalance, StressTestResult, User
from .rental_properties import (
    DEFAULT_CONVERT_TO_RENTAL_AFTER_YEARS,
    DEFAULT_MAINTENANCE_RATE,
    DEFAULT_RENT_PREMIUM_OVER_PI,
    DEFAULT_VACANCY_RATE,
    apply_rental_assets_for_year,
    housing_total_equity,
    initialize_rental_asset_states,
    load_household_assets_for_user,
)


DEFAULT_SIMULATION_COUNT = 10000
MIN_SIMULATION_COUNT = 5000
DEFAULT_INFLATION_PCT = 3.0
DEFAULT_LIFE_EXPECTANCY_AGE = 88
DEFAULT_WITHDRAWAL_PCT = 0.05
DEFAULT_TARGET_VOLATILITY_PCT = 13.5
DEFAULT_SUCCESS_THRESHOLD_PCT = 10.0
POST_DEBT_CONTRIBUTION_STEP_PCT = 0.01
POST_DEBT_CONTRIBUTION_CAP_PCT = 0.15
RETIREMENT_BOND_TARGET_PCT = 0.40
DEFAULT_SOCIAL_SECURITY_CLAIM_AGE = 70
SOCIAL_SECURITY_FULL_RETIREMENT_AGE = 67
SOCIAL_SECURITY_MAX_TAXABLE_EARNINGS = 176100.0
SOCIAL_SECURITY_BEND_POINT_1 = 1174.0
SOCIAL_SECURITY_BEND_POINT_2 = 7078.0
DEFAULT_INTRA_PORTFOLIO_CORRELATION = 0.90
DEFAULT_401K_CONTRIBUTION_LIMIT = 23500.0
DEFAULT_401K_CATCH_UP_AGE = 50
DEFAULT_401K_CATCH_UP_LIMIT = 7500.0
DEFAULT_401K_ENHANCED_CATCH_UP_START_AGE = 60
DEFAULT_401K_ENHANCED_CATCH_UP_END_AGE = 63
DEFAULT_401K_ENHANCED_CATCH_UP_LIMIT = 11250.0
DEFAULT_IRA_CONTRIBUTION_LIMIT = 7000.0
DEFAULT_IRA_CATCH_UP_AGE = 50
DEFAULT_IRA_CATCH_UP_LIMIT = 1000.0

BOND_LIKE_TICKERS = {
    "FXNAX",
    "FUAMX",
    "FNAX",
    "FIPDX",
    "VBTLX",
}

TICKER_ALIASES = {
    # Vanguard equivalents mapped to known fund moments
    "VFIAX": "FXAIX",
    "VTIAX": "FZILX",
    "VBTLX": "FXNAX",
}

BOGLEHEAD_3_FUND_ALLOCATION = (
    ("FXAIX", 0.60),
    ("FZILX", 0.20),
    ("FXNAX", 0.20),
)

# Rating thresholds follow a planning-oriented rubric with conservative cutoffs.
RATING_BANDS = [
    {
        "tier": 5,
        "grade": "A",
        "label": "Fortress Outlook",
        "min_probability": 92.0,
        "description": "Plan remains resilient across most stressed return paths.",
    },
    {
        "tier": 4,
        "grade": "B",
        "label": "Strong Outlook",
        "min_probability": 85.0,
        "description": "High likelihood of sustainability with moderate downside risk.",
    },
    {
        "tier": 3,
        "grade": "C",
        "label": "Stable but Exposed",
        "min_probability": 75.0,
        "description": "Generally viable plan but vulnerable to adverse early sequences.",
    },
    {
        "tier": 2,
        "grade": "D",
        "label": "Fragile Plan",
        "min_probability": 60.0,
        "description": "Meaningful failure probability under plausible market stress.",
    },
    {
        "tier": 1,
        "grade": "F",
        "label": "At Risk",
        "min_probability": 0.0,
        "description": "Plan likely needs contribution, spending, or horizon adjustments.",
    },
]


@dataclass
class AssetMoments:
    mean_return: float
    volatility: float


def _load_household_debts_for_users(usernames: list[str]) -> list[dict[str, Any]]:
    users_data = load_users_data()
    debts = users_data.get("household_debts", [])
    target = set(usernames)

    applicable: list[dict[str, Any]] = []
    for debt in debts:
        participants = set(debt.get("participants", []))
        if not participants:
            continue
        if participants == target:
            applicable.append(debt)

    return applicable


def _load_household_assets_for_users(usernames: list[str]) -> list[dict[str, Any]]:
    users_data = load_users_data()
    assets = users_data.get("household_assets", [])
    target = set(usernames)

    applicable: list[dict[str, Any]] = []
    is_individual = len(usernames) == 1

    for asset in assets:
        participants = set(asset.get("participants", []))
        if not participants:
            continue

        if is_individual:
            include_individual = bool(asset.get("include_in_individual_analysis", False))
            if include_individual and usernames[0] in participants:
                applicable.append(asset)
            continue

        if participants == target:
            applicable.append(asset)

    return applicable


def _build_housing_assets_assumption(asset_configs: list[dict[str, Any]], *, joint: bool) -> dict[str, Any]:
    serialized_assets: list[dict[str, Any]] = []

    for asset in asset_configs:
        current_home_value = float(asset.get("current_home_value", 0.0))
        loan_balance = float(asset.get("loan_balance", 0.0))
        serialized_assets.append(
            {
                "name": asset.get("name") or "Property",
                "asset_type": asset.get("asset_type", "residential_real_estate"),
                "participants": list(asset.get("participants", [])),
                "current_home_value": round(current_home_value, 2),
                "loan_balance": round(loan_balance, 2),
                "current_equity": round(max(current_home_value - loan_balance, 0.0), 2),
                "annual_interest_rate": float(asset.get("annual_interest_rate", 0.0)),
                "monthly_payment": round(float(asset.get("monthly_payment", 0.0)), 2),
                "monthly_escrow": round(float(asset.get("monthly_escrow", 0.0)), 2),
                "annual_appreciation_rate": float(
                    asset.get("conservative_annual_appreciation_rate", 0.0)
                ),
                "convert_to_rental_after_years": int(
                    asset.get(
                        "convert_to_rental_after_years",
                        DEFAULT_CONVERT_TO_RENTAL_AFTER_YEARS,
                    )
                ),
                "rental_monthly_premium_over_p_and_i": round(
                    float(
                        asset.get(
                            "rental_monthly_premium_over_p_and_i",
                            DEFAULT_RENT_PREMIUM_OVER_PI,
                        )
                    ),
                    2,
                ),
                "vacancy_rate": float(asset.get("vacancy_rate", DEFAULT_VACANCY_RATE)),
                "maintenance_rate": float(
                    asset.get("maintenance_rate", DEFAULT_MAINTENANCE_RATE)
                ),
                "include_in_individual_analysis": bool(
                    asset.get("include_in_individual_analysis", False)
                ),
            }
        )

    return {
        "enabled": len(serialized_assets) > 0,
        "assets": serialized_assets,
        "counting_rule": (
            "Counted once for household projections"
            if joint
            else "Included for participant users when individual analysis is enabled"
        ),
        "treatment": (
            "Residential equity is included in terminal net worth; rental conversion cashflow is modeled annually."
        ),
        "ownership_treatment": (
            "Individual analysis uses pro-rata ownership share for multi-participant assets."
            if not joint
            else "Household analysis models full shared-asset economics once."
        ),
        "cashflow_treatment": {
            "pre_retirement": "Net rent is added to investable annual contributions before retirement.",
            "post_retirement": "Net rent reduces portfolio withdrawals after retirement.",
            "rent_basis": "Monthly rent starts at P&I payment plus configured rental premium and then grows with inflation after conversion.",
            "net_cashflow_formula": "Net annual rent = gross rent - vacancy - maintenance - annual mortgage principal & interest.",
            "escrow_treatment": "Escrow is tracked in config but excluded from the Monte Carlo rental cashflow formula.",
            "equity_treatment": "Remaining housing equity is included in terminal assets / net worth.",
        },
    }


def _load_household_retirement_spending_for_users(usernames: list[str]) -> dict[str, Any] | None:
    users_data = load_users_data()
    spending_configs = users_data.get("household_retirement_spending", [])
    target = set(usernames)

    for config in spending_configs:
        participants = set(config.get("participants", []))
        if participants == target:
            return config

    return None


def _load_retirement_spending_for_user(username: str) -> dict[str, Any] | None:
    """Find the most-specific spending profile for a single user.

    Priority:
    1. An exact single-participant match (``participants == [username]``).
    2. The first multi-participant household config that includes the user;
       all monetary expense fields are pro-rated by the number of participants.

    Returns ``None`` when no applicable config is found.
    """
    users_data = load_users_data()
    spending_configs = users_data.get("household_retirement_spending", [])

    # 1 — exact single-user match
    for config in spending_configs:
        participants = list(config.get("participants", []))
        if participants == [username]:
            return config

    # 2 — household config that includes this user (pro-rate by share)
    for config in spending_configs:
        participants = list(config.get("participants", []))
        if username in participants and len(participants) > 1:
            n = len(participants)
            prorated: dict[str, Any] = dict(config)
            for key in (
                "annual_general_living_expenses",
                "annual_medical_quality_of_life_expenses",
            ):
                if key in prorated:
                    prorated[key] = float(prorated[key]) / n
            prorated["_prorated_note"] = (
                f"Pro-rated 1/{n} individual share of household spending "
                f"(household has {n} participants)."
            )
            return prorated

    return None


def _build_fund_moments() -> dict[str, AssetMoments]:
    stocks = load_json_file("stocks.json").get("funds", [])
    bonds = load_json_file("bonds.json").get("funds", [])

    moments: dict[str, AssetMoments] = {}
    for fund in stocks + bonds:
        ticker = fund.get("ticker")
        if not ticker:
            continue

        mean_return = float(fund.get("projected_annual_return_pct", 6.0)) / 100.0
        volatility = float(fund.get("volatility_pct", 12.0)) / 100.0
        moments[ticker.upper()] = AssetMoments(mean_return=mean_return, volatility=volatility)

    # Map equivalent tickers to preserve realistic volatility/return assumptions.
    for alias_ticker, canonical in TICKER_ALIASES.items():
        if canonical in moments and alias_ticker not in moments:
            moments[alias_ticker] = moments[canonical]

    return moments


def _is_bond_like_ticker(ticker: str) -> bool:
    return ticker.upper() in BOND_LIKE_TICKERS


def _normalize_allocation_weights(allocation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    total_weight = sum(float(item.get("pct", 0.0)) for item in allocation.values())
    if total_weight <= 0:
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    for key, item in allocation.items():
        normalized[key] = {
            **item,
            "pct": float(item.get("pct", 0.0)) / total_weight,
        }
    return normalized


def _rebalance_allocation_to_bond_target(allocation: dict[str, Any], bond_target: float = RETIREMENT_BOND_TARGET_PCT) -> dict[str, Any]:
    normalized = _normalize_allocation_weights(allocation)
    if not normalized:
        return normalized

    bond_keys: list[str] = []
    equity_keys: list[str] = []
    for key, alloc in normalized.items():
        ticker = str(alloc.get("ticker", "")).upper()
        if _is_bond_like_ticker(ticker):
            bond_keys.append(key)
        else:
            equity_keys.append(key)

    if not bond_keys or not equity_keys:
        return normalized

    current_bond_weight = sum(float(normalized[key].get("pct", 0.0)) for key in bond_keys)
    current_equity_weight = sum(float(normalized[key].get("pct", 0.0)) for key in equity_keys)

    if current_bond_weight <= 0 or current_equity_weight <= 0:
        return normalized

    target_bond = max(0.0, min(1.0, bond_target))
    target_equity = 1.0 - target_bond

    rebalanced: dict[str, dict[str, Any]] = {}
    for key, alloc in normalized.items():
        alloc_copy = dict(alloc)
        if key in bond_keys:
            alloc_copy["pct"] = float(alloc_copy.get("pct", 0.0)) / current_bond_weight * target_bond
        else:
            alloc_copy["pct"] = float(alloc_copy.get("pct", 0.0)) / current_equity_weight * target_equity
        rebalanced[key] = alloc_copy

    return rebalanced


def _pick_phase(phases: dict[str, Any], age: int) -> dict[str, Any]:
    ordered = []
    for _, phase in phases.items():
        end_age = phase.get("end_age")
        ordered.append((999 if end_age is None else int(end_age), phase))
    ordered.sort(key=lambda p: p[0])

    for end_age, phase in ordered:
        if age <= end_age:
            return phase

    return ordered[-1][1] if ordered else {"allocation": {}}


def _allocation_moments(allocation: dict[str, Any], fund_moments: dict[str, AssetMoments]) -> tuple[float, float]:
    # Independence assumption for cross-fund residual risk keeps implementation simple
    # while still capturing concentration and dispersion by weight.
    weighted_mean = 0.0
    weighted_variance = 0.0

    total_weight = 0.0
    for _, alloc in allocation.items():
        total_weight += float(alloc.get("pct", 0.0))

    if total_weight <= 0:
        return 0.06, 0.12

    for _, alloc in allocation.items():
        weight = float(alloc.get("pct", 0.0)) / total_weight
        ticker = str(alloc.get("ticker", "")).upper()
        moments = fund_moments.get(ticker, AssetMoments(mean_return=0.06, volatility=0.12))

        weighted_mean += weight * moments.mean_return
        weighted_variance += (weight * moments.volatility) ** 2

    return weighted_mean, math.sqrt(max(weighted_variance, 1e-8))


def _account_phase_moments(
    user_profile: dict[str, Any],
    age: int,
    fund_moments: dict[str, AssetMoments],
    retirement_age: int,
) -> tuple[tuple[float, float], tuple[float, float]]:
    k401_phase = _pick_phase(user_profile.get("401k_phases", {}), age)
    ira_phase = _pick_phase(user_profile.get("ira_phases", {}), age)

    k401_allocation = k401_phase.get("allocation", {})
    ira_allocation = ira_phase.get("allocation", {})

    # Professional-style retirement rebalance target: 60/40 equity/bond mix at retirement+.
    if age >= retirement_age:
        k401_allocation = _rebalance_allocation_to_bond_target(k401_allocation)
        ira_allocation = _rebalance_allocation_to_bond_target(ira_allocation)

    k401_mu, k401_sigma = _allocation_moments(k401_allocation, fund_moments)
    ira_mu, ira_sigma = _allocation_moments(ira_allocation, fund_moments)

    return (k401_mu, k401_sigma), (ira_mu, ira_sigma)


def _boglehead_income_moments(fund_moments: dict[str, AssetMoments]) -> tuple[float, float]:
    weighted_mean = 0.0
    weighted_variance = 0.0

    total_weight = sum(weight for _, weight in BOGLEHEAD_3_FUND_ALLOCATION)
    if total_weight <= 0:
        return 0.06, 0.12

    for ticker, raw_weight in BOGLEHEAD_3_FUND_ALLOCATION:
        weight = raw_weight / total_weight
        moments = fund_moments.get(ticker, AssetMoments(mean_return=0.06, volatility=0.12))
        weighted_mean += weight * moments.mean_return
        weighted_variance += (weight * moments.volatility) ** 2

    return weighted_mean, math.sqrt(max(weighted_variance, 1e-8))


def _blended_portfolio_volatility(
    weighted_vol_components: list[tuple[float, float]],
    correlation: float = DEFAULT_INTRA_PORTFOLIO_CORRELATION,
) -> float:
    """Estimate blended volatility from weighted components with a constant pairwise correlation."""
    if not weighted_vol_components:
        return 0.0

    rho = max(0.0, min(1.0, float(correlation)))
    sum_diag = 0.0
    sum_cross = 0.0

    for i, (weight_i, sigma_i) in enumerate(weighted_vol_components):
        weighted_sigma_i = max(weight_i, 0.0) * max(sigma_i, 0.0)
        sum_diag += weighted_sigma_i * weighted_sigma_i
        for j in range(i + 1, len(weighted_vol_components)):
            weight_j, sigma_j = weighted_vol_components[j]
            weighted_sigma_j = max(weight_j, 0.0) * max(sigma_j, 0.0)
            sum_cross += 2.0 * rho * weighted_sigma_i * weighted_sigma_j

    return math.sqrt(max(sum_diag + sum_cross, 0.0))


def _latest_actual_balance_for_account(db: Session, user_id: int, account_type: str) -> float | None:
    rows = (
        db.query(ActualBalance)
        .join(Account)
        .filter(Account.user_id == user_id, Account.account_type == account_type)
        .order_by(ActualBalance.year.desc(), ActualBalance.recorded_at.desc())
        .all()
    )
    return float(rows[0].balance) if rows else None


def _starting_balances(db: Session, db_user: User, user_profile: dict[str, Any]) -> tuple[float, float]:
    latest_401k = _latest_actual_balance_for_account(db, db_user.id, "401k")
    latest_ira = _latest_actual_balance_for_account(db, db_user.id, "roth_ira")

    bal_401k = latest_401k if latest_401k is not None else float(user_profile.get("current_401k_balance", 0.0))
    bal_ira = latest_ira if latest_ira is not None else float(user_profile.get("current_ira_balance", 0.0))

    return max(bal_401k, 0.0), max(bal_ira, 0.0)


def _student_t(rng: random.Random, degrees_of_freedom: int = 7) -> float:
    """Sample from Student-t to inject fat tails into annual returns."""
    normal_draw = rng.gauss(0.0, 1.0)
    chi_square = rng.gammavariate(degrees_of_freedom / 2.0, 2.0)
    return normal_draw / math.sqrt(max(chi_square / degrees_of_freedom, 1e-8))


def _draw_annual_return(mu: float, sigma: float, shock: float) -> float:
    """Lognormal return transform with floor to avoid impossible <-100% returns."""
    sigma = max(sigma, 1e-6)
    log_mean = math.log1p(mu) - 0.5 * (sigma ** 2)
    gross = math.exp(log_mean + sigma * shock)
    return max(gross - 1.0, -0.95)


WITHDRAWAL_STRATEGY_PROPORTIONAL = "proportional"
WITHDRAWAL_STRATEGY_401K_FIRST = "401k_first"


def _route_withdrawal(
    withdrawal: float,
    bal_401k: float,
    bal_ira: float,
    bal_income: float,
    strategy: str,
) -> tuple[float, float, float]:
    """Route a withdrawal amount across account buckets.

    Strategies:
    - ``"proportional"``: Withdraw from all accounts in proportion to their
      current balance.  Classic risk-parity-style drawdown.
    - ``"401k_first"``: Exhaust the traditional 401k first, then the income
      bucket, then the Roth IRA last.  This preserves Roth tax-free
      compounding for as long as possible — the most tax-efficient ordering
      when holding both traditional and Roth accounts simultaneously.

    Returns:
        Tuple of (withdrawal_401k, withdrawal_ira, withdrawal_income).
    """
    if withdrawal <= 0.0:
        return 0.0, 0.0, 0.0

    if strategy == WITHDRAWAL_STRATEGY_401K_FIRST:
        w_401k = min(withdrawal, max(bal_401k, 0.0))
        remaining = withdrawal - w_401k
        w_income = min(remaining, max(bal_income, 0.0))
        remaining -= w_income
        w_ira = min(remaining, max(bal_ira, 0.0))
        return w_401k, w_ira, w_income

    # Default: proportional — withdraw from each account weighted by its balance.
    total = max(bal_401k + bal_ira + bal_income, 0.0)
    if total > 0.0:
        return (
            withdrawal * (max(bal_401k, 0.0) / total),
            withdrawal * (max(bal_ira, 0.0) / total),
            withdrawal * (max(bal_income, 0.0) / total),
        )
    return 0.0, 0.0, 0.0


def _rating_for_probability(probability_pct: float) -> dict[str, Any]:
    for band in RATING_BANDS:
        if probability_pct >= band["min_probability"]:
            return band
    return RATING_BANDS[-1]


def _indexed_contribution_limit(base_limit: float, inflation: float, years_since_start: int) -> float:
    if base_limit <= 0:
        return 0.0
    return base_limit * ((1.0 + inflation) ** max(0, years_since_start))


def _annual_401k_employee_limit(
    contribution_details: dict[str, Any],
    age: int,
    years_since_start: int,
    inflation: float,
) -> float:
    base_limit = float(
        contribution_details.get("annual_401k_contribution_limit", DEFAULT_401K_CONTRIBUTION_LIMIT)
    )
    catch_up_age = int(contribution_details.get("401k_catch_up_start_age", DEFAULT_401K_CATCH_UP_AGE))
    catch_up_limit = float(
        contribution_details.get("annual_401k_catch_up_limit", DEFAULT_401K_CATCH_UP_LIMIT)
    )
    enhanced_start_age = int(
        contribution_details.get(
            "401k_enhanced_catch_up_start_age",
            DEFAULT_401K_ENHANCED_CATCH_UP_START_AGE,
        )
    )
    enhanced_end_age = int(
        contribution_details.get(
            "401k_enhanced_catch_up_end_age",
            DEFAULT_401K_ENHANCED_CATCH_UP_END_AGE,
        )
    )
    enhanced_catch_up_limit = float(
        contribution_details.get(
            "annual_401k_enhanced_catch_up_limit",
            DEFAULT_401K_ENHANCED_CATCH_UP_LIMIT,
        )
    )

    limit = _indexed_contribution_limit(base_limit, inflation, years_since_start)
    if age >= catch_up_age:
        catch_up_to_apply = catch_up_limit
        if enhanced_start_age <= age <= enhanced_end_age:
            catch_up_to_apply = max(catch_up_limit, enhanced_catch_up_limit)
        limit += _indexed_contribution_limit(catch_up_to_apply, inflation, years_since_start)
    return max(limit, 0.0)


def _annual_ira_limit(
    contribution_details: dict[str, Any],
    age: int,
    years_since_start: int,
    inflation: float,
) -> float:
    base_limit = float(
        contribution_details.get("annual_ira_contribution_limit", DEFAULT_IRA_CONTRIBUTION_LIMIT)
    )
    catch_up_age = int(contribution_details.get("ira_catch_up_start_age", DEFAULT_IRA_CATCH_UP_AGE))
    catch_up_limit = float(
        contribution_details.get("annual_ira_catch_up_limit", DEFAULT_IRA_CATCH_UP_LIMIT)
    )

    limit = _indexed_contribution_limit(base_limit, inflation, years_since_start)
    if age >= catch_up_age:
        limit += _indexed_contribution_limit(catch_up_limit, inflation, years_since_start)
    return max(limit, 0.0)


def _annual_contribution(
    user_profile: dict[str, Any],
    salary: float,
    employee_pct_override: float | None = None,
    *,
    age: int | None = None,
    years_since_start: int = 0,
    inflation: float = 0.0,
) -> float:
    contribution = user_profile.get("contribution_details", {})
    maximize_retirement_contributions = bool(
        contribution.get("maximize_retirement_contributions", False)
    )
    employee_pct = (
        float(employee_pct_override)
        if employee_pct_override is not None
        else float(contribution.get("annual_contribution_pct", 0.0))
    )

    if maximize_retirement_contributions:
        employee_contribution = max(salary, 0.0)
    else:
        employee_contribution = salary * employee_pct

    if age is not None:
        annual_employee_limit = _annual_401k_employee_limit(
            contribution,
            age,
            years_since_start,
            inflation,
        )
        employee_contribution = min(employee_contribution, annual_employee_limit)

    company_match_pct = float(contribution.get("company_match_pct", 0.0))
    vested_pct = float(contribution.get("company_match_vested_pct", 1.0))
    company_match = salary * (company_match_pct * vested_pct)

    return max(employee_contribution, 0.0) + max(company_match, 0.0)


def _annual_ira_contribution(
    user_profile: dict[str, Any],
    years_since_start: int,
    inflation: float,
    *,
    age: int | None = None,
) -> float:
    contribution = user_profile.get("contribution_details", {})
    maximize_retirement_contributions = bool(
        contribution.get("maximize_retirement_contributions", False)
    )
    base_ira = float(contribution.get("annual_ira_contribution", 0.0))

    if maximize_retirement_contributions:
        if age is None:
            target_ira = _indexed_contribution_limit(
                DEFAULT_IRA_CONTRIBUTION_LIMIT,
                inflation,
                years_since_start,
            )
        else:
            target_ira = _annual_ira_limit(contribution, age, years_since_start, inflation)
        return max(target_ira, 0.0)

    if base_ira <= 0:
        return 0.0

    ira_contribution = base_ira * ((1.0 + inflation) ** max(0, years_since_start))
    if age is not None:
        ira_contribution = min(
            ira_contribution,
            _annual_ira_limit(contribution, age, years_since_start, inflation),
        )
    return max(ira_contribution, 0.0)


def _apply_second_career_transition(
    salary: float,
    age: int,
    contribution_details: dict[str, Any],
    transition_applied: bool,
) -> tuple[float, bool]:
    transition_age_raw = contribution_details.get("career_transition_age")
    if transition_age_raw is None:
        return salary, transition_applied

    transition_age = int(transition_age_raw)
    transition_income_pct = float(contribution_details.get("career_transition_income_pct", 1.0))
    transition_income_pct = max(0.0, min(1.0, transition_income_pct))

    if not transition_applied and age >= transition_age:
        return salary * transition_income_pct, True

    return salary, transition_applied


def _project_peak_earnings_history(user_profile: dict[str, Any], current_age: int, retirement_age: int) -> list[float]:
    contribution = user_profile.get("contribution_details", {})
    salary = float(contribution.get("annual_salary", 0.0))
    salary_growth = float(contribution.get("salary_increase_pct", 0.0))
    years = max(0, retirement_age - current_age)

    earnings: list[float] = []
    for _ in range(years):
        earnings.append(max(salary, 0.0))
        salary *= (1.0 + salary_growth)

    return earnings


def _estimate_social_security_annual_benefit(
    user_profile: dict[str, Any],
    current_age: int,
    retirement_age: int,
    claim_age: int,
) -> float:
    """Estimate annual Social Security benefit using peak-earnings approach.

    Method:
    - Project annual earnings through retirement from profile salary/growth.
    - Use top 35 capped earning years (peak-income assumption for missing years).
    - Compute PIA from AIME bend points, then adjust for delayed claiming.
    """
    earnings = _project_peak_earnings_history(user_profile, current_age, retirement_age)
    if not earnings:
        return 0.0

    capped = [min(value, SOCIAL_SECURITY_MAX_TAXABLE_EARNINGS) for value in earnings]
    top_years = sorted(capped, reverse=True)[:35]
    if not top_years:
        return 0.0

    while len(top_years) < 35:
        top_years.append(top_years[0])

    aime = sum(top_years) / (35.0 * 12.0)

    pia = (
        0.90 * min(aime, SOCIAL_SECURITY_BEND_POINT_1)
        + 0.32 * min(max(aime - SOCIAL_SECURITY_BEND_POINT_1, 0.0), SOCIAL_SECURITY_BEND_POINT_2 - SOCIAL_SECURITY_BEND_POINT_1)
        + 0.15 * max(aime - SOCIAL_SECURITY_BEND_POINT_2, 0.0)
    )

    if claim_age > SOCIAL_SECURITY_FULL_RETIREMENT_AGE:
        pia *= (1.0 + 0.08 * (claim_age - SOCIAL_SECURITY_FULL_RETIREMENT_AGE))
    elif claim_age < SOCIAL_SECURITY_FULL_RETIREMENT_AGE:
        pia *= max(0.70, 1.0 - 0.06 * (SOCIAL_SECURITY_FULL_RETIREMENT_AGE - claim_age))

    return max(pia * 12.0, 0.0)


def _apply_debt_payments_for_year(debt_state: dict[str, float], rng: random.Random) -> float:
    remaining = float(debt_state.get("remaining_principal", 0.0))
    if remaining <= 0:
        return 0.0

    annual_rate = float(debt_state.get("annual_interest_rate", 0.0))
    monthly_rate = annual_rate / 12.0
    base_payment = float(debt_state.get("base_monthly_payment", 0.0))
    additional_min = float(debt_state.get("additional_monthly_payment_min", 0.0))
    additional_max = float(debt_state.get("additional_monthly_payment_max", 0.0))

    if additional_max < additional_min:
        additional_max = additional_min

    total_paid = 0.0
    for _ in range(12):
        if remaining <= 0:
            break

        remaining *= (1.0 + monthly_rate)
        random_additional = rng.uniform(additional_min, additional_max)
        payment = min(remaining, base_payment + random_additional)
        remaining -= payment
        total_paid += payment

    debt_state["remaining_principal"] = max(remaining, 0.0)
    return total_paid


def run_stress_test(
    username: str,
    db: Session,
    simulation_count: int = DEFAULT_SIMULATION_COUNT,
    random_seed: int | None = None,
    current_year: int = 2026,
) -> StressTestResult:
    """Run Monte Carlo stress test and persist result.

    Statistical model details:
    - Fat tails: Student-t innovations (df=7)
    - Volatility clustering: GARCH-like variance regime recursion
    - Downside skew: negative shocks are amplified by a fixed stress multiplier
    - Return mapping: lognormal transform using portfolio-specific mu/sigma

    Success definition:
    - Portfolio never depletes before life expectancy
    - Final real balance >= success threshold (% of first retirement-year balance)
    """
    if simulation_count < MIN_SIMULATION_COUNT:
        raise ValueError(f"simulation_count must be >= {MIN_SIMULATION_COUNT}")

    db_user = db.query(User).filter(User.name == username).first()
    if not db_user:
        raise ValueError(f"User '{username}' not found in database")

    user_profile = _load_user_profile(username)
    fund_moments = _build_fund_moments()
    household_assets = load_household_assets_for_user(username)

    start_401k, start_ira = _starting_balances(db, db_user, user_profile)
    start_total_balance = start_401k + start_ira

    current_age = int(user_profile.get("age", 35))
    retirement_age = int(user_profile.get("retirement_age", 65))
    life_expectancy_age = DEFAULT_LIFE_EXPECTANCY_AGE
    inflation = DEFAULT_INFLATION_PCT / 100.0
    success_threshold = DEFAULT_SUCCESS_THRESHOLD_PCT / 100.0
    withdrawal_pct = float(user_profile.get("withdrawal_pct") or DEFAULT_WITHDRAWAL_PCT)
    withdrawal_strategy = str(user_profile.get("withdrawal_order") or WITHDRAWAL_STRATEGY_PROPORTIONAL)
    social_security_claim_age = int(user_profile.get("social_security_claim_age", DEFAULT_SOCIAL_SECURITY_CLAIM_AGE))
    social_security_base_annual_income = _estimate_social_security_annual_benefit(
        user_profile,
        current_age,
        retirement_age,
        social_security_claim_age,
    )

    # --- Retirement spending-needs snapshot (static projection, not simulated) ---
    individual_spending_config = _load_retirement_spending_for_user(username)
    spending_base_year = (
        int(individual_spending_config.get("base_year", current_year))
        if individual_spending_config
        else current_year
    )
    base_spending_general = (
        float(individual_spending_config.get("annual_general_living_expenses", 0.0))
        if individual_spending_config
        else 0.0
    )
    base_spending_medical = (
        float(individual_spending_config.get("annual_medical_quality_of_life_expenses", 0.0))
        if individual_spending_config
        else 0.0
    )
    base_spending_total = base_spending_general + base_spending_medical

    retirement_year = current_year + (retirement_age - current_age)
    years_base_to_retirement = max(0, retirement_year - spending_base_year)
    adj_spending_at_retirement = (
        base_spending_total * ((1.0 + inflation) ** years_base_to_retirement)
        if base_spending_total > 0
        else 0.0
    )
    # SS may not have started at retirement age (e.g. claiming at 70, retiring at 67).
    ss_at_retirement_age = (
        social_security_base_annual_income
        * ((1.0 + inflation) ** max(0, retirement_age - social_security_claim_age))
        if social_security_claim_age <= retirement_age
        else 0.0
    )
    net_portfolio_draw_at_retirement = max(
        adj_spending_at_retirement - ss_at_retirement_age, 0.0
    )

    claim_year = current_year + (social_security_claim_age - current_age)
    years_base_to_claim = max(0, claim_year - spending_base_year)
    adj_spending_at_claim = (
        base_spending_total * ((1.0 + inflation) ** years_base_to_claim)
        if base_spending_total > 0
        else 0.0
    )
    net_portfolio_draw_at_claim = max(
        adj_spending_at_claim - social_security_base_annual_income, 0.0
    )

    contribution_details = user_profile.get("contribution_details", {})
    base_salary = float(contribution_details.get("annual_salary", 0.0))
    salary_growth = float(contribution_details.get("salary_increase_pct", 0.0))

    years_to_simulate = max(0, life_expectancy_age - current_age)

    # Estimate current blended moments from account allocations at current age.
    (mu_401k_now, sigma_401k_now), (mu_ira_now, sigma_ira_now) = _account_phase_moments(
        user_profile,
        current_age,
        fund_moments,
        retirement_age,
    )
    account_weight_401k = start_401k / start_total_balance if start_total_balance > 0 else 0.5
    account_weight_ira = 1.0 - account_weight_401k
    blended_mean = (account_weight_401k * mu_401k_now) + (account_weight_ira * mu_ira_now)
    blended_vol = _blended_portfolio_volatility(
        [
            (account_weight_401k, sigma_401k_now),
            (account_weight_ira, sigma_ira_now),
        ]
    )
    target_volatility = DEFAULT_TARGET_VOLATILITY_PCT / 100.0
    volatility_uplift = max(1.0, target_volatility / max(blended_vol, 1e-8))
    effective_blended_vol = blended_vol * volatility_uplift
    income_mu, income_sigma_base = _boglehead_income_moments(fund_moments)
    income_sigma = income_sigma_base * volatility_uplift

    terminal_balances: list[float] = []
    retirement_portfolio_balances: list[float] = []
    terminal_portfolio_balances: list[float] = []
    terminal_net_worth_balances: list[float] = []
    non_depleted_terminal_portfolio_balances: list[float] = []
    non_depleted_terminal_net_worth_balances: list[float] = []
    success_count = 0

    for sim in range(simulation_count):
        rng = random.Random(random_seed + sim if random_seed is not None else None)

        age = current_age
        salary = base_salary
        salary_transition_applied = False
        if contribution_details.get("career_transition_age") is not None and age >= int(
            contribution_details.get("career_transition_age")
        ):
            salary = salary * max(
                0.0,
                min(1.0, float(contribution_details.get("career_transition_income_pct", 1.0))),
            )
            salary_transition_applied = True
        bal_401k = start_401k
        bal_ira = start_ira
        bal_income = 0.0
        housing_asset_states = initialize_rental_asset_states(household_assets)

        # GARCH-like regime state for volatility clustering.
        regime_variance = 1.0
        prev_shock = 0.0

        annual_withdrawal = 0.0
        retirement_start_balance = None
        failed = False

        for year_idx in range(years_to_simulate):
            total_balance = max(bal_401k + bal_ira + bal_income, 0.0)
            # Capture equity before advancing housing state, then advance once per year.
            housing_equity = housing_total_equity(housing_asset_states)
            rental_net_cashflow = apply_rental_assets_for_year(housing_asset_states, inflation)
            (mu_401k, sigma_401k), (mu_ira, sigma_ira) = _account_phase_moments(
                user_profile,
                age,
                fund_moments,
                retirement_age,
            )
            sigma_401k *= volatility_uplift
            sigma_ira *= volatility_uplift

            # Sequence risk mechanics:
            # 1) fat-tail draw
            # 2) downside skew amplification
            # 3) persistent volatility state
            shock = _student_t(rng)
            if shock < 0:
                shock *= 1.15

            omega, alpha, beta = 0.08, 0.17, 0.78
            regime_variance = omega + alpha * (prev_shock ** 2) + beta * regime_variance
            regime_scale = max(0.55, min(1.9, math.sqrt(regime_variance)))
            normalized_shock = shock * regime_scale
            prev_shock = normalized_shock

            contribution = 0.0
            withdrawal = 0.0

            if age < retirement_age:
                salary, salary_transition_applied = _apply_second_career_transition(
                    salary,
                    age,
                    contribution_details,
                    salary_transition_applied,
                )
                contribution = _annual_contribution(
                    user_profile,
                    salary,
                    age=age,
                    years_since_start=max(0, age - current_age),
                    inflation=inflation,
                )
                salary *= (1.0 + salary_growth)
            else:
                if retirement_start_balance is None:
                    retirement_start_balance = total_balance + housing_equity
                    retirement_portfolio_balances.append(total_balance)
                    annual_withdrawal = total_balance * withdrawal_pct
                else:
                    annual_withdrawal *= (1.0 + inflation)

                social_security_income = 0.0
                if age >= social_security_claim_age:
                    years_since_claim = age - social_security_claim_age
                    social_security_income = social_security_base_annual_income * ((1.0 + inflation) ** max(0, years_since_claim))

                # Positive rental income offsets retirement draw; negative net rental cashflow increases it.
                withdrawal = max(annual_withdrawal - social_security_income - rental_net_cashflow, 0.0)

            # Route contributions to their proper account buckets.
            # 401k employee+match → bal_401k, IRA → bal_ira, rental income → bal_income.
            contribution_401k = contribution
            contribution_ira = (
                _annual_ira_contribution(
                    user_profile,
                    year_idx,
                    inflation,
                    age=age,
                )
                if age < retirement_age
                else 0.0
            )
            # Rental income is an investable cash flow; in retirement it already offsets withdrawal above.
            contribution_income = rental_net_cashflow if age < retirement_age else 0.0

            withdrawal_401k, withdrawal_ira, withdrawal_income = _route_withdrawal(
                withdrawal, bal_401k, bal_ira, bal_income, withdrawal_strategy
            )

            # Mid-period cashflow convention avoids overstating or understating timing impacts.
            effective_401k = max(bal_401k + 0.5 * (contribution_401k - withdrawal_401k), 0.0)
            effective_ira = max(bal_ira + 0.5 * (contribution_ira - withdrawal_ira), 0.0)
            effective_income = max(bal_income + 0.5 * (contribution_income - withdrawal_income), 0.0)

            r_401k = _draw_annual_return(mu_401k, sigma_401k, normalized_shock)
            r_ira = _draw_annual_return(mu_ira, sigma_ira, normalized_shock)
            r_income = _draw_annual_return(income_mu, income_sigma, normalized_shock)

            bal_401k = max((effective_401k * (1.0 + r_401k)) + 0.5 * (contribution_401k - withdrawal_401k), 0.0)
            bal_ira = max((effective_ira * (1.0 + r_ira)) + 0.5 * (contribution_ira - withdrawal_ira), 0.0)
            bal_income = max((effective_income * (1.0 + r_income)) + 0.5 * (contribution_income - withdrawal_income), 0.0)

            if (bal_401k + bal_ira + bal_income) <= 1.0:
                failed = True
                bal_401k = 0.0
                bal_ira = 0.0
                bal_income = 0.0
                break

            age += 1

        terminal_portfolio_balance = bal_401k + bal_ira + bal_income
        terminal_balance = terminal_portfolio_balance + housing_total_equity(housing_asset_states)
        terminal_balances.append(terminal_balance)
        terminal_portfolio_balances.append(terminal_portfolio_balance)
        terminal_net_worth_balances.append(terminal_balance)
        if not failed and terminal_portfolio_balance > 0:
            non_depleted_terminal_portfolio_balances.append(terminal_portfolio_balance)
        if not failed and terminal_balance > 0:
            non_depleted_terminal_net_worth_balances.append(terminal_balance)

        if retirement_start_balance is None:
            retirement_portfolio_balances.append(terminal_portfolio_balance)

        years_in_retirement = max(0, life_expectancy_age - retirement_age)
        real_terminal = terminal_balance / ((1.0 + inflation) ** years_in_retirement) if years_in_retirement > 0 else terminal_balance

        if retirement_start_balance is None:
            threshold_value = 0.0
        else:
            threshold_value = retirement_start_balance * success_threshold

        if not failed and real_terminal >= threshold_value:
            success_count += 1

    terminal_balances.sort()

    def percentile(values: list[float], q: float) -> float:
        if not values:
            return 0.0
        idx = max(0, min(len(values) - 1, int(round(q * (len(values) - 1)))))
        return float(values[idx])

    success_probability = (success_count / simulation_count) * 100.0
    rating = _rating_for_probability(success_probability)

    assumptions = {
        "model": {
            "return_distribution": "lognormal with Student-t innovations (df=7)",
            "downside_skew_multiplier": 1.15,
            "volatility_clustering": {
                "type": "garch-like",
                "omega": 0.08,
                "alpha": 0.17,
                "beta": 0.78,
                "regime_scale_bounds": [0.55, 1.9],
            },
        },
        "cashflow": {
            "contribution_schedule": "Pre-retirement annual salary-based 401k contribution with employer match plus inflation-indexed IRA annual contributions",
            "withdrawal_phase": "Retirement withdrawals begin at retirement age and grow with inflation",
            "withdrawal_rate": withdrawal_pct,
            "withdrawal_strategy": withdrawal_strategy,
            "inflation_rate": inflation,
            "maximize_retirement_contributions": bool(
                contribution_details.get("maximize_retirement_contributions", False)
            ),
            "career_transition": {
                "enabled": contribution_details.get("career_transition_age") is not None,
                "transition_age": contribution_details.get("career_transition_age"),
                "post_transition_income_pct": contribution_details.get("career_transition_income_pct"),
            },
            "contribution_limits": {
                "401k_base_limit": contribution_details.get(
                    "annual_401k_contribution_limit",
                    DEFAULT_401K_CONTRIBUTION_LIMIT,
                ),
                "401k_catch_up_start_age": contribution_details.get(
                    "401k_catch_up_start_age",
                    DEFAULT_401K_CATCH_UP_AGE,
                ),
                "401k_catch_up_limit": contribution_details.get(
                    "annual_401k_catch_up_limit",
                    DEFAULT_401K_CATCH_UP_LIMIT,
                ),
                "401k_enhanced_catch_up_age_range": [
                    contribution_details.get(
                        "401k_enhanced_catch_up_start_age",
                        DEFAULT_401K_ENHANCED_CATCH_UP_START_AGE,
                    ),
                    contribution_details.get(
                        "401k_enhanced_catch_up_end_age",
                        DEFAULT_401K_ENHANCED_CATCH_UP_END_AGE,
                    ),
                ],
                "401k_enhanced_catch_up_limit": contribution_details.get(
                    "annual_401k_enhanced_catch_up_limit",
                    DEFAULT_401K_ENHANCED_CATCH_UP_LIMIT,
                ),
                "ira_base_limit": contribution_details.get(
                    "annual_ira_contribution_limit",
                    DEFAULT_IRA_CONTRIBUTION_LIMIT,
                ),
                "ira_catch_up_start_age": contribution_details.get(
                    "ira_catch_up_start_age",
                    DEFAULT_IRA_CATCH_UP_AGE,
                ),
                "ira_catch_up_limit": contribution_details.get(
                    "annual_ira_catch_up_limit",
                    DEFAULT_IRA_CATCH_UP_LIMIT,
                ),
            },
            "social_security_offsets_withdrawals": True,
            "income_investment_strategy": "All modeled income cashflows are invested to a Boglehead 3-fund portfolio (FXAIX/FZILX/FXNAX).",
        },
        "social_security": {
            "enabled": True,
            "claim_age": social_security_claim_age,
            "base_annual_benefit_at_claim_age": round(social_security_base_annual_income, 2),
            "benefit_growth_assumption": "COLA approximated at inflation",
            "estimation_method": "AIME/PIA from projected peak earnings years with delayed-retirement credits",
        },
        "retirement_spending_needs": {
            "spending_profile": {
                "base_year": spending_base_year,
                "annual_general_living_expenses": round(base_spending_general, 2),
                "annual_medical_quality_of_life_expenses": round(base_spending_medical, 2),
                "annual_total_base_spending": round(base_spending_total, 2),
                "prorated_note": (
                    individual_spending_config.get("_prorated_note")
                    if individual_spending_config
                    else None
                ),
            } if individual_spending_config else None,
            "at_retirement_age": {
                "year": retirement_year,
                "age": retirement_age,
                "inflation_adjusted_annual_spending": round(adj_spending_at_retirement, 2),
                "social_security_annual_income": round(ss_at_retirement_age, 2),
                "ss_status": (
                    f"SS not yet claimed at retirement — first benefit at age {social_security_claim_age} ({claim_year})."
                    if social_security_claim_age > retirement_age
                    else f"SS already claimed at retirement age {social_security_claim_age}."
                ),
                "net_annual_portfolio_withdrawal_needed": round(net_portfolio_draw_at_retirement, 2),
            } if individual_spending_config else None,
            "at_ss_claim_age": {
                "year": claim_year,
                "age": social_security_claim_age,
                "inflation_adjusted_annual_spending": round(adj_spending_at_claim, 2),
                "social_security_annual_income": round(social_security_base_annual_income, 2),
                "net_annual_portfolio_withdrawal_needed": round(net_portfolio_draw_at_claim, 2),
            } if individual_spending_config else None,
            "coverage_at_p50": {
                "p50_portfolio_at_retirement": round(
                    percentile(sorted(retirement_portfolio_balances), 0.50), 2
                ),
                "configured_withdrawal_rate": withdrawal_pct,
                "p50_annual_withdrawal": round(
                    percentile(sorted(retirement_portfolio_balances), 0.50) * withdrawal_pct, 2
                ),
                "spending_need_at_retirement": round(adj_spending_at_retirement, 2),
                "coverage_ratio": round(
                    (
                        percentile(sorted(retirement_portfolio_balances), 0.50)
                        * withdrawal_pct
                    ) / adj_spending_at_retirement,
                    3,
                ) if adj_spending_at_retirement > 0 else None,
                "note": "Coverage ratio > 1.0 means the configured withdrawal rate generates more income than the projected spending need.",
            } if individual_spending_config else None,
            "mortgage_note": (
                "Primary residence mortgage is modeled as fully amortized before retirement "
                "via the rental-asset amortization simulation; no mortgage P&I payments "
                "apply during the retirement withdrawal phase."
            ),
        },
        "portfolio_management": {
            "retirement_rebalance_target_bonds_pct": int(RETIREMENT_BOND_TARGET_PCT * 100),
            "dividends_reinvested": True,
            "bond_and_equity_volatility_modeled_separately": True,
            "intra_portfolio_correlation_assumption": DEFAULT_INTRA_PORTFOLIO_CORRELATION,
        },
        "housing_assets": _build_housing_assets_assumption(household_assets, joint=False),
        "success_definition": {
            "no_depletion_before_life_expectancy": True,
            "min_real_terminal_threshold_pct_of_retirement_balance": DEFAULT_SUCCESS_THRESHOLD_PCT,
        },
        "horizon": {
            "current_year": current_year,
            "current_age": current_age,
            "retirement_age": retirement_age,
            "life_expectancy_age": life_expectancy_age,
            "years_simulated": years_to_simulate,
        },
        "portfolio_snapshot": {
            "starting_401k_balance": round(start_401k, 2),
            "starting_ira_balance": round(start_ira, 2),
            "starting_total_balance": round(start_total_balance, 2),
            "blended_expected_return_pct": round(blended_mean * 100.0, 3),
            "blended_volatility_pct": round(effective_blended_vol * 100.0, 3),
            "target_volatility_floor_pct": DEFAULT_TARGET_VOLATILITY_PCT,
        },
        "outcome_percentiles": {
            "retirement": {
                "label": "At Retirement (Portfolio)",
                "p10": round(percentile(sorted(retirement_portfolio_balances), 0.10), 2),
                "p50": round(percentile(sorted(retirement_portfolio_balances), 0.50), 2),
                "p90": round(percentile(sorted(retirement_portfolio_balances), 0.90), 2),
            },
            "life": {
                "label": "At Life Expectancy (Portfolio)",
                "p10": round(percentile(sorted(non_depleted_terminal_portfolio_balances), 0.10), 2),
                "p50": round(percentile(sorted(non_depleted_terminal_portfolio_balances), 0.50), 2),
                "p90": round(percentile(sorted(non_depleted_terminal_portfolio_balances), 0.90), 2),
            },
            "life_net_worth": {
                "label": "At Life Expectancy (Portfolio + Housing)",
                "p10": round(percentile(sorted(non_depleted_terminal_net_worth_balances), 0.10), 2),
                "p50": round(percentile(sorted(non_depleted_terminal_net_worth_balances), 0.50), 2),
                "p90": round(percentile(sorted(non_depleted_terminal_net_worth_balances), 0.90), 2),
            },
        },
    }

    result = StressTestResult(
        user_id=db_user.id,
        simulation_count=simulation_count,
        random_seed=random_seed,
        mean_return_pct=round(blended_mean * 100.0, 4),
        volatility_pct=round(effective_blended_vol * 100.0, 4),
        inflation_pct=round(inflation * 100.0, 4),
        success_probability_pct=round(success_probability, 2),
        rating_tier=rating["tier"],
        rating_grade=rating["grade"],
        rating_label=rating["label"],
        life_expectancy_age=life_expectancy_age,
        success_threshold_pct=DEFAULT_SUCCESS_THRESHOLD_PCT,
        p10_terminal_balance=round(percentile(terminal_balances, 0.10), 2),
        p50_terminal_balance=round(percentile(terminal_balances, 0.50), 2),
        p90_terminal_balance=round(percentile(terminal_balances, 0.90), 2),
        assumptions_json=assumptions,
    )

    db.add(result)
    db.commit()
    db.refresh(result)

    return result


def get_latest_stress_test(username: str, db: Session) -> StressTestResult | None:
    db_user = db.query(User).filter(User.name == username).first()
    if not db_user:
        raise ValueError(f"User '{username}' not found in database")

    return (
        db.query(StressTestResult)
        .filter(StressTestResult.user_id == db_user.id)
        .order_by(StressTestResult.created_at.desc())
        .first()
    )


def is_stress_test_snapshot_stale(
    username: str,
    stress_result: StressTestResult,
    db: Session,
    tolerance: float = 1.0,
) -> bool:
    """Return True when saved stress assumptions no longer match current starting balances."""
    if stress_result is None:
        return False

    db_user = db.query(User).filter(User.name == username).first()
    if not db_user:
        raise ValueError(f"User '{username}' not found in database")

    profile = _load_user_profile(username)
    current_401k, current_ira = _starting_balances(db, db_user, profile)
    current_total = round(current_401k + current_ira, 2)

    try:
        raw = stress_result.assumptions_json or {}
        # Normalise: PostgreSQL TEXT columns may surface the value as a JSON string
        # even when the model declares Column(JSON), so parse it when needed.
        assumptions = json.loads(raw) if isinstance(raw, str) else raw
        snapshot = assumptions.get("portfolio_snapshot", {})
        stored_total_raw = snapshot.get("starting_total_balance")
        if stored_total_raw is None:
            return True
        stored_total = float(stored_total_raw)
    except Exception:
        return True

    return abs(stored_total - current_total) > tolerance


def to_response_payload(stress_result: StressTestResult, username: str) -> dict[str, Any]:
    assumptions = stress_result.assumptions_json
    return {
        "id": stress_result.id,
        "username": username,
        "created_at": stress_result.created_at,
        "simulation_count": stress_result.simulation_count,
        "random_seed": stress_result.random_seed,
        "mean_return_pct": stress_result.mean_return_pct,
        "volatility_pct": stress_result.volatility_pct,
        "inflation_pct": stress_result.inflation_pct,
        "success_probability_pct": stress_result.success_probability_pct,
        "rating_tier": stress_result.rating_tier,
        "rating_grade": stress_result.rating_grade,
        "rating_label": stress_result.rating_label,
        "life_expectancy_age": stress_result.life_expectancy_age,
        "success_threshold_pct": stress_result.success_threshold_pct,
        "p10_terminal_balance": stress_result.p10_terminal_balance,
        "p50_terminal_balance": stress_result.p50_terminal_balance,
        "p90_terminal_balance": stress_result.p90_terminal_balance,
        "assumptions": assumptions,
    }


# ---------------------------------------------------------------------------
# Joint (household) stress test
# ---------------------------------------------------------------------------

def _joint_db_username(usernames: list[str]) -> str:
    """Canonical composite DB name for a household of users."""
    return "+".join(sorted(usernames))


def run_joint_stress_test(
    usernames: list[str],
    db: Session,
    simulation_count: int = DEFAULT_SIMULATION_COUNT,
    random_seed: int | None = None,
    current_year: int = 2026,
) -> StressTestResult:
    """Run Monte Carlo stress test for a joint household and persist the result.

    Design:
    - All members share the same macro return shock each year (correlated markets).
    - Each member's accounts use their phase-specific allocation (mu / sigma).
    - Members contribute independently until their own retirement age.
    - Household withdrawals begin when ALL members are retired and grow with inflation.
    - Success horizon: last member reaches DEFAULT_LIFE_EXPECTANCY_AGE.
    """
    if simulation_count < MIN_SIMULATION_COUNT:
        raise ValueError(f"simulation_count must be >= {MIN_SIMULATION_COUNT}")

    if len(usernames) < 2:
        raise ValueError("Joint stress test requires at least 2 users")

    # ------------------------------------------------------------------
    # Load profiles + DB users + starting balances
    # ------------------------------------------------------------------
    profiles: list[dict[str, Any]] = []
    db_users: list[User] = []
    start_bals: list[tuple[float, float]] = []

    fund_moments = _build_fund_moments()

    for uname in usernames:
        profile = _load_user_profile(uname)
        db_user = db.query(User).filter(User.name == uname).first()
        if not db_user:
            raise ValueError(f"User '{uname}' not found in database")
        bal_401k, bal_ira = _starting_balances(db, db_user, profile)
        profiles.append(profile)
        db_users.append(db_user)
        start_bals.append((bal_401k, bal_ira))

    debt_configs = _load_household_debts_for_users(usernames)
    household_assets = _load_household_assets_for_users(usernames)
    household_retirement_spending = _load_household_retirement_spending_for_users(usernames)

    current_ages = [int(p.get("age", 35)) for p in profiles]
    retirement_ages = [int(p.get("retirement_age", 65)) for p in profiles]
    social_security_claim_ages = [
        int(p.get("social_security_claim_age", DEFAULT_SOCIAL_SECURITY_CLAIM_AGE))
        for p in profiles
    ]
    life_expectancy_age = DEFAULT_LIFE_EXPECTANCY_AGE
    inflation = DEFAULT_INFLATION_PCT / 100.0
    success_threshold = DEFAULT_SUCCESS_THRESHOLD_PCT / 100.0
    withdrawal_pct = float(profiles[0].get("withdrawal_pct") or DEFAULT_WITHDRAWAL_PCT)
    withdrawal_strategy = str(profiles[0].get("withdrawal_order") or WITHDRAWAL_STRATEGY_PROPORTIONAL)
    social_security_base_annual_incomes = [
        _estimate_social_security_annual_benefit(
            profile,
            current_ages[i],
            retirement_ages[i],
            social_security_claim_ages[i],
        )
        for i, profile in enumerate(profiles)
    ]
    retirement_spending_base_year = int(
        household_retirement_spending.get("base_year", current_year)
    ) if household_retirement_spending else current_year
    base_retirement_spending_annual = (
        float(household_retirement_spending.get("annual_general_living_expenses", 0.0))
        + float(household_retirement_spending.get("annual_medical_quality_of_life_expenses", 0.0))
    ) if household_retirement_spending else 0.0
    enforce_retirement_spending_floor = bool(
        household_retirement_spending and household_retirement_spending.get("enforce_floor", False)
    )
    apply_debt_contribution_reduction = any(
        bool(debt.get("reduce_contributions_during_paydown", False)) for debt in debt_configs
    )

    # Simulate until the youngest member would reach life_expectancy_age
    youngest_age = min(current_ages)
    years_to_simulate = max(0, life_expectancy_age - youngest_age)

    combined_start_total = sum(b401 + bira for b401, bira in start_bals)

    # Blended portfolio metrics (for reporting)
    blended_mean = 0.0
    blended_vol_components: list[tuple[float, float]] = []
    for i, profile in enumerate(profiles):
        (mu_401k, sigma_401k), (mu_ira, sigma_ira) = _account_phase_moments(
            profile,
            current_ages[i],
            fund_moments,
            retirement_ages[i],
        )
        member_401k = max(start_bals[i][0], 0.0)
        member_ira = max(start_bals[i][1], 0.0)
        component_weights = [
            member_401k / max(combined_start_total, 1.0),
            member_ira / max(combined_start_total, 1.0),
        ]
        blended_mean += (component_weights[0] * mu_401k) + (component_weights[1] * mu_ira)
        blended_vol_components.append((component_weights[0], sigma_401k))
        blended_vol_components.append((component_weights[1], sigma_ira))

    blended_vol = _blended_portfolio_volatility(blended_vol_components)
    target_volatility = DEFAULT_TARGET_VOLATILITY_PCT / 100.0
    volatility_uplift = max(1.0, target_volatility / max(blended_vol, 1e-8))
    effective_blended_vol = blended_vol * volatility_uplift
    income_mu, income_sigma_base = _boglehead_income_moments(fund_moments)
    income_sigma = income_sigma_base * volatility_uplift

    terminal_balances: list[float] = []
    retirement_portfolio_balances: list[float] = []
    terminal_portfolio_balances: list[float] = []
    terminal_net_worth_balances: list[float] = []
    non_depleted_terminal_portfolio_balances: list[float] = []
    non_depleted_terminal_net_worth_balances: list[float] = []
    success_count = 0

    for sim in range(simulation_count):
        rng = random.Random(random_seed + sim if random_seed is not None else None)

        # Per-member mutable state
        ages = list(current_ages)
        salaries = [
            float(p.get("contribution_details", {}).get("annual_salary", 0.0))
            for p in profiles
        ]
        salary_transition_applied = [False for _ in profiles]
        for i, profile in enumerate(profiles):
            contribution_details = profile.get("contribution_details", {})
            transition_age_raw = contribution_details.get("career_transition_age")
            if transition_age_raw is not None and ages[i] >= int(transition_age_raw):
                salaries[i] = salaries[i] * max(
                    0.0,
                    min(1.0, float(contribution_details.get("career_transition_income_pct", 1.0))),
                )
                salary_transition_applied[i] = True
        employee_contribution_pcts = [
            float(p.get("contribution_details", {}).get("annual_contribution_pct", 0.0))
            for p in profiles
        ]

        bals_401k = [sb[0] for sb in start_bals]
        bals_ira = [sb[1] for sb in start_bals]
        bals_income = [0.0 for _ in profiles]
        housing_asset_states = initialize_rental_asset_states(household_assets)

        debt_states: list[dict[str, float]] = []
        for debt in debt_configs:
            debt_states.append(
                {
                    "remaining_principal": float(debt.get("principal", 0.0)),
                    "annual_interest_rate": float(debt.get("annual_interest_rate", 0.0)),
                    "base_monthly_payment": float(debt.get("base_monthly_payment", 0.0)),
                    "additional_monthly_payment_min": float(debt.get("additional_monthly_payment_min", 0.0)),
                    "additional_monthly_payment_max": float(debt.get("additional_monthly_payment_max", 0.0)),
                }
            )
        debt_fully_paid = bool(debt_states) and (sum(ds["remaining_principal"] for ds in debt_states) <= 0.0)

        regime_variance = 1.0
        prev_shock = 0.0

        annual_withdrawal = 0.0
        annual_withdrawal_rule_based = 0.0
        retirement_start_balance: float | None = None
        failed = False

        for _year_idx in range(years_to_simulate):
            total_household = max(sum(bals_401k[i] + bals_ira[i] + bals_income[i] for i in range(len(profiles))), 0.0)
            rental_net_cashflow = apply_rental_assets_for_year(housing_asset_states, inflation)
            housing_equity = housing_total_equity(housing_asset_states)

            if debt_fully_paid:
                employee_contribution_pcts = [
                    min(POST_DEBT_CONTRIBUTION_CAP_PCT, pct + POST_DEBT_CONTRIBUTION_STEP_PCT)
                    for pct in employee_contribution_pcts
                ]

            # ------ Shared macro shock (correlated returns) ------
            shock = _student_t(rng)
            if shock < 0:
                shock *= 1.15
            omega, alpha, beta = 0.08, 0.17, 0.78
            regime_variance = omega + alpha * (prev_shock ** 2) + beta * regime_variance
            regime_scale = max(0.55, min(1.9, math.sqrt(regime_variance)))
            normalized_shock = shock * regime_scale
            prev_shock = normalized_shock

            # ------ Determine retirement phase for household ------
            all_members_retired = all(ages[i] >= retirement_ages[i] for i in range(len(profiles)))

            if all_members_retired:
                if retirement_start_balance is None:
                    retirement_start_balance = total_household + housing_equity
                    retirement_portfolio_balances.append(total_household)
                    annual_withdrawal_rule_based = total_household * withdrawal_pct
                else:
                    annual_withdrawal_rule_based *= (1.0 + inflation)

                annual_withdrawal = annual_withdrawal_rule_based
                if base_retirement_spending_annual > 0.0:
                    simulation_year = current_year + _year_idx
                    years_since_spending_base = max(0, simulation_year - retirement_spending_base_year)
                    annual_spending_goal = base_retirement_spending_annual * ((1.0 + inflation) ** years_since_spending_base)
                    if enforce_retirement_spending_floor:
                        annual_withdrawal = max(annual_withdrawal, annual_spending_goal)
                    else:
                        annual_withdrawal = annual_spending_goal

            household_social_security_income = 0.0
            for i in range(len(profiles)):
                if ages[i] >= social_security_claim_ages[i]:
                    years_since_claim = ages[i] - social_security_claim_ages[i]
                    household_social_security_income += social_security_base_annual_incomes[i] * (
                        (1.0 + inflation) ** max(0, years_since_claim)
                    )

            annual_portfolio_withdrawal = (
                max(annual_withdrawal - household_social_security_income - rental_net_cashflow, 0.0)
                if all_members_retired
                else 0.0
            )

            total_debt_payment = 0.0
            if debt_states:
                for debt_state in debt_states:
                    total_debt_payment += _apply_debt_payments_for_year(debt_state, rng)
                debt_fully_paid = bool(debt_states) and (sum(ds["remaining_principal"] for ds in debt_states) <= 0.0)

            planned_401k_contributions = [0.0] * len(profiles)
            planned_ira_contributions = [0.0] * len(profiles)
            planned_rental_contributions = [0.0] * len(profiles)
            for i, profile in enumerate(profiles):
                if ages[i] < retirement_ages[i]:
                    contribution_details = profile.get("contribution_details", {})
                    salaries[i], salary_transition_applied[i] = _apply_second_career_transition(
                        salaries[i],
                        ages[i],
                        contribution_details,
                        salary_transition_applied[i],
                    )
                    planned_401k_contributions[i] = _annual_contribution(
                        profile,
                        salaries[i],
                        employee_pct_override=employee_contribution_pcts[i],
                        age=ages[i],
                        years_since_start=max(0, ages[i] - current_ages[i]),
                        inflation=inflation,
                    )
                    salaries[i] *= (
                        1.0 + float(profile.get("contribution_details", {}).get("salary_increase_pct", 0.0))
                    )
                    years_since_start = max(0, ages[i] - current_ages[i])
                    planned_ira_contributions[i] = _annual_ira_contribution(
                        profile,
                        years_since_start,
                        inflation,
                        age=ages[i],
                    )

            # Rental cashflow is invested in the income fund (separate from 401k/IRA).
            if not all_members_retired and abs(rental_net_cashflow) > 0.0:
                total_weight = sum(max(bals_401k[i] + bals_ira[i] + bals_income[i], 0.0) for i in range(len(profiles)))
                for i in range(len(profiles)):
                    if total_weight > 0:
                        member_weight = max(bals_401k[i] + bals_ira[i] + bals_income[i], 0.0) / total_weight
                    else:
                        member_weight = 1.0 / len(profiles)
                    planned_rental_contributions[i] = rental_net_cashflow * member_weight

            # Debt reduction applies to elective 401k + IRA contributions only (not rental income).
            total_planned = sum(planned_401k_contributions) + sum(planned_ira_contributions)
            if apply_debt_contribution_reduction and total_planned > 0 and total_debt_payment > 0:
                reduction_ratio = min(1.0, total_debt_payment / total_planned)
                planned_401k_contributions = [v * (1.0 - reduction_ratio) for v in planned_401k_contributions]
                planned_ira_contributions = [v * (1.0 - reduction_ratio) for v in planned_ira_contributions]

            # ------ Per-member account updates ------
            for i, profile in enumerate(profiles):
                (mu_401k, sigma_401k), (mu_ira, sigma_ira) = _account_phase_moments(
                    profile,
                    ages[i],
                    fund_moments,
                    retirement_ages[i],
                )
                sigma_401k *= volatility_uplift
                sigma_ira *= volatility_uplift

                # Allocate household withdrawal proportionally to this member's share.
                member_total = bals_401k[i] + bals_ira[i] + bals_income[i]
                member_share = member_total / max(total_household, 1.0)
                withdrawal_i = annual_portfolio_withdrawal * member_share if all_members_retired else 0.0

                # Route contributions to the correct account buckets.
                # 401k employee + match → bal_401k, IRA → bal_ira, rental income → bal_income.
                contrib_401k = planned_401k_contributions[i]
                contrib_ira = planned_ira_contributions[i]
                contrib_income = planned_rental_contributions[i]
                w_401k, w_ira, w_income = _route_withdrawal(
                    withdrawal_i, bals_401k[i], bals_ira[i], bals_income[i], withdrawal_strategy
                )

                eff_401k = max(bals_401k[i] + 0.5 * (contrib_401k - w_401k), 0.0)
                eff_ira = max(bals_ira[i] + 0.5 * (contrib_ira - w_ira), 0.0)
                eff_income = max(bals_income[i] + 0.5 * (contrib_income - w_income), 0.0)

                r_401k = _draw_annual_return(mu_401k, sigma_401k, normalized_shock)
                r_ira = _draw_annual_return(mu_ira, sigma_ira, normalized_shock)
                r_income = _draw_annual_return(income_mu, income_sigma, normalized_shock)

                bals_401k[i] = max((eff_401k * (1.0 + r_401k)) + 0.5 * (contrib_401k - w_401k), 0.0)
                bals_ira[i] = max((eff_ira * (1.0 + r_ira)) + 0.5 * (contrib_ira - w_ira), 0.0)
                bals_income[i] = max((eff_income * (1.0 + r_income)) + 0.5 * (contrib_income - w_income), 0.0)

            new_total = sum(bals_401k[i] + bals_ira[i] + bals_income[i] for i in range(len(profiles)))
            if new_total <= 1.0:
                failed = True
                bals_401k = [0.0] * len(profiles)
                bals_ira = [0.0] * len(profiles)
                bals_income = [0.0] * len(profiles)
                break

            ages = [a + 1 for a in ages]

        terminal_portfolio_balance = sum(bals_401k[i] + bals_ira[i] + bals_income[i] for i in range(len(profiles)))
        terminal_balance = terminal_portfolio_balance + housing_total_equity(housing_asset_states)
        terminal_balances.append(terminal_balance)
        terminal_portfolio_balances.append(terminal_portfolio_balance)
        terminal_net_worth_balances.append(terminal_balance)
        if not failed and terminal_portfolio_balance > 0:
            non_depleted_terminal_portfolio_balances.append(terminal_portfolio_balance)
        if not failed and terminal_balance > 0:
            non_depleted_terminal_net_worth_balances.append(terminal_balance)

        if retirement_start_balance is None:
            retirement_portfolio_balances.append(terminal_portfolio_balance)

        years_in_retirement = max(0, life_expectancy_age - max(retirement_ages))
        real_terminal = (
            terminal_balance / ((1.0 + inflation) ** years_in_retirement)
            if years_in_retirement > 0
            else terminal_balance
        )
        threshold_value = (retirement_start_balance or 0.0) * success_threshold

        if not failed and real_terminal >= threshold_value:
            success_count += 1

    terminal_balances.sort()

    def percentile(values: list[float], q: float) -> float:
        if not values:
            return 0.0
        idx = max(0, min(len(values) - 1, int(round(q * (len(values) - 1)))))
        return float(values[idx])

    success_probability = (success_count / simulation_count) * 100.0
    rating = _rating_for_probability(success_probability)

    # ------------------------------------------------------------------
    # Build assumptions snapshot
    # ------------------------------------------------------------------
    members_snapshot = []
    for i, (profile, uname) in enumerate(zip(profiles, usernames)):
        members_snapshot.append({
            "name": uname,
            "age": current_ages[i],
            "retirement_age": retirement_ages[i],
            "starting_401k": round(start_bals[i][0], 2),
            "starting_ira": round(start_bals[i][1], 2),
            "annual_salary": float(profile.get("contribution_details", {}).get("annual_salary", 0)),
            "contribution_pct": float(profile.get("contribution_details", {}).get("annual_contribution_pct", 0)),
            "company_match_pct": float(profile.get("contribution_details", {}).get("company_match_pct", 0)),
            "salary_growth_pct": float(profile.get("contribution_details", {}).get("salary_increase_pct", 0)),
        })

    assumptions = {
        "joint": True,
        "usernames": usernames,
        "model": {
            "return_distribution": "lognormal with Student-t innovations (df=7), correlated across household members",
            "downside_skew_multiplier": 1.15,
            "volatility_clustering": {
                "type": "garch-like",
                "omega": 0.08,
                "alpha": 0.17,
                "beta": 0.78,
                "regime_scale_bounds": [0.55, 1.9],
            },
        },
        "cashflow": {
            "withdrawal_phase": "Household withdrawals begin when all household members are retired",
            "withdrawal_rate": withdrawal_pct,
            "withdrawal_strategy": withdrawal_strategy,
            "inflation_rate": inflation,
            "ira_contributions_included": True,
            "social_security_offsets_withdrawals": True,
            "income_investment_strategy": "All modeled income cashflows are invested to a Boglehead 3-fund portfolio (FXAIX/FZILX/FXNAX).",
            "retirement_spending_floor_enabled": enforce_retirement_spending_floor,
            "retirement_spending_goal_mode": (
                "floor" if enforce_retirement_spending_floor else "target"
            ) if base_retirement_spending_annual > 0.0 else "withdrawal_rate_only",
            "retirement_spending_floor_annual_2026": round(base_retirement_spending_annual, 2),
        },
        "social_security": {
            "enabled": True,
            "claim_age_default": DEFAULT_SOCIAL_SECURITY_CLAIM_AGE,
            "benefit_growth_assumption": "COLA approximated at inflation",
            "estimation_method": "AIME/PIA from projected peak earnings years with delayed-retirement credits",
            "members": [
                {
                    "name": usernames[i],
                    "claim_age": social_security_claim_ages[i],
                    "base_annual_benefit_at_claim_age": round(social_security_base_annual_incomes[i], 2),
                }
                for i in range(len(usernames))
            ],
        },
        "debt_paydown": {
            "enabled": len(debt_configs) > 0,
            "debts": debt_configs,
            "policy": {
                "payments_reduce_available_401k_contributions": apply_debt_contribution_reduction,
                "post_payoff_contribution_step_pct": round(POST_DEBT_CONTRIBUTION_STEP_PCT * 100.0, 2),
                "post_payoff_contribution_cap_pct": round(POST_DEBT_CONTRIBUTION_CAP_PCT * 100.0, 2),
            },
        },
        "housing_assets": _build_housing_assets_assumption(household_assets, joint=True),
        "retirement_spending_goals": {
            "enabled": household_retirement_spending is not None,
            "config": household_retirement_spending,
            "treatment": "Annual spending floor in base-year dollars, inflation-indexed and only enforced when config sets enforce_floor=true",
        },
        "portfolio_management": {
            "retirement_rebalance_target_bonds_pct": int(RETIREMENT_BOND_TARGET_PCT * 100),
            "dividends_reinvested": True,
            "bond_and_equity_volatility_modeled_separately": True,
            "intra_portfolio_correlation_assumption": DEFAULT_INTRA_PORTFOLIO_CORRELATION,
        },
        "success_definition": {
            "no_depletion_before_life_expectancy": True,
            "min_real_terminal_threshold_pct_of_retirement_balance": DEFAULT_SUCCESS_THRESHOLD_PCT,
        },
        "horizon": {
            "current_year": current_year,
            "life_expectancy_age": life_expectancy_age,
            "years_simulated": years_to_simulate,
        },
        "household_portfolio_snapshot": {
            "combined_starting_balance": round(combined_start_total, 2),
            "blended_expected_return_pct": round(blended_mean * 100.0, 3),
            "blended_volatility_pct": round(effective_blended_vol * 100.0, 3),
            "target_volatility_floor_pct": DEFAULT_TARGET_VOLATILITY_PCT,
        },
        "outcome_percentiles": {
            "retirement": {
                "label": "At Retirement (Household Portfolio)",
                "p10": round(percentile(sorted(retirement_portfolio_balances), 0.10), 2),
                "p50": round(percentile(sorted(retirement_portfolio_balances), 0.50), 2),
                "p90": round(percentile(sorted(retirement_portfolio_balances), 0.90), 2),
            },
            "life": {
                "label": "At Life Expectancy (Household Portfolio)",
                "p10": round(percentile(sorted(non_depleted_terminal_portfolio_balances), 0.10), 2),
                "p50": round(percentile(sorted(non_depleted_terminal_portfolio_balances), 0.50), 2),
                "p90": round(percentile(sorted(non_depleted_terminal_portfolio_balances), 0.90), 2),
            },
            "life_net_worth": {
                "label": "At Life Expectancy (Household + Housing)",
                "p10": round(percentile(sorted(non_depleted_terminal_net_worth_balances), 0.10), 2),
                "p50": round(percentile(sorted(non_depleted_terminal_net_worth_balances), 0.50), 2),
                "p90": round(percentile(sorted(non_depleted_terminal_net_worth_balances), 0.90), 2),
            },
        },
        "members": members_snapshot,
    }

    # Store under a synthetic composite user in the DB
    composite_name = _joint_db_username(usernames)
    db_joint_user = db.query(User).filter(User.name == composite_name).first()
    if not db_joint_user:
        from datetime import datetime, timezone

        db_joint_user = User(
            name=composite_name,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        db.add(db_joint_user)
        db.commit()
        db.refresh(db_joint_user)

    result = StressTestResult(
        user_id=db_joint_user.id,
        simulation_count=simulation_count,
        random_seed=random_seed,
        mean_return_pct=round(blended_mean * 100.0, 4),
        volatility_pct=round(effective_blended_vol * 100.0, 4),
        inflation_pct=round(inflation * 100.0, 4),
        success_probability_pct=round(success_probability, 2),
        rating_tier=rating["tier"],
        rating_grade=rating["grade"],
        rating_label=rating["label"],
        life_expectancy_age=life_expectancy_age,
        success_threshold_pct=DEFAULT_SUCCESS_THRESHOLD_PCT,
        p10_terminal_balance=round(percentile(terminal_balances, 0.10), 2),
        p50_terminal_balance=round(percentile(terminal_balances, 0.50), 2),
        p90_terminal_balance=round(percentile(terminal_balances, 0.90), 2),
        assumptions_json=assumptions,
    )

    db.add(result)
    db.commit()
    db.refresh(result)

    return result


def get_latest_joint_stress_test(usernames: list[str], db: Session) -> StressTestResult | None:
    composite_name = _joint_db_username(usernames)
    db_user = db.query(User).filter(User.name == composite_name).first()
    if not db_user:
        return None
    return (
        db.query(StressTestResult)
        .filter(StressTestResult.user_id == db_user.id)
        .order_by(StressTestResult.created_at.desc())
        .first()
    )
