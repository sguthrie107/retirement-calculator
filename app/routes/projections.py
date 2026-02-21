"""Projection and comparison API routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from ..services.comparison import get_comparison_data, get_all_users_comparison
from ..services.projection import get_match_scenario_projections
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
    Return projected balances for +3% and +5% employee 401k contribution scenarios.
    Scenario overlays are rebased year-by-year to the same scaled frame as
    /api/comparison/{username} for direct visual comparison.
    """
    try:
        comparison = get_comparison_data(username, db)
        comparison_projected = comparison.get("projected", [])

        scenarios = get_match_scenario_projections(username)
        raw_baseline = {
            int(item.get("year", 0)): float(item.get("balance", 0.0))
            for item in scenarios.get("baseline", [])
            if int(item.get("year", 0)) > 0
        }
        scaled_baseline = {
            int(item.get("year", 0)): float(item.get("balance", 0.0))
            for item in comparison_projected
            if int(item.get("year", 0)) > 0
        }

        rebased = {}
        for key in ("3pct", "5pct"):
            rows = scenarios.get(key, [])
            year_to_balance = {
                int(item.get("year", 0)): float(item.get("balance", 0.0))
                for item in rows
                if int(item.get("year", 0)) > 0
            }
            rebased_rows = []
            for year in sorted(year_to_balance.keys()):
                base_raw = raw_baseline.get(year)
                base_scaled = scaled_baseline.get(year)
                scenario_raw = year_to_balance[year]
                if base_raw and base_scaled and base_raw > 0:
                    ratio = scenario_raw / base_raw
                    scenario_scaled = base_scaled * ratio
                else:
                    scenario_scaled = scenario_raw
                rebased_rows.append({"year": year, "balance": round(float(scenario_scaled), 2)})
            rebased[key] = rebased_rows

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
