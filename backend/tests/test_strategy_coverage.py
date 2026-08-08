"""Unit tests for per-strategy coverage gate."""

from __future__ import annotations

import pytest

from backend.models.recommendations import StrategyType
from backend.services.quant_snapshot import QuantSnapshot, SignalField
from backend.services.strategy_coverage import evaluate_strategy_coverage



def _sf(value, usable: bool = True, reason: str | None = None) -> SignalField:
    return SignalField(value=value, usable=usable, reason=reason)


def _snap(
    symbol: str,
    *,
    live: bool = True,
    garch_ok: bool = True,
    iv_ok: bool = True,
    iv_z_ok: bool = False,
    rv_ok: bool = False,
    earnings_ok: bool = False,
    days_to_earnings: int | None = None,
    garch_distorted: bool = False,
) -> QuantSnapshot:
    return QuantSnapshot(
        symbol=symbol,
        marks_live=live,
        und_price=_sf(100.0, live),
        iv_annualized=_sf(0.22 if iv_ok else None, iv_ok, None if iv_ok else "missing_iv"),
        garch_forecast=_sf(
            0.28 if garch_ok else None,
            garch_ok and not garch_distorted,
            None if garch_ok else "insufficient_history",
        ),
        garch_distorted=garch_distorted,
        iv_z_score=_sf(-2.1 if iv_z_ok else None, iv_z_ok, None if iv_z_ok else "insufficient_iv_history"),
        realized_vol_intraday=_sf(0.02 if rv_ok else None, rv_ok, None if rv_ok else "missing_rv"),
        days_to_earnings=_sf(
            days_to_earnings if earnings_ok else None,
            earnings_ok,
            None if earnings_ok else "no_calendar_row",
        ),
        atm_premium_inr=50.0,
        volume=5000,
        open_interest=25000,
        spread_pct=0.4,
        dte=21,
        price_history=[100.0 + i * 0.1 for i in range(30)] if garch_ok else [100.0],
        expiry_key="2026-03-28",
    )


def test_coverage_fails_when_ratio_below_80():
    # 79 eligible of 100 → 0.79 < 0.80
    snaps = [_snap(f"S{i}", iv_z_ok=True, rv_ok=True) for i in range(79)]
    snaps += [_snap(f"B{i}", live=False, garch_ok=False, iv_ok=False) for i in range(21)]
    report = evaluate_strategy_coverage(snaps, scanned=100, cfg={
        "strategy_coverage": {"min_coverage_ratio": 0.80},
    })
    simple = report.by_strategy[StrategyType.simple_volatility]
    assert simple.eligible == 79
    assert simple.published is False
    assert StrategyType.simple_volatility not in report.available_strategies


def test_coverage_passes_at_80_percent_above_derived_floor():
    snaps = [_snap(f"S{i}", iv_z_ok=True, rv_ok=True) for i in range(80)]
    snaps += [_snap(f"B{i}", live=False, garch_ok=False, iv_ok=False) for i in range(20)]
    report = evaluate_strategy_coverage(snaps, scanned=100, cfg={
        "strategy_coverage": {"min_coverage_ratio": 0.80},
    })
    assert report.by_strategy[StrategyType.simple_volatility].published is True
    assert StrategyType.simple_volatility in report.available_strategies


def test_truncated_scan_cannot_publish_on_a_perfect_ratio():
    """The absolute floor is derived from the FULL scan cap (default-derived
    cap 20 → floor 16), so a budget-truncated cycle that only scanned 12
    symbols cannot publish on 12/12 = 100% — the exact hole a config-tunable
    floor used to open."""
    snaps = [_snap(f"S{i}", iv_z_ok=True, rv_ok=True) for i in range(12)]
    report = evaluate_strategy_coverage(snaps, scanned=12, cfg={
        "strategy_coverage": {"min_coverage_ratio": 0.80},
    })
    simple = report.by_strategy[StrategyType.simple_volatility]
    assert simple.eligible == 12
    assert simple.coverage == pytest.approx(1.0)
    assert simple.published is False


def test_vega_requires_iv_z():
    snaps = [_snap(f"S{i}", iv_z_ok=False) for i in range(80)]
    report = evaluate_strategy_coverage(snaps, scanned=80, cfg={
        "strategy_coverage": {"min_coverage_ratio": 0.80},
    })
    assert report.by_strategy[StrategyType.simple_volatility].published is True
    assert report.by_strategy[StrategyType.vega_scalping].published is False


def test_gamma_earnings_gap_without_garch_when_dte_leq_1():
    snaps = [
        _snap(
            f"S{i}",
            garch_ok=False,
            earnings_ok=True,
            days_to_earnings=1,
        )
        for i in range(80)
    ]
    report = evaluate_strategy_coverage(snaps, scanned=80, cfg={
        "strategy_coverage": {"min_coverage_ratio": 0.80},
    })
    assert report.by_strategy[StrategyType.gamma_scalping].published is True


def test_warning_lines_on_abort():
    snaps = [_snap("ONLY")]
    report = evaluate_strategy_coverage(snaps, scanned=1, cfg={
        "strategy_coverage": {"min_coverage_ratio": 0.80},
    })
    assert any("STRATEGY_COVERAGE_ABORT" in w for w in report.warnings)


def test_coverage_uses_attempted_denominator_under_enrichment_cap():
    """Bounded enrich (e.g. 40 of 213) must score coverage against attempted, not full universe."""
    # 32 eligible of 40 attempted → 80%, above the derived floor (16 at default inputs).
    snaps = [_snap(f"S{i}", iv_z_ok=True, rv_ok=True) for i in range(32)]
    snaps += [_snap(f"B{i}", live=False, garch_ok=False, iv_ok=False) for i in range(181)]
    report = evaluate_strategy_coverage(
        snaps,
        scanned=40,  # enrichment max_symbols / attempted
        cfg={
            "strategy_coverage": {"min_coverage_ratio": 0.80},
        },
    )
    simple = report.by_strategy[StrategyType.simple_volatility]
    assert simple.eligible == 32
    assert simple.coverage == pytest.approx(0.8)
    assert simple.published is True
    assert StrategyType.simple_volatility in report.available_strategies


def test_coverage_still_aborts_when_denominator_is_full_universe():
    """If scanned stays at full G11 size, 32/213 cannot publish on ratio even though 32 > the floor."""
    snaps = [_snap(f"S{i}", iv_z_ok=True, rv_ok=True) for i in range(32)]
    snaps += [_snap(f"B{i}", live=False, garch_ok=False, iv_ok=False) for i in range(181)]
    report = evaluate_strategy_coverage(
        snaps,
        scanned=213,
        cfg={
            "strategy_coverage": {"min_coverage_ratio": 0.80},
        },
    )
    assert report.by_strategy[StrategyType.simple_volatility].published is False

