from pathlib import Path

from backend.services.atm_liquidity_history import AtmLiquidityHistoryStore


def test_upsert_idempotent_and_prior_excludes_today(tmp_path: Path):
    store = AtmLiquidityHistoryStore(tmp_path / "hist.json")
    for i in range(1, 12):
        store.upsert_snapshot(
            underlying="sbin",
            expiry_key="2026-08-28",
            session_date=f"2026-07-{i:02d}",
            atm_strike=800 + i,
            atm_volume=2000 + i,
            atm_oi=20000 + i,
        )
    store.upsert_snapshot(
        underlying="SBIN",
        expiry_key="2026-08-28",
        session_date="2026-07-11",
        atm_strike=999.0,
        atm_volume=9999,
        atm_oi=99999,
    )
    prior = store.prior_points(
        underlying="SBIN",
        expiry_key="2026-08-28",
        before_date="2026-07-11",
        lookback_days=20,
    )
    assert len(prior) == 10
    assert all(p.session_date < "2026-07-11" for p in prior)

    today_prior = store.prior_points(
        underlying="SBIN",
        expiry_key="2026-08-28",
        before_date="2026-07-12",
        lookback_days=20,
    )
    assert today_prior[-1].atm_volume == 9999
