"""Regression coverage for candle_history.py's ICICI interval strings.

Breeze's get_historical_charts only accepts interval in
{"minute", "5minute", "30minute", "day"} -- "1day" is rejected server-side
with "Interval should be either 'minute', '5minute', '30minute', or 'day'.",
verified live. fetch_daily_closes previously passed "1day", so every real
(non-seeded) daily-close fetch silently failed and returned [].
"""

from __future__ import annotations

import pytest

from backend.services.candle_history import (
    fetch_daily_closes,
    fetch_realized_vol_intraday,
    reset_daily_candle_cache_for_tests,
)


class _RecordingAdapter:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows if rows is not None else [{"close": "100.0"}, {"close": "101.5"}]
        self.calls: list[dict] = []

    async def get_candles(self, **kwargs):
        self.calls.append(kwargs)
        return self.rows


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_daily_candle_cache_for_tests()
    yield
    reset_daily_candle_cache_for_tests()


async def test_fetch_daily_closes_uses_day_interval_not_1day():
    adapter = _RecordingAdapter()
    closes = await fetch_daily_closes(
        symbol="NIFTY", stock_code="NIFTY", lookback_days=750, adapter=adapter
    )
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["interval"] == "day"
    assert closes == [100.0, 101.5]


async def test_fetch_realized_vol_intraday_uses_5minute_interval():
    rows = [{"close": str(100 + i * 0.1)} for i in range(20)]
    adapter = _RecordingAdapter(rows)
    await fetch_realized_vol_intraday(symbol="NIFTY", stock_code="NIFTY", adapter=adapter)
    assert adapter.calls[0]["interval"] == "5minute"
