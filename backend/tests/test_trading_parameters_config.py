"""Sanity checks on backend/config/trading_parameters.defaults.json."""

from __future__ import annotations

from backend.services.strategy_selection import load_trading_config


def test_gamma_scalping_calendar_construction_min_gap_days_present():
    cfg = load_trading_config()
    gap = cfg["strategies"]["gamma_scalping"]["calendar_construction"]["long_expiry_min_gap_days"]
    assert gap == 28
