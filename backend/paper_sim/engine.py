"""Paper trading engine — isolated from ICICI Direct live execution."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from backend.execution.risk_gate import (
    PreTradeContext,
    evaluate_pre_trade_gate,
    quantity_multiple_of_lotsize,
)
from backend.integrations.icici_direct.models import NormalizedTick
from backend.paper_sim.automation import PaperAutomation
from backend.paper_sim.chain import build_option_chain
from backend.paper_sim.config import DEFAULT_CONFIG, PaperSimConfig
from backend.paper_sim.freshness import (
    StaleMarksError,
    assert_marks_fresh,
    evaluate_marks,
    instrument_master_age_sec,
    threshold_for_leg,
)
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

_INDEX_UNDERLYINGS = frozenset(
    {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
)
_CASH_EXCHANGES = frozenset({"NSE", "BSE"})


def _is_cash_underlying_leg(leg: Any) -> bool:
    """True for stock/underlying legs (not NFO option contracts)."""
    exchange = (getattr(leg, "exchange", None) or "").upper()
    if exchange not in _CASH_EXCHANGES:
        return False
    if getattr(leg, "option_type", None) is not None:
        return False
    symbol = (getattr(leg, "symbol", None) or "").upper()
    return not (symbol.endswith("CE") or symbol.endswith("PE"))


def _is_option_leg(exchange: str, symbol: str, option_type: str | None = None) -> bool:
    if option_type is not None:
        return True
    if exchange.upper() == "NFO":
        return True
    upper = symbol.upper()
    return upper.endswith("CE") or upper.endswith("PE")


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
        self._last_marks_report: dict[str, Any] | None = None
        self.automation = PaperAutomation(self)

    def reset(self, starting_capital: float | None = None) -> PaperAccountSnapshot:
        open_positions = self.ledger.list_positions(status="open")
        if open_positions:
            raise PaperLedgerError(
                f"cannot reset while {len(open_positions)} open position(s) — close them first"
            )
        if starting_capital is not None:
            self.config.total_capital_inr = float(starting_capital)
        self.ledger = PaperLedger(self.config)
        if starting_capital is not None:
            self.ledger.reset(starting_capital)
        self._last_marks_report = None
        # Keep automation object bound to this engine; clear runtime counters via stop+status
        if self.automation._running:
            # Synchronous best-effort: mark stopped; caller should await stop via API
            self.automation._running = False
            self.automation._task = None
        return self.ledger.snapshot()

    def account(self) -> PaperAccountSnapshot:
        return self.ledger.snapshot()

    def positions(self, *, status: str | None = "open") -> list[PaperPosition]:
        return self.ledger.list_positions(status=status)

    def fills(self, *, limit: int = 100) -> list[PaperFill]:
        return list(reversed(self.ledger.fills[-limit:]))

    def _leg_threshold(self, *, exchange: str, symbol: str, is_option: bool) -> float:
        return threshold_for_leg(
            exchange=exchange,
            is_option=is_option,
            quote_stale_threshold_sec=self.config.quote_stale_threshold_sec,
            option_stale_threshold_sec=self.config.option_stale_threshold_sec,
        )

    def _gate_ticks(
        self, ticks: list[tuple[NormalizedTick, float]]
    ) -> dict[str, Any]:
        if not self.config.require_fresh_marks:
            report = evaluate_marks(ticks)
            payload = report.to_dict()
            self._last_marks_report = payload
            return payload
        report = assert_marks_fresh(ticks)
        payload = report.to_dict()
        self._last_marks_report = payload
        return payload

    async def _ensure_scrip_master(self) -> int:
        return await self.feed.ensure_instruments(
            max_age_sec=self.config.instrument_master_max_age_sec
        )

    async def submit_order(self, request: PaperOrderRequest) -> dict[str, Any]:
        await self._ensure_scrip_master()
        resolved_legs: list[dict] = []
        ticks_for_gate: list[tuple[NormalizedTick, float]] = []

        # T11: index / spot-cap rules apply only when options are traded with the underlying.
        includes_underlying = any(_is_cash_underlying_leg(leg) for leg in request.legs)
        if includes_underlying and request.underlying:
            und = request.underlying.upper()
            if und in _INDEX_UNDERLYINGS:
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
            is_option = _is_option_leg(
                record.exchange, record.tradingsymbol, leg.option_type
            )
            threshold = self._leg_threshold(
                exchange=record.exchange,
                symbol=record.tradingsymbol,
                is_option=is_option,
            )
            ticks_for_gate.append((tick, threshold))

            qty = int(leg.quantity)
            if not quantity_multiple_of_lotsize(qty, record.lotsize):
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
                    "is_cash_underlying": _is_cash_underlying_leg(leg),
                }
            )

        # MD-01 / PS-03: reject the whole basket if any leg mark is stale or invalid.
        freshness = self._gate_ticks(ticks_for_gate)

        # §11.4 pre-trade thresholds (kill-switch, freshness, lotsize already enforced)
        try:
            from backend.routers.bot import is_kill_switch_armed

            kill_armed = bool(is_kill_switch_armed())
        except Exception:  # noqa: BLE001
            kill_armed = False
        snap = self.ledger.snapshot()
        buying_ok = snap.cash_inr > 0
        drawdown_pct = 0.0
        if snap.starting_capital_inr > 0:
            equity = snap.equity_inr
            drawdown_pct = max(
                0.0,
                (snap.starting_capital_inr - equity) / snap.starting_capital_inr * 100.0,
            )
        gate = evaluate_pre_trade_gate(
            PreTradeContext(
                feeds_fresh=bool(freshness.get("ok", True)),
                kill_switch_armed=kill_armed,
                buying_power_ok=buying_ok,
                drawdown_pct=drawdown_pct,
                quantity=int(resolved_legs[0]["quantity"]) if resolved_legs else None,
                lotsize=int(resolved_legs[0]["lotsize"]) if resolved_legs else None,
            ),
            thresholds=self.config.pre_trade_thresholds(),
        )
        if not gate.passed:
            raise PaperLedgerError(
                f"pre_trade_gate failed: {','.join(gate.failed_ids)}"
            )

        if includes_underlying and self.config.underlying_price_cap_inr > 0:
            spot_marks = [
                float(leg["mark_ltp"])
                for leg in resolved_legs
                if leg.get("is_cash_underlying")
            ]
            if spot_marks:
                spot = max(spot_marks)
                if spot > self.config.underlying_price_cap_inr:
                    raise PaperLedgerError(
                        f"underlying spot {spot:.2f} exceeds Part T cap "
                        f"{self.config.underlying_price_cap_inr:.0f} INR "
                        "(options+underlying path)"
                    )

        # Part J: set hedge_point_price from underlying spot (or cash-leg mark) at entry
        hedge_point: float | None = None
        if includes_underlying:
            cash_marks = [
                float(leg["mark_ltp"])
                for leg in resolved_legs
                if leg.get("is_cash_underlying")
            ]
            if cash_marks:
                hedge_point = float(cash_marks[0])
        if hedge_point is None and request.underlying:
            und_rec = self.feed.resolve(
                exchange="NSE", tradingsymbol=request.underlying.upper()
            )
            if und_rec is None:
                und_rec = self.feed.resolve(tradingsymbol=request.underlying.upper())
            if und_rec is not None:
                und_tick = await self.feed.get_ltp(
                    und_rec.exchange, und_rec.tradingsymbol, und_rec.symboltoken
                )
                hedge_point = float(und_tick.ltp)

        order_id = f"paper_{uuid4().hex[:12]}"
        position, fills = self.ledger.open_position(
            strategy_tag=request.strategy_tag,
            underlying=request.underlying,
            note=request.note,
            legs=resolved_legs,
            slippage_bps=self.config.slippage_bps,
            order_id=order_id,
            hedge_point_price=hedge_point,
            rehedge_method=self.config.rehedge_method,
        )
        logger.info(
            "paper_sim fill order_id=%s position_id=%s legs=%s hedge_point=%s (no broker place_order)",
            order_id,
            position.position_id,
            len(fills),
            hedge_point,
        )
        return {
            "success": True,
            "path": "paper_sim",
            "broker_place_order": False,
            "order_id": order_id,
            "position": position.model_dump(mode="json"),
            "fills": [f.model_dump(mode="json") for f in fills],
            "account": self.ledger.snapshot().model_dump(mode="json"),
            "marks_freshness": freshness,
            "pre_trade_gate": gate.as_dict(),
        }

    async def close_position(self, position_id: str) -> dict[str, Any]:
        position = self.ledger.positions.get(position_id)
        if position is None:
            raise PaperLedgerError(f"unknown position_id={position_id}")
        if position.status != "open":
            raise PaperLedgerError(f"position {position_id} is already closed")

        await self._ensure_scrip_master()
        marks: dict[str, float] = {}
        ticks_for_gate: list[tuple[NormalizedTick, float]] = []
        for leg in position.legs:
            tick = await self.feed.get_ltp(leg.exchange, leg.symbol, leg.symbol_token)
            is_option = _is_option_leg(leg.exchange, leg.symbol)
            threshold = self._leg_threshold(
                exchange=leg.exchange, symbol=leg.symbol, is_option=is_option
            )
            ticks_for_gate.append((tick, threshold))
            marks[leg.symbol_token] = float(tick.ltp)

        freshness = self._gate_ticks(ticks_for_gate)
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
            "marks_freshness": freshness,
        }

    async def refresh_marks(self) -> dict[str, Any]:
        await self._ensure_scrip_master()
        open_positions = self.ledger.list_positions(status="open")
        marks: dict[str, float] = {}
        ticks_for_gate: list[tuple[NormalizedTick, float]] = []
        seen: set[str] = set()

        for position in open_positions:
            for leg in position.legs:
                if leg.symbol_token in seen:
                    continue
                seen.add(leg.symbol_token)
                tick = await self.feed.get_ltp(leg.exchange, leg.symbol, leg.symbol_token)
                is_option = _is_option_leg(leg.exchange, leg.symbol)
                threshold = self._leg_threshold(
                    exchange=leg.exchange, symbol=leg.symbol, is_option=is_option
                )
                ticks_for_gate.append((tick, threshold))
                marks[leg.symbol_token] = float(tick.ltp)

        freshness: dict[str, Any]
        if ticks_for_gate:
            freshness = self._gate_ticks(ticks_for_gate)
            self.ledger.apply_marks(marks)
        else:
            freshness = {
                "ok": True,
                "checked_at": None,
                "blocked_symbols": [],
                "details": [],
                "note": "no_open_positions",
            }
            self._last_marks_report = freshness

        return {
            "success": True,
            "marks_updated": len(marks),
            "marks_freshness": freshness,
            "account": self.ledger.snapshot().model_dump(mode="json"),
            "positions": [p.model_dump(mode="json") for p in self.positions()],
        }

    def marks_status(self) -> dict[str, Any]:
        """Expose fresh-marks gate config + last evaluation (Phase 1.2)."""
        loaded_at = getattr(self.feed, "instruments_loaded_at", None)
        if callable(loaded_at):
            loaded_at = loaded_at()
        return {
            "gate": "fresh_marks",
            "enabled": self.config.require_fresh_marks,
            "mark_provider": self.config.mark_provider,
            "quote_stale_threshold_sec": self.config.quote_stale_threshold_sec,
            "option_stale_threshold_sec": self.config.option_stale_threshold_sec,
            "instrument_master_max_age_sec": self.config.instrument_master_max_age_sec,
            "instrument_master_age_sec": instrument_master_age_sec(loaded_at),
            "last_report": self._last_marks_report,
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
            quote_stale_threshold_sec=self.config.quote_stale_threshold_sec,
            option_stale_threshold_sec=self.config.option_stale_threshold_sec,
            instrument_master_max_age_sec=self.config.instrument_master_max_age_sec,
        )
        return snap.model_dump(mode="json")

    def health(self) -> dict[str, Any]:
        """Phase 1.6: ledger + marks + news + γ–θ automation (no LLM)."""
        feed_health = getattr(self.feed, "health", lambda: {"feed": "custom"})()
        news_meta: dict[str, Any] = {}
        try:
            from backend.services.market_news import get_market_news, market_news_feed_status

            news = get_market_news()
            feed = market_news_feed_status()
            news_meta = {
                "dominant_tone": news.dominant_tone,
                "topics": news.topics,
                "macro_risk_flags": news.macro_risk_flags,
                "news_impact": news.news_impact,
                "workflow_window": news.workflow_window,
                "feed_health": feed.health.value,
                "feed_status": feed.status.value,
            }
        except Exception as exc:  # noqa: BLE001
            news_meta = {"error": str(exc)}
        return {
            "module": "paper_sim",
            "phase": "1.10",
            "status": "ready",
            "separate_from_icici_live": True,
            "broker_place_order": False,
            "execution_mode_hint": "paper",
            "railway_never_live": True,
            "capabilities": {
                "account": True,
                "positions": True,
                "fills": True,
                "multi_leg_orders": True,
                "close": True,
                "reset": True,
                "marks_refresh": True,
                "option_chain_scrip_master": True,
                "fresh_marks_gate": True,
                "market_news": True,
                "signals_garch_iv_z": True,
                "strategy_selection_sh4": True,
                "gamma_theta_automation": True,
                "bsm_oss_parity": True,
                "transaction_cost_model": True,
                "pre_trade_risk_gate": True,
                "llm_in_hedge_path": False,
            },
            "account": self.ledger.snapshot().model_dump(mode="json"),
            "feed": feed_health,
            "marks_gate": self.marks_status(),
            "market_news": news_meta,
            "automation": self.automation.status(),
            "config": {
                "total_capital_inr": self.config.total_capital_inr,
                "max_trade_investment_inr": self.config.max_trade_investment_inr,
                "max_leg_investment_inr": self.config.max_leg_investment_inr,
                "slippage_bps": self.config.slippage_bps,
                "underlying_price_cap_inr": self.config.underlying_price_cap_inr,
                "mark_provider": self.config.mark_provider,
                "quote_stale_threshold_sec": self.config.quote_stale_threshold_sec,
                "option_stale_threshold_sec": self.config.option_stale_threshold_sec,
                "require_fresh_marks": self.config.require_fresh_marks,
                "automation_tick_sec": self.config.automation_tick_sec,
                "rehedge_method": self.config.rehedge_method,
                "use_half_breakeven": self.config.use_half_breakeven,
                "delta_threshold": self.config.delta_threshold,
            },
        }
