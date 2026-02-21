"""Monte Carlo retirement stress testing service.

This module is intentionally separate from deterministic projections to preserve the
existing baseline engine unchanged.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..models import Account, ActualBalance, StressTestResult, User
from .rental_properties import (
    apply_rental_assets_for_year,
    housing_total_equity,
    initialize_rental_asset_states,
    load_household_assets_for_user,
    load_users_file,
)


DEFAULT_SIMULATION_COUNT = 10000
MIN_SIMULATION_COUNT = 5000
DEFAULT_INFLATION_PCT = 3.0
DEFAULT_LIFE_EXPECTANCY_AGE = 88
DEFAULT_WITHDRAWAL_PCT = 0.05
DEFAULT_SUCCESS_THRESHOLD_PCT = 10.0
POST_DEBT_CONTRIBUTION_STEP_PCT = 0.01
POST_DEBT_CONTRIBUTION_CAP_PCT = 0.15
RETIREMENT_BOND_TARGET_PCT = 0.40
DEFAULT_SOCIAL_SECURITY_CLAIM_AGE = 70
SOCIAL_SECURITY_FULL_RETIREMENT_AGE = 67
SOCIAL_SECURITY_MAX_TAXABLE_EARNINGS = 176100.0
SOCIAL_SECURITY_BEND_POINT_1 = 1174.0
SOCIAL_SECURITY_BEND_POINT_2 = 7078.0

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


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_user_profile(username: str) -> dict[str, Any]:
    users_path = _project_root() / "data" / "users.json"
    users_data = _load_json(users_path)
    for user in users_data.get("users", []):
        if user.get("name") == username:
            return user
    raise ValueError(f"User '{username}' not found in users.json")


def _load_household_debts_for_users(usernames: list[str]) -> list[dict[str, Any]]:
    users_path = _project_root() / "data" / "users.json"
    users_data = _load_json(users_path)
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
    users_data = load_users_file()
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


def _load_household_retirement_spending_for_users(usernames: list[str]) -> dict[str, Any] | None:
    users_path = _project_root() / "data" / "users.json"
    users_data = _load_json(users_path)
    spending_configs = users_data.get("household_retirement_spending", [])
    target = set(usernames)

    for config in spending_configs:
        participants = set(config.get("participants", []))
        if participants == target:
            return config

    return None


def _build_fund_moments() -> dict[str, AssetMoments]:
    stocks = _load_json(_project_root() / "data" / "stocks.json").get("funds", [])
    bonds = _load_json(_project_root() / "data" / "bonds.json").get("funds", [])

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


def _rating_for_probability(probability_pct: float) -> dict[str, Any]:
    for band in RATING_BANDS:
        if probability_pct >= band["min_probability"]:
            return band
    return RATING_BANDS[-1]


def _annual_contribution(user_profile: dict[str, Any], salary: float, employee_pct_override: float | None = None) -> float:
    contribution = user_profile.get("contribution_details", {})
    employee_pct = (
        float(employee_pct_override)
        if employee_pct_override is not None
        else float(contribution.get("annual_contribution_pct", 0.0))
    )
    company_match_pct = float(contribution.get("company_match_pct", 0.0))
    vested_pct = float(contribution.get("company_match_vested_pct", 1.0))

    return salary * (employee_pct + (company_match_pct * vested_pct))


def _annual_ira_contribution(user_profile: dict[str, Any], years_since_start: int, inflation: float) -> float:
    contribution = user_profile.get("contribution_details", {})
    base_ira = float(contribution.get("annual_ira_contribution", 0.0))
    if base_ira <= 0:
        return 0.0
    return base_ira * ((1.0 + inflation) ** max(0, years_since_start))


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
    social_security_claim_age = int(user_profile.get("social_security_claim_age", DEFAULT_SOCIAL_SECURITY_CLAIM_AGE))
    social_security_base_annual_income = _estimate_social_security_annual_benefit(
        user_profile,
        current_age,
        retirement_age,
        social_security_claim_age,
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
    blended_vol = math.sqrt(((account_weight_401k * sigma_401k_now) ** 2) + ((account_weight_ira * sigma_ira_now) ** 2))

    terminal_balances: list[float] = []
    success_count = 0

    for sim in range(simulation_count):
        rng = random.Random(random_seed + sim if random_seed is not None else None)

        age = current_age
        salary = base_salary
        bal_401k = start_401k
        bal_ira = start_ira
        housing_asset_states = initialize_rental_asset_states(household_assets)

        # GARCH-like regime state for volatility clustering.
        regime_variance = 1.0
        prev_shock = 0.0

        annual_withdrawal = 0.0
        retirement_start_balance = None
        failed = False

        for year_idx in range(years_to_simulate):
            total_balance = max(bal_401k + bal_ira, 0.0)
            rental_net_cashflow = apply_rental_assets_for_year(housing_asset_states, inflation)
            housing_equity = housing_total_equity(housing_asset_states)
            (mu_401k, sigma_401k), (mu_ira, sigma_ira) = _account_phase_moments(
                user_profile,
                age,
                fund_moments,
                retirement_age,
            )

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

            rental_net_cashflow = apply_rental_assets_for_year(housing_asset_states, inflation)

            if age < retirement_age:
                contribution = _annual_contribution(user_profile, salary)
                salary *= (1.0 + salary_growth)

                # Rental net cashflow is treated as additional investable contribution.
                contribution += rental_net_cashflow
            else:
                if retirement_start_balance is None:
                    retirement_start_balance = total_balance + housing_equity
                    annual_withdrawal = total_balance * withdrawal_pct
                else:
                    annual_withdrawal *= (1.0 + inflation)

                social_security_income = 0.0
                if age >= social_security_claim_age:
                    years_since_claim = age - social_security_claim_age
                    social_security_income = social_security_base_annual_income * ((1.0 + inflation) ** max(0, years_since_claim))

                # Positive rental income offsets retirement draw; negative net rental cashflow increases it.
                withdrawal = max(annual_withdrawal - social_security_income - rental_net_cashflow, 0.0)

            contribution_401k = contribution
            contribution_ira = _annual_ira_contribution(user_profile, year_idx, inflation) if age < retirement_age else 0.0

            if total_balance > 0:
                share_401k = bal_401k / total_balance
                share_ira = bal_ira / total_balance
            else:
                share_401k = account_weight_401k
                share_ira = account_weight_ira

            withdrawal_401k = withdrawal * share_401k
            withdrawal_ira = withdrawal * share_ira

            # Mid-period cashflow convention avoids overstating or understating timing impacts.
            effective_401k = max(bal_401k + 0.5 * (contribution_401k - withdrawal_401k), 0.0)
            effective_ira = max(bal_ira + 0.5 * (contribution_ira - withdrawal_ira), 0.0)

            r_401k = _draw_annual_return(mu_401k, sigma_401k, normalized_shock)
            r_ira = _draw_annual_return(mu_ira, sigma_ira, normalized_shock)

            bal_401k = max((effective_401k * (1.0 + r_401k)) + 0.5 * (contribution_401k - withdrawal_401k), 0.0)
            bal_ira = max((effective_ira * (1.0 + r_ira)) + 0.5 * (contribution_ira - withdrawal_ira), 0.0)

            if (bal_401k + bal_ira) <= 1.0:
                failed = True
                bal_401k = 0.0
                bal_ira = 0.0
                break

            age += 1

        terminal_balance = bal_401k + bal_ira + housing_total_equity(housing_asset_states)
        terminal_balances.append(terminal_balance)

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
            "inflation_rate": inflation,
            "social_security_offsets_withdrawals": True,
        },
        "social_security": {
            "enabled": True,
            "claim_age": social_security_claim_age,
            "base_annual_benefit_at_claim_age": round(social_security_base_annual_income, 2),
            "benefit_growth_assumption": "COLA approximated at inflation",
            "estimation_method": "AIME/PIA from projected peak earnings years with delayed-retirement credits",
        },
        "portfolio_management": {
            "retirement_rebalance_target_bonds_pct": int(RETIREMENT_BOND_TARGET_PCT * 100),
            "dividends_reinvested": True,
            "bond_and_equity_volatility_modeled_separately": True,
        },
        "housing_assets": {
            "enabled": len(household_assets) > 0,
            "assets": household_assets,
            "treatment": "Residential real estate equity included in terminal assets; rental conversion cashflow modeled after configured conversion year",
        },
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
            "blended_volatility_pct": round(blended_vol * 100.0, 3),
        },
    }

    result = StressTestResult(
        user_id=db_user.id,
        simulation_count=simulation_count,
        random_seed=random_seed,
        mean_return_pct=round(blended_mean * 100.0, 4),
        volatility_pct=round(blended_vol * 100.0, 4),
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
        assumptions_json=json.dumps(assumptions),
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


def to_response_payload(stress_result: StressTestResult, username: str) -> dict[str, Any]:
    assumptions = json.loads(stress_result.assumptions_json)
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

    # Simulate until the youngest member would reach life_expectancy_age
    youngest_age = min(current_ages)
    years_to_simulate = max(0, life_expectancy_age - youngest_age)

    combined_start_total = sum(b401 + bira for b401, bira in start_bals)

    # Blended portfolio metrics (for reporting)
    blended_mean = 0.0
    blended_variance = 0.0
    for i, profile in enumerate(profiles):
        (mu_401k, sigma_401k), (mu_ira, sigma_ira) = _account_phase_moments(
            profile,
            current_ages[i],
            fund_moments,
            retirement_ages[i],
        )
        share = (start_bals[i][0] + start_bals[i][1]) / max(combined_start_total, 1.0)
        blended_mean += share * (mu_401k * 0.6 + mu_ira * 0.4)
        blended_variance += (share * (sigma_401k * 0.6 + sigma_ira * 0.4)) ** 2
    blended_vol = math.sqrt(max(blended_variance, 1e-8))

    terminal_balances: list[float] = []
    success_count = 0

    for sim in range(simulation_count):
        rng = random.Random(random_seed + sim if random_seed is not None else None)

        # Per-member mutable state
        ages = list(current_ages)
        salaries = [
            float(p.get("contribution_details", {}).get("annual_salary", 0.0))
            for p in profiles
        ]
        employee_contribution_pcts = [
            float(p.get("contribution_details", {}).get("annual_contribution_pct", 0.0))
            for p in profiles
        ]
        ira_annual_contributions = [
            float(p.get("contribution_details", {}).get("annual_ira_contribution", 0.0))
            for p in profiles
        ]

        bals_401k = [sb[0] for sb in start_bals]
        bals_ira = [sb[1] for sb in start_bals]
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
        retirement_start_balance: float | None = None
        failed = False

        for _year_idx in range(years_to_simulate):
            total_household = max(sum(bals_401k[i] + bals_ira[i] for i in range(len(profiles))), 0.0)
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
                    annual_withdrawal = total_household * withdrawal_pct
                else:
                    annual_withdrawal *= (1.0 + inflation)

                if base_retirement_spending_annual > 0.0:
                    simulation_year = current_year + _year_idx
                    years_since_spending_base = max(0, simulation_year - retirement_spending_base_year)
                    annual_spending_floor = base_retirement_spending_annual * ((1.0 + inflation) ** years_since_spending_base)
                    annual_withdrawal = max(annual_withdrawal, annual_spending_floor)

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

            planned_contributions = [0.0] * len(profiles)
            planned_ira_contributions = [0.0] * len(profiles)
            for i, profile in enumerate(profiles):
                if ages[i] < retirement_ages[i]:
                    planned_contributions[i] = _annual_contribution(
                        profile,
                        salaries[i],
                        employee_pct_override=employee_contribution_pcts[i],
                    )
                    salaries[i] *= (
                        1.0 + float(profile.get("contribution_details", {}).get("salary_increase_pct", 0.0))
                    )
                    years_since_start = max(0, ages[i] - current_ages[i])
                    planned_ira_contributions[i] = ira_annual_contributions[i] * ((1.0 + inflation) ** years_since_start)

            if not all_members_retired and abs(rental_net_cashflow) > 0.0:
                total_weight = sum(max(bals_401k[i] + bals_ira[i], 0.0) for i in range(len(profiles)))
                for i in range(len(profiles)):
                    if total_weight > 0:
                        member_weight = max(bals_401k[i] + bals_ira[i], 0.0) / total_weight
                    else:
                        member_weight = 1.0 / len(profiles)
                    planned_contributions[i] += rental_net_cashflow * member_weight

            total_planned = sum(planned_contributions)
            if total_planned > 0 and total_debt_payment > 0:
                reduction_ratio = min(1.0, total_debt_payment / total_planned)
                planned_contributions = [value * (1.0 - reduction_ratio) for value in planned_contributions]

            # ------ Per-member account updates ------
            for i, profile in enumerate(profiles):
                (mu_401k, sigma_401k), (mu_ira, sigma_ira) = _account_phase_moments(
                    profile,
                    ages[i],
                    fund_moments,
                    retirement_ages[i],
                )

                contrib_i = planned_contributions[i]
                contrib_ira_i = planned_ira_contributions[i]

                # Allocate household withdrawal proportionally to this member's share
                member_total = bals_401k[i] + bals_ira[i]
                member_share = member_total / max(total_household, 1.0)
                withdrawal_i = annual_portfolio_withdrawal * member_share if all_members_retired else 0.0

                # Sub-allocate withdrawal across 401k / IRA within member
                k_share = bals_401k[i] / max(member_total, 1.0)
                ira_share = 1.0 - k_share

                contrib_401k = contrib_i
                contrib_ira = contrib_ira_i
                w_401k = withdrawal_i * k_share
                w_ira = withdrawal_i * ira_share

                eff_401k = max(bals_401k[i] + 0.5 * (contrib_401k - w_401k), 0.0)
                eff_ira = max(bals_ira[i] + 0.5 * (contrib_ira - w_ira), 0.0)

                r_401k = _draw_annual_return(mu_401k, sigma_401k, normalized_shock)
                r_ira = _draw_annual_return(mu_ira, sigma_ira, normalized_shock)

                bals_401k[i] = max((eff_401k * (1.0 + r_401k)) + 0.5 * (contrib_401k - w_401k), 0.0)
                bals_ira[i] = max((eff_ira * (1.0 + r_ira)) + 0.5 * (contrib_ira - w_ira), 0.0)

            new_total = sum(bals_401k[i] + bals_ira[i] for i in range(len(profiles)))
            if new_total <= 1.0:
                failed = True
                bals_401k = [0.0] * len(profiles)
                bals_ira = [0.0] * len(profiles)
                break

            ages = [a + 1 for a in ages]

        terminal_balance = sum(bals_401k[i] + bals_ira[i] for i in range(len(profiles))) + housing_total_equity(housing_asset_states)
        terminal_balances.append(terminal_balance)

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
            "inflation_rate": inflation,
            "ira_contributions_included": True,
            "social_security_offsets_withdrawals": True,
            "retirement_spending_floor_enabled": base_retirement_spending_annual > 0.0,
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
                "payments_reduce_available_401k_contributions": True,
                "post_payoff_contribution_step_pct": round(POST_DEBT_CONTRIBUTION_STEP_PCT * 100.0, 2),
                "post_payoff_contribution_cap_pct": round(POST_DEBT_CONTRIBUTION_CAP_PCT * 100.0, 2),
            },
        },
        "housing_assets": {
            "enabled": len(household_assets) > 0,
            "assets": household_assets,
            "counting_rule": "Counted once for household projections",
            "treatment": "Residential equity included in terminal assets and rental conversion cashflow modeled annually",
        },
        "retirement_spending_goals": {
            "enabled": household_retirement_spending is not None,
            "config": household_retirement_spending,
            "treatment": "Annual spending floor in base-year dollars, inflation-indexed and enforced after first retirement",
        },
        "portfolio_management": {
            "retirement_rebalance_target_bonds_pct": int(RETIREMENT_BOND_TARGET_PCT * 100),
            "dividends_reinvested": True,
            "bond_and_equity_volatility_modeled_separately": True,
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
            "blended_volatility_pct": round(blended_vol * 100.0, 3),
        },
        "members": members_snapshot,
    }

    # Store under a synthetic composite user in the DB
    composite_name = _joint_db_username(usernames)
    db_joint_user = db.query(User).filter(User.name == composite_name).first()
    if not db_joint_user:
        from datetime import datetime
        db_joint_user = User(name=composite_name, created_at=datetime.utcnow().isoformat())
        db.add(db_joint_user)
        db.commit()
        db.refresh(db_joint_user)

    result = StressTestResult(
        user_id=db_joint_user.id,
        simulation_count=simulation_count,
        random_seed=random_seed,
        mean_return_pct=round(blended_mean * 100.0, 4),
        volatility_pct=round(blended_vol * 100.0, 4),
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
        assumptions_json=json.dumps(assumptions),
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
