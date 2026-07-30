"""Decision-log models — read-only audit view over recommendations + learning store.

Field names and enum values mirror `frontend/src/types/decisions.ts` so the
decision log and pre-approval packet screens can bind directly.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DecisionStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class StrategyModule(str, Enum):
    """Frontend-facing module ids (`stat_arb` is reserved for a later phase)."""

    stat_arb = "stat_arb"
    volatility = "volatility"
    gamma_scalping = "gamma_scalping"
    vega_scalping = "vega_scalping"


class GateStatus(str, Enum):
    pass_ = "pass"
    fail = "fail"
    warn = "warn"


class RagCitation(BaseModel):
    document: str
    chapter: str | None = None
    page: int | None = None


class OptionLeg(BaseModel):
    leg_id: int
    type: str
    position: int
    strike: float | None = None
    expiration: str | None = None
    delta: float
    gamma: float
    theta: float
    vega: float
    mid_price: float | None = None


class GreeksTotals(BaseModel):
    total_delta: float = 0.0
    total_gamma: float = 0.0
    total_theta: float = 0.0
    total_vega: float = 0.0


class TradeEconomics(BaseModel):
    net_edge_after_costs: float
    margin_estimate: float
    expected_gamma_pnl: float = 0.0
    expected_theta_loss: float = 0.0
    total_transaction_cost: float = 0.0
    slippage_cap_bps: float = 0.0


class TradePlan(BaseModel):
    stop: str
    target: str
    time_exit: str


class RiskGate(BaseModel):
    id: str
    label: str
    status: GateStatus
    detail: str | None = None


class StrategyContext(BaseModel):
    iv_annualized: float | None = None
    garch_forecast: float | None = None
    gamma_theta_breakeven_pct: float | None = None
    entry_mode: str | None = None
    term_structure_ok: bool | None = None
    vega_neutral_at_entry: bool | None = None
    intraday_iv_z_score: float | None = None
    must_flatten_same_day: bool | None = None


class DecisionRecord(BaseModel):
    """One audited decision — matches the frontend `PendingDecision` shape."""

    decision_id: str
    signal_id: str
    status: DecisionStatus
    module: StrategyModule
    underlying_symbol: str
    confidence: float
    regime: str
    explanation: str
    rationale: str
    rag_citations: list[RagCitation] = Field(default_factory=list)
    legs: list[OptionLeg] = Field(default_factory=list)
    totals: GreeksTotals = Field(default_factory=GreeksTotals)
    economics: TradeEconomics
    plan: TradePlan
    event_risks: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    strategy_context: StrategyContext = Field(default_factory=StrategyContext)
    risk_gates: list[RiskGate] = Field(default_factory=list)
    created_at: datetime
    expires_at: datetime
    scenario_tag: str | None = None
    alternative_strategies: list[str] | None = None
