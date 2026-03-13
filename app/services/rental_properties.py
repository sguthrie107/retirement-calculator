"""Rental property cashflow modeling helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_CONVERT_TO_RENTAL_AFTER_YEARS = 5
DEFAULT_RENT_PREMIUM_OVER_PI = 250.0
DEFAULT_VACANCY_RATE = 0.06
DEFAULT_MAINTENANCE_RATE = 0.08


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def load_users_file() -> dict[str, Any]:
    users_path = project_root() / "data" / "users.json"
    with open(users_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_household_assets_for_user(username: str) -> list[dict[str, Any]]:
    users_data = load_users_file()
    assets = users_data.get("household_assets", [])

    applicable: list[dict[str, Any]] = []
    for asset in assets:
        participants = [str(name) for name in asset.get("participants", [])]
        participant_set = set(participants)
        if username not in participant_set:
            continue
        if not bool(asset.get("include_in_individual_analysis", False)):
            continue
        if str(asset.get("asset_type", "")).lower() != "residential_real_estate":
            continue

        ownership_share = 1.0 / max(len(participants), 1)
        prorated_asset = dict(asset)
        prorated_asset["analysis_ownership_share"] = ownership_share

        for numeric_key in (
            "current_home_value",
            "loan_balance",
            "monthly_payment",
            "monthly_escrow",
            "rental_monthly_premium_over_p_and_i",
        ):
            prorated_asset[numeric_key] = float(prorated_asset.get(numeric_key, 0.0)) * ownership_share

        applicable.append(prorated_asset)

    return applicable


def initialize_rental_asset_states(asset_configs: list[dict[str, Any]]) -> list[dict[str, float]]:
    states: list[dict[str, float]] = []

    for asset in asset_configs:
        annual_interest_rate = float(asset.get("annual_interest_rate", 0.0))
        monthly_payment = float(asset.get("monthly_payment", 0.0))
        remaining_principal = float(asset.get("loan_balance", 0.0))

        if monthly_payment <= 0.0 or remaining_principal <= 0.0:
            continue

        states.append(
            {
                "home_value": max(float(asset.get("current_home_value", remaining_principal)), 0.0),
                "remaining_principal": max(remaining_principal, 0.0),
                "annual_interest_rate": max(annual_interest_rate, 0.0),
                "monthly_payment": max(monthly_payment, 0.0),
                "annual_appreciation_rate": float(asset.get("conservative_annual_appreciation_rate", 0.0)),
                "convert_to_rental_after_years": float(asset.get("convert_to_rental_after_years", DEFAULT_CONVERT_TO_RENTAL_AFTER_YEARS)),
                "monthly_rent_premium": float(asset.get("rental_monthly_premium_over_p_and_i", DEFAULT_RENT_PREMIUM_OVER_PI)),
                "vacancy_rate": max(0.0, min(0.95, float(asset.get("vacancy_rate", DEFAULT_VACANCY_RATE)))),
                "maintenance_rate": max(0.0, min(0.95, float(asset.get("maintenance_rate", DEFAULT_MAINTENANCE_RATE)))),
                "year_index": 0.0,
                "allow_sale_or_refi": 0.0,
            }
        )

    return states


def apply_rental_assets_for_year(asset_states: list[dict[str, float]], inflation_rate: float) -> float:
    """Advance one year for each asset and return aggregate net rental cashflow.

    Assumptions:
    - monthly_payment is principal + interest (P&I) only.
    - no sale/refinance events are modeled (hold through amortization term).
    - rental starts after convert_to_rental_after_years and rent grows with inflation.
    """
    total_net_rental_cashflow = 0.0

    for state in asset_states:
        home_value = float(state.get("home_value", 0.0))
        remaining = float(state.get("remaining_principal", 0.0))
        annual_rate = float(state.get("annual_interest_rate", 0.0))
        monthly_payment = float(state.get("monthly_payment", 0.0))
        annual_appreciation = float(state.get("annual_appreciation_rate", 0.0))
        year_index = int(state.get("year_index", 0.0))

        convert_after_years = int(state.get("convert_to_rental_after_years", DEFAULT_CONVERT_TO_RENTAL_AFTER_YEARS))
        monthly_rent_premium = float(state.get("monthly_rent_premium", DEFAULT_RENT_PREMIUM_OVER_PI))
        vacancy_rate = float(state.get("vacancy_rate", DEFAULT_VACANCY_RATE))
        maintenance_rate = float(state.get("maintenance_rate", DEFAULT_MAINTENANCE_RATE))

        monthly_rate = annual_rate / 12.0
        monthly_growth = (1.0 + annual_appreciation) ** (1.0 / 12.0) - 1.0

        annual_mortgage_pi_paid = 0.0
        for _ in range(12):
            if remaining > 0.0:
                interest = remaining * monthly_rate
                principal_paid = max(0.0, monthly_payment - interest)
                principal_paid = min(principal_paid, remaining)
                remaining = max(remaining - principal_paid, 0.0)
                annual_mortgage_pi_paid += (interest + principal_paid)

            home_value = max(home_value * (1.0 + monthly_growth), 0.0)

        is_rental_active = year_index >= convert_after_years
        annual_net_rental_cashflow = 0.0

        if is_rental_active:
            years_since_conversion = year_index - convert_after_years
            monthly_rent = (monthly_payment + monthly_rent_premium) * ((1.0 + inflation_rate) ** max(0, years_since_conversion))
            gross_annual_rent = monthly_rent * 12.0
            vacancy_loss = gross_annual_rent * vacancy_rate
            maintenance_cost = gross_annual_rent * maintenance_rate
            effective_annual_rent = gross_annual_rent - vacancy_loss
            annual_net_rental_cashflow = effective_annual_rent - maintenance_cost - annual_mortgage_pi_paid

        total_net_rental_cashflow += annual_net_rental_cashflow

        state["home_value"] = home_value
        state["remaining_principal"] = remaining
        state["year_index"] = float(year_index + 1)

    return total_net_rental_cashflow


def housing_total_equity(asset_states: list[dict[str, float]]) -> float:
    return sum(
        max(float(state.get("home_value", 0.0)) - float(state.get("remaining_principal", 0.0)), 0.0)
        for state in asset_states
    )


def estimate_rental_net_cashflow_by_year(
    username: str,
    start_year: int,
    end_year: int,
    inflation_rate: float,
) -> dict[int, float]:
    if end_year < start_year:
        return {}

    assets = load_household_assets_for_user(username)
    states = initialize_rental_asset_states(assets)
    if not states:
        return {}

    output: dict[int, float] = {}
    for year in range(start_year, end_year + 1):
        output[year] = round(apply_rental_assets_for_year(states, inflation_rate), 2)

    return output
