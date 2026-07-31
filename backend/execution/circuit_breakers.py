"""Portfolio circuit breakers (architecture §11.4.1).

Evaluates live paper-sim / learning state against non-negotiable ceilings.
Full auto-pause wiring is Phase 2.4; this module surfaces status for the
risk dashboard and bot status.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

BreakerTone = Literal["safe", "warn", "danger"]


@dataclass(frozen=True, slots=True)
class CircuitBreakerThresholds:
    """§11.4.1 defaults — adjustable later via configuration blobs."""

    max_daily_loss_pct: float = 2.0
    max_drawdown_pct: float = 10.0
    max_consecutive_losses: int = 5
    quote_stale_threshold_sec: float = 60.0
    warn_utilization_pct: float = 80.0


@dataclass(frozen=True, slots=True)
class BreakerStatus:
    id: str
    name: str
    current: float
    limit: float
    unit: str
    pct: float
    tone: BreakerTone
    detail: str | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "current": self.current,
            "limit": self.limit,
            "unit": self.unit,
            "pct": round(self.pct, 1),
            "tone": self.tone,
            "detail": self.detail,
        }


def _tone(pct: float, *, warn_at: float) -> BreakerTone:
    if pct >= 100.0:
        return "danger"
    if pct >= warn_at:
        return "warn"
    return "safe"


def _pct(current: float, limit: float) -> float:
    if not isfinite(current) or not isfinite(limit) or limit <= 0:
        return 0.0
    return max(0.0, min(999.0, (current / limit) * 100.0))


def evaluate_circuit_breakers(
    *,
    drawdown_pct: float,
    daily_loss_inr: float,
    equity_inr: float,
    consecutive_losses: int,
    feed_age_sec: float | None,
    thresholds: CircuitBreakerThresholds | None = None,
) -> tuple[BreakerStatus, ...]:
    """Return ordered breaker cards for the risk dashboard."""
    thr = thresholds or CircuitBreakerThresholds()
    daily_limit = max(0.0, float(equity_inr) * (thr.max_daily_loss_pct / 100.0))
    loss_abs = max(0.0, float(daily_loss_inr))
    age = float(feed_age_sec) if feed_age_sec is not None and isfinite(feed_age_sec) else 0.0

    return (
        BreakerStatus(
            id="max_drawdown",
            name="Max Drawdown",
            current=round(float(drawdown_pct), 2),
            limit=float(thr.max_drawdown_pct),
            unit="pct",
            pct=_pct(float(drawdown_pct), thr.max_drawdown_pct),
            tone=_tone(_pct(float(drawdown_pct), thr.max_drawdown_pct), warn_at=thr.warn_utilization_pct),
            detail=f"Circuit at ≤ {thr.max_drawdown_pct:.0f}% equity (§2.2 / §11.4.1)",
        ),
        BreakerStatus(
            id="max_daily_loss",
            name="Max Daily Loss",
            current=round(loss_abs, 2),
            limit=round(daily_limit, 2),
            unit="inr",
            pct=_pct(loss_abs, daily_limit) if daily_limit > 0 else 0.0,
            tone=_tone(
                _pct(loss_abs, daily_limit) if daily_limit > 0 else 0.0,
                warn_at=thr.warn_utilization_pct,
            ),
            detail=f"{thr.max_daily_loss_pct:.0f}% of equity (§11.4.1)",
        ),
        BreakerStatus(
            id="consecutive_losses",
            name="Consecutive Losses",
            current=float(max(0, int(consecutive_losses))),
            limit=float(thr.max_consecutive_losses),
            unit="count",
            pct=_pct(float(consecutive_losses), float(thr.max_consecutive_losses)),
            tone=_tone(
                _pct(float(consecutive_losses), float(thr.max_consecutive_losses)),
                warn_at=thr.warn_utilization_pct,
            ),
            detail=f"Pause discretionary entries at {thr.max_consecutive_losses} (§11.4.1)",
        ),
        BreakerStatus(
            id="feed_staleness",
            name="Feed Staleness",
            current=round(age, 3),
            limit=float(thr.quote_stale_threshold_sec),
            unit="sec",
            pct=_pct(age, thr.quote_stale_threshold_sec),
            tone=_tone(_pct(age, thr.quote_stale_threshold_sec), warn_at=thr.warn_utilization_pct),
            detail=f"Quote stale threshold {thr.quote_stale_threshold_sec:.0f}s",
        ),
    )


def active_breaker_ids(breakers: tuple[BreakerStatus, ...] | list[BreakerStatus]) -> list[str]:
    """Ids currently in warn/danger (plus callers may append kill_switch)."""
    return [b.id for b in breakers if b.tone in ("warn", "danger")]
