"""
Autonomous trade execution from ranked recommendations.

When the bot is active, tries rank #1, then #2, then #3
until a paper broker submit succeeds or all candidates are exhausted.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from backend.analytics.confidence_calibration import is_seed_outcome
from backend.models.recommendations import InstrumentRecommendation, StrategyType
from backend.models.trades import AutonomousExecutionResult, TradeAttemptResult
from backend.paper_sim.engine import PaperEngine
from backend.paper_sim.models import PaperLegRequest, PaperSide
from backend.services.learning_service import get_learning_service
from backend.services.universe_enrichment import select_preferred_expiry


def get_active_trade_id() -> str | None:
    """
    Ledger-derived, not an in-memory global — the `paper_sim` open-trades store
    (`learning_store.json`) is written on open/close and survives a process
    restart, so the lock can't desync from reality the way a plain module
    global would (Docs/bot_health/BACKLOG.md P0). Seeded demo records are
    excluded so the bundled fixture trade never blocks real entries.
    """
    for trade in get_learning_service().list_open_trades():
        if not is_seed_outcome({"trade_id": trade.trade_id}):
            return trade.trade_id
    return None


def is_one_trade_locked() -> bool:
    return get_active_trade_id() is not None


def _all_gates_pass(rec: InstrumentRecommendation) -> bool:
    return all(g.passed for g in rec.parameter_gates)


async def resolve_atm_ce_leg(
    rec: InstrumentRecommendation, *, engine: PaperEngine
) -> PaperLegRequest | None:
    """
    Resolve a single ATM call-option entry leg for a recommendation's underlying.

    Fixed convention: always buy ATM CE, 1 lot, nearest expiry with DTE >= 10
    (matching the recommendation engine's own DTE gate). `structure_builder.py`
    expands this single leg into the full strategy structure — see
    Docs/superpowers/specs/2026-08-04-wire-trade-executor-paper-sim-design.md §1.
    """
    feed = engine.feed
    await feed.ensure_instruments(max_age_sec=engine.config.instrument_master_max_age_sec)

    symbol = rec.underlying_symbol.upper()
    preferred = select_preferred_expiry(feed, symbol, min_dte=10)
    if preferred is None:
        return None
    expiry, _dte = preferred

    records = feed.list_options(name=symbol, exchange="NFO", expiry=expiry, limit=500)
    ce_records = [r for r in records if (r.tradingsymbol or "").upper().endswith("CE")]
    if not ce_records:
        return None

    spot = float(rec.parameters.und_price)
    best = min(ce_records, key=lambda r: abs(float(r.strike or 0.0) - spot))

    return PaperLegRequest(
        symbol=best.tradingsymbol,
        side=PaperSide.buy,
        quantity=int(best.lotsize),
        exchange=best.exchange,
        symbol_token=best.symboltoken,
        option_type="CE",
        strike=float(best.strike) if best.strike is not None else None,
        expiry=best.expiry,
    )


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
    *,
    simulate_first_rank_failure: bool = False,
) -> tuple[bool, str | None, str | None]:
    """
    Submit via broker router (ICICI Direct shadow dry-run by default).

    `simulate_first_rank_failure` is a test-only injection point for exercising
    the rank-1-rejects/fallback-to-rank-2 path — it must never be enabled from
    a production call site. Defaults to False (no simulated rejection).
    """
    if simulate_first_rank_failure and rec.rank == 1:
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


async def execute_autonomous_from_recommendations(
    recommendations: list[InstrumentRecommendation],
    *,
    simulate_first_rank_failure: bool = False,
) -> AutonomousExecutionResult:
    """
    Try opening a trade on each ranked recommendation in order until one succeeds.

    `simulate_first_rank_failure` is a test-only injection point (see
    `_simulate_broker_submit`) — production callers must leave it at the default.
    """
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

        success, trade_id, broker_error = await _simulate_broker_submit(
            rec, simulate_first_rank_failure=simulate_first_rank_failure
        )
        if success and trade_id:
            # Persist to the open-trades ledger — this is also what locks
            # the one-trade scope (see get_active_trade_id above) and feeds
            # continual learning's outcome recording.
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
