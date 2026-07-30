from __future__ import annotations

from pydantic import BaseModel, Field


class TradeAttemptResult(BaseModel):
    rank: int
    underlying_symbol: str
    success: bool
    error: str | None = None
    trade_id: str | None = None
    order_status: str | None = None


class AutonomousExecutionResult(BaseModel):
    executed: bool
    selected_rank: int | None = None
    trade_id: str | None = None
    underlying_symbol: str | None = None
    attempts: list[TradeAttemptResult] = Field(default_factory=list)
    message: str
