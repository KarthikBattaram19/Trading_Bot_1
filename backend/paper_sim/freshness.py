"""Fresh-marks gate for paper_sim (Architecture §8.6–8.9, edge case MD-01).

Rejects paper fills / MTM when ICICI Direct LTP age exceeds the configured
``stale_threshold_sec``, or when a tick is explicitly flagged ``stale``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from backend.integrations.icici_direct.models import NormalizedTick
from backend.paper_sim.ledger import PaperLedgerError


class StaleMarksError(PaperLedgerError):
    """Raised when required marks are missing or older than the freshness gate."""


@dataclass
class MarkFreshnessDetail:
    symbol: str
    exchange: str
    provider_symbol_id: str
    ltp: float
    age_sec: float | None
    threshold_sec: float
    stale: bool
    reason: str | None = None


@dataclass
class MarksFreshnessReport:
    """Result of evaluating one or more ticks against the fresh-marks gate."""

    ok: bool
    checked_at: datetime
    details: list[MarkFreshnessDetail] = field(default_factory=list)
    blocked_symbols: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "checked_at": self.checked_at.isoformat(),
            "blocked_symbols": list(self.blocked_symbols),
            "details": [
                {
                    "symbol": d.symbol,
                    "exchange": d.exchange,
                    "provider_symbol_id": d.provider_symbol_id,
                    "ltp": d.ltp,
                    "age_sec": d.age_sec,
                    "threshold_sec": d.threshold_sec,
                    "stale": d.stale,
                    "reason": d.reason,
                }
                for d in self.details
            ],
        }


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def tick_age_sec(tick: NormalizedTick, *, now: datetime | None = None) -> float | None:
    """Seconds since tick timestamp; ``None`` if timestamp is missing."""
    ts = tick.ts
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (_now(now) - ts.astimezone(timezone.utc)).total_seconds())


def threshold_for_leg(
    *,
    exchange: str,
    is_option: bool,
    quote_stale_threshold_sec: float,
    option_stale_threshold_sec: float,
) -> float:
    """Quote (cash/underlying) vs option-chain thresholds from Architecture §8.2."""
    if is_option or exchange.upper() == "NFO":
        return float(option_stale_threshold_sec)
    return float(quote_stale_threshold_sec)


def evaluate_tick(
    tick: NormalizedTick,
    *,
    threshold_sec: float,
    now: datetime | None = None,
) -> MarkFreshnessDetail:
    age = tick_age_sec(tick, now=now)
    reason: str | None = None
    stale = False

    if tick.ltp is None or float(tick.ltp) <= 0:
        stale = True
        reason = "missing_or_invalid_ltp"
    elif tick.stale:
        stale = True
        reason = "tick_flagged_stale"
    elif age is None:
        stale = True
        reason = "missing_timestamp"
    elif age > threshold_sec:
        stale = True
        reason = f"age_{age:.1f}s_exceeds_{threshold_sec:.0f}s"

    return MarkFreshnessDetail(
        symbol=tick.symbol,
        exchange=tick.exchange,
        provider_symbol_id=tick.provider_symbol_id,
        ltp=float(tick.ltp or 0),
        age_sec=age,
        threshold_sec=float(threshold_sec),
        stale=stale,
        reason=reason,
    )


def evaluate_marks(
    ticks: Iterable[tuple[NormalizedTick, float]],
    *,
    now: datetime | None = None,
) -> MarksFreshnessReport:
    """
    Evaluate ticks against per-leg thresholds.

    ``ticks`` items are ``(NormalizedTick, threshold_sec)``.
    """
    checked = _now(now)
    details: list[MarkFreshnessDetail] = []
    blocked: list[str] = []
    for tick, threshold in ticks:
        detail = evaluate_tick(tick, threshold_sec=threshold, now=checked)
        details.append(detail)
        if detail.stale:
            blocked.append(detail.symbol)
    return MarksFreshnessReport(
        ok=len(blocked) == 0,
        checked_at=checked,
        details=details,
        blocked_symbols=blocked,
    )


def assert_marks_fresh(
    ticks: Iterable[tuple[NormalizedTick, float]],
    *,
    now: datetime | None = None,
) -> MarksFreshnessReport:
    """Raise ``StaleMarksError`` (MD-01 / PS-03) when any required mark fails the gate."""
    report = evaluate_marks(ticks, now=now)
    if report.ok:
        return report
    reasons = ", ".join(
        f"{d.symbol} ({d.reason})" for d in report.details if d.stale
    )
    raise StaleMarksError(
        f"fresh marks gate blocked paper action — stale/missing: {reasons}"
    )


def instrument_master_age_sec(
    loaded_at: datetime | None, *, now: datetime | None = None
) -> float | None:
    if loaded_at is None:
        return None
    ts = loaded_at if loaded_at.tzinfo else loaded_at.replace(tzinfo=timezone.utc)
    return max(0.0, (_now(now) - ts.astimezone(timezone.utc)).total_seconds())


def assert_instrument_master_fresh(
    loaded_at: datetime | None,
    *,
    max_age_sec: float,
    now: datetime | None = None,
) -> float | None:
    """MD-11: reject unresolved / stale scrip master beyond daily refresh window."""
    if loaded_at is None:
        raise StaleMarksError("instrument master not loaded — refresh scrip master first")
    age = instrument_master_age_sec(loaded_at, now=now)
    assert age is not None
    if age > max_age_sec:
        raise StaleMarksError(
            f"instrument master stale — age {age:.0f}s exceeds max {max_age_sec:.0f}s"
        )
    return age
