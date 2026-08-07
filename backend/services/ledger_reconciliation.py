"""Boot-time reconciliation between learning_store open trades and the paper_sim ledger.

The paper_sim ledger (backend/paper_sim/ledger.py) is in-memory only, while
learning_store.json is disk-persisted. After a process restart the ledger is
empty but the learning store may still list a trade as open — which keeps
`trade_executor.is_one_trade_locked()` engaged forever with no closeable
position behind it. Called once from the FastAPI lifespan at startup, this
closes every such orphan at 0 PnL with an explicit exit reason so the
one-trade lock releases and the day's trading can proceed.

Full ledger persistence remains a backlog item (P0-2c); this removes the
deadlock, not the data loss.
"""

from __future__ import annotations

import logging

from backend.models.learning import CloseTradeRequest, TradeOutcomeLabel

logger = logging.getLogger(__name__)


def reconcile_open_trades(*, engine=None, learning=None) -> list[str]:
    """Close learning-store open trades with no live ledger position. Returns closed ids."""
    if engine is None:
        from backend.paper_sim.service import get_paper_engine

        engine = get_paper_engine()
    if learning is None:
        from backend.services.learning_service import get_learning_service

        learning = get_learning_service()

    reconciled: list[str] = []
    for trade in learning.list_open_trades():  # already excludes seed fixtures
        position = engine.ledger.positions.get(trade.trade_id)
        if position is not None and getattr(position, "status", None) == "open":
            continue
        logger.warning(
            "Reconciling orphaned open trade %s (no live paper_sim position) — "
            "closing at 0 PnL, reason=orphaned_by_restart",
            trade.trade_id,
        )
        learning.record_outcome(
            CloseTradeRequest(
                trade_id=trade.trade_id,
                outcome=TradeOutcomeLabel.scratch,
                realized_pnl_inr=0.0,
                exit_reason="orphaned_by_restart",
            )
        )
        reconciled.append(trade.trade_id)
    return reconciled
