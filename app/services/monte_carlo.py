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


DEFAULT_SIMULATION_COUNT = 10000
MIN_SIMULATION_COUNT = 5000
DEFAULT_INFLATION_PCT = 2.5
DEFAULT_LIFE_EXPECTANCY_AGE = 95
DEFAULT_WITHDRAWAL_PCT = 0.04
DEFAULT_SUCCESS_THRESHOLD_PCT = 10.0

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

    return moments


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


def _account_phase_moments(user_profile: dict[str, Any], age: int, fund_moments: dict[str, AssetMoments]) -> tuple[tuple[float, float], tuple[float, float]]:
    k401_phase = _pick_phase(user_profile.get("401k_phases", {}), age)
    ira_phase = _pick_phase(user_profile.get("ira_phases", {}), age)

    k401_mu, k401_sigma = _allocation_moments(k401_phase.get("allocation", {}), fund_moments)
    ira_mu, ira_sigma = _allocation_moments(ira_phase.get("allocation", {}), fund_moments)

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


def _annual_contribution(user_profile: dict[str, Any], salary: float) -> float:
    contribution = user_profile.get("contribution_details", {})
    employee_pct = float(contribution.get("annual_contribution_pct", 0.0))
    company_match_pct = float(contribution.get("company_match_pct", 0.0))
    vested_pct = float(contribution.get("company_match_vested_pct", 1.0))

    return salary * (employee_pct + (company_match_pct * vested_pct))


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

    start_401k, start_ira = _starting_balances(db, db_user, user_profile)
    start_total_balance = start_401k + start_ira

    current_age = int(user_profile.get("age", 35))
    retirement_age = int(user_profile.get("retirement_age", 65))
    life_expectancy_age = DEFAULT_LIFE_EXPECTANCY_AGE
    inflation = DEFAULT_INFLATION_PCT / 100.0
    success_threshold = DEFAULT_SUCCESS_THRESHOLD_PCT / 100.0
    withdrawal_pct = float(user_profile.get("withdrawal_pct") or DEFAULT_WITHDRAWAL_PCT)

    contribution_details = user_profile.get("contribution_details", {})
    base_salary = float(contribution_details.get("annual_salary", 0.0))
    salary_growth = float(contribution_details.get("salary_increase_pct", 0.0))

    years_to_simulate = max(0, life_expectancy_age - current_age)

    # Estimate current blended moments from account allocations at current age.
    (mu_401k_now, sigma_401k_now), (mu_ira_now, sigma_ira_now) = _account_phase_moments(user_profile, current_age, fund_moments)
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

        # GARCH-like regime state for volatility clustering.
        regime_variance = 1.0
        prev_shock = 0.0

        annual_withdrawal = 0.0
        retirement_start_balance = None
        failed = False

        for _ in range(years_to_simulate):
            total_balance = max(bal_401k + bal_ira, 0.0)
            (mu_401k, sigma_401k), (mu_ira, sigma_ira) = _account_phase_moments(user_profile, age, fund_moments)

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
                contribution = _annual_contribution(user_profile, salary)
                salary *= (1.0 + salary_growth)
            else:
                if retirement_start_balance is None:
                    retirement_start_balance = total_balance
                    annual_withdrawal = total_balance * withdrawal_pct
                else:
                    annual_withdrawal *= (1.0 + inflation)

                withdrawal = annual_withdrawal

            contribution_401k = contribution
            contribution_ira = 0.0

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

        terminal_balance = bal_401k + bal_ira
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
            "contribution_schedule": "Pre-retirement annual salary-based 401k contribution with employer match",
            "withdrawal_phase": "Retirement withdrawals begin at retirement age and grow with inflation",
            "withdrawal_rate": withdrawal_pct,
            "inflation_rate": inflation,
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
