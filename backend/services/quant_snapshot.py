"""Shared quant snapshot — live-clean signals for recommendations / SH-4."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from backend.quant.signals.garch import forecast_garch_11, log_returns_from_prices
from backend.quant.signals.iv_zscore import compute_iv_zscore
from backend.services.universe_enrichment import LiveMarks


@dataclass(frozen=True, slots=True)
class SignalField:
    value: float | int | None
    usable: bool
    reason: str | None = None


@dataclass
class QuantSnapshot:
    """Per-symbol quant packet with explicit usability flags."""

    symbol: str
    marks_live: bool
    und_price: SignalField
    iv_annualized: SignalField
    garch_forecast: SignalField
    garch_distorted: bool
    iv_z_score: SignalField
    realized_vol_intraday: SignalField
    days_to_earnings: SignalField
    atm_premium_inr: float
    volume: int
    open_interest: int
    spread_pct: float
    dte: int
    price_history: list[float] = field(default_factory=list)
    expiry_key: str | None = None
    atm_strike: float | None = None
    near_atm_volume_median: float | None = None
    near_atm_oi_median: float | None = None


def _flat_or_short(history: list[float], min_obs: int) -> bool:
    if len(history) < min_obs + 1:
        return True
    if not history:
        return True
    # Constant series cannot produce usable GARCH returns.
    return max(history) - min(history) < 1e-12


def build_quant_snapshot(
    *,
    marks: LiveMarks | None,
    price_history_daily: list[float],
    iv_series_intraday: list[float],
    days_to_earnings: int | None,
    cfg: dict[str, Any],
    realized_vol_intraday: float | None = None,
    symbol: str | None = None,
) -> QuantSnapshot:
    """Build a snapshot from live marks + real history series (no synthetic fills)."""
    gcfg = cfg.get("garch_forecast") or {}
    zcfg = cfg.get("iv_zscore") or {}
    min_obs = int(gcfg.get("min_observations", 20))

    if marks is None:
        missing = SignalField(None, False, "no_live_marks")
        return QuantSnapshot(
            symbol=(symbol or "").upper(),
            marks_live=False,
            und_price=missing,
            iv_annualized=missing,
            garch_forecast=SignalField(None, False, "no_live_marks"),
            garch_distorted=True,
            iv_z_score=SignalField(None, False, "no_live_marks"),
            realized_vol_intraday=SignalField(None, False, "no_live_marks"),
            days_to_earnings=SignalField(None, False, "no_live_marks"),
            atm_premium_inr=0.0,
            volume=0,
            open_interest=0,
            spread_pct=99.0,
            dte=0,
            price_history=list(price_history_daily),
        )

    iv_ok = marks.iv_annualized > 0 and not math.isnan(marks.iv_annualized)
    iv_field = SignalField(
        marks.iv_annualized if iv_ok else None,
        iv_ok,
        None if iv_ok else "missing_iv",
    )
    und_ok = marks.und_price > 0
    und_field = SignalField(
        marks.und_price if und_ok else None,
        und_ok,
        None if und_ok else "missing_spot",
    )

    history = [float(x) for x in price_history_daily if x is not None and float(x) > 0]
    if _flat_or_short(history, min_obs):
        garch_field = SignalField(None, False, "insufficient_or_flat_history")
        garch_distorted = True
    else:
        result = forecast_garch_11(
            log_returns_from_prices(history),
            gamma=float(gcfg.get("gamma_weight", 0.05)),
            alpha=float(gcfg.get("alpha_weight", 0.05)),
            beta=float(gcfg.get("beta_weight", 0.9)),
            annualization_factor=int(gcfg.get("annualization_factor", 252)),
            min_observations=min_obs,
            fit_weights=bool(gcfg.get("enable_mle_fit", True)),
            fit_min_observations=int(gcfg.get("fit_min_observations", 60)),
        )
        if result.usable and result.sigma_annual is not None and not result.garch_distorted:
            garch_field = SignalField(float(result.sigma_annual), True, None)
            garch_distorted = False
        else:
            garch_field = SignalField(
                float(result.sigma_annual) if result.sigma_annual is not None else None,
                False,
                result.reason or "garch_unusable",
            )
            garch_distorted = True

    z_result = compute_iv_zscore(
        iv_series_intraday,
        current_iv=marks.iv_annualized if iv_ok else None,
        min_observations=int(zcfg.get("min_observations", 5)),
        entry_z_threshold=float(zcfg.get("entry_z_threshold", -2.0)),
    )
    iv_z_field = SignalField(
        z_result.iv_z_score if z_result.usable else None,
        z_result.usable,
        None if z_result.usable else (z_result.reason or "iv_z_unusable"),
    )

    if realized_vol_intraday is not None and realized_vol_intraday > 0:
        rv_field = SignalField(float(realized_vol_intraday), True, None)
    else:
        rv_field = SignalField(None, False, "missing_rv")

    if days_to_earnings is not None:
        earn_field = SignalField(int(days_to_earnings), True, None)
    else:
        earn_field = SignalField(None, False, "no_calendar_row")

    return QuantSnapshot(
        symbol=marks.symbol.upper(),
        marks_live=True,
        und_price=und_field,
        iv_annualized=iv_field,
        garch_forecast=garch_field,
        garch_distorted=garch_distorted,
        iv_z_score=iv_z_field,
        realized_vol_intraday=rv_field,
        days_to_earnings=earn_field,
        atm_premium_inr=float(marks.atm_premium_inr),
        volume=int(marks.volume),
        open_interest=int(marks.open_interest),
        spread_pct=float(marks.spread_pct),
        dte=int(marks.dte),
        price_history=history,
        expiry_key=str(marks.expiry) if marks.expiry else None,
        atm_strike=marks.atm_strike,
        near_atm_volume_median=marks.near_atm_volume_median,
        near_atm_oi_median=marks.near_atm_oi_median,
    )


def snapshot_to_candidate_fields(snap: QuantSnapshot) -> dict[str, Any]:
    """Map QuantSnapshot → InstrumentCandidate kwargs (partial)."""
    return {
        "und_price": float(snap.und_price.value or 0.0),
        "iv_annualized": float(snap.iv_annualized.value or 0.0),
        "garch_forecast": float(snap.garch_forecast.value or 0.0),
        "iv_z_score": float(snap.iv_z_score.value) if snap.iv_z_score.usable else None,
        "days_to_earnings": (
            int(snap.days_to_earnings.value)
            if snap.days_to_earnings.usable and snap.days_to_earnings.value is not None
            else None
        ),
        "atm_premium_inr": snap.atm_premium_inr,
        "volume": snap.volume,
        "open_interest": snap.open_interest,
        "spread_pct": snap.spread_pct,
        "dte": snap.dte,
        "realized_vol_intraday": (
            float(snap.realized_vol_intraday.value)
            if snap.realized_vol_intraday.usable
            else None
        ),
        "garch_distorted": snap.garch_distorted or not snap.garch_forecast.usable,
        "price_history": list(snap.price_history) or [1.0],
        "expiry_key": snap.expiry_key,
        "marks_source": "live" if snap.marks_live else "stub",
        "near_atm_volume_median": snap.near_atm_volume_median,
        "near_atm_oi_median": snap.near_atm_oi_median,
    }
