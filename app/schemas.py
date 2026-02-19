"""Pydantic models for request/response validation."""
from pydantic import BaseModel, Field
from typing import Literal, Optional


class BalanceCreate(BaseModel):
    account_type: Literal["401k", "roth_ira"]
    year: int = Field(ge=2000, le=2100)
    balance: float = Field(ge=0)
    notes: Optional[str] = None


class BalanceUpdate(BaseModel):
    balance: float = Field(ge=0)
    notes: Optional[str] = None


class BalanceResponse(BaseModel):
    id: int
    account_id: int
    year: int
    balance: float
    notes: Optional[str]
    recorded_at: str

    class Config:
        from_attributes = True


class ProjectionPoint(BaseModel):
    year: int
    balance: float


class ComparisonResponse(BaseModel):
    projected: list[ProjectionPoint]
    actual: list[ProjectionPoint]
    deltas: list[dict]


class StressTestRecalculateRequest(BaseModel):
    simulation_count: int = Field(default=10000, ge=5000, le=100000)
    random_seed: Optional[int] = Field(default=None, ge=0)


class StressTestResponse(BaseModel):
    id: int
    username: str
    created_at: str
    simulation_count: int
    random_seed: Optional[int]
    mean_return_pct: float
    volatility_pct: float
    inflation_pct: float
    success_probability_pct: float
    rating_tier: int
    rating_grade: str
    rating_label: str
    life_expectancy_age: int
    success_threshold_pct: float
    p10_terminal_balance: float
    p50_terminal_balance: float
    p90_terminal_balance: float
    assumptions: dict


class StressTestEnvelope(BaseModel):
    result: Optional[StressTestResponse] = None
