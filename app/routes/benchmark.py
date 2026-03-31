"""Benchmark comparison API routes.

Provides month-by-month portfolio performance vs the Boglehead 3-Fund
for any recorded year, with local disk caching so Yahoo Finance is only
hit once per ticker/year combination.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Path as FPath, Query

from ..services.benchmark import get_benchmark_comparison

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/benchmark")


@router.get("/{username}/{year}")
async def benchmark_comparison(
    username: str = FPath(..., description="User's display name (e.g. 'Steven')"),
    year: int = FPath(..., ge=2000, le=2100, description="Calendar year to compare"),
):
    """
    Return monthly normalized portfolio performance vs the Boglehead 3-Fund
    for the requested *username* and *year*.

    Monthly data is fetched from Yahoo Finance on the first request and
    cached locally, so subsequent calls are served from disk.

    Response
    --------
    ``{ year, username, months, user_portfolio, boglehead, alpha_pct,
        outperformed, data_source }``
    """
    try:
        data = get_benchmark_comparison(username, year)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("Failed to compute benchmark for %s/%d", username, year)
        raise HTTPException(
            status_code=500,
            detail=f"Could not compute benchmark: {exc}",
        ) from exc

    return data
