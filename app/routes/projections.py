"""Projection and comparison API routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.comparison import get_comparison_data
from ..schemas import ComparisonResponse

router = APIRouter(prefix="/api")


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
