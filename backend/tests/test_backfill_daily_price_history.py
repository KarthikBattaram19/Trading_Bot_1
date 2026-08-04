from __future__ import annotations

from backend.quant.analytics.daily_price_history_store import DailyPriceHistoryStore
from backend.scripts.backfill_daily_price_history import run_backfill


class _FakeAdapter:
    def __init__(self, rows_by_symbol: dict[str, list[dict]]) -> None:
        self.rows_by_symbol = rows_by_symbol
        self.calls: list[dict] = []

    async def get_candles(self, **kwargs):
        self.calls.append(kwargs)
        return self.rows_by_symbol.get(kwargs["stock_code"], [])


def _rows(n: int) -> list[dict]:
    return [{"datetime": f"2026-01-{i + 1:02d} 12:00:00", "close": str(100.0 + i)} for i in range(n)]


async def test_backfill_writes_parsed_rows_to_store(tmp_path):
    store = DailyPriceHistoryStore(store_path=tmp_path / "prices.json")
    adapter = _FakeAdapter({"NIFTY": _rows(5), "SBIN": _rows(3)})
    results = await run_backfill(
        symbols=("NIFTY", "SBIN"), sleep_sec=0.0, adapter=adapter, store=store
    )
    assert results == {"NIFTY": 5, "SBIN": 3}
    assert store.series(symbol="NIFTY") == [100.0, 101.0, 102.0, 103.0, 104.0]
    assert store.series(symbol="SBIN") == [100.0, 101.0, 102.0]


async def test_backfill_skips_already_stored_symbols_without_force(tmp_path):
    store = DailyPriceHistoryStore(store_path=tmp_path / "prices.json")
    store.replace(symbol="NIFTY", rows=[{"date": "2026-01-01", "close": 999.0}])
    adapter = _FakeAdapter({"NIFTY": _rows(5)})

    results = await run_backfill(symbols=("NIFTY",), sleep_sec=0.0, adapter=adapter, store=store)

    assert results == {}
    assert len(adapter.calls) == 0
    assert store.series(symbol="NIFTY") == [999.0]  # untouched


async def test_backfill_force_refetches_existing_symbol(tmp_path):
    store = DailyPriceHistoryStore(store_path=tmp_path / "prices.json")
    store.replace(symbol="NIFTY", rows=[{"date": "2026-01-01", "close": 999.0}])
    adapter = _FakeAdapter({"NIFTY": _rows(5)})

    results = await run_backfill(
        symbols=("NIFTY",), sleep_sec=0.0, force=True, adapter=adapter, store=store
    )

    assert results == {"NIFTY": 5}
    assert len(adapter.calls) == 1
    assert store.series(symbol="NIFTY") == [100.0, 101.0, 102.0, 103.0, 104.0]


async def test_backfill_uses_day_interval():
    store = DailyPriceHistoryStore(store_path=None)
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        store = DailyPriceHistoryStore(store_path=Path(d) / "prices.json")
        adapter = _FakeAdapter({"NIFTY": _rows(5)})
        await run_backfill(symbols=("NIFTY",), sleep_sec=0.0, adapter=adapter, store=store)
        assert adapter.calls[0]["interval"] == "day"


async def test_backfill_drops_unparseable_rows(tmp_path):
    store = DailyPriceHistoryStore(store_path=tmp_path / "prices.json")
    bad_rows = [
        {"datetime": "2026-01-01 12:00:00", "close": "0"},  # non-positive
        {"datetime": "2026-01-02 12:00:00", "close": "bad"},  # unparseable
        {"datetime": None, "close": "100"},  # missing datetime
        {"datetime": "2026-01-04 12:00:00", "close": "105.0"},  # valid
    ]
    adapter = _FakeAdapter({"NIFTY": bad_rows})
    results = await run_backfill(symbols=("NIFTY",), sleep_sec=0.0, adapter=adapter, store=store)
    assert results == {"NIFTY": 1}
    assert store.series(symbol="NIFTY") == [105.0]
