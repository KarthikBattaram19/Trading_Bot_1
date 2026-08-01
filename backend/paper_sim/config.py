"""Paper simulator capital defaults (aligned with Trading_Strategies.md)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.execution.risk_gate import PreTradeThresholds
from backend.quant.costs.transaction_cost import TransactionCostConfig

RehedgeMethod = Literal["increase_hedge", "reduce_options", "adjust_call_put_mix"]


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
        default=0.0,
        description=(
            "Deprecated under the options-only hard lock; cash stock/underlying legs are rejected "
            "before any numeric spot-cap check. 0 keeps the legacy check disabled."
        ),
    )
    default_exchange: str = "NFO"
    mark_provider: str = "icici_direct_data_only"
    # Fresh-marks gate (Architecture §8.2 / §8.6 — MD-01)
    quote_stale_threshold_sec: float = Field(
        default=60.0,
        description="Max age for cash/underlying LTP before gate rejects (feed stale_threshold_sec)",
    )
    option_stale_threshold_sec: float = Field(
        default=120.0,
        description="Max age for NFO option marks before gate rejects",
    )
    instrument_master_max_age_sec: float = Field(
        default=86_400.0,
        description="Max age for scrip master cache before forced refresh (MD-11 daily)",
    )
    require_fresh_marks: bool = Field(
        default=True,
        description="When true, submit/close/refresh reject stale or missing LTPs",
    )
    # Phase 1.6 — continuous γ–θ re-hedge automation (Part J; no LLM)
    automation_tick_sec: float = Field(
        default=30.0,
        ge=1.0,
        description="Seconds between automation loop ticks",
    )
    rehedge_cooldown_sec: float = Field(
        default=60.0,
        ge=0.0,
        description="Min seconds between re-hedges on the same position (PS-07)",
    )
    max_breakeven_paid_count: int = Field(
        default=20,
        ge=1,
        description="Cap re-hedge thrash per position (PS-07)",
    )
    use_half_breakeven: bool = Field(
        default=False,
        description="J3: trigger at half breakeven distance",
    )
    rehedge_method: RehedgeMethod = Field(
        default="adjust_call_put_mix",
        description="J4 default re-hedge method",
    )
    min_edge_threshold: float = Field(
        default=0.0,
        description="§9.4 net_hedge_edge must exceed this to execute",
    )
    delta_threshold: float = Field(
        default=0.1,
        ge=0.0,
        description="§9.4 |total_delta| must exceed this to execute hedge",
    )
    default_iv_annual_pct: float = Field(
        default=25.0,
        gt=0.0,
        description="Fallback IV (%) for BSM Greeks when mark IV unavailable",
    )
    risk_free_rate_pct: float = Field(default=6.5, ge=0.0)
    dividend_yield_pct: float = Field(default=0.0, ge=0.0)
    # Phase 1.7 — cost model override (None → estimate via TransactionCostConfig)
    hedge_transaction_cost_inr: float | None = Field(
        default=None,
        description=(
            "If set, overrides §9.4 cost-model estimate for net_hedge_edge. "
            "None → estimate stock-hedge cost via TransactionCostConfig."
        ),
    )
    # Cost model knobs (subset surfaced on paper config; full defaults in TransactionCostConfig)
    equity_commission_bps: float = Field(default=2.5, ge=0.0)
    equity_slippage_bps: float = Field(default=5.0, ge=0.0)
    option_slippage_pct_of_mid: float = Field(default=0.015, ge=0.0)
    # Pre-trade Greek ceilings (§11.4)
    max_abs_total_delta: float = Field(default=10_000.0, gt=0.0)
    max_abs_total_gamma: float = Field(default=5_000.0, gt=0.0)
    max_abs_total_vega: float = Field(default=50_000.0, gt=0.0)
    min_total_theta: float = Field(default=-50_000.0)
    min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    max_drawdown_pct: float = Field(default=10.0, ge=0.0)

    def transaction_cost_config(self) -> TransactionCostConfig:
        """Build §9.4 cost config from paper-sim knobs."""
        return TransactionCostConfig(
            equity_commission_bps=self.equity_commission_bps,
            equity_slippage_bps=self.equity_slippage_bps,
            option_slippage_pct_of_mid=self.option_slippage_pct_of_mid,
        )

    def pre_trade_thresholds(self) -> PreTradeThresholds:
        """Build §11.4 thresholds aligned with paper freshness + Greek caps."""
        return PreTradeThresholds(
            quote_stale_threshold_sec=self.quote_stale_threshold_sec,
            option_stale_threshold_sec=self.option_stale_threshold_sec,
            max_abs_total_delta=self.max_abs_total_delta,
            max_abs_total_gamma=self.max_abs_total_gamma,
            max_abs_total_vega=self.max_abs_total_vega,
            min_total_theta=self.min_total_theta,
            min_confidence=self.min_confidence,
            max_drawdown_pct=self.max_drawdown_pct,
            min_edge_threshold=self.min_edge_threshold,
        )


DEFAULT_CONFIG = PaperSimConfig()
