"""Transaction cost model (architecture §9.4 / Trading_Parameters Part O).

Every gamma hedge and signal must net these costs before the decision engine:

    net_hedge_edge = expected_gamma_pnl − expected_theta_loss − total_transaction_cost
    execute_hedge  = net_hedge_edge > min_edge_threshold AND |Δ| > delta_threshold

Components (configurable):
- Commission — ICICI Direct / NSE brokerage + statutory proxy
- Bid-ask — half-spread per leg
- Slippage — 0.05% equity; 1–2% of option mid for illiquid strikes
- Market impact — fixed bps by notional tier
- Optional borrow / financing / re-hedge estimates for signal scoring
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Literal, Mapping, Sequence

InstrumentKind = Literal["equity", "option"]


@dataclass(frozen=True, slots=True)
class ImpactTier:
    """Market-impact schedule: apply ``impact_bps`` when notional ≤ ``max_notional_inr``."""

    max_notional_inr: float
    impact_bps: float


@dataclass(frozen=True, slots=True)
class TransactionCostConfig:
    """Retail India F&O / equity cost defaults (override per strategy or env)."""

    # Commission
    equity_commission_bps: float = 2.5  # ~0.025% of equity notional
    option_commission_bps: float = 5.0  # of premium turnover
    option_commission_per_lot_inr: float = 20.0
    min_commission_inr: float = 0.0

    # Slippage (§9.4)
    equity_slippage_bps: float = 5.0  # 0.05%
    option_slippage_pct_of_mid: float = 0.015  # 1.5% of mid (mid of 1–2%)

    # Spread: use live half-spread when bid/ask present; else estimate
    default_half_spread_pct_of_mid: float = 0.5  # 0.5% of mid
    max_spread_pct: float = 2.0  # liquidity gate (Part T15 / I1)

    # Market impact by notional (INR)
    impact_tiers: tuple[ImpactTier, ...] = (
        ImpactTier(max_notional_inr=50_000.0, impact_bps=1.0),
        ImpactTier(max_notional_inr=200_000.0, impact_bps=2.0),
        ImpactTier(max_notional_inr=1_000_000.0, impact_bps=4.0),
        ImpactTier(max_notional_inr=float("inf"), impact_bps=8.0),
    )

    # Optional scoring extras (Part O)
    borrow_fee_annual_pct: float = 0.0
    financing_rate_annual_pct: float = 0.0
    days_held: float = 1.0
    expected_rehedge_count: int = 0
    rehedge_cost_multiplier: float = 1.0  # each re-hedge ≈ one round-trip fraction

    # Stat-arb: inflate |z| entry threshold so mean-reversion clears round-trip
    stat_arb_cost_buffer_z: float = 0.25


@dataclass(frozen=True, slots=True)
class LegCostInput:
    """One leg for cost estimation (share qty × price = notional)."""

    kind: InstrumentKind
    quantity: int
    mid_price: float
    bid: float | None = None
    ask: float | None = None
    lotsize: int = 1
    is_short_stock: bool = False


@dataclass(frozen=True, slots=True)
class LegCostBreakdown:
    kind: InstrumentKind
    notional_inr: float
    commission_inr: float
    half_spread_inr: float
    slippage_inr: float
    impact_inr: float
    borrow_inr: float
    financing_inr: float
    total_inr: float
    spread_pct: float | None


@dataclass(frozen=True, slots=True)
class TransactionCostResult:
    """Aggregate cost for a one-way or round-trip basket."""

    legs: tuple[LegCostBreakdown, ...]
    cost_commissions: float
    cost_spread: float
    cost_slippage: float
    cost_impact: float
    cost_borrow: float
    cost_financing: float
    cost_rehedge_est: float
    total_transaction_cost: float
    round_trip: bool
    liquidity_ok: bool
    detail: str = ""

    @property
    def total(self) -> float:
        return self.total_transaction_cost


def _bps_to_frac(bps: float) -> float:
    return float(bps) / 10_000.0


def _pct_to_frac(pct: float) -> float:
    return float(pct) / 100.0


def market_impact_bps(notional_inr: float, config: TransactionCostConfig) -> float:
    n = abs(float(notional_inr))
    for tier in config.impact_tiers:
        if n <= float(tier.max_notional_inr):
            return float(tier.impact_bps)
    return float(config.impact_tiers[-1].impact_bps) if config.impact_tiers else 0.0


def half_spread_per_share(
    *,
    mid: float,
    bid: float | None,
    ask: float | None,
    config: TransactionCostConfig,
) -> tuple[float, float | None]:
    """Return (half-spread INR per share, spread_pct of mid or None)."""
    m = float(mid)
    if m <= 0 or not isfinite(m):
        raise ValueError("mid_price must be > 0")
    if bid is not None and ask is not None and float(ask) >= float(bid) > 0:
        spread = float(ask) - float(bid)
        spread_pct = (spread / m) * 100.0
        return spread / 2.0, spread_pct
    half = m * _pct_to_frac(config.default_half_spread_pct_of_mid)
    return half, None


def estimate_leg_cost(
    leg: LegCostInput,
    *,
    config: TransactionCostConfig | None = None,
) -> LegCostBreakdown:
    cfg = config or TransactionCostConfig()
    qty = abs(int(leg.quantity))
    mid = float(leg.mid_price)
    if qty <= 0:
        raise ValueError("quantity must be > 0")
    if mid <= 0 or not isfinite(mid):
        raise ValueError("mid_price must be > 0")

    notional = mid * qty
    half_ps, spread_pct = half_spread_per_share(
        mid=mid, bid=leg.bid, ask=leg.ask, config=cfg
    )
    half_spread_inr = half_ps * qty

    if leg.kind == "equity":
        commission = max(
            notional * _bps_to_frac(cfg.equity_commission_bps),
            float(cfg.min_commission_inr),
        )
        slippage = notional * _bps_to_frac(cfg.equity_slippage_bps)
    else:
        lots = max(qty / max(int(leg.lotsize), 1), 1.0)
        commission = max(
            notional * _bps_to_frac(cfg.option_commission_bps)
            + lots * float(cfg.option_commission_per_lot_inr),
            float(cfg.min_commission_inr),
        )
        slippage = notional * float(cfg.option_slippage_pct_of_mid)

    impact = notional * _bps_to_frac(market_impact_bps(notional, cfg))

    borrow = 0.0
    if leg.is_short_stock and cfg.borrow_fee_annual_pct > 0:
        borrow = notional * _pct_to_frac(cfg.borrow_fee_annual_pct) * (
            float(cfg.days_held) / 365.0
        )
    financing = 0.0
    if cfg.financing_rate_annual_pct > 0 and leg.kind == "equity":
        financing = notional * _pct_to_frac(cfg.financing_rate_annual_pct) * (
            float(cfg.days_held) / 365.0
        )

    total = (
        commission + half_spread_inr + slippage + impact + borrow + financing
    )
    return LegCostBreakdown(
        kind=leg.kind,
        notional_inr=notional,
        commission_inr=commission,
        half_spread_inr=half_spread_inr,
        slippage_inr=slippage,
        impact_inr=impact,
        borrow_inr=borrow,
        financing_inr=financing,
        total_inr=total,
        spread_pct=spread_pct,
    )


def estimate_transaction_cost(
    legs: Sequence[LegCostInput] | Iterable[LegCostInput],
    *,
    config: TransactionCostConfig | None = None,
    round_trip: bool = False,
) -> TransactionCostResult:
    """Sum per-leg costs; optionally double for round-trip (entry+exit)."""
    cfg = config or TransactionCostConfig()
    breakdowns = tuple(estimate_leg_cost(leg, config=cfg) for leg in legs)
    if not breakdowns:
        raise ValueError("legs must be non-empty")

    commissions = sum(b.commission_inr for b in breakdowns)
    spread = sum(b.half_spread_inr for b in breakdowns)
    slippage = sum(b.slippage_inr for b in breakdowns)
    impact = sum(b.impact_inr for b in breakdowns)
    borrow = sum(b.borrow_inr for b in breakdowns)
    financing = sum(b.financing_inr for b in breakdowns)
    one_way = commissions + spread + slippage + impact + borrow + financing

    rehedge = 0.0
    if cfg.expected_rehedge_count > 0:
        rehedge = (
            one_way
            * float(cfg.expected_rehedge_count)
            * float(cfg.rehedge_cost_multiplier)
        )

    scale = 2.0 if round_trip else 1.0
    total = one_way * scale + rehedge

    liquidity_ok = True
    for b in breakdowns:
        if b.spread_pct is not None and b.spread_pct > float(cfg.max_spread_pct):
            liquidity_ok = False
            break

    return TransactionCostResult(
        legs=breakdowns,
        cost_commissions=commissions * scale,
        cost_spread=spread * scale,
        cost_slippage=slippage * scale,
        cost_impact=impact * scale,
        cost_borrow=borrow * scale,
        cost_financing=financing * scale,
        cost_rehedge_est=rehedge,
        total_transaction_cost=total,
        round_trip=round_trip,
        liquidity_ok=liquidity_ok,
        detail="ok" if liquidity_ok else "spread_exceeds_max",
    )


def edge_after_costs(*, gross_edge: float, total_transaction_cost: float) -> float:
    """Part O net edge — reject signal/hedge when ≤ 0."""
    return float(gross_edge) - float(total_transaction_cost)


def net_hedge_edge_after_costs(
    *,
    expected_gamma_pnl: float,
    expected_theta_loss: float,
    total_transaction_cost: float,
) -> float:
    """Architecture §9.4 hedge profitability identity."""
    return (
        float(expected_gamma_pnl)
        - float(expected_theta_loss)
        - float(total_transaction_cost)
    )


def cost_gate_passes(
    *,
    net_hedge_edge: float,
    min_edge_threshold: float = 0.0,
) -> bool:
    """§11.4 transaction cost gate: ``net_hedge_edge > min_edge_threshold`` (default 0)."""
    return float(net_hedge_edge) > float(min_edge_threshold)


def stat_arb_entry_z_with_cost_buffer(
    *,
    base_entry_z: float,
    config: TransactionCostConfig | None = None,
) -> float:
    """Inflate |z| entry so expected mean-reversion clears round-trip costs."""
    cfg = config or TransactionCostConfig()
    base = abs(float(base_entry_z))
    return base + float(cfg.stat_arb_cost_buffer_z)


def estimate_stock_hedge_cost(
    *,
    quantity: int,
    spot: float,
    config: TransactionCostConfig | None = None,
    round_trip: bool = False,
) -> TransactionCostResult:
    """Convenience for γ–θ stock re-hedges (mechanical path)."""
    return estimate_transaction_cost(
        [
            LegCostInput(
                kind="equity",
                quantity=abs(int(quantity)),
                mid_price=float(spot),
            )
        ],
        config=config,
        round_trip=round_trip,
    )


def estimate_from_mapping(
    legs: Sequence[Mapping[str, object]],
    *,
    config: TransactionCostConfig | None = None,
    round_trip: bool = False,
) -> TransactionCostResult:
    """Build ``LegCostInput`` from dicts (paper fills / order legs)."""
    parsed: list[LegCostInput] = []
    for raw in legs:
        kind_raw = str(raw.get("kind") or raw.get("type") or "option").lower()
        if kind_raw in {"stock", "equity", "underlying"}:
            kind: InstrumentKind = "equity"
        else:
            kind = "option"
        mid = float(raw.get("mid_price") or raw.get("mark_ltp") or raw.get("price") or 0)
        qty = abs(int(raw.get("quantity") or 0))  # type: ignore[arg-type]
        bid = raw.get("bid")
        ask = raw.get("ask")
        parsed.append(
            LegCostInput(
                kind=kind,
                quantity=qty,
                mid_price=mid,
                bid=float(bid) if bid is not None else None,
                ask=float(ask) if ask is not None else None,
                lotsize=int(raw.get("lotsize") or 1),  # type: ignore[arg-type]
                is_short_stock=bool(raw.get("is_short_stock")),
            )
        )
    return estimate_transaction_cost(parsed, config=config, round_trip=round_trip)


def default_cost_config() -> TransactionCostConfig:
    return TransactionCostConfig()
