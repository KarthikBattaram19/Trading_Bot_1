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
    """Multi-leg paper order — never forwarded to ICICI Direct place_order."""

    strategy_tag: str | None = None
    underlying: str | None = None
    legs: list[PaperLegRequest] = Field(min_length=1)
    note: str | None = None


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
