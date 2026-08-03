from backend.services.atm_liquidity import (
    ATM_CHAIN_RELATIVE_DATA_MISSING,
    ATM_CHAIN_RELATIVE_MODE,
    ATM_HISTORY_TOO_SHORT,
    ATM_SPREAD_TOO_WIDE,
    AtmHistoryPoint,
    AtmLiquidityLive,
    AtmSideMarks,
    evaluate_atm_liquidity,
)


def _side(vol, oi, bid, ask):
    return AtmSideMarks(volume=vol, open_interest=oi, bid=bid, ask=ask)


def _live(vol=3000, oi=25000, bid=99.0, ask=99.4):
    s = _side(vol, oi, bid, ask)
    return AtmLiquidityLive(ce=s, pe=s)


def _prior(n, vol=2000, oi=20000):
    return [
        AtmHistoryPoint(session_date=f"2026-01-{i + 1:02d}", atm_volume=vol, atm_oi=oi)
        for i in range(n)
    ]


def _eval(live, prior, **over):
    kw = dict(
        live=live,
        prior=prior,
        min_volume=2000,
        min_open_interest=20000,
        max_spread_pct=0.5,
        volume_vs_avg_min_ratio=1.5,
        oi_vs_avg_min_ratio=1.3,
    )
    kw.update(over)
    return evaluate_atm_liquidity(**kw)


def test_passes_when_hot_vs_average_and_tight_spread():
    live = _live(vol=3001, oi=26001, bid=100.0, ask=100.4)
    r = _eval(live, _prior(10, vol=2000, oi=20000))
    assert r.liquidity_ok is True
    assert r.history_days == 10
    assert r.abs_volume_ok and r.rel_volume_ok and r.abs_oi_ok and r.rel_oi_ok and r.spread_ok


def test_fails_at_exact_ratio_boundary():
    live = _live(vol=3000, oi=26000, bid=100.0, ask=100.4)
    r = _eval(live, _prior(10, vol=2000, oi=20000))
    assert r.rel_volume_ok is False
    assert r.liquidity_ok is False


def test_fails_when_history_shorter_than_10():
    r = _eval(_live(vol=5000, oi=50000), _prior(9))
    assert r.rel_volume_ok is False
    assert ATM_HISTORY_TOO_SHORT in r.reason_codes
    assert r.liquidity_ok is False


def test_fails_spread_at_half_percent():
    # Exactly 0.5%: mid=100 → width=0.5 → bid=99.75, ask=100.25
    live = _live(vol=5000, oi=50000, bid=99.75, ask=100.25)
    r = _eval(live, _prior(10))
    assert abs(r.spread_pct - 0.5) < 1e-9
    assert r.spread_ok is False
    assert ATM_SPREAD_TOO_WIDE in r.reason_codes


def test_uses_min_ce_pe_and_max_spread():
    live = AtmLiquidityLive(
        ce=_side(5000, 40000, 100.0, 100.2),
        pe=_side(2500, 22000, 50.0, 50.3),
    )
    r = _eval(live, _prior(10, vol=1000, oi=10000))
    assert r.atm_volume == 2500
    assert r.atm_oi == 22000
    assert abs(r.spread_pct - 0.5982053838484489) < 1e-9 or r.spread_pct > 0.5
    assert r.spread_ok is False


def test_abs_floor_still_required():
    live = _live(vol=1500, oi=15000, bid=100.0, ask=100.2)
    r = _eval(live, _prior(10, vol=500, oi=5000))
    assert r.abs_volume_ok is False
    assert r.liquidity_ok is False


# --- §3.2 chain-relative cold-start fallback (history_days < min_history_days) ---


def test_new_expiry_passes_via_chain_relative_median():
    """No prior sessions (n=0) but ATM clearly beats its same-session peer strikes."""
    live = _live(vol=3000, oi=25000, bid=100.0, ask=100.4)
    r = _eval(
        live,
        _prior(0),
        near_atm_volume_median=2000.0,
        near_atm_oi_median=20000.0,
    )
    assert r.history_days == 0
    assert r.relative_basis == "chain_relative"
    assert r.rel_volume_ok is True
    assert r.rel_oi_ok is True
    assert r.liquidity_ok is True
    assert ATM_CHAIN_RELATIVE_MODE in r.reason_codes
    assert ATM_HISTORY_TOO_SHORT in r.reason_codes


def test_new_expiry_fails_when_below_chain_median():
    """ATM clears absolute floors but sits below its peer strikes today — not just quiet history."""
    live = _live(vol=2500, oi=21000, bid=100.0, ask=100.4)
    r = _eval(
        live,
        _prior(3),
        near_atm_volume_median=5000.0,
        near_atm_oi_median=40000.0,
    )
    assert r.relative_basis == "chain_relative"
    assert r.rel_volume_ok is False
    assert r.rel_oi_ok is False
    assert r.liquidity_ok is False


def test_new_expiry_with_no_peer_chain_data_fails_explicitly():
    """No history AND no near-ATM peer data (e.g. a single-strike chain) — cannot pass on any basis."""
    live = _live(vol=5000, oi=50000)
    r = _eval(live, _prior(0), near_atm_volume_median=None, near_atm_oi_median=None)
    assert r.relative_basis == "chain_relative"
    assert r.liquidity_ok is False
    assert ATM_CHAIN_RELATIVE_DATA_MISSING in r.reason_codes


def test_established_expiry_ignores_chain_relative_params():
    """n >= min_history_days: temporal average still governs even if peer medians are passed."""
    live = _live(vol=3001, oi=26001, bid=100.0, ask=100.4)
    r = _eval(
        live,
        _prior(10, vol=2000, oi=20000),
        near_atm_volume_median=999999.0,
        near_atm_oi_median=999999.0,
    )
    assert r.relative_basis == "temporal"
    assert r.liquidity_ok is True
