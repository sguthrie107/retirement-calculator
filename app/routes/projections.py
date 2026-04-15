"""Projection and comparison API routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from ..services.comparison import (
    _apply_projected_chart_seed,
    _ensure_continuous_projected_series,
    get_comparison_data,
    get_all_users_comparison,
)
from ..services.projection import get_match_scenario_projections
from ..schemas import ComparisonResponse
from lib.calculator_utils import load_user_profile

router = APIRouter(prefix="/api")


class UsersComparisonResponse(BaseModel):
    users: list[dict]


@router.get("/comparison/{username}", response_model=ComparisonResponse)
async def get_comparison(username: str, db: Session = Depends(get_db)):
    """
    Get projected vs actual balance comparison for a user.
    
    Args:
        username: Name of user from users.json
        
    Returns:
        ComparisonResponse with projected, actual, and delta data
    """
    try:
        data = get_comparison_data(username, db)
        return data
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get("/match-scenarios/{username}")
async def get_match_scenarios(username: str, db: Session = Depends(get_db)):
    """
    Return projected balances for +3% and +5% employee 401k contribution scenarios.
    Scenario overlays use the same seeded projection mapping as the main chart.
    """
    try:
        profile = load_user_profile(username)
        scenarios = get_match_scenario_projections(username)
        rebased = {}
        for key, pct_boost in (("3pct", 0.03), ("5pct", 0.05)):
            rebased_rows = _apply_projected_chart_seed(
                scenarios.get(key, []),
                profile,
                contribution_pct_boost=pct_boost,
            )
            rebased[key] = [
                {
                    "year": int(item.get("year", 0)),
                    "balance": round(float(item.get("balance", 0.0)), 2),
                }
                for item in _ensure_continuous_projected_series(rebased_rows)
                if int(item.get("year", 0)) > 0
            ]

        return rebased
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get("/comparison-all", response_model=UsersComparisonResponse)
async def get_all_users_comparison_endpoint(db: Session = Depends(get_db)):
    """
    Get projected balances for all users to compare side-by-side.
    
    Returns:
        UsersComparisonResponse with list of users and their projections
    """
    try:
        data = get_all_users_comparison(db)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")
