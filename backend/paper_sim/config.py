"""Paper simulator capital defaults (aligned with Trading_Strategies.md)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PaperSimConfig(BaseModel):
    """Virtual account and fill defaults. Independent of EXECUTION_MODE / live broker."""

    total_capital_inr: float = Field(default=1_000_000.0, description="Virtual account ceiling")
    max_trade_investment_inr: float = Field(default=100_000.0)
    max_leg_investment_inr: float = Field(default=100_000.0)
    slippage_bps: float = Field(
        default=50.0,
        description="Conservative fill slippage in basis points (50 = 0.50%)",
    )
    underlying_price_cap_inr: float = Field(
        default=1000.0,
        description=(
            "When a paper order includes stock/underlying legs, cash-equity spot must be ≤ this INR. "
            "Options-only orders have no underlying price cap. Index underlyings are rejected only "
            "when the order includes stock/underlying. 0 disables the numeric spot check only."
        ),
    )
    default_exchange: str = "NFO"
    mark_provider: str = "icici_direct_data_only"


DEFAULT_CONFIG = PaperSimConfig()
