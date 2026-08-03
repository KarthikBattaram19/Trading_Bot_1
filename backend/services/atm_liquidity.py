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
# §3.2 fix: below atm_history_min_days of logged history, the relative gates
# fall back to a same-session chain-relative comparison (ATM vs. its near-ATM
# peer strikes) instead of forcing an automatic fail. This code is attached
# (pass or fail) whenever that fallback basis was used, so callers/audits can
# tell it apart from the steady-state temporal-average basis.
ATM_CHAIN_RELATIVE_MODE = "ATM_CHAIN_RELATIVE_MODE"
# Fallback engaged (history too short) but no usable near-ATM peer strikes
# were available either — relative gates cannot be evaluated on any basis.
ATM_CHAIN_RELATIVE_DATA_MISSING = "ATM_CHAIN_RELATIVE_DATA_MISSING"


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
    # "temporal" (n >= min_history_days, avg = this expiry's own prior sessions)
    # or "chain_relative" (n < min_history_days, avg = same-session near-ATM
    # peer strikes — §3.2 cold-start fallback).
    relative_basis: str = "temporal"


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
    near_atm_volume_median: float | None = None,
    near_atm_oi_median: float | None = None,
    chain_relative_min_ratio: float = 1.0,
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
    temporal_avg_vol = mean(p.atm_volume for p in prior_sorted) if n else None
    temporal_avg_oi = mean(p.atm_oi for p in prior_sorted) if n else None

    abs_volume_ok = vol >= min_volume
    abs_oi_ok = oi >= min_open_interest
    spread_ok = sp < max_spread_pct

    if n >= min_history_days:
        # Steady state: this expiry has its own trading history — compare
        # today against its own rolling average (T13b/T14b).
        relative_basis = "temporal"
        avg_vol, avg_oi = temporal_avg_vol, temporal_avg_oi
        rel_volume_ok = (
            avg_vol is not None and avg_vol > 0 and vol > volume_vs_avg_min_ratio * avg_vol
        )
        rel_oi_ok = avg_oi is not None and avg_oi > 0 and oi > oi_vs_avg_min_ratio * avg_oi
    else:
        # §3.2 cold-start fallback: a brand-new expiry has no prior sessions
        # of its own, so compare ATM against its same-session near-ATM peer
        # strikes instead of forcing an automatic fail (see
        # backend/services/universe_enrichment.py:_near_atm_peer_medians).
        relative_basis = "chain_relative"
        reasons.append(ATM_HISTORY_TOO_SHORT)
        reasons.append(ATM_CHAIN_RELATIVE_MODE)
        avg_vol, avg_oi = near_atm_volume_median, near_atm_oi_median
        rel_volume_ok = (
            avg_vol is not None and avg_vol > 0 and vol > chain_relative_min_ratio * avg_vol
        )
        rel_oi_ok = avg_oi is not None and avg_oi > 0 and oi > chain_relative_min_ratio * avg_oi
        if avg_vol is None and avg_oi is None:
            reasons.append(ATM_CHAIN_RELATIVE_DATA_MISSING)

    volume_vs_avg = (vol / avg_vol) if avg_vol and avg_vol > 0 else None
    oi_vs_avg = (oi / avg_oi) if avg_oi and avg_oi > 0 else None

    if not abs_volume_ok or not abs_oi_ok:
        reasons.append(ATM_ABS_FLOOR_FAIL)
    if not rel_volume_ok:
        reasons.append(ATM_VOLUME_BELOW_AVG_RATIO)
    if not rel_oi_ok:
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
        relative_basis=relative_basis,
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
