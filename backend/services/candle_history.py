"""Candle history helpers for live-clean GARCH / RV (ICICI historicalcharts)."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any

from backend.quant.signals.garch import log_returns_from_prices
from backend.services.breeze_pacing import history_pacer

logger = logging.getLogger(__name__)

# In-process daily close cache: SYMBOL|as_of_date → closes
_daily_cache: dict[str, list[float]] = {}


def reset_daily_candle_cache_for_tests() -> None:
    _daily_cache.clear()


def _parse_close(row: Any) -> float | None:
    if isinstance(row, dict):
        for key in ("close", "Close", "CLOSE", "c"):
            if key in row and row[key] is not None:
                try:
                    v = float(row[key])
                except (TypeError, ValueError):
                    return None
                return v if v > 0 else None
    return None


async def fetch_daily_closes(
    *,
    symbol: str,
    stock_code: str | None,
    lookback_days: int = 60,
    as_of_date: str | None = None,
    adapter: Any | None = None,
) -> list[float]:
    """Fetch daily closes via ICICI get_candles; cache once per symbol/day."""
    as_of = as_of_date or datetime.utcnow().date().isoformat()
    cache_key = f"{symbol.upper()}|{as_of}"
    if cache_key in _daily_cache:
        return list(_daily_cache[cache_key])

    if adapter is None:
        from backend.integrations.icici_direct.market_data import get_market_data_adapter

        adapter = get_market_data_adapter()

    end = datetime.fromisoformat(as_of)
    start = end - timedelta(days=max(lookback_days * 2, 90))
    code = stock_code or symbol
    try:
        # Paced: scan_capacity counts this call in breeze_history_calls_per_symbol.
        await history_pacer.acquire()
        rows = await adapter.get_candles(
            exchange="NSE",
            symboltoken=code,
            interval="day",
            from_date=start.strftime("%Y-%m-%dT09:00:00.000Z"),
            to_date=end.strftime("%Y-%m-%dT16:00:00.000Z"),
            stock_code=code,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("daily candles failed for %s: %s", symbol, exc)
        return []

    closes: list[float] = []
    for row in rows or []:
        c = _parse_close(row)
        if c is not None:
            closes.append(c)
    _daily_cache[cache_key] = closes
    return list(closes)


async def fetch_realized_vol_intraday(
    *,
    symbol: str,
    stock_code: str | None,
    as_of_date: str | None = None,
    adapter: Any | None = None,
) -> float | None:
    """Annualized-ish intraday RV from 5-minute log returns (session sample)."""
    if adapter is None:
        from backend.integrations.icici_direct.market_data import get_market_data_adapter

        adapter = get_market_data_adapter()

    as_of = as_of_date or datetime.utcnow().date().isoformat()
    code = stock_code or symbol
    try:
        # Paced: scan_capacity counts this call in breeze_history_calls_per_symbol.
        await history_pacer.acquire()
        rows = await adapter.get_candles(
            exchange="NSE",
            symboltoken=code,
            interval="5minute",
            from_date=f"{as_of}T03:45:00.000Z",
            to_date=f"{as_of}T10:00:00.000Z",
            stock_code=code,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("intraday candles failed for %s: %s", symbol, exc)
        return None

    closes = [c for c in (_parse_close(r) for r in rows or []) if c is not None]
    rets = log_returns_from_prices(closes)
    if len(rets) < 5:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1)
    # Scale 5-min variance to a rough daily fraction (≈75 bars/session).
    daily = math.sqrt(var * 75)
    return float(daily) if daily > 0 else None
