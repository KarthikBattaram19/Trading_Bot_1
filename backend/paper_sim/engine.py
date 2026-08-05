"""Paper trading engine — isolated from ICICI Direct live execution."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from backend.execution.options_only import OPTIONS_ONLY_REQUIRED
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
    PaperIntendedLeg,
    PaperOrderRequest,
    PaperPosition,
    PaperSide,
    PaperLegRequest,
)
from backend.paper_sim.structure_builder import (
    build_intended_legs_from_entry,
    missing_intended_legs,
    strategy_implies_multi_leg,
)

logger = logging.getLogger(__name__)

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


def _is_option_leg(
    exchange: str,
    symbol: str,
    instrument_type: str | None = None,
) -> bool:
    if exchange.upper() != "NFO":
        return False
    if (instrument_type or "").upper().startswith("OPT"):
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

    async def _resolve_and_gate_legs(
        self,
        legs: list[PaperLegRequest],
        *,
        underlying: str | None,
    ) -> tuple[list[dict], dict[str, Any], Any]:
        """Resolve instruments, freshness, lotsize, pre-trade, Part T — same open rules."""
        if any(_is_cash_underlying_leg(leg) for leg in legs):
            raise PaperLedgerError(
                f"{OPTIONS_ONLY_REQUIRED}: Call/Put legs only; "
                "stock/underlying legs are not allowed"
            )

        resolved_legs: list[dict] = []
        ticks_for_gate: list[tuple[NormalizedTick, float]] = []

        for leg in legs:
            record = None
            if leg.symbol_token:
                record = self.feed.resolve(symboltoken=leg.symbol_token)
            if record is None:
                record = self.feed.resolve(exchange=leg.exchange, tradingsymbol=leg.symbol)
            if record is None:
                raise PaperLedgerError(
                    f"cannot resolve paper instrument {leg.exchange}:{leg.symbol}"
                )

            is_option = _is_option_leg(
                record.exchange,
                record.tradingsymbol,
                getattr(record, "instrumenttype", None),
            )
            if not is_option:
                raise PaperLedgerError(
                    f"{OPTIONS_ONLY_REQUIRED}: Call/Put legs only; "
                    "stock/underlying legs are not allowed"
                )

            tick = await self.feed.get_ltp(
                record.exchange, record.tradingsymbol, record.symboltoken
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

        freshness = self._gate_ticks(ticks_for_gate)

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

        return resolved_legs, freshness, gate

    @staticmethod
    def _to_intended_models(legs: list[PaperLegRequest]) -> list[PaperIntendedLeg]:
        return [
            PaperIntendedLeg(
                symbol=lg.symbol,
                exchange=lg.exchange,
                symbol_token=lg.symbol_token,
                side=lg.side,
                quantity=lg.quantity,
                option_type=lg.option_type,
                strike=lg.strike,
                expiry=lg.expiry,
            )
            for lg in legs
        ]

    @staticmethod
    def _intended_to_requests(legs: list[PaperIntendedLeg]) -> list[PaperLegRequest]:
        return [
            PaperLegRequest(
                symbol=lg.symbol,
                exchange=lg.exchange,
                symbol_token=lg.symbol_token,
                side=lg.side,
                quantity=lg.quantity,
                option_type=lg.option_type,
                strike=lg.strike,
                expiry=lg.expiry,
            )
            for lg in legs
        ]

    async def submit_order(self, request: PaperOrderRequest) -> dict[str, Any]:
        await self._ensure_scrip_master()

        # Resolve bot's intended multi-leg plan (explicit or inferred from strategy).
        if request.intended_legs:
            intended = list(request.intended_legs)
        elif strategy_implies_multi_leg(request.strategy_tag):
            intended = build_intended_legs_from_entry(
                strategy_tag=request.strategy_tag,
                underlying=request.underlying,
                entry_legs=list(request.legs),
                feed=self.feed,
            )
        else:
            intended = list(request.legs)

        resolved_legs, freshness, gate = await self._resolve_and_gate_legs(
            list(request.legs), underlying=request.underlying
        )

        includes_underlying = any(leg.get("is_cash_underlying") for leg in resolved_legs)
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

        missing_at_open = missing_intended_legs(
            current_legs=resolved_legs, intended_legs=intended
        )
        structure_complete = len(missing_at_open) == 0

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
            intended_legs=self._to_intended_models(intended),
            auto_complete_multi_leg=bool(request.auto_complete_multi_leg),
            structure_complete=structure_complete,
        )
        logger.info(
            "paper_sim fill order_id=%s position_id=%s legs=%s hedge_point=%s (no broker place_order)",
            order_id,
            position.position_id,
            len(fills),
            hedge_point,
        )

        multi_leg_completion: dict[str, Any] | None = None
        if (
            request.auto_complete_multi_leg
            and not structure_complete
            and strategy_implies_multi_leg(request.strategy_tag)
        ):
            multi_leg_completion = await self.complete_multi_leg_structure(
                position.position_id
            )
            position = self.ledger.positions[position.position_id]

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
            "multi_leg_completion": multi_leg_completion,
            "operator_consent_required_for_completion": False,
        }

    async def complete_multi_leg_structure(
        self, position_id: str, *, force: bool = False
    ) -> dict[str, Any]:
        """
        Auto-complete remaining intended opening legs without operator consent.

        Re-applies the same open-trade rules as the first entry (fresh marks,
        lotsize, pre-trade gate, Part T, cumulative ₹1L trade / per-leg caps).

        ``force=True`` is used by the explicit HTTP retry path; automatic
        submit/automation paths honor ``auto_complete_multi_leg``.
        """
        position = self.ledger.positions.get(position_id)
        if position is None:
            raise PaperLedgerError(f"unknown position_id={position_id}")
        if position.status != "open":
            raise PaperLedgerError(f"position {position_id} is already closed")
        if position.structure_complete:
            return {
                "action": "noop",
                "reason": "structure_already_complete",
                "position_id": position_id,
                "operator_consent_required": False,
            }
        if not force and not position.auto_complete_multi_leg:
            return {
                "action": "skip",
                "reason": "auto_complete_disabled",
                "position_id": position_id,
                "operator_consent_required": False,
            }
        if not position.intended_legs:
            position.structure_complete = True
            return {
                "action": "noop",
                "reason": "no_intended_legs",
                "position_id": position_id,
                "operator_consent_required": False,
            }

        await self._ensure_scrip_master()
        intended_reqs = self._intended_to_requests(position.intended_legs)
        missing = missing_intended_legs(
            current_legs=position.legs, intended_legs=intended_reqs
        )
        if not missing:
            position.structure_complete = True
            self.ledger._touch()
            return {
                "action": "noop",
                "reason": "no_missing_legs",
                "position_id": position_id,
                "operator_consent_required": False,
            }

        resolved_legs, freshness, gate = await self._resolve_and_gate_legs(
            missing, underlying=position.underlying
        )
        order_id = f"paper_ml_{uuid4().hex[:10]}"
        position, fills = self.ledger.add_opening_legs(
            position_id,
            legs=resolved_legs,
            slippage_bps=self.config.slippage_bps,
            order_id=order_id,
            mark_structure_complete=True,
        )
        # Re-check: if somehow still missing, leave incomplete for next tick.
        still_missing = missing_intended_legs(
            current_legs=position.legs,
            intended_legs=self._intended_to_requests(position.intended_legs),
        )
        if still_missing:
            position.structure_complete = False
            self.ledger._touch()

        logger.info(
            "paper_sim multi-leg auto-complete position_id=%s added_legs=%s "
            "(no consent; same open-trade rules)",
            position_id,
            len(fills),
        )
        return {
            "action": "complete_multi_leg",
            "position_id": position_id,
            "order_id": order_id,
            "added_legs": len(fills),
            "fills": [f.model_dump(mode="json") for f in fills],
            "position": position.model_dump(mode="json"),
            "account": self.ledger.snapshot().model_dump(mode="json"),
            "marks_freshness": freshness,
            "pre_trade_gate": gate.as_dict(),
            "operator_consent_required": False,
            "structure_complete": position.structure_complete,
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
        # Architecture §12.2 / §12.7 — ledger close is the learning input.
        try:
            from backend.services.learning_service import get_learning_service

            get_learning_service().record_ledger_close(
                position_id,
                realized_pnl_inr=float(pnl),
                exit_reason="paper_sim close",
            )
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception(
                "learning record_ledger_close failed for position_id=%s", position_id
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
                "multi_leg_auto_complete": True,
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
