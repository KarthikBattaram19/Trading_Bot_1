"""Assemble live risk dashboard snapshot from paper-sim + learning + feeds."""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any

from backend.execution.circuit_breakers import (
    CircuitBreakerThresholds,
    active_breaker_ids,
    evaluate_circuit_breakers,
)
from backend.quant.risk.greeks_limits import GreeksLimitThresholds, check_greeks_limits

SHARED_KILL_CONDITIONS = [
    "liquidity collapses or spreads blow out beyond limits",
    "a hedge leg becomes unavailable",
    "the model input is stale or clearly corrupted",
    "required neutrality cannot be restored within cost limits",
    "residual delta or vega exposure exceeds portfolio limits",
    "the strategy's core assumption no longer holds",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _drawdown_pct(starting: float, equity: float) -> float:
    if starting <= 0 or not isfinite(starting) or not isfinite(equity):
        return 0.0
    return max(0.0, (starting - equity) / starting * 100.0)


def _portfolio_greeks(positions: list[Any]) -> dict[str, float]:
    totals = {
        "total_delta": 0.0,
        "total_gamma": 0.0,
        "total_theta": 0.0,
        "total_vega": 0.0,
    }
    for pos in positions:
        for key in totals:
            val = getattr(pos, key, None)
            if val is not None and isfinite(float(val)):
                totals[key] += float(val)
    return {k: round(v, 4) for k, v in totals.items()}


def _greek_rows(
    greeks: dict[str, float],
    thr: GreeksLimitThresholds,
) -> list[dict[str, Any]]:
    specs = [
        ("Delta", "total_delta", thr.max_abs_total_delta, True),
        ("Gamma", "total_gamma", thr.max_abs_total_gamma, True),
        ("Vega", "total_vega", thr.max_abs_total_vega, True),
        ("Theta", "total_theta", abs(thr.min_total_theta), False),
    ]
    rows: list[dict[str, Any]] = []
    for label, key, limit, use_abs in specs:
        current = float(greeks.get(key, 0.0))
        util_base = abs(current) if use_abs else max(0.0, -current)
        pct = 0.0 if limit <= 0 else min(999.0, (util_base / limit) * 100.0)
        rows.append(
            {
                "greek": label,
                "key": key,
                "current": round(current, 4),
                "limit": float(limit),
                "pct": round(pct, 1),
            }
        )
    return rows


def _consecutive_losses(outcomes: list[Any]) -> int:
    streak = 0
    for o in reversed(list(outcomes)):
        label = getattr(o, "outcome", None)
        value = label.value if hasattr(label, "value") else str(label or "")
        if value == "loss":
            streak += 1
            continue
        if value == "scratch":
            continue
        break
    return streak


def _feed_age_sec(marks: dict[str, Any], feeds: list[Any]) -> float | None:
    """Best-effort quote age for the feed-staleness breaker (seconds).

    Returns ``None`` when no live quote age is available so an idle paper
    ledger does not look like a stale-feed breach.
    """
    report = marks.get("last_report") or {}
    ages: list[float] = []
    for detail in report.get("details") or []:
        age = detail.get("age_sec")
        if age is not None and isfinite(float(age)):
            ages.append(float(age))
    for feed in feeds:
        source_id = getattr(feed, "source_id", "") or ""
        if source_id and source_id != "icici_direct":
            continue
        last = getattr(feed, "last_fetch_at", None)
        if last is None:
            continue
        try:
            ts = (
                last
                if isinstance(last, datetime)
                else datetime.fromisoformat(str(last).replace("Z", "+00:00"))
            )
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ages.append(max(0.0, (_now() - ts).total_seconds()))
        except (TypeError, ValueError):
            continue
    if not ages:
        return None
    return max(ages)


def _risk_events(
    *,
    breakers: list[dict[str, Any]],
    freeze_reason: str | None,
    greeks_passed: bool,
    account_updated_at: datetime | None,
    open_positions: int,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    now = _now()

    def add(level: str, text: str, when: datetime | None = None) -> None:
        ts = when or now
        events.append(
            {
                "level": level,
                "text": text,
                "ts": ts.isoformat(),
            }
        )

    if freeze_reason:
        add("warn", f"Learning adaptation frozen: {freeze_reason}")
    for b in breakers:
        if b["tone"] == "danger":
            add("danger", f"{b['name']} breached ({b['current']} / {b['limit']} {b['unit']}).")
        elif b["tone"] == "warn":
            add("warn", f"{b['name']} approaching limit ({b['pct']:.0f}% utilization).")
    if not greeks_passed:
        add("warn", "Portfolio Greeks outside configured limits.")
    if open_positions == 0:
        add("info", "No open paper positions — portfolio Greeks at flat.")
    if account_updated_at is not None:
        add("info", "Paper ledger snapshot refreshed.", account_updated_at)
    else:
        add("info", "Session ready. Initializing margin and circuit-breaker checks.")
    return events[:12]


def build_risk_snapshot() -> dict[str, Any]:
    """Live risk dashboard payload for GET /api/v1/risk/snapshot."""
    from backend.paper_sim.service import get_paper_engine
    from backend.services.feed_health import get_feed_sources
    from backend.services.learning_service import get_learning_service

    engine = get_paper_engine()
    account = engine.account()
    open_positions = engine.positions(status="open")
    marks = engine.marks_status()
    feeds = get_feed_sources()
    learning = get_learning_service().dashboard()

    starting = float(account.starting_capital_inr)
    equity = float(account.equity_inr)
    drawdown = _drawdown_pct(starting, equity)
    session_pnl = float(account.realized_pnl) + float(account.unrealized_pnl)
    daily_loss = max(0.0, -session_pnl)
    consecutive = _consecutive_losses(learning.recent_outcomes)
    feed_age = _feed_age_sec(marks, feeds)

    thr = CircuitBreakerThresholds(
        max_drawdown_pct=float(engine.config.max_drawdown_pct),
        quote_stale_threshold_sec=float(engine.config.quote_stale_threshold_sec),
    )
    breakers = evaluate_circuit_breakers(
        drawdown_pct=drawdown,
        daily_loss_inr=daily_loss,
        equity_inr=max(equity, starting),
        consecutive_losses=consecutive,
        feed_age_sec=feed_age,
        thresholds=thr,
    )
    breaker_dicts = [b.as_dict() for b in breakers]
    active = active_breaker_ids(breakers)

    greeks = _portfolio_greeks(open_positions)
    greek_thr = GreeksLimitThresholds(
        max_abs_total_delta=float(engine.config.max_abs_total_delta),
        max_abs_total_gamma=float(engine.config.max_abs_total_gamma),
        max_abs_total_vega=float(engine.config.max_abs_total_vega),
        min_total_theta=float(engine.config.min_total_theta),
    )
    greek_check = check_greeks_limits(
        total_delta=greeks["total_delta"],
        total_gamma=greeks["total_gamma"],
        total_vega=greeks["total_vega"],
        total_theta=greeks["total_theta"],
        thresholds=greek_thr,
    )
    greek_rows = _greek_rows(greeks, greek_thr)

    decided = [
        o
        for o in learning.recent_outcomes
        if str(getattr(getattr(o, "outcome", None), "value", o.outcome)) in ("win", "loss")
    ]
    wins = sum(
        1
        for o in decided
        if str(getattr(getattr(o, "outcome", None), "value", o.outcome)) == "win"
    )
    win_rate = (wins / len(decided)) if decided else float(learning.win_rate or 0.0)

    return {
        "as_of": _now().isoformat(),
        "equity_inr": round(equity, 2),
        "starting_capital_inr": round(starting, 2),
        "reserved_margin_inr": round(float(account.reserved_margin_inr), 2),
        "cash_inr": round(float(account.cash_inr), 2),
        "realized_pnl": round(float(account.realized_pnl), 2),
        "unrealized_pnl": round(float(account.unrealized_pnl), 2),
        "session_pnl": round(session_pnl, 2),
        "daily_pnl": round(session_pnl, 2),
        "drawdown_pct": round(drawdown, 2),
        "win_rate": round(float(win_rate), 4),
        "open_positions": int(account.open_positions),
        "portfolio_greeks": greeks,
        "greek_limits": greek_rows,
        "greeks_within_limits": bool(greek_check.passed),
        "greeks_failures": list(greek_check.failures),
        "circuit_breakers": breaker_dicts,
        "circuit_breakers_active": active,
        "feed_age_sec": feed_age,
        "events": _risk_events(
            breakers=breaker_dicts,
            freeze_reason=learning.freeze_reason,
            greeks_passed=bool(greek_check.passed),
            account_updated_at=account.updated_at,
            open_positions=int(account.open_positions),
        ),
        "shared_kill_conditions": list(SHARED_KILL_CONDITIONS),
        "limits": {
            "max_drawdown_pct": thr.max_drawdown_pct,
            "max_daily_loss_pct": thr.max_daily_loss_pct,
            "max_consecutive_losses": thr.max_consecutive_losses,
            "quote_stale_threshold_sec": thr.quote_stale_threshold_sec,
            "max_abs_total_delta": greek_thr.max_abs_total_delta,
            "max_abs_total_gamma": greek_thr.max_abs_total_gamma,
            "max_abs_total_vega": greek_thr.max_abs_total_vega,
            "min_total_theta": greek_thr.min_total_theta,
        },
    }


def bot_metrics_from_risk() -> dict[str, Any]:
    """Subset used by GET /api/v1/bot/status so SituationalBar stays live."""
    snap = build_risk_snapshot()
    return {
        "daily_pnl": snap["daily_pnl"],
        "win_rate": snap["win_rate"],
        "drawdown_pct": snap["drawdown_pct"],
        "portfolio_greeks": snap["portfolio_greeks"],
        "circuit_breakers_active": snap["circuit_breakers_active"],
    }
