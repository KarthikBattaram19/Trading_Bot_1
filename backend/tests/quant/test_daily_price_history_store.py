from __future__ import annotations

from backend.quant.analytics.daily_price_history_store import DailyPriceHistoryStore


def _store(tmp_path):
    return DailyPriceHistoryStore(store_path=tmp_path / "daily_price_history.json")


def test_replace_and_series_round_trip(tmp_path):
    store = _store(tmp_path)
    store.replace(
        symbol="nifty",
        rows=[
            {"date": "2026-01-02", "close": 100.0},
            {"date": "2026-01-01", "close": 99.0},  # out of order on input
        ],
    )
    assert store.series(symbol="NIFTY") == [99.0, 100.0]  # sorted by date
    assert store.date_range(symbol="NIFTY") == ("2026-01-01", "2026-01-02")


def test_replace_drops_invalid_rows(tmp_path):
    store = _store(tmp_path)
    store.replace(
        symbol="SBIN",
        rows=[
            {"date": "2026-01-01", "close": 0.0},  # non-positive
            {"date": "2026-01-02", "close": "bad"},  # unparseable
            {"date": None, "close": 50.0},  # missing date
            {"date": "2026-01-03", "close": 50.0},  # valid
        ],
    )
    assert store.series(symbol="SBIN") == [50.0]


def test_replace_is_idempotent_overwrite(tmp_path):
    store = _store(tmp_path)
    store.replace(symbol="SBIN", rows=[{"date": "2026-01-01", "close": 10.0}])
    store.replace(symbol="SBIN", rows=[{"date": "2026-01-01", "close": 20.0}])
    assert store.series(symbol="SBIN") == [20.0]


def test_symbols_lists_stored_keys(tmp_path):
    store = _store(tmp_path)
    store.replace(symbol="NIFTY", rows=[{"date": "2026-01-01", "close": 100.0}])
    store.replace(symbol="SBIN", rows=[{"date": "2026-01-01", "close": 50.0}])
    assert store.symbols() == ["NIFTY", "SBIN"]


def test_missing_symbol_returns_empty(tmp_path):
    store = _store(tmp_path)
    assert store.series(symbol="GHOST") == []
    assert store.date_range(symbol="GHOST") is None
