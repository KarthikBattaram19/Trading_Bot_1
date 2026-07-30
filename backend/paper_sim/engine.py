"""Paper trading engine — isolated from ICICI Direct live execution."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from backend.paper_sim.chain import build_option_chain
from backend.paper_sim.config import DEFAULT_CONFIG, PaperSimConfig
from backend.paper_sim.ledger import PaperLedger, PaperLedgerError
from backend.paper_sim.market_feed import IciciDirectDataOnlyFeed, MarketQuoteFeed
from backend.paper_sim.models import (
    PaperAccountSnapshot,
    PaperFill,
    PaperOrderRequest,
    PaperPosition,
    PaperSide,
)

logger = logging.getLogger(__name__)


class PaperEngine:
    """
    In-house options paper simulator.

    - Marks: ICICI Direct data-only feed (or any MarketQuoteFeed)
    - Fills / ledger: local only
    - Never calls ICICI Direct place_order / cancel_order
    """

    def __init__(
        self,
        config: PaperSimConfig | None = None,
        feed: MarketQuoteFeed | None = None,
    ) -> None:
        self.config = config or DEFAULT_CONFIG.model_copy(deep=True)
        self.feed: MarketQuoteFeed = feed or IciciDirectDataOnlyFeed()
        self.ledger = PaperLedger(self.config)

    def reset(self, starting_capital: float | None = None) -> PaperAccountSnapshot:
        if starting_capital is not None:
            self.config.total_capital_inr = float(starting_capital)
        self.ledger = PaperLedger(self.config)
        if starting_capital is not None:
            self.ledger.reset(starting_capital)
        return self.ledger.snapshot()

    def account(self) -> PaperAccountSnapshot:
        return self.ledger.snapshot()

    def positions(self, *, status: str | None = "open") -> list[PaperPosition]:
        return self.ledger.list_positions(status=status)

    def fills(self, *, limit: int = 100) -> list[PaperFill]:
        return list(reversed(self.ledger.fills[-limit:]))

    async def submit_order(self, request: PaperOrderRequest) -> dict[str, Any]:
        await self.feed.ensure_instruments()
        resolved_legs: list[dict] = []

        # T11: index / spot-cap rules apply only when options are traded with the underlying.
        includes_underlying = any(
            (leg.exchange or "").upper() in {"NSE", "BSE"} and leg.option_type is None
            for leg in request.legs
        )
        if includes_underlying and request.underlying:
            und = request.underlying.upper()
            if und in {
                "NIFTY",
                "BANKNIFTY",
                "FINNIFTY",
                "MIDCPNIFTY",
                "NIFTYNXT50",
            }:
                raise PaperLedgerError(
                    f"underlying {request.underlying} is an index — "
                    "cannot trade options with cash underlying under Part T "
                    f"(spot cap {self.config.underlying_price_cap_inr:.0f} INR applies)"
                )

        for leg in request.legs:
            record = None
            if leg.symbol_token:
                record = self.feed.resolve(symboltoken=leg.symbol_token)
            if record is None:
                record = self.feed.resolve(exchange=leg.exchange, tradingsymbol=leg.symbol)
            if record is None:
                raise PaperLedgerError(
                    f"cannot resolve paper instrument {leg.exchange}:{leg.symbol}"
                )

            tick = await self.feed.get_ltp(
                record.exchange, record.tradingsymbol, record.symboltoken
            )
            if tick.ltp <= 0:
                raise PaperLedgerError(f"invalid LTP for {record.tradingsymbol}")

            qty = int(leg.quantity)
            if qty % max(record.lotsize, 1) != 0:
                raise PaperLedgerError(
                    f"quantity {qty} must be a multiple of lotsize {record.lotsize}"
                )

            resolved_legs.append(
                {
                    "symbol": record.tradingsymbol,
                    "exchange": record.exchange,
                    "symbol_token": record.symboltoken,
                    "side": PaperSide(leg.side),
                    "quantity": qty,
                    "mark_ltp": float(tick.ltp),
                    "lotsize": record.lotsize,
                }
            )

        order_id = f"paper_{uuid4().hex[:12]}"
        position, fills = self.ledger.open_position(
            strategy_tag=request.strategy_tag,
            underlying=request.underlying,
            note=request.note,
            legs=resolved_legs,
            slippage_bps=self.config.slippage_bps,
            order_id=order_id,
        )
        logger.info(
            "paper_sim fill order_id=%s position_id=%s legs=%s (no broker place_order)",
            order_id,
            position.position_id,
            len(fills),
        )
        return {
            "success": True,
            "path": "paper_sim",
            "broker_place_order": False,
            "order_id": order_id,
            "position": position.model_dump(mode="json"),
            "fills": [f.model_dump(mode="json") for f in fills],
            "account": self.ledger.snapshot().model_dump(mode="json"),
        }

    async def close_position(self, position_id: str) -> dict[str, Any]:
        position = self.ledger.positions.get(position_id)
        if position is None:
            raise PaperLedgerError(f"unknown position_id={position_id}")
        if position.status != "open":
            raise PaperLedgerError(f"position {position_id} is already closed")

        marks: dict[str, float] = {}
        for leg in position.legs:
            tick = await self.feed.get_ltp(leg.exchange, leg.symbol, leg.symbol_token)
            marks[leg.symbol_token] = float(tick.ltp)

        closed, fills, pnl = self.ledger.close_position(
            position_id, marks, self.config.slippage_bps
        )
        return {
            "success": True,
            "path": "paper_sim",
            "broker_place_order": False,
            "realized_pnl": pnl,
            "position": closed.model_dump(mode="json"),
            "fills": [f.model_dump(mode="json") for f in fills],
            "account": self.ledger.snapshot().model_dump(mode="json"),
        }

    async def refresh_marks(self) -> dict[str, Any]:
        open_positions = self.ledger.list_positions(status="open")
        marks: dict[str, float] = {}
        for position in open_positions:
            for leg in position.legs:
                if leg.symbol_token in marks:
                    continue
                tick = await self.feed.get_ltp(leg.exchange, leg.symbol, leg.symbol_token)
                marks[leg.symbol_token] = float(tick.ltp)
        self.ledger.apply_marks(marks)
        return {
            "success": True,
            "marks_updated": len(marks),
            "account": self.ledger.snapshot().model_dump(mode="json"),
            "positions": [p.model_dump(mode="json") for p in self.positions()],
        }

    async def option_chain(
        self,
        *,
        underlying: str,
        expiry: str | None = None,
        include_ltp: bool = False,
        max_contracts: int = 80,
    ) -> dict[str, Any]:
        snap = await build_option_chain(
            self.feed,
            underlying=underlying,
            expiry=expiry,
            include_ltp=include_ltp,
            max_contracts=max_contracts,
        )
        return snap.model_dump(mode="json")

    def health(self) -> dict[str, Any]:
        """Phase 0 stub fields + ledger snapshot (playbook expands in Phase 1)."""
        feed_health = getattr(self.feed, "health", lambda: {"feed": "custom"})()
        return {
            "module": "paper_sim",
            "phase": "0",
            "status": "stub",
            "separate_from_icici_live": True,
            "broker_place_order": False,
            "execution_mode_hint": "shadow",
            "account": self.ledger.snapshot().model_dump(mode="json"),
            "feed": feed_health,
            "config": {
                "total_capital_inr": self.config.total_capital_inr,
                "max_trade_investment_inr": self.config.max_trade_investment_inr,
                "max_leg_investment_inr": self.config.max_leg_investment_inr,
                "slippage_bps": self.config.slippage_bps,
                "mark_provider": self.config.mark_provider,
            },
        }
