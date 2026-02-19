"""Stress test API routes for Monte Carlo simulation results."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import StressTestEnvelope, StressTestRecalculateRequest
from ..services.monte_carlo import get_latest_stress_test, run_stress_test, to_response_payload

router = APIRouter(prefix="/api/stress-test")


@router.get("/{username}", response_model=StressTestEnvelope)
def get_stress_test_result(username: str, db: Session = Depends(get_db)):
    """Get most recent stored stress test result for a user (without recalculating)."""
    try:
        latest = get_latest_stress_test(username, db)
        if not latest:
            return {"result": None}
        return {"result": to_response_payload(latest, username)}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error: {str(e)}")


@router.post("/{username}/recalculate", response_model=StressTestEnvelope)
def recalculate_stress_test(
    username: str,
    request: StressTestRecalculateRequest,
    db: Session = Depends(get_db),
):
    """Run a new Monte Carlo stress test and persist the result."""
    try:
        result = run_stress_test(
            username=username,
            db=db,
            simulation_count=request.simulation_count,
            random_seed=request.random_seed,
        )
        return {"result": to_response_payload(result, username)}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error: {str(e)}")
