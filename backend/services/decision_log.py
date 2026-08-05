"""Read-only decision log.

Phase 0 has no decision store: the bot generates recommendations and acts on them
in one cycle. This module projects an audit view from the two sources that do hold
state — the live recommendation engine and the continual-learning store:

    live recommendation      -> pending   (surfaced, not yet acted on)
    learning open_trade      -> approved  (bot opened a position on it)
    learning outcome         -> approved  (opened and since closed)

Nothing here places, approves, or rejects orders. Option legs and per-leg Greeks
are left empty because Phase 0 does not build option structures yet.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from backend.models.decisions import (
    DecisionRecord,
    DecisionStatus,
    GateStatus,
    RagCitation,
    RiskGate,
    StrategyContext,
    StrategyModule,
    TradeEconomics,
    TradePlan,
)
from backend.models.recommendations import InstrumentRecommendation, StrategyType
from backend.services.decision_state import get_decision_state_store
from backend.services.learning_service import get_learning_service
from backend.services.recommendation_engine import (
    generate_recommendations,
    peek_cached_recommendations,
)

logger = logging.getLogger(__name__)

# How long a surfaced recommendation stays actionable before it reads as expired.
DECISION_TTL_MINUTES = 15
# Bound live decision projection so /decisions never hangs on a cold enrich cycle.
_LIVE_DECISIONS_TIMEOUT_SEC = 12.0

_MODULE_BY_STRATEGY = {
    StrategyType.simple_volatility.value: StrategyModule.volatility,
    StrategyType.gamma_scalping.value: StrategyModule.gamma_scalping,
    StrategyType.vega_scalping.value: StrategyModule.vega_scalping,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _module_for(strategy: str) -> StrategyModule:
    return _MODULE_BY_STRATEGY.get(strategy, StrategyModule.volatility)


def _regime_for(rec: InstrumentRecommendation) -> str:
    """Label the vol regime from the engine's own IV vs GARCH comparison."""
    iv = rec.parameters.iv_annualized
    garch = rec.parameters.garch_forecast
    if rec.parameters.garch_distorted:
        return "distorted_vol"
    if iv < garch:
        return "cheap_vol"
    if iv > garch * 1.05:
        return "rich_vol"
    return "mixed_vol"


def _citations_for(rec: InstrumentRecommendation) -> list[RagCitation]:
    """Cite the parameter/strategy docs the engine actually referenced."""
    citations: list[RagCitation] = []
    seen: set[tuple[str, str | None]] = set()

    for gate in rec.parameter_gates:
        if not gate.parameter_ref:
            continue
        document, _, chapter = gate.parameter_ref.partition(" ")
        key = (document, chapter or None)
        if key in seen:
            continue
        seen.add(key)
        citations.append(RagCitation(document=document, chapter=chapter or None))

    matrix_ref = rec.strategy.cross_strategy_matrix_ref
    if matrix_ref:
        key = ("Trading_Strategies.md", matrix_ref)
        if key not in seen:
            seen.add(key)
            citations.append(
                RagCitation(document="Trading_Strategies.md", chapter=matrix_ref)
            )

    return citations


def _plan_for(rec: InstrumentRecommendation) -> TradePlan:
    """Split the engine's single exit-plan sentence set into stop / target / time."""
    sentences = [s.strip() for s in rec.exit_plan.split(".") if s.strip()]
    stop = next((s for s in sentences if "stop" in s.lower()), None)
    target = next((s for s in sentences if "target" in s.lower()), None)
    time_exit = next(
        (
            s
            for s in sentences
            if any(k in s.lower() for k in ("flatten", "session", "close", "d+", "hold"))
        ),
        None,
    )
    return TradePlan(
        stop=stop or "Per strategy stop rules",
        target=target or rec.exit_plan,
        time_exit=time_exit or "Per strategy time exit",
    )


def _economics_for(rec: InstrumentRecommendation) -> TradeEconomics:
    """Proxy the net edge from the engine's IV−GARCH edge less estimated slippage.

    Phase 0 has no per-leg pricing model, so this is a premium-scaled approximation
    of the same edge the ranking uses — not a filled-order P&L estimate.
    """
    econ = rec.economics
    edge_fraction = rec.parameters.garch_forecast - rec.parameters.iv_annualized
    gross_edge = econ.atm_premium_inr * edge_fraction
    transaction_cost = econ.atm_premium_inr * (econ.estimated_slippage_pct / 100.0)

    return TradeEconomics(
        net_edge_after_costs=round(gross_edge - transaction_cost, 2),
        margin_estimate=econ.margin_estimate_inr,
        total_transaction_cost=round(transaction_cost, 2),
        slippage_cap_bps=round(econ.estimated_slippage_pct * 100, 2),
    )


def _context_for(rec: InstrumentRecommendation) -> StrategyContext:
    strategy = rec.strategy
    is_vega = strategy.selected_strategy == StrategyType.vega_scalping
    return StrategyContext(
        iv_annualized=rec.parameters.iv_annualized,
        garch_forecast=rec.parameters.garch_forecast,
        entry_mode=strategy.entry_mode,
        intraday_iv_z_score=rec.parameters.iv_z_score,
        must_flatten_same_day=True if is_vega else None,
    )


def _gates_for(rec: InstrumentRecommendation) -> list[RiskGate]:
    return [
        RiskGate(
            id=gate.gate_id,
            label=gate.label,
            status=GateStatus.pass_ if gate.passed else GateStatus.fail,
            detail=gate.detail,
        )
        for gate in rec.parameter_gates
    ]


def _to_decision(
    rec: InstrumentRecommendation,
    *,
    decision_id: str,
    status: DecisionStatus,
    created_at: datetime,
) -> DecisionRecord:
    return DecisionRecord(
        decision_id=decision_id,
        signal_id=f"rec_rank_{rec.rank}",
        status=status,
        module=_module_for(rec.strategy.selected_strategy.value),
        underlying_symbol=rec.underlying_symbol,
        confidence=rec.confidence,
        regime=_regime_for(rec),
        explanation=rec.market_summary,
        rationale=rec.entry_rationale,
        rag_citations=_citations_for(rec),
        economics=_economics_for(rec),
        plan=_plan_for(rec),
        event_risks=rec.event_risks,
        failure_modes=rec.failure_modes,
        strategy_context=_context_for(rec),
        risk_gates=_gates_for(rec),
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=DECISION_TTL_MINUTES),
        scenario_tag=rec.strategy.scenario_tag,
        alternative_strategies=rec.strategy.rejected_strategies or None,
    )


def _from_snapshot(snapshot: dict) -> InstrumentRecommendation | None:
    try:
        return InstrumentRecommendation.model_validate(snapshot)
    except Exception:
        # A snapshot written by an older schema must not break the audit view.
        return None


def _acted_on_decisions() -> list[DecisionRecord]:
    """Decisions the bot already acted on, from the learning store."""
    learning = get_learning_service()
    decisions: list[DecisionRecord] = []

    for trade in learning.list_open_trades():
        rec = _from_snapshot(trade.recommendation_snapshot)
        if rec is None:
            continue
        decisions.append(
            _to_decision(
                rec,
                decision_id=f"dec_{trade.trade_id}",
                status=DecisionStatus.approved,
                created_at=trade.opened_at,
            )
        )

    for outcome in learning.dashboard().recent_outcomes:
        rec = _from_snapshot(outcome.recommendation_snapshot)
        if rec is None:
            continue
        decisions.append(
            _to_decision(
                rec,
                decision_id=f"dec_{outcome.trade_id}",
                status=DecisionStatus.approved,
                created_at=outcome.opened_at,
            )
        )

    return decisions


async def _live_decisions() -> list[DecisionRecord]:
    """Currently surfaced recommendations, pending until the bot acts or they age out.

    Prefer the in-process recommendation cache so listing decisions does not
    trigger a multi-minute FNO enrich. On a cold cache, wait briefly for a
    generation; on timeout, return no live rows (acted-on history still shows).
    """
    result = peek_cached_recommendations()
    if result is None:
        try:
            result = await asyncio.wait_for(
                generate_recommendations(),
                timeout=_LIVE_DECISIONS_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "list_decisions: live recommendation cycle exceeded %.1fs — "
                "returning acted-on history only",
                _LIVE_DECISIONS_TIMEOUT_SEC,
            )
            return []

    created_at = result.generated_at
    day = created_at.strftime("%Y%m%d")
    expired = _now() - created_at > timedelta(minutes=DECISION_TTL_MINUTES)
    status = DecisionStatus.expired if expired else DecisionStatus.pending

    return [
        _to_decision(
            rec,
            decision_id=f"dec_{rec.underlying_symbol.lower()}_{day}",
            status=status,
            created_at=created_at,
        )
        for rec in result.recommendations
    ]


def _apply_decision_state_overlay(decisions: list[DecisionRecord]) -> list[DecisionRecord]:
    """An operator's approve/reject verdict always wins over the derived status."""
    store = get_decision_state_store()
    overlaid: list[DecisionRecord] = []
    for decision in decisions:
        state = store.get(decision.decision_id)
        if state is None:
            overlaid.append(decision)
            continue
        status = DecisionStatus.approved if state.status == "approved" else DecisionStatus.rejected
        overlaid.append(decision.model_copy(update={"status": status}))
    return overlaid


async def list_decisions() -> list[DecisionRecord]:
    """Full audit trail, newest first, with acted-on records taking precedence."""
    decisions = _acted_on_decisions()
    seen_symbols = {d.underlying_symbol for d in decisions}
    seen_ids = {d.decision_id for d in decisions}
    state_store = get_decision_state_store()

    for decision in await _live_decisions():
        if decision.decision_id in seen_ids:
            continue
        has_explicit_verdict = state_store.get(decision.decision_id) is not None
        if decision.underlying_symbol in seen_symbols and not has_explicit_verdict:
            continue
        decisions.append(decision)

    decisions = _apply_decision_state_overlay(decisions)
    decisions.sort(key=lambda d: d.created_at, reverse=True)
    return decisions


async def list_pending_decisions() -> list[DecisionRecord]:
    return [d for d in await list_decisions() if d.status == DecisionStatus.pending]


async def get_decision(decision_id: str) -> DecisionRecord | None:
    return next((d for d in await list_decisions() if d.decision_id == decision_id), None)
