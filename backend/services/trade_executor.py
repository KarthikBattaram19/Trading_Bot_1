"""
Autonomous trade execution from ranked recommendations.

When the bot is active, tries rank #1, then #2, then #3
until a paper broker submit succeeds or all candidates are exhausted.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from backend.models.recommendations import InstrumentRecommendation, StrategyType
from backend.models.trades import AutonomousExecutionResult, TradeAttemptResult
from backend.services.learning_service import get_learning_service

# In-memory session state (replaced by PostgreSQL in full implementation)
_one_trade_locked = False
_active_trade_id: str | None = None


def is_one_trade_locked() -> bool:
    return _one_trade_locked


def get_active_trade_id() -> str | None:
    return _active_trade_id


def unlock_trade() -> None:
    """Release one-trade lock after close / learning outcome."""
    global _one_trade_locked, _active_trade_id
    _one_trade_locked = False
    _active_trade_id = None


def _all_gates_pass(rec: InstrumentRecommendation) -> bool:
    return all(g.passed for g in rec.parameter_gates)


def _pre_submit_checks(rec: InstrumentRecommendation) -> str | None:
    """Return error message if candidate cannot be submitted, else None."""
    if rec.strategy.selected_strategy == StrategyType.blocked:
        return "Strategy blocked by cross-strategy matrix"
    if not _all_gates_pass(rec):
        failed = [g.label for g in rec.parameter_gates if not g.passed]
        return f"Parameter gates failed: {', '.join(failed)}"
    if is_one_trade_locked():
        return "One-trade scope locked — another discretionary entry is open"
    return None


async def _simulate_broker_submit(
    rec: InstrumentRecommendation,
) -> tuple[bool, str | None, str | None]:
    """
    Submit via broker router (ICICI Direct shadow dry-run by default).
    Rank #1 may fail when SIMULATE_FIRST_RANK_FAILURE=true (demo fallback path).
    """
    simulate_first_fail = os.getenv("SIMULATE_FIRST_RANK_FAILURE", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    if simulate_first_fail and rec.rank == 1:
        return (
            False,
            None,
            "Broker reject: vega scalp structure — insufficient liquidity at session open",
        )

    if rec.parameters.spread_pct > 2.0:
        return False, None, f"Broker reject: spread {rec.parameters.spread_pct}% exceeds 2% cap"

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    trade_id = f"trd_{rec.underlying_symbol.lower()}_{ts}"

    # Log a shadow ICICI Direct payload when the integration is wired (never live-submit here).
    use_icici = os.getenv("USE_ICICI_DIRECT_SHADOW", "true").lower() in ("1", "true", "yes")
    if use_icici:
        try:
            from backend.execution.broker_router import get_broker_router
            from backend.integrations.base import InternalOrder, OrderLeg

            order = InternalOrder(
                internal_order_id=trade_id,
                strategy_id=rec.strategy.selected_strategy.value
                if hasattr(rec.strategy.selected_strategy, "value")
                else str(rec.strategy.selected_strategy),
                signal_id=f"rec_rank_{rec.rank}",
                underlying_symbol=rec.underlying_symbol,
                legs=[
                    OrderLeg(
                        leg_id=1,
                        symbol=rec.underlying_symbol,
                        side="buy",
                        quantity=1,
                        order_type="limit",
                        limit_price=float(rec.parameters.und_price or 0) or None,
                        exchange="NSE",
                        product="INTRADAY",
                    )
                ],
            )
            await get_broker_router().submit(order)
        except Exception:
            # Shadow mapping failures must not block autonomous paper path.
            pass

    return True, trade_id, None


def _lock_trade(trade_id: str) -> None:
    global _one_trade_locked, _active_trade_id
    _one_trade_locked = True
    _active_trade_id = trade_id


async def execute_autonomous_from_recommendations(
    recommendations: list[InstrumentRecommendation],
) -> AutonomousExecutionResult:
    """
    Try opening a trade on each ranked recommendation in order until one succeeds.
    """
    global _one_trade_locked, _active_trade_id

    if not recommendations:
        return AutonomousExecutionResult(
            executed=False,
            attempts=[],
            message="No recommendations available to execute",
        )

    sorted_recs = sorted(recommendations, key=lambda r: r.rank)
    attempts: list[TradeAttemptResult] = []

    for rec in sorted_recs:
        pre_error = _pre_submit_checks(rec)
        if pre_error:
            attempts.append(
                TradeAttemptResult(
                    rank=rec.rank,
                    underlying_symbol=rec.underlying_symbol,
                    success=False,
                    error=pre_error,
                )
            )
            continue

        success, trade_id, broker_error = await _simulate_broker_submit(rec)
        if success and trade_id:
            _lock_trade(trade_id)
            # Register open trade so continual learning can record the outcome
            get_learning_service().register_open_trade(trade_id, rec)
            attempts.append(
                TradeAttemptResult(
                    rank=rec.rank,
                    underlying_symbol=rec.underlying_symbol,
                    success=True,
                    trade_id=trade_id,
                    order_status="filled",
                )
            )
            failed_ranks = [a.rank for a in attempts if not a.success]
            if failed_ranks:
                msg = (
                    f"Opened trade on rank #{rec.rank} ({rec.underlying_symbol}) "
                    f"after rank(s) {failed_ranks} failed"
                )
            else:
                msg = f"Opened trade on rank #{rec.rank} ({rec.underlying_symbol})"
            return AutonomousExecutionResult(
                executed=True,
                selected_rank=rec.rank,
                trade_id=trade_id,
                underlying_symbol=rec.underlying_symbol,
                attempts=attempts,
                message=msg,
            )

        attempts.append(
            TradeAttemptResult(
                rank=rec.rank,
                underlying_symbol=rec.underlying_symbol,
                success=False,
                error=broker_error or "Broker submit failed",
            )
        )

    return AutonomousExecutionResult(
        executed=False,
        attempts=attempts,
        message="All ranked recommendations failed to open — no trade opened",
    )
