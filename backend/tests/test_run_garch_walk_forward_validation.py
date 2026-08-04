from __future__ import annotations

import math
import random

from backend.quant.analytics.daily_price_history_store import DailyPriceHistoryStore
from backend.scripts.run_garch_walk_forward_validation import render_report, run_validation


def _price_series(n: int, *, seed: int) -> list[dict]:
    rng = random.Random(seed)
    price = 100.0
    rows = []
    for i in range(n):
        price *= 1.0 + rng.gauss(0.0, 0.01)
        rows.append({"date": f"2020-01-01+{i:05d}", "close": price})
    return rows


def test_run_validation_produces_one_summary_per_symbol_plus_combined(tmp_path):
    store = DailyPriceHistoryStore(store_path=tmp_path / "prices.json")
    store.replace(symbol="NIFTY", rows=_price_series(400, seed=1))
    store.replace(symbol="SBIN", rows=_price_series(400, seed=2))

    per_symbol, combined = run_validation(store=store, window=250, fit_min_observations=60)

    assert {s.symbol for s in per_symbol} == {"NIFTY", "SBIN"}
    assert combined.symbol == "ALL"
    assert combined.n_events == sum(s.n_events for s in per_symbol)


def test_run_validation_empty_store_returns_empty(tmp_path):
    store = DailyPriceHistoryStore(store_path=tmp_path / "prices.json")
    per_symbol, combined = run_validation(store=store)
    assert per_symbol == []
    assert combined.n_events == 0
    assert combined.insufficient_sample is True


def test_render_report_flags_insufficient_sample(tmp_path):
    store = DailyPriceHistoryStore(store_path=tmp_path / "prices.json")
    store.replace(symbol="NIFTY", rows=_price_series(260, seed=1))  # only ~10 walk-forward events
    per_symbol, combined = run_validation(store=store, window=250, fit_min_observations=60)
    report = render_report(
        per_symbol=per_symbol, combined=combined, store=store, window=250, fit_min_observations=60
    )
    assert "INSUFFICIENT SAMPLE" in report
    assert "keep `garch_forecast.enable_mle_fit: false`" in report


def test_render_report_includes_all_pilot_symbols(tmp_path):
    store = DailyPriceHistoryStore(store_path=tmp_path / "prices.json")
    store.replace(symbol="NIFTY", rows=_price_series(400, seed=1))
    store.replace(symbol="SBIN", rows=_price_series(400, seed=2))
    per_symbol, combined = run_validation(store=store, window=250, fit_min_observations=60)
    report = render_report(
        per_symbol=per_symbol, combined=combined, store=store, window=250, fit_min_observations=60
    )
    assert "NIFTY" in report
    assert "SBIN" in report
    assert "## Recommendation" in report
