"""Pydantic models for request/response validation."""
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Optional

# Supported account types.  Add new types here and in the models.py
# CheckConstraint so both layers stay in sync.
ACCOUNT_TYPES = Literal["401k", "roth_ira", "403b", "hsa", "taxable", "traditional_ira"]


class BalanceCreate(BaseModel):
    account_type: ACCOUNT_TYPES
    year: int = Field(ge=2000, le=2100)
    balance: float = Field(ge=0)
    notes: Optional[str] = None


class BalanceUpdate(BaseModel):
    balance: float = Field(ge=0)
    notes: Optional[str] = None


class BalanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    year: int
    balance: float
    notes: Optional[str]
    recorded_at: str


class ProjectionPoint(BaseModel):
    year: int
    balance: float


class ComparisonResponse(BaseModel):
    projected: list[ProjectionPoint]
    actual: list[ProjectionPoint]
    deltas: list[dict]
    retirement_age: Optional[int] = None
    retirement_year: Optional[int] = None
    life_expectancy_age: Optional[int] = None
    withdrawal_pct: Optional[float] = None


class StressTestRecalculateRequest(BaseModel):
    simulation_count: int = Field(default=10000, ge=5000, le=100000)
    random_seed: Optional[int] = Field(default=None, ge=0)


class JointStressTestRecalculateRequest(BaseModel):
    usernames: list[str] = Field(min_length=2)
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
