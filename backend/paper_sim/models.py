"""DTOs for the in-house paper simulator (not ICICI Direct order payloads)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class PaperSide(str, Enum):
    buy = "buy"
    sell = "sell"


class PaperLegRequest(BaseModel):
    symbol: str
    side: PaperSide
    quantity: int = Field(gt=0)
    exchange: str = "NFO"
    symbol_token: str | None = None
    limit_price: float | None = None
    option_type: Literal["CE", "PE"] | None = None
    strike: float | None = None
    expiry: str | None = None


class PaperOrderRequest(BaseModel):
    """Multi-leg paper order — never forwarded to ICICI Direct place_order.

    Phase 1: after the entry ``legs`` fill, remaining ``intended_legs`` of a
    multi-leg strategy may auto-complete without operator consent, subject to
    the same open-trade gates (capital, freshness, lotsize, pre-trade, Part T).
    """

    strategy_tag: str | None = None
    underlying: str | None = None
    legs: list[PaperLegRequest] = Field(min_length=1)
    note: str | None = None
    # Full opening structure the bot intends (defaults to inferred / entry legs).
    intended_legs: list[PaperLegRequest] | None = None
    # When true (Phase 1 default), auto-submit missing intended opening legs.
    auto_complete_multi_leg: bool = True


class PaperFill(BaseModel):
    fill_id: str
    order_id: str
    symbol: str
    exchange: str
    symbol_token: str
    side: PaperSide
    quantity: int
    mark_ltp: float
    fill_price: float
    slippage_bps: float
    notional_inr: float
    filled_at: datetime


class PaperLegPosition(BaseModel):
    symbol: str
    exchange: str
    symbol_token: str
    side: PaperSide
    quantity: int
    avg_price: float
    mark_ltp: float | None = None
    unrealized_pnl: float = 0.0
    lotsize: int = 1


class PaperIntendedLeg(BaseModel):
    """Persisted intended opening leg (for auto multi-leg completion)."""

    symbol: str
    exchange: str = "NFO"
    symbol_token: str | None = None
    side: PaperSide
    quantity: int = Field(gt=0)
    option_type: Literal["CE", "PE"] | None = None
    strike: float | None = None
    expiry: str | None = None


class PaperPosition(BaseModel):
    position_id: str
    strategy_tag: str | None = None
    underlying: str | None = None
    status: Literal["open", "closed"] = "open"
    opened_at: datetime
    closed_at: datetime | None = None
    legs: list[PaperLegPosition] = Field(default_factory=list)
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    note: str | None = None
    # Phase 1 multi-leg opening plan (auto-complete without consent)
    intended_legs: list[PaperIntendedLeg] = Field(default_factory=list)
    structure_complete: bool = True
    opening_investment_inr: float = 0.0
    auto_complete_multi_leg: bool = True
    # Part J — γ–θ re-hedge state (mechanical; set on entry / each re-hedge)
    hedge_point_price: float | None = None
    gamma_theta_breakeven_pct: float | None = None
    breakeven_paid_count: int = 0
    rehedge_method: Literal[
        "increase_hedge", "reduce_options", "adjust_call_put_mix"
    ] = "increase_hedge"
    last_rehedge_at: datetime | None = None
    total_delta: float | None = None
    total_gamma: float | None = None
    total_theta: float | None = None
    total_vega: float | None = None


class PaperAccountSnapshot(BaseModel):
    cash_inr: float
    starting_capital_inr: float
    reserved_margin_inr: float
    equity_inr: float
    realized_pnl: float
    unrealized_pnl: float
    open_positions: int
    max_trade_investment_inr: float
    max_leg_investment_inr: float
    mark_provider: str
    updated_at: datetime


class OptionChainContract(BaseModel):
    tradingsymbol: str
    symboltoken: str
    exchange: str
    name: str | None = None
    expiry: str | None = None
    strike: float | None = None
    option_type: Literal["CE", "PE"] | None = None
    lotsize: int = 1
    ltp: float | None = None


class OptionChainSnapshot(BaseModel):
    underlying: str
    exchange: str
    expiry: str | None
    spot_ltp: float | None = None
    contracts: list[OptionChainContract]
    as_of: datetime
    source: str = "icici_direct_data_only"
    marks_fresh: bool | None = None
    stale_contracts: list[str] = Field(default_factory=list)
    spot_age_sec: float | None = None
    instrument_master_age_sec: float | None = None
