"""Projection and comparison API routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from ..services.comparison import get_comparison_data, get_all_users_comparison
from ..services.projection import get_match_scenario_projections, get_user_projection
from ..schemas import ComparisonResponse

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
        print(f"\nDEBUG: API /api/comparison/{username} called")
        data = get_comparison_data(username, db)
        print(f"DEBUG: Comparison data retrieved for {username}")
        print(f"DEBUG: Number of deltas: {len(data.get('deltas', []))}")
        if data.get('deltas'):
            print(f"DEBUG: First delta keys: {data['deltas'][0].keys()}")
            print(f"DEBUG: First delta: {data['deltas'][0]}")
        return data
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get("/match-scenarios/{username}")
async def get_match_scenarios(username: str, db: Session = Depends(get_db)):
    """
    Return projected balances under 3% and 5% employer 401k match scenarios.
    Useful for showing the benefit of a company match on the chart.
    """
    try:
        # Keep scenario overlays on the same rebased chart scale as /api/comparison/{username}
        # so baseline and scenario lines are directly comparable.
        comparison = get_comparison_data(username, db)
        comparison_projected = comparison.get("projected", [])
        raw_projected = get_user_projection(username).get("projected", [])

        comparison_by_year = {int(item.get("year", 0)): float(item.get("balance", 0.0)) for item in comparison_projected}
        raw_by_year = {int(item.get("year", 0)): float(item.get("balance", 0.0)) for item in raw_projected}
        common_years = sorted(year for year in comparison_by_year.keys() if year in raw_by_year and raw_by_year[year] > 0)

        scale_factor = None
        if common_years:
            ratios = [comparison_by_year[year] / raw_by_year[year] for year in common_years]
            scale_factor = sum(ratios) / len(ratios)

        return get_match_scenario_projections(username, scale_factor=scale_factor)
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
