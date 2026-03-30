"""Live holdings service for dashboard MVP."""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import urllib.parse
import urllib.request

from cachetools import TTLCache

from lib.calculator_utils import load_user_profile as _load_user_profile


DEFAULT_AGE_REFERENCE_YEAR = 2026
# Cache up to 256 ticker/date combinations; each entry lives for 30 minutes.
_QUOTE_CACHE: TTLCache = TTLCache(maxsize=256, ttl=1800)


def resolve_current_year(as_of: date | None = None) -> int:
    reference = as_of or date.today()
    return int(reference.year)


def resolve_current_age(profile: dict, as_of: date | None = None) -> int:
    as_of_year = resolve_current_year(as_of)
    base_age = int(profile.get("age", 0))
    reference_year = int(profile.get("age_reference_year", DEFAULT_AGE_REFERENCE_YEAR))
    return base_age + (as_of_year - reference_year)


def _phase_sort_key(phase_key: str) -> tuple[int, str]:
    try:
        return int(phase_key.split("_")[-1]), phase_key
    except Exception:
        return 999, phase_key


def resolve_phase(phase_map: dict, current_age: int) -> tuple[str | None, dict | None]:
    if not isinstance(phase_map, dict) or not phase_map:
        return None, None

    ordered = sorted(phase_map.items(), key=lambda item: _phase_sort_key(str(item[0])))
    for phase_key, phase_data in ordered:
        end_age = phase_data.get("end_age")
        if end_age is None or current_age <= int(end_age):
            return str(phase_key), phase_data

    last_key, last_data = ordered[-1]
    return str(last_key), last_data


def _fetch_quote_from_yahoo(ticker: str) -> dict:
    symbol = urllib.parse.quote(str(ticker).strip())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "retirement-calculator/1.0"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))

    chart = payload.get("chart", {})
    results = chart.get("result") or []
    if not results:
        raise ValueError("No quote result")

    meta = results[0].get("meta", {})
    quote_series = (((results[0].get("indicators") or {}).get("quote") or [{}])[0] or {})
    closes = [float(value) for value in (quote_series.get("close") or []) if value is not None]

    price = meta.get("regularMarketPrice")
    if price is None and closes:
        price = closes[-1]
    # Use regularMarketPreviousClose (yesterday's actual close) for an accurate
    # 24-hour day change.  chartPreviousClose reflects the close at the START of
    # the chart range (5 days ago here), which would produce a cumulative figure.
    previous_close = (
        meta.get("regularMarketPreviousClose")
        or meta.get("previousClose")
    )
    if previous_close is None and len(closes) >= 2:
        previous_close = closes[-2]

    if price is None or previous_close is None:
        raise ValueError("Missing market price fields")

    price = float(price)
    previous_close = float(previous_close)
    day_change = round(price - previous_close, 4)
    day_change_pct = round((day_change / previous_close) * 100, 4) if previous_close else 0.0

    regular_market_time = meta.get("regularMarketTime")
    updated_at = None
    if regular_market_time:
        updated_at = (
            datetime.fromtimestamp(int(regular_market_time), tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )

    return {
        "ticker": ticker,
        "price": round(price, 4),
        "previous_close": round(previous_close, 4),
        "day_change": day_change,
        "day_change_pct": day_change_pct,
        "updated_at": updated_at,
        "status": "ok",
        "source": "yahoo_finance",
    }


def get_quote_snapshot(ticker: str, as_of: date | None = None) -> dict:
    cache_date = (as_of or date.today()).isoformat()
    cache_key = (str(ticker).upper(), cache_date)
    if cache_key in _QUOTE_CACHE:
        return dict(_QUOTE_CACHE[cache_key])

    try:
        snapshot = _fetch_quote_from_yahoo(ticker)
    except Exception as exc:
        snapshot = {
            "ticker": ticker,
            "price": None,
            "previous_close": None,
            "day_change": None,
            "day_change_pct": None,
            "updated_at": None,
            "status": "unavailable",
            "source": "yahoo_finance",
            "error": str(exc),
        }

    _QUOTE_CACHE[cache_key] = dict(snapshot)
    return snapshot


def get_live_holdings_for_user(username: str, as_of: date | None = None) -> dict:
    profile = _load_user_profile(username)
    as_of_date = as_of or date.today()
    current_year = resolve_current_year(as_of_date)
    current_age = resolve_current_age(profile, as_of_date)

    k401_phase_key, k401_phase = resolve_phase(profile.get("401k_phases", {}), current_age)
    ira_phase_key, ira_phase = resolve_phase(profile.get("ira_phases", {}), current_age)

    k401_balance = float(profile.get("current_401k_balance", 0.0) or 0.0)
    ira_balance = float(profile.get("current_ira_balance", 0.0) or 0.0)
    total_balance = k401_balance + ira_balance
    k401_weight = (k401_balance / total_balance) if total_balance > 0 else 0.5
    ira_weight = (ira_balance / total_balance) if total_balance > 0 else 0.5

    rows: list[dict] = []
    ticker_cache: dict[str, dict] = {}

    def add_rows(account_type: str, phase_key: str | None, phase_data: dict | None, account_weight: float):
        if not phase_data:
            return
        allocation = phase_data.get("allocation", {}) or {}
        for _, fund in allocation.items():
            ticker = str(fund.get("ticker", "")).strip()
            if not ticker:
                continue
            if ticker not in ticker_cache:
                ticker_cache[ticker] = get_quote_snapshot(ticker, as_of_date)
            quote = ticker_cache[ticker]
            allocation_pct = float(fund.get("pct", 0.0) or 0.0)
            rows.append(
                {
                    "account_type": account_type,
                    "phase_key": phase_key,
                    "phase_name": phase_data.get("name", phase_key),
                    "ticker": ticker,
                    "label": fund.get("label", ticker),
                    "allocation_pct": round(allocation_pct * 100, 2),
                    "portfolio_weight_pct": round((allocation_pct * account_weight) * 100, 2),
                    "price": quote.get("price"),
                    "previous_close": quote.get("previous_close"),
                    "day_change": quote.get("day_change"),
                    "day_change_pct": quote.get("day_change_pct"),
                    "updated_at": quote.get("updated_at"),
                    "status": quote.get("status", "unavailable"),
                    "source": quote.get("source", "yahoo_finance"),
                }
            )

    add_rows("401k", k401_phase_key, k401_phase, k401_weight)
    add_rows("roth_ira", ira_phase_key, ira_phase, ira_weight)

    return {
        "username": username,
        "as_of_date": as_of_date.isoformat(),
        "as_of_year": current_year,
        "current_age": current_age,
        "phase": {
            "401k": {"key": k401_phase_key, "name": (k401_phase or {}).get("name")},
            "roth_ira": {"key": ira_phase_key, "name": (ira_phase or {}).get("name")},
        },
        "holdings": rows,
    }
