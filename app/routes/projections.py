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
        comparison_years = sorted({
            int(item.get("year", 0))
            for item in comparison_projected
            if int(item.get("year", 0)) > 0
        })
        for key in ("3pct", "5pct"):
            rows = scenarios.get(key, [])
            year_to_balance = {
                int(item.get("year", 0)): float(item.get("balance", 0.0))
                for item in rows
                if int(item.get("year", 0)) > 0
            }
            available_years = sorted(year_to_balance.keys())
            rebased_rows = []
            for year in comparison_years:
                scenario_raw = year_to_balance.get(year)
                ratio = None
                if scenario_raw is not None:
                    base_raw = raw_baseline.get(year)
                    if base_raw and base_raw > 0:
                        ratio = scenario_raw / base_raw
                else:
                    prior_years = [y for y in available_years if y < year and raw_baseline.get(y)]
                    if prior_years:
                        prior_year = prior_years[-1]
                        prior_base = raw_baseline.get(prior_year)
                        prior_scenario = year_to_balance.get(prior_year)
                        if prior_base and prior_base > 0 and prior_scenario is not None:
                            ratio = prior_scenario / prior_base

                base_scaled = scaled_baseline.get(year)
                if ratio is not None and base_scaled is not None:
                    scenario_scaled = base_scaled * ratio
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
