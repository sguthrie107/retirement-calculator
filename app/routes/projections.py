"""Projection and comparison API routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from ..services.comparison import get_comparison_data, get_all_users_comparison
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
