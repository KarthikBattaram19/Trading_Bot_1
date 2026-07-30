"""Continual learning models — architecture §12."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TradeOutcomeLabel(str, Enum):
    win = "win"
    loss = "loss"
    scratch = "scratch"


class FailureMemoryMatch(BaseModel):
    """A past losing context similar to the current recommendation (§12.6)."""

    failure_id: str
    similarity: float
    summary: str
    loss_pnl_inr: float
    lesson: str
    strategy: str
    underlying_symbol: str
    closed_at: datetime


class LearningInsight(BaseModel):
    """Per-recommendation learning overlay shown in the insight packet."""

    failure_matches: list[FailureMemoryMatch] = Field(default_factory=list)
    confidence_penalty: float = 0.0
    confidence_before: float
    confidence_after: float
    module_win_rate: float | None = None
    module_trade_count: int = 0
    module_expectancy_inr: float | None = None
    learning_note: str


class OpenTradeRecord(BaseModel):
    """Open discretionary trade awaiting outcome for the learning loop."""

    trade_id: str
    underlying_symbol: str
    rank: int
    strategy: str
    entry_mode: str | None = None
    scenario_tag: str
    primary_signal: str
    score: float
    confidence: float
    recommendation_snapshot: dict[str, Any]
    opened_at: datetime
    config_snapshot_id: str = "defaults"


class TradeOutcomeRecord(BaseModel):
    """Closed trade with full lineage for attribution (§12.7)."""

    outcome_id: str
    trade_id: str
    underlying_symbol: str
    rank: int
    strategy: str
    entry_mode: str | None = None
    scenario_tag: str
    primary_signal: str
    score_at_entry: float
    confidence_at_entry: float
    outcome: TradeOutcomeLabel
    realized_pnl_inr: float
    exit_reason: str
    notes: str | None = None
    recommendation_snapshot: dict[str, Any]
    opened_at: datetime
    closed_at: datetime
    failure_memory_id: str | None = None
    config_snapshot_id: str = "defaults"


class FailureMemoryEntry(BaseModel):
    """Structured losing-trade context stored for pre-trade retrieval."""

    failure_id: str
    trade_id: str
    underlying_symbol: str
    strategy: str
    entry_mode: str | None = None
    scenario_tag: str
    primary_signal: str
    market_summary: str
    loss_pnl_inr: float
    exit_reason: str
    lesson: str
    tags: list[str] = Field(default_factory=list)
    closed_at: datetime


class ModuleAttribution(BaseModel):
    strategy: str
    trade_count: int
    wins: int
    losses: int
    scratches: int
    win_rate: float
    total_pnl_inr: float
    expectancy_inr: float
    weight: float = 1.0


class AdaptationEvent(BaseModel):
    adaptation_id: str
    triggered_at: datetime
    trigger: str
    action: str
    parameter_changes: dict[str, Any] = Field(default_factory=dict)
    walk_forward_passed: bool
    deployed: bool
    detail: str
    config_snapshot_id: str


class CloseTradeRequest(BaseModel):
    trade_id: str
    outcome: TradeOutcomeLabel
    realized_pnl_inr: float
    exit_reason: str
    notes: str | None = None


class LearningDashboard(BaseModel):
    """Operator view of the continual learning loop."""

    as_of: datetime
    closed_trade_count: int
    open_trade_count: int
    win_rate: float | None
    total_pnl_inr: float
    profit_factor: float | None
    failure_memory_count: int
    adaptation_frozen: bool
    freeze_reason: str | None = None
    module_attribution: list[ModuleAttribution]
    recent_outcomes: list[TradeOutcomeRecord]
    open_trades: list[OpenTradeRecord]
    failure_memories: list[FailureMemoryEntry]
    adaptation_history: list[AdaptationEvent]
    learning_loop_notes: list[str]
