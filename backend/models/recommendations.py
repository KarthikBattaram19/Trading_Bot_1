from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from backend.models.learning import LearningInsight
from backend.models.trades import AutonomousExecutionResult


class FeedSourceStatus(str, Enum):
    """Operational status of a marks / sentiment feed (not MCP assignment)."""

    active = "active"
    unavailable = "unavailable"
    stub = "stub"


class FeedHealth(str, Enum):
    fresh = "fresh"
    stale = "stale"
    error = "error"


class StrategyType(str, Enum):
    simple_volatility = "simple_volatility"
    gamma_scalping = "gamma_scalping"
    vega_scalping = "vega_scalping"
    blocked = "blocked"


class GateResult(BaseModel):
    gate_id: str
    label: str
    passed: bool
    detail: str | None = None
    parameter_ref: str | None = None


class NewsItem(BaseModel):
    title: str
    summary: str
    source: str
    time_published: str
    sentiment_label: str
    sentiment_score: float
    tickers: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    relevance_to_trade: str | None = None


class FeedSource(BaseModel):
    """ICICI Direct or Market_News feed health entry for UI / packets."""

    source_id: str
    source_name: str
    status: FeedSourceStatus
    capabilities: list[str]
    last_fetch_at: datetime | None = None
    health: FeedHealth = FeedHealth.fresh
    detail: str | None = None


class ParameterSnapshot(BaseModel):
    und_price: float
    iv_annualized: float
    garch_forecast: float
    iv_z_score: float | None = None
    days_to_earnings: int | None = None
    atm_premium_inr: float
    volume: int
    open_interest: int
    spread_pct: float
    dte: int
    realized_vol_intraday: float | None = None
    garch_distorted: bool = False


class StrategySelectionLogic(BaseModel):
    selected_strategy: StrategyType
    entry_mode: str | None = None
    scenario_tag: str
    cross_strategy_matrix_ref: str
    primary_signal: str
    rejected_strategies: list[str] = Field(default_factory=list)
    news_impact: str | None = None


class ScoreBreakdown(BaseModel):
    """Transparent ranking components for UI insight packets."""

    base: float
    strategy_boost: float
    liquidity_boost: float
    spread_penalty: float
    failure_memory_penalty: float = 0.0
    module_weight_factor: float = 1.0
    total: float
    components: list[str] = Field(default_factory=list)


class HedgeInsight(BaseModel):
    """P1.5 — hedge construction summary (recommendation stage)."""

    method: str
    greek_targets: str
    structure_note: str


class TradeEconomicsInsight(BaseModel):
    """P1.6 — size & margin estimate within retail INR caps."""

    margin_estimate_inr: float
    max_trade_budget_inr: float = 100_000
    atm_premium_inr: float
    estimated_slippage_pct: float
    net_edge_note: str


class InstrumentRecommendation(BaseModel):
    """Top-N ranked trade with complete operator insight packet (P1 + ranking)."""

    rank: int
    underlying_symbol: str
    score: float
    confidence: float
    strategy: StrategySelectionLogic
    parameters: ParameterSnapshot
    parameter_gates: list[GateResult]
    market_summary: str
    entry_rationale: str
    complete_logic: list[str]
    score_breakdown: ScoreBreakdown
    hedge: HedgeInsight
    economics: TradeEconomicsInsight
    exit_plan: str
    event_risks: list[str]
    failure_modes: list[str]
    why_this_rank: str
    alternative_considered: str | None = None
    insight_checklist: list[str] = Field(default_factory=list)
    learning: LearningInsight | None = None


class MarketNewsSummary(BaseModel):
    headline_count: int
    dominant_sentiment: str
    earnings_mentions: int
    macro_risk_flags: list[str]
    interpretation: str
    items: list[NewsItem]


class RecommendationResponse(BaseModel):
    generated_at: datetime
    feed_as_of: datetime
    feed_sources: list[FeedSource]
    market_news: MarketNewsSummary
    universe_scanned: int
    candidates_passing_gates: int
    recommendations: list[InstrumentRecommendation]
    analysis_notes: list[str]
    autonomous_execution: AutonomousExecutionResult | None = None
