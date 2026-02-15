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
