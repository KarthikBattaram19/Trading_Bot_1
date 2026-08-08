from __future__ import annotations

import math
import random

from backend.quant.analytics.daily_price_history_store import DailyPriceHistoryStore
from backend.scripts.calibrate_garch_weights import (
    recommended_overrides,
    render_report,
    run_calibration,
)


def _garch_price_series(
    n: int, *, gamma: float, alpha: float, beta: float, vl: float, seed: int
) -> list[dict]:
    rng = random.Random(seed)
    sigma2 = vl
    price = 100.0
    rows = []
    for i in range(n):
        r = rng.gauss(0.0, math.sqrt(sigma2))
        sigma2 = gamma * vl + alpha * (r * r) + beta * sigma2
        price *= math.exp(r)
        rows.append({"date": f"2020-01-01+{i:05d}", "close": price})
    return rows


def test_calibration_accepts_override_for_reactive_series(tmp_path):
    store = DailyPriceHistoryStore(store_path=tmp_path / "prices.json")
    store.replace(
        symbol="BANKNIFTY",
        rows=_garch_price_series(700, gamma=0.03, alpha=0.15, beta=0.82, vl=0.0002, seed=5),
    )
    results = run_calibration(store=store, window=250)
    (cal,) = results
    assert cal.symbol == "BANKNIFTY"
    assert cal.accepted is not None
    # The winning candidate must be more reactive than the sluggish default.
    assert cal.accepted.alpha > 0.05
    assert cal.reject_reason is None


def test_calibration_rejects_when_default_generated_the_series(tmp_path):
    store = DailyPriceHistoryStore(store_path=tmp_path / "prices.json")
    store.replace(
        symbol="RELIANCE",
        rows=_garch_price_series(700, gamma=0.05, alpha=0.05, beta=0.90, vl=0.0002, seed=3),
    )
    results = run_calibration(store=store, window=250)
    (cal,) = results
    assert cal.accepted is None
    assert cal.reject_reason is not None


def test_calibration_rejects_insufficient_events(tmp_path):
    store = DailyPriceHistoryStore(store_path=tmp_path / "prices.json")
    store.replace(
        symbol="INFY",
        rows=_garch_price_series(300, gamma=0.03, alpha=0.15, beta=0.82, vl=0.0002, seed=9),
    )
    # 300 prices -> ~299 returns -> ~49 events, below the 100-event floor.
    results = run_calibration(store=store, window=250)
    (cal,) = results
    assert cal.accepted is None
    assert cal.reject_reason == "insufficient_events"


def test_recommended_overrides_shape_and_sum(tmp_path):
    store = DailyPriceHistoryStore(store_path=tmp_path / "prices.json")
    store.replace(
        symbol="BANKNIFTY",
        rows=_garch_price_series(700, gamma=0.03, alpha=0.15, beta=0.82, vl=0.0002, seed=5),
    )
    results = run_calibration(store=store, window=250)
    overrides = recommended_overrides(results)
    assert set(overrides) == {"BANKNIFTY"}
    entry = overrides["BANKNIFTY"]
    assert set(entry) == {"gamma_weight", "alpha_weight", "beta_weight"}
    assert abs(sum(entry.values()) - 1.0) < 1e-9


def test_render_report_lists_all_symbols_and_verdicts(tmp_path):
    store = DailyPriceHistoryStore(store_path=tmp_path / "prices.json")
    store.replace(
        symbol="BANKNIFTY",
        rows=_garch_price_series(700, gamma=0.03, alpha=0.15, beta=0.82, vl=0.0002, seed=5),
    )
    store.replace(
        symbol="INFY",
        rows=_garch_price_series(300, gamma=0.03, alpha=0.15, beta=0.82, vl=0.0002, seed=9),
    )
    results = run_calibration(store=store, window=250)
    report = render_report(results=results, store=store, window=250)
    assert "BANKNIFTY" in report
    assert "INFY" in report
    assert "insufficient_events" in report
    assert "symbol_overrides" in report
