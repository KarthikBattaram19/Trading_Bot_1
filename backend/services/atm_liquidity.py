"""ATM liquidity metrics and relative volume/OI gates (Part T T13–T16)."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Sequence

ATM_HISTORY_TOO_SHORT = "ATM_HISTORY_TOO_SHORT"
ATM_VOLUME_BELOW_AVG_RATIO = "ATM_VOLUME_BELOW_AVG_RATIO"
ATM_OI_BELOW_AVG_RATIO = "ATM_OI_BELOW_AVG_RATIO"
ATM_SPREAD_TOO_WIDE = "ATM_SPREAD_TOO_WIDE"
ATM_ABS_FLOOR_FAIL = "ATM_ABS_FLOOR_FAIL"
ATM_LIQUIDITY_DATA_MISSING = "ATM_LIQUIDITY_DATA_MISSING"


@dataclass(frozen=True)
class AtmSideMarks:
    volume: int
    open_interest: int
    bid: float
    ask: float


@dataclass(frozen=True)
class AtmLiquidityLive:
    ce: AtmSideMarks | None
    pe: AtmSideMarks | None


@dataclass(frozen=True)
class AtmHistoryPoint:
    session_date: str
    atm_volume: int
    atm_oi: int


@dataclass(frozen=True)
class AtmLiquidityResult:
    liquidity_ok: bool
    atm_volume: int
    atm_oi: int
    spread_pct: float
    history_days: int
    avg_vol: float | None
    avg_oi: float | None
    volume_vs_avg: float | None
    oi_vs_avg: float | None
    reason_codes: list[str] = field(default_factory=list)
    abs_volume_ok: bool = False
    rel_volume_ok: bool = False
    abs_oi_ok: bool = False
    rel_oi_ok: bool = False
    spread_ok: bool = False


def spread_pct(bid: float, ask: float) -> float | None:
    if bid is None or ask is None:
        return None
    if bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return (ask - bid) / mid * 100.0


def aggregate_atm_volume_oi(live: AtmLiquidityLive) -> tuple[int | None, int | None]:
    if live.ce is None or live.pe is None:
        return None, None
    if live.ce.volume <= 0 or live.pe.volume <= 0:
        return None, None
    if live.ce.open_interest <= 0 or live.pe.open_interest <= 0:
        return None, None
    return min(live.ce.volume, live.pe.volume), min(live.ce.open_interest, live.pe.open_interest)


def aggregate_spread_pct(live: AtmLiquidityLive) -> float | None:
    if live.ce is None or live.pe is None:
        return None
    ce_sp = spread_pct(live.ce.bid, live.ce.ask)
    pe_sp = spread_pct(live.pe.bid, live.pe.ask)
    if ce_sp is None or pe_sp is None:
        return None
    return max(ce_sp, pe_sp)


def evaluate_atm_liquidity(
    *,
    live: AtmLiquidityLive,
    prior: Sequence[AtmHistoryPoint],
    min_volume: int,
    min_open_interest: int,
    max_spread_pct: float,
    volume_vs_avg_min_ratio: float,
    oi_vs_avg_min_ratio: float,
    lookback_days: int = 20,
    min_history_days: int = 10,
) -> AtmLiquidityResult:
    vol, oi = aggregate_atm_volume_oi(live)
    sp = aggregate_spread_pct(live)
    reasons: list[str] = []

    if vol is None or oi is None or sp is None:
        return AtmLiquidityResult(
            liquidity_ok=False,
            atm_volume=int(vol or 0),
            atm_oi=int(oi or 0),
            spread_pct=float(sp if sp is not None else 99.0),
            history_days=0,
            avg_vol=None,
            avg_oi=None,
            volume_vs_avg=None,
            oi_vs_avg=None,
            reason_codes=[ATM_LIQUIDITY_DATA_MISSING],
        )

    prior_sorted = sorted(prior, key=lambda p: p.session_date)[-lookback_days:]
    n = len(prior_sorted)
    avg_vol = mean(p.atm_volume for p in prior_sorted) if n else None
    avg_oi = mean(p.atm_oi for p in prior_sorted) if n else None

    abs_volume_ok = vol >= min_volume
    abs_oi_ok = oi >= min_open_interest
    spread_ok = sp < max_spread_pct

    rel_volume_ok = (
        n >= min_history_days
        and avg_vol is not None
        and avg_vol > 0
        and vol > volume_vs_avg_min_ratio * avg_vol
    )
    rel_oi_ok = (
        n >= min_history_days
        and avg_oi is not None
        and avg_oi > 0
        and oi > oi_vs_avg_min_ratio * avg_oi
    )

    volume_vs_avg = (vol / avg_vol) if avg_vol and avg_vol > 0 else None
    oi_vs_avg = (oi / avg_oi) if avg_oi and avg_oi > 0 else None

    if n < min_history_days:
        reasons.append(ATM_HISTORY_TOO_SHORT)
    if not abs_volume_ok or not abs_oi_ok:
        reasons.append(ATM_ABS_FLOOR_FAIL)
    if n >= min_history_days and not rel_volume_ok:
        reasons.append(ATM_VOLUME_BELOW_AVG_RATIO)
    if n >= min_history_days and not rel_oi_ok:
        reasons.append(ATM_OI_BELOW_AVG_RATIO)
    if not spread_ok:
        reasons.append(ATM_SPREAD_TOO_WIDE)

    liquidity_ok = abs_volume_ok and abs_oi_ok and rel_volume_ok and rel_oi_ok and spread_ok
    return AtmLiquidityResult(
        liquidity_ok=liquidity_ok,
        atm_volume=vol,
        atm_oi=oi,
        spread_pct=sp,
        history_days=n,
        avg_vol=avg_vol,
        avg_oi=avg_oi,
        volume_vs_avg=volume_vs_avg,
        oi_vs_avg=oi_vs_avg,
        reason_codes=reasons,
        abs_volume_ok=abs_volume_ok,
        rel_volume_ok=rel_volume_ok,
        abs_oi_ok=abs_oi_ok,
        rel_oi_ok=rel_oi_ok,
        spread_ok=spread_ok,
    )


def live_from_aggregated(
    *,
    volume: int,
    open_interest: int,
    spread_pct_value: float,
) -> AtmLiquidityLive:
    """Demo/stub helper: synthesize symmetric CE/PE sides from aggregates."""
    # Reconstruct a tight bid/ask around mid=100 that yields spread_pct_value.
    mid = 100.0
    half = mid * (spread_pct_value / 100.0) / 2.0
    bid = mid - half
    ask = mid + half
    side = AtmSideMarks(volume=volume, open_interest=open_interest, bid=bid, ask=ask)
    return AtmLiquidityLive(ce=side, pe=side)
