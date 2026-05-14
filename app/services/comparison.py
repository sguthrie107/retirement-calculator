"""Comparison service - merges actual vs projected data."""
from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session
from ..models import User, Account, ActualBalance
from .monte_carlo import (
    AssetMoments,
    _build_fund_moments,
    _is_bond_like_ticker,
    _normalize_allocation_weights,
    _pick_phase,
    _rebalance_allocation_to_bond_target,
)
from .projection import get_user_projection
from lib.calculator_utils import (
    compute_contribution_pct_for_year,
    load_user_profile as _load_user_profile,
)


ACTUAL_BALANCE_YEAR_OFFSET = -1
DEFAULT_SEQUENCE_RISK_RETURNS = [-0.18, -0.10, -0.05, 0.00, 0.03, 0.05, 0.04, 0.03, 0.03, 0.025]
BOND_SEQUENCE_RISK_RETURNS = [0.04, 0.035, 0.03, 0.028, 0.03, 0.032, 0.03, 0.028, 0.026, 0.025]
HISTORICAL_US_INFLATION_BY_YEAR = {
    2000: 3.4,
    2001: 1.6,
    2002: 2.4,
    2003: 1.9,
    2004: 3.3,
    2005: 3.4,
    2006: 2.5,
    2007: 4.1,
    2008: 0.1,
    2009: 2.7,
    2010: 1.5,
    2011: 3.0,
    2012: 1.7,
    2013: 1.5,
    2014: 0.8,
    2015: 0.7,
    2016: 2.1,
    2017: 2.1,
    2018: 1.9,
    2019: 2.3,
    2020: 1.4,
    2021: 7.0,
    2022: 6.5,
    2023: 3.4,
    2024: 2.9,
    2025: 2.7,
}


def _parse_joint_usernames(username: str) -> list[str] | None:
    if "," in username:
        members = [name.strip() for name in username.split(",") if name.strip()]
        return members if len(members) >= 2 else None
    if "+" in username:
        members = [name.strip() for name in username.split("+") if name.strip()]
        return members if len(members) >= 2 else None
    return None



def _build_actual_series(rows: list) -> list[dict]:
    actual_by_year: dict[int, float] = {}
    balance_id_map: dict[int, list[int]] = defaultdict(list)
    timestamp_map: dict[int, str] = {}
    account_balances_map: dict[int, dict[str, float]] = {}

    for row in rows:
        year = _normalize_actual_balance_year(row.year)
        if year <= 0:
            continue

        actual_by_year[year] = actual_by_year.get(year, 0.0) + float(row.balance)

        if year not in account_balances_map:
            account_balances_map[year] = {}
        account_balances_map[year][str(row.account_type)] = round(float(row.balance), 2)

        balance_id_map[year].append(int(row.id))
        if year not in timestamp_map or str(row.recorded_at) > str(timestamp_map[year]):
            timestamp_map[year] = row.recorded_at

    return [
        {
            "year": year,
            "balance": round(balance, 2),
            "balance_ids": [int(bid) for bid in balance_id_map.get(year, [])],
            "timestamp": timestamp_map.get(year),
            "account_balances": account_balances_map.get(year, {}),
        }
        for year, balance in sorted(actual_by_year.items())
    ]


def _preload_actual_series_for_users(db: Session, users: list[User]) -> dict[str, list[dict]]:
    if not users:
        return {}

    user_id_to_name = {int(user.id): user.name for user in users}
    user_ids = list(user_id_to_name.keys())

    rows = (
        db.query(
            ActualBalance.id.label("id"),
            ActualBalance.year.label("year"),
            ActualBalance.balance.label("balance"),
            ActualBalance.recorded_at.label("recorded_at"),
            Account.user_id.label("user_id"),
            Account.account_type.label("account_type"),
        )
        .join(Account, ActualBalance.account_id == Account.id)
        .filter(
            Account.user_id.in_(user_ids),
            Account.account_type.in_(("401k", "roth_ira")),
        )
        .order_by(ActualBalance.year)
        .all()
    )

    rows_by_username: dict[str, list] = defaultdict(list)
    for row in rows:
        username = user_id_to_name.get(int(row.user_id))
        if username:
            rows_by_username[username].append(row)

    return {
        username: _build_actual_series(user_rows)
        for username, user_rows in rows_by_username.items()
    }


def _sum_account_balances(account_balances: dict) -> float:
    """Sum all account balance values in the dict."""
    return round(sum(float(v) for v in account_balances.values()), 2)


def _combine_account_balances(existing: dict[str, float], incoming: dict[str, float]) -> dict[str, float]:
    return {
        "401k": round(float(existing.get("401k", 0.0)) + float(incoming.get("401k", 0.0)), 2),
        "roth_ira": round(float(existing.get("roth_ira", 0.0)) + float(incoming.get("roth_ira", 0.0)), 2),
    }


def _latest_timestamp(ts_a, ts_b):
    if ts_a is None:
        return ts_b
    if ts_b is None:
        return ts_a
    try:
        a = datetime.fromisoformat(str(ts_a).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(ts_b).replace("Z", "+00:00"))
        return ts_b if b >= a else ts_a
    except Exception:
        return ts_b


def _normalize_actual_balance_year(stored_year: int) -> int:
    return int(stored_year) + ACTUAL_BALANCE_YEAR_OFFSET


def _normalize_chart_seed_year(stored_year: int) -> int:
    return _normalize_actual_balance_year(stored_year)


def _historical_inflation_for_year(year: int) -> float | None:
    return HISTORICAL_US_INFLATION_BY_YEAR.get(int(year))


def _first_point_at_or_after_year(projected: list[dict], target_year: int) -> dict | None:
    if not projected:
        return None

    for point in sorted(projected, key=lambda item: int(item.get("year", 0))):
        if int(point.get("year", 0)) >= target_year:
            return point

    return max(projected, key=lambda item: int(item.get("year", 0)))


def _allocation_sequence_risk_returns(
    allocation: dict,
    fund_moments: dict[str, AssetMoments],
) -> list[float]:
    normalized = _normalize_allocation_weights(allocation)
    if not normalized:
        return list(DEFAULT_SEQUENCE_RISK_RETURNS)

    returns: list[float] = []
    for year_idx in range(len(DEFAULT_SEQUENCE_RISK_RETURNS)):
        annual_return = 0.0

        for asset in normalized.values():
            weight = float(asset.get("pct", 0.0))
            ticker = str(asset.get("ticker", "")).upper()
            moments = fund_moments.get(ticker, AssetMoments(mean_return=0.06, volatility=0.12))
            is_bond = _is_bond_like_ticker(ticker)
            template = BOND_SEQUENCE_RISK_RETURNS if is_bond else DEFAULT_SEQUENCE_RISK_RETURNS
            template_value = float(template[year_idx])
            template_avg = sum(template) / len(template)

            reference_volatility = 0.06 if is_bond else 0.18
            volatility_scale = max(0.6, min(1.15, moments.volatility / reference_volatility))
            centered_template_value = template_avg + ((template_value - template_avg) * volatility_scale)
            mean_adjustment = (moments.mean_return - template_avg) * 0.25
            adjusted_return = centered_template_value + mean_adjustment

            if is_bond:
                adjusted_return = max(-0.05, min(0.08, adjusted_return))
            else:
                adjusted_return = max(-0.30, min(0.10, adjusted_return))

            annual_return += weight * adjusted_return

        returns.append(round(annual_return, 4))

    return returns


def _sequence_risk_returns_for_projected_portfolio(
    profile: dict,
    projected: list[dict],
    *,
    current_year: int = 2026,
    fund_moments: dict[str, AssetMoments] | None = None,
) -> list[float]:
    retirement_age = int(profile.get("retirement_age", 65))
    current_age = int(profile.get("age", 35))
    retirement_year = current_year + max(0, retirement_age - current_age)
    retirement_point = _first_point_at_or_after_year(projected, retirement_year)
    if not retirement_point:
        return list(DEFAULT_SEQUENCE_RISK_RETURNS)

    account_balances = retirement_point.get("account_balances", {}) or {}
    fund_moments = fund_moments or _build_fund_moments()

    account_configs = [
        ("401k", profile.get("401k_phases", {})),
        ("roth_ira", profile.get("ira_phases", {})),
    ]
    weighted_paths: list[tuple[float, list[float]]] = []
    total_balance = 0.0

    for account_key, phases in account_configs:
        balance = float(account_balances.get(account_key, 0.0) or 0.0)
        if balance <= 0.0 or not phases:
            continue

        phase = _pick_phase(phases, retirement_age)
        allocation = _rebalance_allocation_to_bond_target(phase.get("allocation", {}))
        if not allocation:
            continue

        weighted_paths.append(
            (balance, _allocation_sequence_risk_returns(allocation, fund_moments))
        )
        total_balance += balance

    if total_balance <= 0.0 or not weighted_paths:
        return list(DEFAULT_SEQUENCE_RISK_RETURNS)

    path_length = len(weighted_paths[0][1])
    blended = []
    for idx in range(path_length):
        annual_return = sum(
            (balance / total_balance) * path[idx]
            for balance, path in weighted_paths
        )
        blended.append(round(annual_return, 4))

    return blended


def _retirement_balance_for_weighting(
    projected: list[dict],
    retirement_year: int,
) -> float:
    point = _first_point_at_or_after_year(projected, retirement_year)
    if not point:
        return 0.0
    return float(point.get("balance", 0.0) or 0.0)


def _blend_sequence_risk_returns(weighted_paths: list[tuple[float, list[float]]]) -> list[float]:
    valid_paths = [(weight, path) for weight, path in weighted_paths if weight > 0 and path]
    if not valid_paths:
        return list(DEFAULT_SEQUENCE_RISK_RETURNS)

    total_weight = sum(weight for weight, _ in valid_paths)
    if total_weight <= 0.0:
        return list(DEFAULT_SEQUENCE_RISK_RETURNS)

    path_length = len(valid_paths[0][1])
    blended = []
    for idx in range(path_length):
        annual_return = sum((weight / total_weight) * path[idx] for weight, path in valid_paths)
        blended.append(round(annual_return, 4))

    return blended


def _aggregate_projected_series(series_list: list[list[dict]]) -> list[dict]:
    member_by_year: list[dict[int, dict]] = []
    all_years: set[int] = set()

    for series in series_list:
        year_map: dict[int, dict] = {}
        for item in series:
            year = int(item.get("year", 0))
            if year <= 0:
                continue
            year_map[year] = item
            all_years.add(year)
        member_by_year.append(year_map)

    if not all_years:
        return []

    min_year = min(all_years)
    max_year = max(all_years)
    member_last_seen: list[dict | None] = [None] * len(member_by_year)

    combined_by_year: dict[int, dict] = {}
    for year in range(min_year, max_year + 1):
        combined_by_year[year] = {
            "year": year,
            "balance": 0.0,
            "account_balances": {"401k": 0.0, "roth_ira": 0.0},
        }

        for idx, year_map in enumerate(member_by_year):
            if year in year_map:
                member_last_seen[idx] = year_map[year]

            point = member_last_seen[idx]
            if point is None:
                continue

            combined_by_year[year]["balance"] = round(
                float(combined_by_year[year]["balance"]) + float(point.get("balance", 0.0)),
                2,
            )
            combined_by_year[year]["account_balances"] = _combine_account_balances(
                combined_by_year[year]["account_balances"],
                point.get("account_balances", {}),
            )

    return [combined_by_year[year] for year in sorted(combined_by_year.keys())]


def _aggregate_actual_series(series_list: list[list[dict]]) -> list[dict]:
    by_year: dict[int, dict] = {}
    for series in series_list:
        for item in series:
            year = int(item.get("year", 0))
            if year <= 0:
                continue
            if year not in by_year:
                by_year[year] = {
                    "year": year,
                    "balance": 0.0,
                    "balance_ids": [],
                    "timestamp": None,
                    "account_balances": {"401k": 0.0, "roth_ira": 0.0},
                }
            by_year[year]["balance"] = round(float(by_year[year]["balance"]) + float(item.get("balance", 0.0)), 2)
            by_year[year]["account_balances"] = _combine_account_balances(
                by_year[year]["account_balances"],
                item.get("account_balances", {}),
            )
            by_year[year]["balance_ids"].extend(int(bid) for bid in item.get("balance_ids", []))
            by_year[year]["timestamp"] = _latest_timestamp(by_year[year]["timestamp"], item.get("timestamp"))

    for year in by_year:
        by_year[year]["balance_ids"] = sorted(set(by_year[year]["balance_ids"]))

    return [by_year[year] for year in sorted(by_year.keys())]


def _ensure_continuous_projected_series(projected: list[dict]) -> list[dict]:
    valid_points = [point for point in projected if int(point.get("year", 0)) > 0]
    if not valid_points:
        return []

    by_year = {int(point.get("year", 0)): dict(point) for point in valid_points}
    years = sorted(by_year.keys())
    if len(years) <= 1:
        return [by_year[year] for year in years]

    filled: dict[int, dict] = {year: by_year[year] for year in years}
    for idx in range(len(years) - 1):
        start_year = years[idx]
        end_year = years[idx + 1]
        gap = end_year - start_year
        if gap <= 1:
            continue

        start_point = by_year[start_year]
        end_point = by_year[end_year]

        start_total = float(start_point.get("balance", 0.0))
        end_total = float(end_point.get("balance", 0.0))
        start_401k = float(start_point.get("account_balances", {}).get("401k", 0.0))
        end_401k = float(end_point.get("account_balances", {}).get("401k", 0.0))
        start_ira = float(start_point.get("account_balances", {}).get("roth_ira", 0.0))
        end_ira = float(end_point.get("account_balances", {}).get("roth_ira", 0.0))

        for offset in range(1, gap):
            fraction = offset / gap
            year = start_year + offset
            interpolated_401k = start_401k + (end_401k - start_401k) * fraction
            interpolated_ira = start_ira + (end_ira - start_ira) * fraction
            interpolated_total = start_total + (end_total - start_total) * fraction

            filled[year] = {
                "year": year,
                "balance": round(interpolated_total, 2),
                "account_balances": {
                    "401k": round(interpolated_401k, 2),
                    "roth_ira": round(interpolated_ira, 2),
                },
            }

    return [filled[year] for year in sorted(filled.keys())]


def _estimated_annual_contribution(
    profile: dict,
    years_since_base: int = 0,
    contribution_pct_boost: float = 0.0,
) -> float:
    contribution = profile.get("contribution_details", {})
    salary = float(contribution.get("annual_salary", 0.0))
    salary_growth = float(contribution.get("salary_increase_pct", 0.0))
    base_year = 2026 + max(0, years_since_base)
    employee_pct = compute_contribution_pct_for_year(
        contribution,
        base_year,
        pct_boost=contribution_pct_boost,
    )
    company_match_pct = float(contribution.get("company_match_pct", 0.0))
    vested_pct = float(contribution.get("company_match_vested_pct", 1.0))
    company_match_start_year_raw = contribution.get("company_match_start_year")
    company_match_start_year = (
        int(company_match_start_year_raw)
        if company_match_start_year_raw is not None
        else None
    )
    company_match_employee_cap_pct_raw = contribution.get("company_match_employee_cap_pct")
    company_match_employee_cap_pct = (
        float(company_match_employee_cap_pct_raw)
        if company_match_employee_cap_pct_raw is not None
        else None
    )
    annual_ira_contribution = float(contribution.get("annual_ira_contribution", 0.0))

    effective_salary = salary * ((1.0 + salary_growth) ** max(0, years_since_base))

    employee_contribution = effective_salary * employee_pct
    match_is_active = (
        company_match_start_year is None or base_year >= company_match_start_year
    )
    if match_is_active:
        if company_match_employee_cap_pct is not None:
            match_eligible_pct = max(0.0, min(employee_pct, company_match_employee_cap_pct))
            employer_match = effective_salary * (match_eligible_pct * company_match_pct * vested_pct)
        else:
            employer_match = effective_salary * (company_match_pct * vested_pct)
    else:
        employer_match = 0.0

    annual_401k_contribution = employee_contribution + employer_match
    return max(annual_401k_contribution + annual_ira_contribution, 0.0)


def _apply_projected_chart_seed(
    projected: list[dict],
    profile: dict,
    contribution_pct_boost: float = 0.0,
) -> list[dict]:
    seed = profile.get("chart_seed", {})
    projected_backcast = seed.get("projected_backcast", {})
    if projected_backcast:
        native_projected = sorted(projected, key=lambda item: item.get("year", 0))
        if not native_projected:
            return projected

        first_native_year = int(native_projected[0].get("year", 0))
        if first_native_year <= 0:
            return projected

        target_years = sorted({
            _normalize_chart_seed_year(int(year))
            for year in projected_backcast.get("years", [])
            if int(year) > 0
        })
        if not target_years:
            return projected

        actual_seed_map = {
            _normalize_chart_seed_year(int(item.get("year", 0))): item
            for item in seed.get("actual_balances", [])
            if int(item.get("year", 0)) > 0
        }
        native_by_year = {int(item.get("year", 0)): dict(item) for item in native_projected}

        raw_anchor_year = int(projected_backcast.get("anchor_year", min(target_years)))
        anchor_year = _normalize_chart_seed_year(raw_anchor_year)
        anchor_accounts: dict[str, float] = {}
        anchor_total = 0.0

        if anchor_year in actual_seed_map:
            anchor_accounts = {
                "401k": float(actual_seed_map[anchor_year].get("account_balances", {}).get("401k", 0.0)),
                "roth_ira": float(actual_seed_map[anchor_year].get("account_balances", {}).get("roth_ira", 0.0)),
            }
            anchor_total = _sum_account_balances(anchor_accounts)
        elif anchor_year in native_by_year:
            anchor_accounts = {
                "401k": float(native_by_year[anchor_year].get("account_balances", {}).get("401k", 0.0)),
                "roth_ira": float(native_by_year[anchor_year].get("account_balances", {}).get("roth_ira", 0.0)),
            }
            anchor_total = float(native_by_year[anchor_year].get("balance", 0.0))

        if anchor_total <= 0.0:
            return projected

        implied_return = 0.08
        if (first_native_year + 1) in native_by_year:
            first_total = float(native_by_year[first_native_year].get("balance", 0.0))
            second_total = float(native_by_year[first_native_year + 1].get("balance", 0.0))
            if first_total > 0.0:
                native_contribution = _estimated_annual_contribution(
                    profile,
                    years_since_base=max(0, first_native_year - anchor_year),
                    contribution_pct_boost=contribution_pct_boost,
                )
                native_mid = 0.5 * native_contribution
                denom = first_total + native_mid
                if denom > 0.0:
                    implied_return = ((second_total - native_mid) / denom) - 1.0
                    implied_return = max(-0.60, min(0.60, implied_return))

        rebased_by_year: dict[int, dict] = {}
        rebased_by_year[anchor_year] = {
            "year": anchor_year,
            "balance": round(anchor_total, 2),
            "account_balances": {
                "401k": round(float(anchor_accounts.get("401k", 0.0)), 2),
                "roth_ira": round(float(anchor_accounts.get("roth_ira", 0.0)), 2),
            },
        }

        cursor_total = anchor_total
        cursor_accounts = {
            "401k": float(anchor_accounts.get("401k", 0.0)),
            "roth_ira": float(anchor_accounts.get("roth_ira", 0.0)),
        }

        for year in range(anchor_year + 1, first_native_year + 1):
            years_since_base = max(0, year - anchor_year - 1)
            contribution = _estimated_annual_contribution(
                profile,
                years_since_base=years_since_base,
                contribution_pct_boost=contribution_pct_boost,
            )
            next_total = (cursor_total + 0.5 * contribution) * (1.0 + implied_return) + (0.5 * contribution)

            k401_weight = cursor_accounts["401k"] / cursor_total if cursor_total > 0 else 0.5
            ira_weight = 1.0 - k401_weight
            next_accounts = {
                "401k": next_total * k401_weight,
                "roth_ira": next_total * ira_weight,
            }

            rebased_by_year[year] = {
                "year": year,
                "balance": round(next_total, 2),
                "account_balances": {
                    "401k": round(next_accounts["401k"], 2),
                    "roth_ira": round(next_accounts["roth_ira"], 2),
                },
            }

            cursor_total = next_total
            cursor_accounts = next_accounts

        merged: dict[int, dict] = {
            int(point.get("year", 0)): dict(point)
            for point in native_projected
            if int(point.get("year", 0)) > 0
        }

        native_first_total = float(native_by_year.get(first_native_year, {}).get("balance", 0.0))
        rebased_first_total = float(rebased_by_year.get(first_native_year, {}).get("balance", 0.0))
        scale_factor = (rebased_first_total / native_first_total) if native_first_total > 0 else 1.0

        if scale_factor > 0 and abs(scale_factor - 1.0) > 1e-6:
            for year, point in list(merged.items()):
                if year <= first_native_year:
                    continue

                account_balances = point.get("account_balances", {}) or {}
                if account_balances:
                    scaled_accounts = {
                        "401k": round(float(account_balances.get("401k", 0.0)) * scale_factor, 2),
                        "roth_ira": round(float(account_balances.get("roth_ira", 0.0)) * scale_factor, 2),
                    }
                    # Rental is an independent cashflow stream anchored to its own
                    # real cashflow model — carry it forward unscaled.
                    rental_balance = float(account_balances.get("rental", 0.0))
                    if rental_balance > 0:
                        scaled_accounts["rental"] = round(rental_balance, 2)
                    scaled_total = _sum_account_balances(scaled_accounts)
                else:
                    scaled_accounts = {}
                    scaled_total = round(float(point.get("balance", 0.0)) * scale_factor, 2)

                merged[year] = {
                    **point,
                    "year": year,
                    "balance": scaled_total,
                    "account_balances": scaled_accounts,
                }

        for year, rebased_point in rebased_by_year.items():
            merged[year] = rebased_point

        return [merged[year] for year in sorted(merged.keys())]

    projected_start = seed.get("projected_start")
    if not projected_start:
        return projected

    native_projected = sorted(projected, key=lambda item: item.get("year", 0))
    seeded_projected = list(native_projected)
    existing_years = {int(item.get("year", 0)) for item in seeded_projected}

    start_year = int(projected_start.get("year", 0))
    start_accounts = projected_start.get("account_balances", {})
    start_total = _sum_account_balances(start_accounts)

    if start_year and start_year not in existing_years:
        seeded_projected.append(
            {
                "year": start_year,
                "balance": start_total,
                "account_balances": {
                    "401k": round(float(start_accounts.get("401k", 0.0)), 2),
                    "roth_ira": round(float(start_accounts.get("roth_ira", 0.0)), 2),
                },
            }
        )
        existing_years.add(start_year)

    bridge_year = int(seed.get("bridge_year", 0))
    if bridge_year and bridge_year not in existing_years and start_total > 0:
        implied_return = 0.08
        if len(native_projected) >= 2:
            first_total = float(native_projected[0].get("balance", 0.0))
            second_total = float(native_projected[1].get("balance", 0.0))
            if first_total > 0.0:
                native_contribution = _estimated_annual_contribution(
                    profile,
                    years_since_base=0,
                    contribution_pct_boost=contribution_pct_boost,
                )
                native_mid = 0.5 * native_contribution
                denom = first_total + native_mid
                if denom > 0.0:
                    implied_return = ((second_total - native_mid) / denom) - 1.0
                    implied_return = max(-0.60, min(0.60, implied_return))

        years_from_seed_start = max(0, bridge_year - start_year)
        bridge_contribution = _estimated_annual_contribution(
            profile,
            years_since_base=years_from_seed_start,
            contribution_pct_boost=contribution_pct_boost,
        )
        bridge_total = (start_total + 0.5 * bridge_contribution) * (1.0 + implied_return) + (0.5 * bridge_contribution)

        start_401k = float(start_accounts.get("401k", 0.0))
        start_ira = float(start_accounts.get("roth_ira", 0.0))
        if start_total > 0.0:
            k401_weight = start_401k / start_total
            ira_weight = start_ira / start_total
        else:
            k401_weight = 0.5
            ira_weight = 0.5

        bridge_accounts = {
            "401k": round(bridge_total * k401_weight, 2),
            "roth_ira": round(bridge_total * ira_weight, 2),
        }
        seeded_projected.append(
            {
                "year": bridge_year,
                "balance": _sum_account_balances(bridge_accounts),
                "account_balances": bridge_accounts,
            }
        )

    return sorted(seeded_projected, key=lambda item: item.get("year", 0))


def _apply_actual_chart_seed(actual: list[dict], profile: dict) -> list[dict]:
    seed = profile.get("chart_seed", {})
    seed_actual = seed.get("actual_balances", [])
    if not seed_actual:
        return actual

    by_year = {int(item.get("year", 0)): item for item in actual}
    for item in seed_actual:
        year = _normalize_chart_seed_year(int(item.get("year", 0)))
        if year <= 0:
            continue

        account_balances = item.get("account_balances", {})
        seeded_entry = {
            "year": year,
            "balance": _sum_account_balances(account_balances),
            "balance_ids": by_year.get(year, {}).get("balance_ids", []),
            "timestamp": by_year.get(year, {}).get("timestamp"),
            "account_balances": {
                "401k": round(float(account_balances.get("401k", 0.0)), 2),
                "roth_ira": round(float(account_balances.get("roth_ira", 0.0)), 2),
            },
        }
        by_year[year] = seeded_entry

    return [by_year[year] for year in sorted(by_year.keys())]


def get_comparison_data(
    username: str,
    db: Session,
    current_year: int = 2026,
    preloaded_actual_series: dict[str, list[dict]] | None = None,
) -> dict:
    """
    Get actual vs projected comparison data for a user.
    
    Args:
        username: Name of user
        db: Database session
        current_year: Current year for projections
        
    Returns:
        Dict with 'projected', 'actual', and 'deltas' lists
    """
    joint_usernames = _parse_joint_usernames(username)
    if joint_usernames:
        member_results = [
            get_comparison_data(
                member,
                db,
                current_year,
                preloaded_actual_series=preloaded_actual_series,
            )
            for member in joint_usernames
        ]
        projected = _aggregate_projected_series([result.get("projected", []) for result in member_results])
        projected = _ensure_continuous_projected_series(projected)
        actual = _aggregate_actual_series([result.get("actual", []) for result in member_results])
        deltas = compute_deltas(projected, actual)

        return {
            "projected": projected,
            "actual": actual,
            "deltas": deltas,
            "retirement_age": max(int(result.get("retirement_age", 65)) for result in member_results),
            "retirement_year": max(int(result.get("retirement_year", current_year)) for result in member_results),
            "life_expectancy_age": max(int(result.get("life_expectancy_age", 88)) for result in member_results),
            "withdrawal_pct": float(member_results[0].get("withdrawal_pct", 0.05)) if member_results else 0.05,
            "sequence_risk_returns": _blend_sequence_risk_returns(
                [
                    (
                        _retirement_balance_for_weighting(
                            result.get("projected", []),
                            int(result.get("retirement_year", current_year)),
                        ),
                        result.get("sequence_risk_returns", list(DEFAULT_SEQUENCE_RISK_RETURNS)),
                    )
                    for result in member_results
                ]
            ),
        }

    # Get projected data from calculator engine
    projection_data = get_user_projection(username, current_year)
    projected = projection_data["projected"]
    profile = _load_user_profile(username)
    projected = _apply_projected_chart_seed(projected, profile)
    projected = _ensure_continuous_projected_series(projected)
    retirement_age = int(profile.get("retirement_age", 65))
    current_age = int(profile.get("age", 35))
    retirement_year = current_year + max(0, retirement_age - current_age)
    life_expectancy_age = int(profile.get("life_expectancy_age", 88))
    withdrawal_pct = float(profile.get("withdrawal_pct", 0.05))
    
    # Keep projected account balances as true projected values.
    
    # Get actual balances from database
    actual = []
    if preloaded_actual_series is not None:
        actual = preloaded_actual_series.get(username, [])
    else:
        user = db.query(User).filter(User.name == username).first()
        if user:
            rows = (
                db.query(
                    ActualBalance.id.label("id"),
                    ActualBalance.year.label("year"),
                    ActualBalance.balance.label("balance"),
                    ActualBalance.recorded_at.label("recorded_at"),
                    Account.account_type.label("account_type"),
                )
                .join(Account, ActualBalance.account_id == Account.id)
                .filter(
                    Account.user_id == user.id,
                    Account.account_type.in_(("401k", "roth_ira")),
                )
                .order_by(ActualBalance.year)
                .all()
            )
            actual = _build_actual_series(rows)
    
    actual = _apply_actual_chart_seed(actual, profile)

    deltas = compute_deltas(projected, actual)
    
    return {
        "projected": projected,
        "actual": actual,
        "deltas": deltas,
        "retirement_age": retirement_age,
        "retirement_year": retirement_year,
        "life_expectancy_age": life_expectancy_age,
        "withdrawal_pct": withdrawal_pct,
        "sequence_risk_returns": _sequence_risk_returns_for_projected_portfolio(
            profile,
            projected,
            current_year=current_year,
        ),
    }


def get_all_users_comparison(db: Session, current_year: int = 2026) -> dict:
    """
    Get projections for all users to compare side-by-side.
    All projections are padded to the same end year for uniform comparison.
    
    Args:
        db: Database session
        current_year: Current year for projections
        
    Returns:
        Dict with 'users' list containing {username, projected} for each user.
        All projections extended to same end year with null values for padding.
    """
    users = db.query(User).all()
    preloaded_actual_series = _preload_actual_series_for_users(db, users)

    users_data = []
    usernames = {u.name for u in users}

    for user in users:
        try:
            comparison = get_comparison_data(
                user.name,
                db,
                current_year,
                preloaded_actual_series=preloaded_actual_series,
            )
            users_data.append(
                {
                    "username": user.name,
                    "projected": comparison.get("projected", []),
                    "actual": comparison.get("actual", []),
                    "retirement_age": comparison.get("retirement_age"),
                    "retirement_year": comparison.get("retirement_year"),
                    "life_expectancy_age": comparison.get("life_expectancy_age"),
                    "withdrawal_pct": comparison.get("withdrawal_pct"),
                    "sequence_risk_returns": comparison.get("sequence_risk_returns"),
                }
            )
        except Exception:
            continue

    existing_labels = {str(item.get("username", "")).replace(" ", "").lower() for item in users_data}
    has_existing_joint = any(label in {"steven+alyssa", "alyssa+steven", "steven,alyssa", "alyssa,steven"} for label in existing_labels)

    if {"Steven", "Alyssa"}.issubset(usernames) and not has_existing_joint:
        try:
            household = get_comparison_data(
                "Steven+Alyssa",
                db,
                current_year,
                preloaded_actual_series=preloaded_actual_series,
            )
            users_data.append(
                {
                    "username": "Steven + Alyssa Portfolio",
                    "projected": household.get("projected", []),
                    "actual": household.get("actual", []),
                    "retirement_age": household.get("retirement_age"),
                    "retirement_year": household.get("retirement_year"),
                    "life_expectancy_age": household.get("life_expectancy_age"),
                    "withdrawal_pct": household.get("withdrawal_pct"),
                    "sequence_risk_returns": household.get("sequence_risk_returns"),
                    "is_portfolio": True,
                }
            )
        except Exception:
            pass

    return {"users": users_data}


def compute_deltas(projected: list[dict], actual: list[dict]) -> list[dict]:
    """
    Compute dollar and percentage deltas between actual and projected.
    
    Args:
        projected: List of {year, balance} dicts
        actual: List of {year, balance, balance_ids, timestamp, account_balances} dicts
        
    Returns:
        List of delta dicts with year, projected, actual, delta, delta_pct, balance_ids, timestamp, account_balances
    """
    proj_by_year = {p["year"]: p["balance"] for p in projected}
    deltas = []
    
    for a in actual:
        year = a["year"]
        proj_bal = proj_by_year.get(year)
        actual_bal = a["balance"]
        actual_inflation_pct = _historical_inflation_for_year(year)

        if proj_bal is None:
            deltas.append({
                "year": year,
                "projected": 0.0,
                "actual": round(actual_bal, 2),
                "delta": 0.0,
                "delta_pct": 0.0,
                "has_projection": False,
                "balance_ids": a.get("balance_ids", []),
                "timestamp": a.get("timestamp"),
                "account_balances": a.get("account_balances", {}),
                "actual_inflation_pct": actual_inflation_pct,
            })
            continue

        diff = actual_bal - proj_bal
        pct = (diff / proj_bal * 100) if proj_bal else 0

        deltas.append({
            "year": year,
            "projected": round(proj_bal, 2),
            "actual": round(actual_bal, 2),
            "delta": round(diff, 2),
            "delta_pct": round(pct, 2),
            "has_projection": True,
            "balance_ids": a.get("balance_ids", []),
            "timestamp": a.get("timestamp"),
            "account_balances": a.get("account_balances", {}),
            "actual_inflation_pct": actual_inflation_pct,
        })
    
    return deltas
