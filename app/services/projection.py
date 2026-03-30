"""Projection service - wraps existing retirement calculator engine."""
import pandas as pd

from lib.plan_by_age import retirement_401k_full_plan, _calculate_blended_yield_and_appreciation
from lib.ira import retirement_ira_full_plan
from lib.display_utils import merge_projections
from lib.calculator_utils import load_user_profile as _load_user_profile
from app.services.rental_properties import (
    load_household_assets_for_user,
    initialize_rental_asset_states,
    apply_rental_assets_for_year,
)


def _pick_active_phase(phases: dict, age: int) -> dict | None:
    """Return the allocation dict for the phase active at the given age."""
    ordered = sorted(
        ((p.get("end_age") or 999, p) for p in phases.values()),
        key=lambda x: x[0],
    )
    for end_age, phase in ordered:
        if age <= end_age:
            return phase.get("allocation", {})
    return ordered[-1][1].get("allocation", {}) if ordered else {}


def _compute_rental_income_overlay(
    username: str,
    user_profile: dict,
    projected_years: list[int],
    current_year: int,
    inflation: float = 0.03,
) -> dict[int, float]:
    """
    Compute a deterministic rental income overlay for each projected year.

    Pre-retirement: mirrors how the Monte Carlo treats rental net cashflow —
    added to investable contributions, compounded at the active 401k phase rate.

    Post-retirement: the rental asset continues to be held and generates income.
    The balance keeps growing at the conservative (Phase 3) allocation rate,
    and net rental cashflow continues to compound into the rental portfolio
    (equivalent to offsetting retirement withdrawals, consistent with the MC
    which lets rental income reduce the annual portfolio draw).

    Returns a dict of {year: cumulative_rental_balance}.
    """
    household_assets = load_household_assets_for_user(username)
    if not household_assets:
        return {}

    asset_states = initialize_rental_asset_states(household_assets)
    if not asset_states:
        return {}

    user_age_now = int(user_profile.get("age", 35))
    phases_401k = user_profile.get("401k_phases", {})

    rental_balance = 0.0
    overlay: dict[int, float] = {}

    year_start = min(projected_years)
    year_end = max(projected_years)

    for year in range(year_start, year_end + 1):
        age = user_age_now + (year - current_year)

        # Advance rental assets and get this year's net cashflow
        cashflow = apply_rental_assets_for_year(asset_states, inflation)

        # Determine the blended portfolio rate for the active phase at this age.
        # Post-retirement this resolves to the conservative Phase 3 allocation.
        allocation = _pick_active_phase(phases_401k, age)
        blended_yield, blended_appreciation = _calculate_blended_yield_and_appreciation(allocation)
        blended_rate = blended_yield + blended_appreciation

        # Mid-year convention: cashflow earns half a year's return.
        # Applied both pre- and post-retirement so the rental keeps compounding.
        rental_balance = (rental_balance + cashflow / 2.0) * (1.0 + blended_rate) + cashflow / 2.0

        if year in set(projected_years):
            overlay[year] = round(rental_balance, 2)

    return overlay


def get_user_projection(username: str, current_year: int = 2026) -> dict:
    """
    Get projected retirement balances for a user.
    
    Args:
        username: Name of user from users.json
        current_year: Current year for calculations
        
    Returns:
        Dict with 'projected' list of {year, balance, account_balances} dicts
    """
    try:
        user_profile = _load_user_profile(username)

        # Run existing calculator engine
        df_401k = retirement_401k_full_plan(username, current_year=current_year)
        df_ira = retirement_ira_full_plan(username, current_year=current_year)
        
        # Merge projections
        merged = merge_projections(df_401k, df_ira, current_year=current_year)
        
        if merged.empty:
            return {"projected": []}
        
        # Build 401k and IRA lookup tables from individual projections
        df_401k_lookup = df_401k.set_index('year') if not df_401k.empty else pd.DataFrame()
        df_ira_lookup = df_ira.set_index('year') if not df_ira.empty else pd.DataFrame()

        # Compute rental income overlay — mirrors MC behavior where net rental
        # cashflow is treated as additional investable contribution each year.
        projected_years = [int(row["year"]) for _, row in merged.iterrows()]
        rental_overlay = _compute_rental_income_overlay(
            username, user_profile, projected_years, current_year
        )
        
        # Convert to list of dicts with account breakdown
        projected = []
        for _, row in merged.iterrows():
            year = int(row["year"])
            total_balance = round(float(row["total_balance"]), 2)
            rental_balance = rental_overlay.get(year, 0.0)
            
            # Get account balances for this year
            account_balances = {}
            if year in df_401k_lookup.index:
                account_balances['401k'] = round(float(df_401k_lookup.loc[year, 'balance']), 2)
            if year in df_ira_lookup.index:
                account_balances['roth_ira'] = round(float(df_ira_lookup.loc[year, 'ira_balance']), 2)
            if rental_balance > 0:
                account_balances['rental'] = rental_balance
            
            projected.append({
                "year": year,
                "balance": round(total_balance + rental_balance, 2),
                "account_balances": account_balances
            })
        
        return {"projected": projected}
    except Exception as e:
        raise ValueError(f"Failed to compute projection for {username}: {str(e)}")


def get_match_scenario_projections(
    username: str,
    current_year: int = 2026,
) -> dict:
    """
    Return projected totals for +3% and +5% 401k employee contribution-rate scenarios.
    Baseline user settings are preserved, then employee 401k contribution pct is
    increased by 0.03 and 0.05 respectively. IRA projections remain unchanged.
    """
    baseline_401k = retirement_401k_full_plan(username, current_year=current_year)
    df_ira = retirement_ira_full_plan(username, current_year=current_year)
    baseline_merged = merge_projections(baseline_401k, df_ira, current_year=current_year)

    if baseline_merged.empty:
        return {"3pct": [], "5pct": [], "baseline": []}

    baseline_by_year = {
        int(row["year"]): round(float(row["total_balance"]), 2)
        for _, row in baseline_merged.iterrows()
    }

    user_profile = _load_user_profile(username)
    contribution = user_profile.get("contribution_details", {})
    base_contribution_pct = float(contribution.get("annual_contribution_pct", 0.0))

    scenarios = {}
    for key, pct_boost in [("3pct", 0.03), ("5pct", 0.05)]:
        boosted_contribution_pct = max(0.0, base_contribution_pct + pct_boost)
        df_401k = retirement_401k_full_plan(
            username,
            current_year=current_year,
            contribution_pct_override=boosted_contribution_pct,
        )
        merged = merge_projections(df_401k, df_ira, current_year=current_year)
        scenarios[key] = [
            {
                "year": int(row["year"]),
                "balance": round(float(row["total_balance"]), 2),
            }
            for _, row in merged.iterrows()
        ]
    scenarios["baseline"] = [
        {"year": year, "balance": balance}
        for year, balance in sorted(baseline_by_year.items())
    ]
    return scenarios


def get_401k_projection(username: str, current_year: int = 2026) -> list[dict]:
    """Get 401k-only projection."""
    df = retirement_401k_full_plan(username, current_year=current_year)
    return [
        {"year": int(row["year"]), "balance": round(float(row["balance"]), 2)}
        for _, row in df.iterrows()
    ]


def get_ira_projection(username: str, current_year: int = 2026) -> list[dict]:
    """Get IRA-only projection."""
    df = retirement_ira_full_plan(username, current_year=current_year)
    return [
        {"year": int(row["year"]), "balance": round(float(row["ira_balance"]), 2)}
        for _, row in df.iterrows()
    ]
