"""Continuous γ–θ re-hedge automation for paper-sim (Phase 1.6–1.7; no LLM).

Authority: ``Docs/Paper_Simulator.md`` automation section, Part J, edge PS-05–PS-09.
Phase 1.7: §9.4 transaction cost model + §11.4 Greeks ceilings on the hedge path.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from backend.paper_sim.freshness import StaleMarksError
from backend.paper_sim.ledger import PaperLedgerError
from backend.paper_sim.models import PaperSide
from backend.quant.costs.transaction_cost import estimate_stock_hedge_cost
from backend.quant.gamma.hedge_optimizer import (
    gamma_theta_breakeven_pct,
    should_execute_hedge,
)
from backend.quant.pricing.bsm import mark_strategy
from backend.quant.risk.greeks_limits import GreeksLimitThresholds, check_greeks_limits

if TYPE_CHECKING:
    from backend.paper_sim.engine import PaperEngine

logger = logging.getLogger(__name__)

AutomationState = Literal["stopped", "running", "paused_kill_switch", "degraded"]


def _parse_expiry(raw: str | None) -> datetime | None:
    if not raw:
        return None
    s = raw.upper().replace("-", "").replace(" ", "")
    for fmt in ("%d%b%Y", "%d%b%y", "%Y%m%d"):
        try:
            return datetime.strptime(s[:9] if fmt.startswith("%d") else s[:8], fmt)
        except ValueError:
            continue
    return None


def _days_to_expiry(expiry: str | None, *, now: datetime | None = None) -> float:
    dt = _parse_expiry(expiry)
    if dt is None:
        return 20.0  # retail default when expiry missing
    as_of = now or datetime.now(timezone.utc)
    # Treat naive expiry as UTC calendar date
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = (dt.date() - as_of.astimezone(timezone.utc).date()).days
    # Expired / fixture dates: use playbook-like DTE so Γ/Θ remain defined
    return float(delta) if delta >= 1 else 20.0


def _option_type_from_symbol(symbol: str, option_type: str | None = None) -> str | None:
    if option_type:
        ot = option_type.upper()
        if ot in {"CE", "CALL"}:
            return "call"
        if ot in {"PE", "PUT"}:
            return "put"
    upper = symbol.upper()
    if upper.endswith("CE"):
        return "call"
    if upper.endswith("PE"):
        return "put"
    return None


def _is_kill_switch_armed() -> bool:
    try:
        from backend.routers.bot import is_kill_switch_armed

        return bool(is_kill_switch_armed())
    except Exception:  # noqa: BLE001
        return False


class PaperAutomation:
    """Background tick loop: refresh marks → news kills → γ–θ re-hedge."""

    def __init__(self, engine: PaperEngine) -> None:
        self.engine = engine
        self._task: asyncio.Task | None = None
        self._running = False
        self._started_at: datetime | None = None
        self._stopped_at: datetime | None = None
        self._last_tick_at: datetime | None = None
        self._last_actions: list[dict[str, Any]] = []
        self._last_error: str | None = None
        self._ticks = 0
        self._hedges = 0
        self._flattens = 0
        self._skips = 0
        self._last_news_impact: str | None = None
        self._last_signal: dict[str, Any] | None = None

    @property
    def state(self) -> AutomationState:
        if not self._running:
            return "stopped"
        if _is_kill_switch_armed():
            return "paused_kill_switch"
        if self._last_error:
            return "degraded"
        return "running"

    def _hedge_transaction_cost(self, *, spot: float, total_delta: float) -> float:
        """§9.4: override if set, else estimate stock-hedge one-way cost from |Δ| shares."""
        cfg = self.engine.config
        if cfg.hedge_transaction_cost_inr is not None:
            return float(cfg.hedge_transaction_cost_inr)
        qty = max(int(round(abs(float(total_delta)))), 1)
        result = estimate_stock_hedge_cost(
            quantity=qty,
            spot=float(spot),
            config=cfg.transaction_cost_config(),
            round_trip=False,
        )
        return float(result.total_transaction_cost)

    def status(self) -> dict[str, Any]:
        open_positions = self.engine.positions(status="open")
        hedge_points = [
            {
                "position_id": p.position_id,
                "underlying": p.underlying,
                "strategy_tag": p.strategy_tag,
                "hedge_point_price": p.hedge_point_price,
                "gamma_theta_breakeven_pct": p.gamma_theta_breakeven_pct,
                "breakeven_paid_count": p.breakeven_paid_count,
                "rehedge_method": p.rehedge_method,
                "last_rehedge_at": p.last_rehedge_at.isoformat()
                if p.last_rehedge_at
                else None,
                "total_delta": p.total_delta,
                "total_gamma": p.total_gamma,
                "total_theta": p.total_theta,
            }
            for p in open_positions
        ]
        return {
            "state": self.state,
            "running": self._running,
            "llm_in_path": False,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "stopped_at": self._stopped_at.isoformat() if self._stopped_at else None,
            "last_tick_at": self._last_tick_at.isoformat() if self._last_tick_at else None,
            "tick_sec": self.engine.config.automation_tick_sec,
            "ticks": self._ticks,
            "hedges": self._hedges,
            "flattens": self._flattens,
            "skips": self._skips,
            "last_error": self._last_error,
            "last_news_impact": self._last_news_impact,
            "last_signal": self._last_signal,
            "hedge_points": hedge_points,
            "last_actions": list(self._last_actions[-20:]),
            "config": {
                "use_half_breakeven": self.engine.config.use_half_breakeven,
                "rehedge_method": self.engine.config.rehedge_method,
                "rehedge_cooldown_sec": self.engine.config.rehedge_cooldown_sec,
                "max_breakeven_paid_count": self.engine.config.max_breakeven_paid_count,
                "min_edge_threshold": self.engine.config.min_edge_threshold,
                "delta_threshold": self.engine.config.delta_threshold,
            },
        }

    async def start(self) -> dict[str, Any]:
        if self._running and self._task and not self._task.done():
            return self.status()
        self._running = True
        self._started_at = datetime.now(timezone.utc)
        self._stopped_at = None
        self._last_error = None
        self._task = asyncio.create_task(self._loop(), name="paper_sim_gamma_theta")
        logger.info("paper_sim automation started (γ–θ; no LLM)")
        return self.status()

    async def stop(self) -> dict[str, Any]:
        self._running = False
        task = self._task
        self._task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._stopped_at = datetime.now(timezone.utc)
        logger.info("paper_sim automation stopped")
        return self.status()

    def _record(self, action: dict[str, Any]) -> None:
        action = {**action, "at": datetime.now(timezone.utc).isoformat()}
        self._last_actions.append(action)
        if len(self._last_actions) > 100:
            self._last_actions = self._last_actions[-100:]

    async def _loop(self) -> None:
        try:
            while self._running:
                try:
                    await self.tick()
                    self._last_error = None
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self._last_error = str(exc)
                    logger.exception("paper_sim automation tick failed")
                    self._record({"action": "tick_error", "detail": str(exc)})
                await asyncio.sleep(float(self.engine.config.automation_tick_sec))
        except asyncio.CancelledError:
            logger.debug("paper_sim automation cancelled")
            raise

    async def tick(self) -> dict[str, Any]:
        """One automation cycle — callable from tests without starting the loop."""
        self._ticks += 1
        self._last_tick_at = datetime.now(timezone.utc)
        actions: list[dict[str, Any]] = []

        if _is_kill_switch_armed():
            # PS-08: stop new hedges while kill-switch armed
            actions.append({"action": "skip", "reason": "kill_switch_armed"})
            self._skips += 1
            self._record(actions[-1])
            return {"actions": actions, "status": self.status()}

        # Refresh marks (PS-09: skip actions if refresh fails / stale)
        try:
            marks_result = await self.engine.refresh_marks()
            freshness = marks_result.get("marks_freshness") or {}
            if freshness.get("ok") is False:
                actions.append(
                    {
                        "action": "skip",
                        "reason": "marks_stale",
                        "detail": freshness,
                    }
                )
                self._skips += 1
                self._record(actions[-1])
                return {"actions": actions, "status": self.status()}
        except StaleMarksError as exc:
            actions.append({"action": "skip", "reason": "marks_stale", "detail": str(exc)})
            self._skips += 1
            self._record(actions[-1])
            self._last_error = str(exc)
            return {"actions": actions, "status": self.status()}
        except Exception as exc:  # noqa: BLE001
            actions.append({"action": "skip", "reason": "marks_refresh_failed", "detail": str(exc)})
            self._skips += 1
            self._record(actions[-1])
            self._last_error = str(exc)
            return {"actions": actions, "status": self.status()}

        from backend.services.market_news import get_market_news
        from backend.services.strategy_selection import post_entry_news_action

        news = get_market_news()
        self._last_news_impact = news.news_impact
        news_action = post_entry_news_action(news, position_open=True)
        self._last_signal = {
            "news_impact": news.news_impact,
            "post_entry_action": news_action,
            "dominant_tone": news.dominant_tone,
            "kill_event": news.kill_event,
        }

        open_positions = list(self.engine.positions(status="open"))
        if not open_positions:
            actions.append({"action": "idle", "reason": "no_open_positions"})
            self._record(actions[-1])
            return {"actions": actions, "status": self.status()}

        # Phase 1: complete intended multi-leg opening structures without consent
        # (same open-trade rules), before γ–θ management.
        for position in list(open_positions):
            if position.structure_complete or not position.auto_complete_multi_leg:
                continue
            try:
                completion = await self.engine.complete_multi_leg_structure(
                    position.position_id
                )
                actions.append(
                    {
                        "action": "multi_leg_auto_complete",
                        **{
                            k: completion.get(k)
                            for k in (
                                "position_id",
                                "added_legs",
                                "structure_complete",
                                "reason",
                                "operator_consent_required",
                            )
                            if k in completion
                        },
                    }
                )
                self._record(actions[-1])
            except Exception as exc:  # noqa: BLE001
                actions.append(
                    {
                        "action": "multi_leg_auto_complete_failed",
                        "position_id": position.position_id,
                        "detail": str(exc),
                    }
                )
                self._record(actions[-1])

        open_positions = list(self.engine.positions(status="open"))

        # PS-06: news kill / early exit / take_profit prefer flatten over re-hedge
        if news_action in {"kill_event", "early_exit", "take_profit"}:
            for position in open_positions:
                try:
                    closed = await self.engine.close_position(position.position_id)
                    actions.append(
                        {
                            "action": "flatten",
                            "reason": news_action,
                            "position_id": position.position_id,
                            "realized_pnl": closed.get("realized_pnl"),
                        }
                    )
                    self._flattens += 1
                    self._record(actions[-1])
                except Exception as exc:  # noqa: BLE001
                    actions.append(
                        {
                            "action": "flatten_failed",
                            "position_id": position.position_id,
                            "detail": str(exc),
                        }
                    )
                    self._record(actions[-1])
            return {"actions": actions, "status": self.status()}

        aggressive = news_action == "rehedge_aggressive"
        for position in open_positions:
            result = await self._maybe_rehedge(position.position_id, aggressive=aggressive)
            actions.append(result)
            self._record(result)
            if result.get("action") == "rehedge":
                self._hedges += 1
            elif result.get("action") == "skip":
                self._skips += 1

        return {"actions": actions, "status": self.status()}

    async def _underlying_spot(self, underlying: str | None) -> float | None:
        if not underlying:
            return None
        und = underlying.upper()
        await self.engine._ensure_scrip_master()
        record = self.engine.feed.resolve(exchange="NSE", tradingsymbol=und)
        if record is None:
            record = self.engine.feed.resolve(tradingsymbol=und)
        if record is None:
            return None
        tick = await self.engine.feed.get_ltp(
            record.exchange, record.tradingsymbol, record.symboltoken
        )
        return float(tick.ltp)

    async def _position_greeks(
        self, position_id: str, spot: float
    ) -> dict[str, float]:
        position = self.engine.ledger.positions[position_id]
        cfg = self.engine.config
        legs: list[dict[str, Any]] = []
        for i, leg in enumerate(position.legs):
            record = self.engine.feed.resolve(
                exchange=leg.exchange, tradingsymbol=leg.symbol, symboltoken=leg.symbol_token
            )
            signed_qty = leg.quantity if leg.side == PaperSide.buy else -leg.quantity
            ot = _option_type_from_symbol(
                leg.symbol, getattr(record, "option_type", None) if record else None
            )
            if ot is None and leg.exchange.upper() in {"NSE", "BSE"}:
                legs.append(
                    {
                        "leg_id": i + 1,
                        "type": "stock",
                        "position": signed_qty,
                        "initial_price": leg.avg_price,
                        "contract_multiplier": 1,
                    }
                )
                continue
            if ot is None or record is None:
                continue
            strike = float(record.strike or 0.0)
            if strike <= 0:
                continue
            # India NFO: use instrument lotsize as contract multiplier (not US 100).
            mult = max(int(record.lotsize or leg.lotsize or 1), 1)
            # position in mark_strategy is contract count; quantity is shares = contracts * lotsize
            contracts = int(signed_qty // mult) if abs(signed_qty) >= mult else int(signed_qty)
            if contracts == 0:
                contracts = 1 if signed_qty > 0 else -1
            legs.append(
                {
                    "leg_id": i + 1,
                    "type": ot,
                    "position": contracts,
                    "strike": strike,
                    "days_to_expiry": _days_to_expiry(record.expiry),
                    "initial_price": leg.avg_price,
                    "contract_multiplier": mult,
                }
            )

        if not legs:
            return {
                "total_delta": 0.0,
                "total_gamma": 0.0,
                "total_theta": 0.0,
                "total_vega": 0.0,
            }

        marked = mark_strategy(
            global_params={
                "und_price": spot,
                "div_yield": cfg.dividend_yield_pct,
                "int_rate": cfg.risk_free_rate_pct,
                "volatility": cfg.default_iv_annual_pct,
                "display_mode": "total",
                "default_contract_multiplier": 1,
                "flat_volatility": True,
            },
            legs=legs,
        )
        return {
            "total_delta": float(marked.total_delta),
            "total_gamma": float(marked.total_gamma),
            "total_theta": float(marked.total_theta),
            "total_vega": float(marked.total_vega),
        }

    async def _maybe_rehedge(
        self, position_id: str, *, aggressive: bool = False
    ) -> dict[str, Any]:
        position = self.engine.ledger.positions.get(position_id)
        if position is None or position.status != "open":
            return {"action": "skip", "reason": "position_gone", "position_id": position_id}

        cfg = self.engine.config
        if int(position.breakeven_paid_count or 0) >= int(cfg.max_breakeven_paid_count):
            return {
                "action": "skip",
                "reason": "max_breakeven_paid_count",
                "position_id": position_id,
                "breakeven_paid_count": position.breakeven_paid_count,
            }

        if position.last_rehedge_at is not None:
            age = (datetime.now(timezone.utc) - position.last_rehedge_at).total_seconds()
            if age < float(cfg.rehedge_cooldown_sec):
                return {
                    "action": "skip",
                    "reason": "cooldown",
                    "position_id": position_id,
                    "cooldown_remaining_sec": float(cfg.rehedge_cooldown_sec) - age,
                }

        spot = await self._underlying_spot(position.underlying)
        if spot is None or spot <= 0:
            return {
                "action": "skip",
                "reason": "underlying_spot_unavailable",
                "position_id": position_id,
            }

        # Initialize hedge point on first automation sighting
        if position.hedge_point_price is None or position.hedge_point_price <= 0:
            self.engine.ledger.update_hedge_state(
                position_id, hedge_point_price=spot
            )
            position = self.engine.ledger.positions[position_id]

        greeks = await self._position_greeks(position_id, spot)
        be_pct = gamma_theta_breakeven_pct(
            total_gamma=greeks["total_gamma"],
            total_theta=greeks["total_theta"],
            spot=spot,
        )
        self.engine.ledger.update_hedge_state(
            position_id,
            gamma_theta_breakeven_pct=be_pct,
            total_delta=greeks["total_delta"],
            total_gamma=greeks["total_gamma"],
            total_theta=greeks["total_theta"],
            total_vega=greeks["total_vega"],
        )
        position = self.engine.ledger.positions[position_id]

        use_half = bool(cfg.use_half_breakeven) or aggressive
        method = position.rehedge_method or cfg.rehedge_method

        # §11.4 Greeks limits — skip hedge if portfolio Greeks already breach ceilings
        greeks_gate = check_greeks_limits(
            total_delta=greeks["total_delta"],
            total_gamma=greeks["total_gamma"],
            total_vega=greeks["total_vega"],
            total_theta=greeks["total_theta"],
            thresholds=GreeksLimitThresholds(
                max_abs_total_delta=cfg.max_abs_total_delta,
                max_abs_total_gamma=cfg.max_abs_total_gamma,
                max_abs_total_vega=cfg.max_abs_total_vega,
                min_total_theta=cfg.min_total_theta,
            ),
        )
        if not greeks_gate.passed:
            return {
                "action": "skip",
                "reason": "greeks_limits",
                "position_id": position_id,
                "failures": list(greeks_gate.failures),
            }

        txn_cost = self._hedge_transaction_cost(
            spot=spot, total_delta=greeks["total_delta"]
        )
        decision = should_execute_hedge(
            spot=spot,
            hedge_point_price=float(position.hedge_point_price or spot),
            breakeven_pct=be_pct,
            total_delta=greeks["total_delta"],
            total_gamma=greeks["total_gamma"],
            total_theta=greeks["total_theta"],
            transaction_cost=txn_cost,
            min_edge_threshold=cfg.min_edge_threshold,
            delta_threshold=cfg.delta_threshold,
            use_half_breakeven=use_half,
            method=method,  # type: ignore[arg-type]
            force=aggressive and be_pct > 0,
        )

        if not decision.should_hedge:
            return {
                "action": "skip",
                "reason": decision.reason,
                "position_id": position_id,
                "spot": spot,
                "hedge_point_price": decision.hedge_point_price,
                "move_pct": decision.move_pct,
                "trigger_pct": decision.trigger_pct,
                "breakeven_pct": decision.breakeven_pct,
                "net_hedge_edge": decision.net_hedge_edge,
                "total_delta": decision.total_delta,
            }

        try:
            if method == "reduce_options":
                return await self._execute_reduce_options(
                    position_id, spot=spot, greeks=greeks, be_pct=be_pct, decision=decision
                )
            if method == "adjust_call_put_mix":
                return await self._execute_adjust_call_put(
                    position_id, spot=spot, greeks=greeks, be_pct=be_pct, decision=decision
                )
            return await self._execute_increase_hedge(
                position_id, spot=spot, greeks=greeks, be_pct=be_pct, decision=decision
            )
        except PaperLedgerError as exc:
            # PS-05: capital cap → try reduce_options fallback once
            if "exceeds" in str(exc).lower() or "insufficient" in str(exc).lower():
                try:
                    return await self._execute_reduce_options(
                        position_id,
                        spot=spot,
                        greeks=greeks,
                        be_pct=be_pct,
                        decision=decision,
                        fallback_from=method,
                        capital_error=str(exc),
                    )
                except PaperLedgerError as exc2:
                    return {
                        "action": "skip",
                        "reason": "capital_cap",
                        "position_id": position_id,
                        "detail": str(exc2),
                    }
            return {
                "action": "skip",
                "reason": "ledger_reject",
                "position_id": position_id,
                "detail": str(exc),
            }

    async def _execute_increase_hedge(
        self,
        position_id: str,
        *,
        spot: float,
        greeks: dict[str, float],
        be_pct: float,
        decision: Any,
    ) -> dict[str, Any]:
        """Neutralize residual delta with a stock hedge leg."""
        position = self.engine.ledger.positions[position_id]
        underlying = (position.underlying or "").upper()
        if not underlying:
            return {
                "action": "skip",
                "reason": "no_underlying_for_stock_hedge",
                "position_id": position_id,
            }

        delta = float(greeks["total_delta"])
        # Shares to trade ≈ −delta (buy if short delta, sell if long delta)
        shares = int(round(-delta))
        if shares == 0:
            # Still roll hedge point when force/aggressive crossed breakeven
            self.engine.ledger.update_hedge_state(
                position_id,
                hedge_point_price=spot,
                gamma_theta_breakeven_pct=be_pct,
            )
            pos = self.engine.ledger.positions[position_id]
            pos.breakeven_paid_count = int(pos.breakeven_paid_count or 0) + 1
            pos.last_rehedge_at = datetime.now(timezone.utc)
            return {
                "action": "rehedge",
                "method": "increase_hedge",
                "position_id": position_id,
                "note": "delta_already_flat_rolled_hedge_point",
                "spot": spot,
                "decision": decision.reason,
            }

        await self.engine._ensure_scrip_master()
        record = self.engine.feed.resolve(exchange="NSE", tradingsymbol=underlying)
        if record is None:
            return {
                "action": "skip",
                "reason": "underlying_instrument_missing",
                "position_id": position_id,
                "underlying": underlying,
            }

        # Part T: stock hedge requires spot ≤ cap
        if (
            self.engine.config.underlying_price_cap_inr > 0
            and spot > self.engine.config.underlying_price_cap_inr
        ):
            return await self._execute_reduce_options(
                position_id,
                spot=spot,
                greeks=greeks,
                be_pct=be_pct,
                decision=decision,
                fallback_from="increase_hedge",
                capital_error=f"spot {spot} exceeds Part T cap for stock hedge",
            )

        side = PaperSide.buy if shares > 0 else PaperSide.sell
        qty = abs(shares)
        tick = await self.engine.feed.get_ltp(
            record.exchange, record.tradingsymbol, record.symboltoken
        )
        legs = [
            {
                "symbol": record.tradingsymbol,
                "exchange": record.exchange,
                "symbol_token": record.symboltoken,
                "side": side,
                "quantity": qty,
                "mark_ltp": float(tick.ltp),
                "lotsize": record.lotsize or 1,
            }
        ]
        pos, fills = self.engine.ledger.apply_rehedge_legs(
            position_id,
            legs=legs,
            slippage_bps=self.engine.config.slippage_bps,
            hedge_point_price=spot,
            gamma_theta_breakeven_pct=be_pct,
            total_delta=greeks["total_delta"],
            total_gamma=greeks["total_gamma"],
            total_theta=greeks["total_theta"],
            total_vega=greeks.get("total_vega"),
            rehedge_method="increase_hedge",
        )
        return {
            "action": "rehedge",
            "method": "increase_hedge",
            "position_id": position_id,
            "shares": shares,
            "spot": spot,
            "hedge_point_price": pos.hedge_point_price,
            "breakeven_paid_count": pos.breakeven_paid_count,
            "fills": [f.model_dump(mode="json") for f in fills],
            "decision": decision.reason,
            "net_hedge_edge": decision.net_hedge_edge,
        }

    async def _execute_reduce_options(
        self,
        position_id: str,
        *,
        spot: float,
        greeks: dict[str, float],
        be_pct: float,
        decision: Any,
        fallback_from: str | None = None,
        capital_error: str | None = None,
    ) -> dict[str, Any]:
        position = self.engine.ledger.positions[position_id]
        marks = {
            leg.symbol_token: float(leg.mark_ltp or 0.0)
            for leg in position.legs
            if leg.mark_ltp
        }
        # Refresh marks for option legs
        for leg in position.legs:
            tick = await self.engine.feed.get_ltp(leg.exchange, leg.symbol, leg.symbol_token)
            marks[leg.symbol_token] = float(tick.ltp)

        pos, fills = self.engine.ledger.reduce_option_legs(
            position_id,
            reduce_by_lots=1,
            marks=marks,
            slippage_bps=self.engine.config.slippage_bps,
            hedge_point_price=spot,
            gamma_theta_breakeven_pct=be_pct,
            total_delta=greeks["total_delta"],
            total_gamma=greeks["total_gamma"],
            total_theta=greeks["total_theta"],
        )
        return {
            "action": "rehedge",
            "method": "reduce_options",
            "position_id": position_id,
            "spot": spot,
            "hedge_point_price": pos.hedge_point_price,
            "breakeven_paid_count": pos.breakeven_paid_count,
            "fills": [f.model_dump(mode="json") for f in fills],
            "decision": decision.reason,
            "fallback_from": fallback_from,
            "capital_error": capital_error,
            "net_hedge_edge": decision.net_hedge_edge,
        }

    async def _execute_adjust_call_put(
        self,
        position_id: str,
        *,
        spot: float,
        greeks: dict[str, float],
        be_pct: float,
        decision: Any,
    ) -> dict[str, Any]:
        """Reduce the option side contributing most to residual delta (VT-6 style)."""
        position = self.engine.ledger.positions[position_id]
        delta = float(greeks["total_delta"])
        # Long delta → reduce calls; short delta → reduce puts
        prefer_ce = delta > 0
        marks: dict[str, float] = {}
        target_leg = None
        for leg in position.legs:
            tick = await self.engine.feed.get_ltp(leg.exchange, leg.symbol, leg.symbol_token)
            marks[leg.symbol_token] = float(tick.ltp)
            ot = _option_type_from_symbol(leg.symbol)
            if ot is None:
                continue
            if prefer_ce and ot == "call":
                target_leg = leg
            if (not prefer_ce) and ot == "put":
                target_leg = leg

        if target_leg is None:
            return await self._execute_reduce_options(
                position_id, spot=spot, greeks=greeks, be_pct=be_pct, decision=decision
            )

        # Reduce preferred side by one lot (VT-6 call vs put adjustment)
        lot = max(int(target_leg.lotsize or 1), 1)
        cut = min(target_leg.quantity, lot)
        close_side = PaperSide.sell if target_leg.side == PaperSide.buy else PaperSide.buy
        from uuid import uuid4

        from backend.paper_sim.fill_model import compute_fill_price, leg_notional
        from backend.paper_sim.models import PaperFill

        ledger = self.engine.ledger
        fill_price = compute_fill_price(
            marks[target_leg.symbol_token], close_side, self.engine.config.slippage_bps
        )
        notional = leg_notional(fill_price, cut)
        if target_leg.side == PaperSide.buy:
            cash_delta = fill_price * cut
            realized = (fill_price - target_leg.avg_price) * cut
        else:
            cash_delta = -(fill_price * cut)
            realized = (target_leg.avg_price - fill_price) * cut

        order_id = f"paper_mix_{uuid4().hex[:10]}"
        fill = PaperFill(
            fill_id=f"fill_{uuid4().hex[:10]}",
            order_id=order_id,
            symbol=target_leg.symbol,
            exchange=target_leg.exchange,
            symbol_token=target_leg.symbol_token,
            side=close_side,
            quantity=cut,
            mark_ltp=marks[target_leg.symbol_token],
            fill_price=fill_price,
            slippage_bps=self.engine.config.slippage_bps,
            notional_inr=notional,
            filled_at=datetime.now(timezone.utc),
        )
        reduced_symbol = target_leg.symbol
        ledger.cash += cash_delta
        ledger.realized_pnl += realized
        ledger.fills.append(fill)
        target_leg.quantity -= cut
        position.legs = [lg for lg in position.legs if lg.quantity > 0]
        if not position.legs:
            position.status = "closed"
            position.closed_at = datetime.now(timezone.utc)
            position.unrealized_pnl = 0.0
        position.realized_pnl = float(position.realized_pnl or 0.0) + realized
        position.hedge_point_price = spot
        position.breakeven_paid_count = int(position.breakeven_paid_count or 0) + 1
        position.last_rehedge_at = datetime.now(timezone.utc)
        position.rehedge_method = "adjust_call_put_mix"
        position.gamma_theta_breakeven_pct = be_pct
        position.total_delta = greeks["total_delta"]
        position.total_gamma = greeks["total_gamma"]
        position.total_theta = greeks["total_theta"]
        ledger._touch()

        return {
            "action": "rehedge",
            "method": "adjust_call_put_mix",
            "position_id": position_id,
            "reduced_symbol": reduced_symbol,
            "quantity": cut,
            "spot": spot,
            "hedge_point_price": position.hedge_point_price,
            "breakeven_paid_count": position.breakeven_paid_count,
            "fills": [fill.model_dump(mode="json")],
            "decision": decision.reason,
            "net_hedge_edge": decision.net_hedge_edge,
        }
