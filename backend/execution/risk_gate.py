"""Pre-trade risk gate checklist (architecture §11.4).

Thresholds are configurable (defaults below). Portfolio circuit breakers
(§11.4.1) are Phase 2 — this module evaluates per-order / per-signal gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

from backend.quant.costs.transaction_cost import cost_gate_passes
from backend.quant.risk.greeks_limits import (
    GreeksLimitThresholds,
    check_greeks_limits,
)

GateOutcome = Literal["pass", "fail", "skip"]


@dataclass(frozen=True, slots=True)
class PreTradeThresholds:
    """Default §11.4 thresholds (adjustable without redeploy in later phases)."""

    quote_stale_threshold_sec: float = 60.0
    option_stale_threshold_sec: float = 120.0
    max_abs_total_delta: float = 10_000.0
    max_abs_total_gamma: float = 5_000.0
    max_abs_total_vega: float = 50_000.0
    max_abs_total_rho: float = 50_000.0
    min_total_theta: float = -50_000.0
    max_drawdown_pct: float = 10.0
    max_error_rate_1h: float = 0.05
    min_confidence: float = 0.70
    min_recommendation_confidence: float = 0.80
    min_rag_faithfulness: float = 0.85
    max_broker_reject_rate_1h: float = 0.10
    min_edge_threshold: float = 0.0
    max_spread_pct: float = 2.0
    blocked_regimes: tuple[str, ...] = ("unknown", "high_vol_stress")


@dataclass(frozen=True, slots=True)
class GateCheckResult:
    id: str
    label: str
    status: GateOutcome
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class PreTradeGateResult:
    passed: bool
    checks: tuple[GateCheckResult, ...]
    failed_ids: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "failed_ids": list(self.failed_ids),
            "checks": [
                {
                    "id": c.id,
                    "label": c.label,
                    "status": c.status,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
        }


@dataclass
class PreTradeContext:
    """Inputs for §11.4 evaluation. ``None`` means the check is skipped (N/A)."""

    feeds_fresh: bool | None = None
    mark_age_sec: float | None = None
    is_option_mark: bool = False

    total_delta: float | None = None
    total_gamma: float | None = None
    total_vega: float | None = None
    total_theta: float | None = None
    total_rho: float | None = None

    drawdown_pct: float | None = None
    error_rate_1h: float | None = None
    buying_power_ok: bool | None = None
    confidence: float | None = None
    recommendation_confidence: float | None = None
    net_hedge_edge: float | None = None
    is_hedge: bool = False
    rag_faithfulness: float | None = None
    is_discretionary: bool = False
    regime: str | None = None
    broker_reject_rate_1h: float | None = None
    symbol: str | None = None
    allowed_symbols: frozenset[str] | None = None
    within_market_hours: bool | None = None
    duplicate_signal: bool | None = None
    one_trade_scope_clear: bool | None = None
    quantity: int | None = None
    lotsize: int | None = None
    limit_price: float | None = None
    tick_size: float | None = None
    spread_pct: float | None = None
    position_limit_ok: bool | None = None


def _check(
    gate_id: str,
    label: str,
    *,
    status: GateOutcome,
    detail: str | None = None,
) -> GateCheckResult:
    return GateCheckResult(id=gate_id, label=label, status=status, detail=detail)


def price_on_tick_grid(price: float, tick_size: float, *, tol: float = 1e-9) -> bool:
    """True when ``price`` is an integer multiple of ``tick_size`` (Q-06)."""
    if tick_size <= 0 or not isfinite(price) or not isfinite(tick_size):
        return False
    ratio = price / tick_size
    return abs(ratio - round(ratio)) <= tol


def quantity_multiple_of_lotsize(quantity: int, lotsize: int) -> bool:
    """True when share qty is an integer multiple of NFO lotsize (Q-05)."""
    lot = max(int(lotsize), 1)
    return int(quantity) % lot == 0 and int(quantity) != 0


def evaluate_pre_trade_gate(
    ctx: PreTradeContext,
    *,
    thresholds: PreTradeThresholds | None = None,
) -> PreTradeGateResult:
    """Evaluate §11.4 checklist; hard fails block the order."""
    thr = thresholds or PreTradeThresholds()
    checks: list[GateCheckResult] = []

    # Feeds fresh
    if ctx.feeds_fresh is not None:
        checks.append(
            _check(
                "feeds_fresh",
                "Bound data feeds fresh",
                status="pass" if ctx.feeds_fresh else "fail",
                detail=None if ctx.feeds_fresh else "stale_or_missing_marks",
            )
        )
    elif ctx.mark_age_sec is not None:
        limit = (
            thr.option_stale_threshold_sec
            if ctx.is_option_mark
            else thr.quote_stale_threshold_sec
        )
        fresh = float(ctx.mark_age_sec) <= float(limit)
        checks.append(
            _check(
                "feeds_fresh",
                "Bound data feeds fresh",
                status="pass" if fresh else "fail",
                detail=f"age_sec={ctx.mark_age_sec:.1f} limit={limit}",
            )
        )
    else:
        checks.append(
            _check("feeds_fresh", "Bound data feeds fresh", status="skip", detail="not_provided")
        )

    # Position limit
    if ctx.position_limit_ok is not None:
        checks.append(
            _check(
                "position_limit",
                "Position limit not exceeded",
                status="pass" if ctx.position_limit_ok else "fail",
            )
        )
    else:
        checks.append(
            _check("position_limit", "Position limit not exceeded", status="skip")
        )

    # Greeks limits
    if (
        ctx.total_delta is not None
        and ctx.total_gamma is not None
        and ctx.total_vega is not None
        and ctx.total_theta is not None
    ):
        greeks = check_greeks_limits(
            total_delta=ctx.total_delta,
            total_gamma=ctx.total_gamma,
            total_vega=ctx.total_vega,
            total_theta=ctx.total_theta,
            total_rho=ctx.total_rho,
            thresholds=GreeksLimitThresholds(
                max_abs_total_delta=thr.max_abs_total_delta,
                max_abs_total_gamma=thr.max_abs_total_gamma,
                max_abs_total_vega=thr.max_abs_total_vega,
                max_abs_total_rho=thr.max_abs_total_rho,
                min_total_theta=thr.min_total_theta,
            ),
        )
        checks.append(
            _check(
                "greeks_limits",
                "Greeks within limits",
                status="pass" if greeks.passed else "fail",
                detail=None if greeks.passed else ",".join(greeks.failures),
            )
        )
    else:
        checks.append(_check("greeks_limits", "Greeks within limits", status="skip"))

    # Drawdown
    if ctx.drawdown_pct is not None:
        ok = float(ctx.drawdown_pct) <= float(thr.max_drawdown_pct)
        checks.append(
            _check(
                "drawdown",
                "Drawdown below circuit breaker",
                status="pass" if ok else "fail",
                detail=f"drawdown_pct={ctx.drawdown_pct}",
            )
        )
    else:
        checks.append(_check("drawdown", "Drawdown below circuit breaker", status="skip"))

    # Bot health / error rate
    if ctx.error_rate_1h is not None:
        ok = float(ctx.error_rate_1h) < float(thr.max_error_rate_1h)
        checks.append(
            _check(
                "bot_health",
                "Bot health metrics within bounds",
                status="pass" if ok else "fail",
                detail=f"error_rate_1h={ctx.error_rate_1h}",
            )
        )
    else:
        checks.append(_check("bot_health", "Bot health metrics within bounds", status="skip"))

    # Buying power
    if ctx.buying_power_ok is not None:
        checks.append(
            _check(
                "buying_power",
                "Sufficient buying power",
                status="pass" if ctx.buying_power_ok else "fail",
            )
        )
    else:
        checks.append(_check("buying_power", "Sufficient buying power", status="skip"))

    # Confidence (discretionary risk gate)
    if ctx.confidence is not None and ctx.is_discretionary:
        ok = float(ctx.confidence) >= float(thr.min_confidence)
        checks.append(
            _check(
                "confidence",
                f"Confidence ≥ {thr.min_confidence:.2f}",
                status="pass" if ok else "fail",
                detail=f"confidence={ctx.confidence}",
            )
        )
    else:
        checks.append(_check("confidence", "Confidence ≥ threshold", status="skip"))

    # Recommendation surface floor
    if ctx.recommendation_confidence is not None:
        ok = float(ctx.recommendation_confidence) >= float(
            thr.min_recommendation_confidence
        )
        checks.append(
            _check(
                "recommendation_floor",
                f"Recommendation confidence ≥ {thr.min_recommendation_confidence:.2f}",
                status="pass" if ok else "fail",
                detail=f"confidence={ctx.recommendation_confidence}",
            )
        )
    else:
        checks.append(
            _check("recommendation_floor", "Recommendation confidence floor", status="skip")
        )

    # Transaction cost / net hedge edge
    if ctx.net_hedge_edge is not None and ctx.is_hedge:
        ok = cost_gate_passes(
            net_hedge_edge=ctx.net_hedge_edge,
            min_edge_threshold=thr.min_edge_threshold,
        )
        checks.append(
            _check(
                "transaction_cost",
                "Transaction cost gate (net_hedge_edge)",
                status="pass" if ok else "fail",
                detail=f"net_hedge_edge={ctx.net_hedge_edge}",
            )
        )
    elif ctx.net_hedge_edge is not None and not ctx.is_hedge:
        ok = float(ctx.net_hedge_edge) > float(thr.min_edge_threshold)
        checks.append(
            _check(
                "transaction_cost",
                "Net edge after costs > 0",
                status="pass" if ok else "fail",
                detail=f"net_edge={ctx.net_hedge_edge}",
            )
        )
    else:
        checks.append(_check("transaction_cost", "Transaction cost gate", status="skip"))

    # RAG faithfulness (discretionary)
    if ctx.rag_faithfulness is not None and ctx.is_discretionary:
        ok = float(ctx.rag_faithfulness) >= float(thr.min_rag_faithfulness)
        checks.append(
            _check(
                "rag_faithfulness",
                f"RAG faithfulness ≥ {thr.min_rag_faithfulness:.2f}",
                status="pass" if ok else "fail",
                detail=f"faithfulness={ctx.rag_faithfulness}",
            )
        )
    else:
        checks.append(_check("rag_faithfulness", "RAG faithfulness", status="skip"))

    # Regime
    if ctx.regime is not None and ctx.is_discretionary:
        blocked = ctx.regime.lower() in {r.lower() for r in thr.blocked_regimes}
        checks.append(
            _check(
                "regime",
                "Regime classifier known / not stressed",
                status="fail" if blocked else "pass",
                detail=ctx.regime,
            )
        )
    else:
        checks.append(_check("regime", "Regime classifier", status="skip"))

    # Broker reject rate
    if ctx.broker_reject_rate_1h is not None:
        ok = float(ctx.broker_reject_rate_1h) < float(thr.max_broker_reject_rate_1h)
        checks.append(
            _check(
                "broker_reject_rate",
                "Broker reject rate < 10%/1h",
                status="pass" if ok else "fail",
                detail=f"rate={ctx.broker_reject_rate_1h}",
            )
        )
    else:
        checks.append(_check("broker_reject_rate", "Broker reject rate", status="skip"))

    # Symbol whitelist
    if ctx.allowed_symbols is not None:
        sym = (ctx.symbol or "").upper()
        ok = bool(sym) and sym in {s.upper() for s in ctx.allowed_symbols}
        checks.append(
            _check(
                "symbol_whitelist",
                "Symbol ∈ allowed_symbols",
                status="pass" if ok else "fail",
                detail=sym or "missing_symbol",
            )
        )
    else:
        checks.append(_check("symbol_whitelist", "Symbol whitelist", status="skip"))

    # Market hours
    if ctx.within_market_hours is not None:
        checks.append(
            _check(
                "market_hours",
                "Within market session",
                status="pass" if ctx.within_market_hours else "fail",
            )
        )
    else:
        checks.append(_check("market_hours", "Within market session", status="skip"))

    # Duplicate / idempotency
    if ctx.duplicate_signal is not None:
        checks.append(
            _check(
                "idempotency",
                "No duplicate signal",
                status="fail" if ctx.duplicate_signal else "pass",
            )
        )
    else:
        checks.append(_check("idempotency", "No duplicate signal", status="skip"))

    # One-trade scope
    if ctx.one_trade_scope_clear is not None and ctx.is_discretionary:
        checks.append(
            _check(
                "one_trade_scope",
                "One trade at a time",
                status="pass" if ctx.one_trade_scope_clear else "fail",
            )
        )
    else:
        checks.append(_check("one_trade_scope", "One trade at a time", status="skip"))

    # Lot size
    if ctx.quantity is not None and ctx.lotsize is not None:
        ok = quantity_multiple_of_lotsize(ctx.quantity, ctx.lotsize)
        checks.append(
            _check(
                "lotsize",
                "Quantity multiple of lotsize",
                status="pass" if ok else "fail",
                detail=f"qty={ctx.quantity} lot={ctx.lotsize}",
            )
        )
    else:
        checks.append(_check("lotsize", "Quantity multiple of lotsize", status="skip"))

    # Tick grid
    if ctx.limit_price is not None and ctx.tick_size is not None:
        ok = price_on_tick_grid(ctx.limit_price, ctx.tick_size)
        checks.append(
            _check(
                "tick_size",
                "Limit price on tick grid",
                status="pass" if ok else "fail",
                detail=f"price={ctx.limit_price} tick={ctx.tick_size}",
            )
        )
    else:
        checks.append(_check("tick_size", "Limit price on tick grid", status="skip"))

    # Spread / liquidity
    if ctx.spread_pct is not None:
        ok = float(ctx.spread_pct) <= float(thr.max_spread_pct)
        checks.append(
            _check(
                "liquidity_spread",
                f"Bid-ask spread ≤ {thr.max_spread_pct}%",
                status="pass" if ok else "fail",
                detail=f"spread_pct={ctx.spread_pct}",
            )
        )
    else:
        checks.append(_check("liquidity_spread", "Bid-ask spread", status="skip"))

    failed = tuple(c.id for c in checks if c.status == "fail")
    return PreTradeGateResult(
        passed=len(failed) == 0,
        checks=tuple(checks),
        failed_ids=failed,
    )


DEFAULT_THRESHOLDS = PreTradeThresholds()
