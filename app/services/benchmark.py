"""Boglehead 3-Fund benchmark comparison service.

Each year's monthly closing prices are fetched once from Yahoo Finance then
cached on disk at ``data/benchmark_cache.json``.  Subsequent requests for the
same ticker/year are served instantly from the local file.

Usage
-----
    from app.services.benchmark import get_benchmark_comparison
    data = get_benchmark_comparison("Steven", 2024)
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# ── Boglehead 3-Fund canonical allocation ─────────────────────────────────────
# Source: common "moderate" Boglehead three-fund portfolio
BOGLEHEAD_ALLOCATION: dict[str, float] = {
    "VTI":  0.60,   # Vanguard Total Stock Market ETF
    "VXUS": 0.20,   # Vanguard Total International Stock ETF
    "BND":  0.20,   # Vanguard Total Bond Market ETF
}

BOGLEHEAD_TICKER_INFO: dict[str, str] = {
    "VTI":  "Total US Market",
    "VXUS": "Total International",
    "BND":  "Total Bond Market",
}

# ── Fidelity Freedom Index 2060 (Target Date Fund) ────────────────────────────
# FDKLX is the index-based share class of Fidelity Freedom 2060.
# Treated as a single ticker with 100% weight — composition is opaque by design.
FREEDOM_2060_TICKER = "FDKLX"
FREEDOM_2060_INFO   = "Fidelity Freedom Index 2060 Fund (Target Date)"

# ── Proxy ETF map: fund ticker → liquid ETF with public price history ─────────
# Many Fidelity/Vanguard mutual-fund tickers are not directly quoted on Yahoo
# Finance.  We map each to its closest tradable ETF equivalent.
TICKER_PROXY_MAP: dict[str, str] = {
    # Fidelity ZERO funds
    "FZROX": "VTI",    # Total US Market (zero expense, tracks MSCI US Broad Mkt)
    "FZILX": "VXUS",   # Total International (zero expense)
    # Fidelity equity index / active
    "FXAIX": "VOO",    # S&P 500 index
    "FSPGX": "VUG",    # Large-cap growth → Vanguard Growth ETF
    "FNCMX": "ONEQ",   # Nasdaq Composite Index → Fidelity Nasdaq Composite ETF
    "FSGGX": "VXUS",   # Global Equity ex-US
    "FSSNX": "VB",     # Small Cap Index → Vanguard Small-Cap ETF
    # Fidelity bond funds
    "FUAMX": "VCIT",   # Intermediate corp bonds
    "FNAX":  "AGG",    # US aggregate bonds
    "FXNAX": "AGG",    # Total bond market
    "FIPDX": "SCHP",   # TIPS / inflation-protected
    # Vanguard mutual funds → ETF share-class equivalents
    "VFIAX": "VOO",    # S&P 500
    "VTIAX": "VXUS",   # Total international
    "VBTLX": "BND",    # Total bond
    "VTSAX": "VTI",    # Total stock market
}

# Human-readable descriptions for common proxy ETFs (shown in UI)
PROXY_TICKER_INFO: dict[str, str] = {
    "VTI":  "Vanguard Total Stock Market ETF",
    "VOO":  "Vanguard S&P 500 ETF",
    "VUG":  "Vanguard Growth ETF",
    "ONEQ": "Fidelity Nasdaq Composite Index ETF",
    "VXUS": "Vanguard Total International ETF",
    "VB":   "Vanguard Small-Cap ETF",
    "BND":  "Vanguard Total Bond Market ETF",
    "AGG":  "iShares Core US Aggregate Bond ETF",
    "VCIT": "Vanguard Intermediate-Term Corp Bond ETF",
    "SCHP": "Schwab US TIPS ETF",
}

MONTHS: list[str] = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

_DEFAULT_AGE_REFERENCE_YEAR = 2026


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _cache_path() -> Path:
    return _project_root() / "data" / "benchmark_cache.json"


def _load_cache() -> dict:
    path = _cache_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            log.warning("Could not read benchmark cache; starting fresh")
    return {}


def _save_cache(data: dict) -> None:
    path = _cache_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        log.warning("Could not persist benchmark cache to %s", path)


# ── Yahoo Finance fetch ───────────────────────────────────────────────────────

def _fetch_monthly_closes_yahoo(ticker: str, year: int) -> list[float | None]:
    """
    Fetch 12 monthly closing prices for *ticker* in *year* from Yahoo Finance.

    Returns a list of 12 values indexed Jan=0 … Dec=11.
    Missing months (e.g. fund not yet trading) are returned as ``None``.
    """
    start_ts = int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp())
    end_ts   = int(datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp())
    symbol   = urllib.parse.quote(ticker.strip())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={start_ts}&period2={end_ts}&interval=1mo"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "retirement-calculator/1.0"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    chart   = payload.get("chart", {})
    results = chart.get("result") or []
    if not results:
        log.warning("Yahoo Finance: no result for %s/%d", ticker, year)
        return [None] * 12

    result     = results[0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote_data = (indicators.get("quote") or [{}])[0] or {}
    closes     = quote_data.get("adjclose") or quote_data.get("close") or []

    # Prefer adjusted close when available (handles dividends/splits)
    adj_indicators = indicators.get("adjclose") or []
    if adj_indicators:
        adj_closes = (adj_indicators[0] or {}).get("adjclose") or []
        if adj_closes and len(adj_closes) == len(timestamps):
            closes = adj_closes

    month_close: dict[int, float] = {}
    for i, ts in enumerate(timestamps):
        if ts is None:
            continue
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        if dt.year == year and i < len(closes) and closes[i] is not None:
            month_close[dt.month] = float(closes[i])

    return [month_close.get(m) for m in range(1, 13)]


def _get_monthly_closes(ticker: str, year: int, cache: dict) -> list[float | None]:
    """Return cached monthly closes, fetching from Yahoo Finance if absent."""
    year_key = str(year)
    entry = (cache.get(ticker) or {}).get(year_key) or {}
    closes = entry.get("monthly_closes")
    if isinstance(closes, list) and len(closes) == 12:
        return closes

    try:
        closes = _fetch_monthly_closes_yahoo(ticker, year)
        non_null = sum(v is not None for v in closes)
        log.info("Fetched %s/%d from Yahoo Finance (%d/12 months)", ticker, year, non_null)
    except Exception as exc:
        log.warning("Failed to fetch %s/%d from Yahoo Finance: %s", ticker, year, exc)
        closes = [None] * 12

    cache.setdefault(ticker, {})[year_key] = {
        "monthly_closes": closes,
        "cached_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    return closes


# ── Normalization ─────────────────────────────────────────────────────────────

def _normalize_series(closes: list[float | None]) -> list[float | None]:
    """
    Convert raw price closes to a growth index starting at 100.

    The index represents "what $100 invested on Jan 1 is worth each month".
    Missing (None) values are forward-filled from the last known close.
    """
    start: float | None = next((v for v in closes if v is not None), None)
    if not start:
        return [None] * len(closes)

    result: list[float | None] = []
    last = start
    for v in closes:
        if v is not None:
            last = v
        result.append(round((last / start) * 100.0, 4))
    return result


# ── Portfolio math ────────────────────────────────────────────────────────────

def _weighted_normalized(
    ticker_weights: dict[str, float],
    year: int,
    cache: dict,
) -> tuple[list[float | None], dict[str, list[float | None]]]:
    """
    Compute the weighted monthly normalized growth for a portfolio.

    Returns ``(portfolio_series, per_ticker_normalized_series)``.
    """
    per_ticker_norm: dict[str, list[float | None]] = {}
    for ticker in ticker_weights:
        closes = _get_monthly_closes(ticker, year, cache)
        per_ticker_norm[ticker] = _normalize_series(closes)

    portfolio: list[float | None] = []
    for m in range(12):
        total = 0.0
        total_weight = 0.0
        for ticker, weight in ticker_weights.items():
            v = per_ticker_norm[ticker][m]
            if v is not None:
                total += v * weight
                total_weight += weight
        portfolio.append(round(total / total_weight, 4) if total_weight else None)

    return portfolio, per_ticker_norm


def _annual_return_pct(norm: list[float | None]) -> float | None:
    """Return the full-year return in percentage points (e.g. 12.5 for 12.5%)."""
    valid = [v for v in norm if v is not None]
    if len(valid) < 2:
        return None
    return round(valid[-1] - 100.0, 2)


# ── User allocation helpers ───────────────────────────────────────────────────

def _phase_alloc_for_age(phases: dict, age: int) -> dict[str, float]:
    """Return {ticker: weight} for the *phases* map active at *age*."""
    ordered = sorted(
        phases.items(),
        key=lambda kv: (int(kv[0].split("_")[-1]) if "_" in kv[0] else 999, kv[0]),
    )
    active: dict | None = None
    for _, phase_data in ordered:
        end_age = phase_data.get("end_age")
        if end_age is None or age <= int(end_age):
            active = phase_data.get("allocation", {})
            break
    if active is None and ordered:
        active = ordered[-1][1].get("allocation", {})
    return {
        v["ticker"]: float(v["pct"])
        for v in (active or {}).values()
        if "ticker" in v
    }


def _user_proxy_weights(profile: dict, year: int) -> dict[str, float]:
    """
    Build {proxy_etf: combined_weight} for the user's active allocation in *year*.

    IRA and 401k allocations are merged proportionally using the user's
    current account balances (or 50/50 if balances are unavailable).
    """
    age_ref  = int(profile.get("age_reference_year", _DEFAULT_AGE_REFERENCE_YEAR))
    base_age = int(profile.get("age", 0))
    age      = base_age + (year - age_ref)

    ira_alloc  = _phase_alloc_for_age(profile.get("ira_phases", {}), age)
    k401_alloc = _phase_alloc_for_age(profile.get("401k_phases", {}), age)

    ira_bal  = float(profile.get("current_ira_balance", 0))
    k401_bal = float(profile.get("current_401k_balance", 0))
    total    = ira_bal + k401_bal
    ira_w    = (ira_bal / total) if total > 0 else 0.5
    k401_w   = 1.0 - ira_w

    raw: dict[str, float] = {}
    for ticker, pct in ira_alloc.items():
        raw[ticker] = raw.get(ticker, 0.0) + pct * ira_w
    for ticker, pct in k401_alloc.items():
        raw[ticker] = raw.get(ticker, 0.0) + pct * k401_w

    # Remap to proxy ETFs and merge duplicates
    proxy: dict[str, float] = {}
    for ticker, weight in raw.items():
        etf = TICKER_PROXY_MAP.get(ticker, ticker)
        proxy[etf] = proxy.get(etf, 0.0) + weight

    # Renormalize so weights sum to 1.0
    total_w = sum(proxy.values())
    if total_w > 0:
        proxy = {k: round(v / total_w, 4) for k, v in proxy.items()}

    return proxy


def _original_ticker_map(profile: dict, year: int) -> dict[str, str]:
    """Return {proxy_etf: original_ticker} for display purposes."""
    age_ref  = int(profile.get("age_reference_year", _DEFAULT_AGE_REFERENCE_YEAR))
    base_age = int(profile.get("age", 0))
    age      = base_age + (year - age_ref)

    ira_alloc  = _phase_alloc_for_age(profile.get("ira_phases", {}), age)
    k401_alloc = _phase_alloc_for_age(profile.get("401k_phases", {}), age)

    mapping: dict[str, str] = {}
    for ticker in {**ira_alloc, **k401_alloc}:
        proxy = TICKER_PROXY_MAP.get(ticker, ticker)
        if proxy not in mapping:
            mapping[proxy] = ticker
    return mapping


def _blended_projected_return_pct(profile: dict, year: int) -> float | None:
    """
    Compute the user's blended *plan-assumed* annual return (%) for *year*.

    Uses the same phase/age logic as ``_user_proxy_weights`` but works with
    the original fund tickers (FZROX, FXAIX …) rather than the proxy ETFs,
    so we can look up each fund's ``projected_annual_return_pct`` from
    stocks.json / bonds.json.

    Returns a percentage, e.g. ``9.12`` for 9.12 %.
    Returns ``None`` if the data cannot be resolved.
    """
    try:
        from lib.data_loader import get_fund_by_ticker
        from lib.constants import DATA_FILES
    except ImportError:
        return None

    age_ref  = int(profile.get("age_reference_year", _DEFAULT_AGE_REFERENCE_YEAR))
    base_age = int(profile.get("age", 0))
    age      = base_age + (year - age_ref)

    ira_alloc  = _phase_alloc_for_age(profile.get("ira_phases",  {}), age)
    k401_alloc = _phase_alloc_for_age(profile.get("401k_phases", {}), age)

    ira_bal  = float(profile.get("current_ira_balance",  0))
    k401_bal = float(profile.get("current_401k_balance", 0))
    total    = ira_bal + k401_bal
    ira_w    = (ira_bal / total) if total > 0 else 0.5
    k401_w   = 1.0 - ira_w

    # Merge raw (original-ticker) allocations weighted by account balances
    raw: dict[str, float] = {}
    for ticker, pct in ira_alloc.items():
        raw[ticker] = raw.get(ticker, 0.0) + pct * ira_w
    for ticker, pct in k401_alloc.items():
        raw[ticker] = raw.get(ticker, 0.0) + pct * k401_w

    total_weight = sum(raw.values())
    if not total_weight:
        return None

    blended = 0.0
    resolved_weight = 0.0
    for ticker, weight in raw.items():
        ret = None
        for source in [DATA_FILES["STOCKS"], DATA_FILES["BONDS"]]:
            try:
                fund = get_fund_by_ticker(source, ticker)
                ret  = fund.get("projected_annual_return_pct")
                if ret is not None:
                    break
            except (ValueError, KeyError):
                continue
        if ret is not None:
            blended         += (weight / total_weight) * float(ret)
            resolved_weight += weight / total_weight

    if resolved_weight <= 0:
        return None

    # Scale up if some tickers had no data (use resolved weight as denominator)
    return round(blended / resolved_weight, 3) if resolved_weight > 0 else None


# ── Public API ────────────────────────────────────────────────────────────────

def get_benchmark_comparison(username: str, year: int) -> dict:
    """
    Return month-by-month portfolio performance vs the Boglehead 3-Fund
    for the full calendar *year*.

    The first valid monthly close is treated as the Jan 1 baseline ($100).
    All subsequent months show how $100 invested at the start of the year
    grew (or shrank) by that point.

    Response structure
    ------------------
    {
        year, username, months,
        user_portfolio: { label, normalized, ticker_weights, ticker_returns,
                          original_tickers, allocation_label, annual_return_pct },
        boglehead:      { label, normalized, ticker_weights, ticker_returns,
                          allocation_label, annual_return_pct },
        alpha_pct,
        outperformed,
        data_source,
    }
    """
    from lib.calculator_utils import load_user_profile

    profile = load_user_profile(username)
    cache   = _load_cache()

    # ── Plan-assumed blended return (the straight-line "rate of fit") ───────────
    plan_return_pct = _blended_projected_return_pct(profile, year)

    # ── User portfolio ────────────────────────────────────────────────────────
    user_weights = _user_proxy_weights(profile, year)
    user_norm, user_per_ticker = _weighted_normalized(user_weights, year, cache)
    orig_map = _original_ticker_map(profile, year)

    # ── Boglehead 3-Fund ─────────────────────────────────────────────────────
    bog_norm, bog_per_ticker = _weighted_normalized(BOGLEHEAD_ALLOCATION, year, cache)

    # ── Fidelity Freedom Index 2060 ───────────────────────────────────────────
    f2060_weights = {FREEDOM_2060_TICKER: 1.0}
    f2060_norm, f2060_per_ticker = _weighted_normalized(f2060_weights, year, cache)

    _save_cache(cache)

    # ── Returns & alpha ───────────────────────────────────────────────────────
    user_return  = _annual_return_pct(user_norm)
    bog_return   = _annual_return_pct(bog_norm)
    f2060_return = _annual_return_pct(f2060_norm)
    alpha        = (
        round(user_return - bog_return, 2)
        if user_return is not None and bog_return is not None
        else None
    )

    # ── Per-ticker annual returns (for the breakdown table) ───────────────────
    user_ticker_returns  = {t: _annual_return_pct(n) for t, n in user_per_ticker.items()}
    bog_ticker_returns   = {t: _annual_return_pct(n) for t, n in bog_per_ticker.items()}
    f2060_ticker_returns = {t: _annual_return_pct(n) for t, n in f2060_per_ticker.items()}

    # ── Richly annotated ticker info ──────────────────────────────────────────
    user_ticker_details = [
        {
            "proxy":    etf,
            "original": orig_map.get(etf, etf),
            "weight":   user_weights[etf],
            "desc":     PROXY_TICKER_INFO.get(etf, etf),
            "return_pct": user_ticker_returns.get(etf),
        }
        for etf in user_weights
    ]
    bog_ticker_details = [
        {
            "ticker":   t,
            "weight":   w,
            "desc":     BOGLEHEAD_TICKER_INFO.get(t, t),
            "return_pct": bog_ticker_returns.get(t),
        }
        for t, w in BOGLEHEAD_ALLOCATION.items()
    ]

    f2060_ticker_details = [
        {
            "ticker":     FREEDOM_2060_TICKER,
            "weight":     1.0,
            "desc":       FREEDOM_2060_INFO,
            "return_pct": f2060_ticker_returns.get(FREEDOM_2060_TICKER),
        }
    ]

    return {
        "year":     year,
        "username": username,
        "months":   MONTHS,
        "user_portfolio": {
            "label":            f"{username}'s Portfolio",
            "normalized":       user_norm,
            "ticker_weights":   user_weights,
            "ticker_returns":   user_ticker_returns,
            "ticker_details":   user_ticker_details,
            "original_tickers": orig_map,
            "allocation_label": " / ".join(
                f"{t} {round(w * 100, 0):.0f}%"
                for t, w in user_weights.items()
            ),
            "annual_return_pct":          user_return,
            "plan_projected_return_pct":  plan_return_pct,
        },
        "boglehead": {
            "label":            "Boglehead 3-Fund (VTI / VXUS / BND)",
            "normalized":       bog_norm,
            "ticker_weights":   dict(BOGLEHEAD_ALLOCATION),
            "ticker_returns":   bog_ticker_returns,
            "ticker_details":   bog_ticker_details,
            "allocation_label": "VTI 60% / VXUS 20% / BND 20%",
            "annual_return_pct": bog_return,
        },
        "freedom_2060": {
            "label":            "Fidelity Freedom Index 2060 (FDKLX)",
            "normalized":       f2060_norm,
            "ticker_details":   f2060_ticker_details,
            "allocation_label": "FDKLX 100% (target-date fund)",
            "annual_return_pct": f2060_return,
        },
        "alpha_pct":    alpha,
        "outperformed": alpha is not None and alpha > 0,
        "data_source":  "Yahoo Finance (monthly closes, adjusted for dividends & splits)",
    }
