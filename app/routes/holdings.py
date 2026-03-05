"""Live holdings API routes."""
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from ..services.holdings import get_live_holdings_for_user


router = APIRouter(prefix="/api")


@router.get("/holdings/{username}")
async def get_live_holdings(username: str, as_of: date | None = Query(default=None)):
    """Return current-phase holdings with daily trend for a user."""
    try:
        return get_live_holdings_for_user(username, as_of=as_of)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(exc)}")
