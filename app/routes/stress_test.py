"""Stress test API routes for Monte Carlo simulation results."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..limiter import limiter
from ..schemas import JointStressTestRecalculateRequest, StressTestEnvelope, StressTestRecalculateRequest
from ..services.monte_carlo import (
    get_latest_joint_stress_test,
    get_latest_stress_test,
    is_stress_test_snapshot_stale,
    run_joint_stress_test,
    run_stress_test,
    to_response_payload,
)

router = APIRouter(prefix="/api/stress-test")


@router.get("/joint-result", response_model=StressTestEnvelope)
def get_joint_stress_test_result(
    usernames: list[str] = Query(..., description="List of usernames in the household"),
    db: Session = Depends(get_db),
):
    """Get the most recent joint household stress test result (without recalculating)."""
    try:
        latest = get_latest_joint_stress_test(usernames, db)
        if not latest:
            return {"result": None}
        assumptions = latest.assumptions_json or {}
        display_name = " + ".join(assumptions.get("usernames", usernames))
        return {"result": to_response_payload(latest, display_name)}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error: {str(e)}")


@router.post("/recalculate-joint", response_model=StressTestEnvelope)
@limiter.limit("5/minute")
async def recalculate_joint_stress_test(
    request: Request,
    body: JointStressTestRecalculateRequest,
    db: Session = Depends(get_db),
):
    """Run a new joint household Monte Carlo stress test and persist the result."""
    try:
        result = await asyncio.to_thread(
            run_joint_stress_test,
            usernames=body.usernames,
            db=db,
            simulation_count=body.simulation_count,
            random_seed=body.random_seed,
        )
        assumptions = result.assumptions_json or {}
        display_name = " + ".join(assumptions.get("usernames", body.usernames))
        return {"result": to_response_payload(result, display_name)}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error: {str(e)}")


@router.get("/{username}", response_model=StressTestEnvelope)
def get_stress_test_result(username: str, db: Session = Depends(get_db)):
    """Get most recent stored stress test result for a user (without recalculating)."""
    try:
        latest = get_latest_stress_test(username, db)
        if not latest:
            return {"result": None}
        if is_stress_test_snapshot_stale(username, latest, db):
            latest = run_stress_test(
                username=username,
                db=db,
                simulation_count=latest.simulation_count,
                random_seed=latest.random_seed,
            )
        return {"result": to_response_payload(latest, username)}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error: {str(e)}")


@router.post("/{username}/recalculate", response_model=StressTestEnvelope)
@limiter.limit("5/minute")
async def recalculate_stress_test(
    request: Request,
    username: str,
    body: StressTestRecalculateRequest,
    db: Session = Depends(get_db),
):
    """Run a new Monte Carlo stress test (offloaded to thread pool) and persist the result."""
    try:
        result = await asyncio.to_thread(
            run_stress_test,
            username=username,
            db=db,
            simulation_count=body.simulation_count,
            random_seed=body.random_seed,
        )
        return {"result": to_response_payload(result, username)}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error: {str(e)}")
