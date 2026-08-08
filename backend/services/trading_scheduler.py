"""Background trading scheduler — the missing trigger for the whole pipeline.

Before this module existed, recommendation cycles only ran when someone
loaded the dashboard, nothing auto-started the paper_sim automation loop,
and no code path ever closed an open position at session close. The
scheduler runs a small asyncio loop (same skeleton as
backend/paper_sim/automation.py) whose per-tick behavior is gated by
backend/services/market_session.session_phase:

- closed / pre_open: idle.
- entry (09:20–14:30 IST): ensure the paper_sim automation loop is running,
  and run a fresh recommendation cycle on a config cadence unless the
  one-trade lock is engaged. In SUPERVISION_MODE=fully_autonomous the cycle
  itself opens the trade; in supervised mode it keeps the recommendation
  cache warm so POST /decisions/{id}/approve works reliably.
- no_entry (14:30–15:15): automation keeps running; no new cycles.
- flatten (15:15–15:30): close every open paper_sim position through
  PaperEngine.close_position (the one path that feeds learning), retrying
  each tick on stale-marks/transient failures.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from backend.services.market_session import CONFIG_PATH, now_ist, session_phase
from backend.services.recommendation_cycle import run_recommendation_cycle
from backend.services.scan_capacity import DEFAULT_RECOMMENDATION_CADENCE_SEC
from backend.services.trade_executor import has_open_paper_position, is_one_trade_locked

logger = logging.getLogger(__name__)


def get_paper_engine():
    from backend.paper_sim.service import get_paper_engine as _get

    return _get()


def _load_scheduler_config() -> dict[str, Any]:
    defaults = {
        "enabled": True,
        "tick_sec": 30.0,
        # Shared with scan_capacity._cycles_per_day: if the fallbacks diverged,
        # boot validation would certify a daily call budget for a cadence the
        # scheduler doesn't actually run.
        "recommendation_cadence_sec": DEFAULT_RECOMMENDATION_CADENCE_SEC,
        "flatten_retry_max": 30,
    }
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            section = json.load(f).get("scheduler", {})
    except (OSError, ValueError) as exc:
        # Falling back to defaults changes trading cadence — never do it mutely.
        logger.error("scheduler config unreadable, using defaults: %s", exc)
        section = {}
    return {**defaults, **{k: v for k, v in section.items() if k in defaults}}


class TradingScheduler:
    """Phase-gated market-hours loop: cycles during entry, flatten at close."""

    def __init__(self) -> None:
        self.config = _load_scheduler_config()
        self._task: asyncio.Task | None = None
        self._running = False
        self._started_at: datetime | None = None
        self._last_tick_at: datetime | None = None
        self._last_phase: str | None = None
        self._last_generation_at: datetime | None = None
        self._ticks = 0
        self._generations = 0
        self._flatten_attempts = 0
        self._flatten_closed = 0
        self._flatten_failures: dict[str, int] = {}
        self._last_error: str | None = None
        self._last_actions: list[dict[str, Any]] = []

    # ── lifecycle (same shape as paper_sim automation) ───────────────────

    @property
    def state(self) -> str:
        if not self._running:
            return "stopped"
        if self._last_error:
            return "degraded"
        return "running"

    async def start(self) -> dict[str, Any]:
        if self._running and self._task and not self._task.done():
            return self.status()
        self._running = True
        self._started_at = datetime.now(timezone.utc)
        self._last_error = None
        self._task = asyncio.create_task(self._loop(), name="trading_scheduler")
        logger.info("trading scheduler started (tick=%ss)", self.config["tick_sec"])
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
        logger.info("trading scheduler stopped")
        return self.status()

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
                    logger.exception("trading scheduler tick failed")
                    self._record({"action": "tick_error", "detail": str(exc)})
                await asyncio.sleep(float(self.config["tick_sec"]))
        except asyncio.CancelledError:
            logger.debug("trading scheduler cancelled")
            raise

    def _record(self, action: dict[str, Any]) -> None:
        self._last_actions.append(
            {**action, "at": datetime.now(timezone.utc).isoformat()}
        )
        if len(self._last_actions) > 100:
            self._last_actions = self._last_actions[-100:]

    # ── per-tick behavior ────────────────────────────────────────────────

    async def tick(self, now: datetime | None = None) -> dict[str, Any]:
        moment = now or now_ist()
        phase = session_phase(moment)
        self._ticks += 1
        self._last_tick_at = datetime.now(timezone.utc)
        self._last_phase = phase

        if phase in ("closed", "pre_open"):
            return {"phase": phase, "action": "idle"}

        engine = get_paper_engine()

        # Market is open: the automation loop must run so marks refresh and
        # any open position gets its γ–θ re-hedge.
        if engine.automation.state == "stopped":
            await engine.automation.start()
            self._record({"action": "automation_started", "phase": phase})

        if phase == "entry":
            return await self._entry_tick(moment, phase)
        if phase == "flatten":
            return await self._flatten_tick(phase, engine)
        return {"phase": phase, "action": "hold"}  # no_entry

    async def _entry_tick(self, moment: datetime, phase: str) -> dict[str, Any]:
        # `is_one_trade_locked()` only sees positions registered via
        # `LearningService.register_open_trade` — it misses a position opened
        # directly via POST /api/v1/paper-sim/orders, or a leaked partial
        # open from a prior autonomous attempt (see `has_open_paper_position()`
        # docstring in trade_executor.py). Checking both HERE — before
        # `run_recommendation_cycle` (and therefore before its Breeze-calling
        # `generate_recommendations`) — is what actually saves rate budget;
        # the mirrored check in `recommendation_cycle.autonomous_execution_for`
        # runs too late for that (recommendations are already generated by
        # then) and only avoids a doomed executor call. This check must never
        # run in `_flatten_tick` — flatten needs to close positions during
        # 15:15–15:30 IST regardless of lock state, and it does not call
        # `_entry_tick` or this check at all.
        if is_one_trade_locked() or has_open_paper_position():
            return {"phase": phase, "action": "skip", "reason": "one_trade_locked"}

        cadence = float(self.config["recommendation_cadence_sec"])
        if (
            self._last_generation_at is not None
            and (moment - self._last_generation_at).total_seconds() < cadence
        ):
            return {"phase": phase, "action": "skip", "reason": "within_cadence"}

        self._last_generation_at = moment
        result = await run_recommendation_cycle(force_refresh=True)
        self._generations += 1
        execution = getattr(result, "autonomous_execution", None)
        summary = {
            "action": "generated",
            "phase": phase,
            "recommendations": len(getattr(result, "recommendations", []) or []),
            "executed": bool(getattr(execution, "executed", False)),
            "message": getattr(execution, "message", None),
        }
        self._record(summary)
        return summary

    async def _flatten_tick(self, phase: str, engine) -> dict[str, Any]:
        closed: list[str] = []
        failed: list[str] = []
        retry_max = int(self.config["flatten_retry_max"])
        for position in engine.positions(status="open"):
            pid = position.position_id
            if self._flatten_failures.get(pid, 0) >= retry_max:
                continue
            self._flatten_attempts += 1
            try:
                result = await engine.close_position(pid)
                self._flatten_closed += 1
                closed.append(pid)
                self._record(
                    {
                        "action": "flatten_closed",
                        "position_id": pid,
                        "realized_pnl": (result or {}).get("realized_pnl"),
                    }
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — retried next tick
                self._flatten_failures[pid] = self._flatten_failures.get(pid, 0) + 1
                failed.append(pid)
                logger.warning("flatten failed for %s (attempt %s): %s",
                               pid, self._flatten_failures[pid], exc)
                self._record(
                    {"action": "flatten_retry", "position_id": pid, "detail": str(exc)}
                )
        return {"phase": phase, "action": "flatten", "closed": closed, "failed": failed}

    # ── status ───────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "phase": self._last_phase or session_phase(),
            "running": self._running,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "last_tick_at": self._last_tick_at.isoformat() if self._last_tick_at else None,
            "ticks": self._ticks,
            "generations": self._generations,
            "last_generation_at": (
                self._last_generation_at.isoformat() if self._last_generation_at else None
            ),
            "flatten_attempts": self._flatten_attempts,
            "flatten_closed": self._flatten_closed,
            "last_error": self._last_error,
            "last_actions": list(self._last_actions[-20:]),
            "config": dict(self.config),
        }


_scheduler: TradingScheduler | None = None


def get_trading_scheduler() -> TradingScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = TradingScheduler()
    return _scheduler


def reset_for_tests() -> None:
    global _scheduler
    _scheduler = None
