"""One-off backfill: daily close history for the GARCH walk-forward evidence
pilot universe (Improve_Recoemmendation_Engine.md §3.4 / BACKLOG.md P1).

Usage (from repo root):
  python -m backend.scripts.backfill_daily_price_history
  python -m backend.scripts.backfill_daily_price_history --force
  python -m backend.scripts.backfill_daily_price_history --symbols NIFTY,SBIN --lookback-days 900

Requires .env: ICICI_DIRECT_API_KEY, ICICI_DIRECT_API_SECRET, ICICI_DIRECT_SESSION_TOKEN
(same as backend/scripts/connect_icici_direct.py).

Idempotent: skips symbols already present in the store unless --force.
Rate-limited: sleeps between calls, well under CLAUDE.md's ~100 calls/min envelope.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

# Same pilot universe as Docs/superpowers/plans/2026-08-02-vega-reversion-evidence.md
# (PILOT_UNDERLYINGS) for consistency across this repo's evidence-gathering work.
PILOT_UNDERLYINGS: tuple[str, ...] = ("NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK", "INFY")


def _parse_row(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    raw_dt = row.get("datetime") or row.get("date")
    raw_close = row.get("close") or row.get("Close")
    if not raw_dt or raw_close is None:
        return None
    try:
        close = float(raw_close)
    except (TypeError, ValueError):
        return None
    if close <= 0:
        return None
    date = str(raw_dt).split(" ")[0].split("T")[0]
    return {"date": date, "close": close}


async def backfill_symbol(
    *,
    symbol: str,
    adapter: Any,
    store: Any,
    lookback_days: int,
) -> int:
    """Fetch + store one symbol's daily closes. Returns row count written."""
    from datetime import datetime, timedelta

    stock_code = None
    try:
        from backend.integrations.icici_direct.instrument_master import get_instrument_master

        stock_code = get_instrument_master().stock_code_for_underlying(symbol)
    except Exception:  # noqa: BLE001
        stock_code = None
    stock_code = stock_code or symbol

    end = datetime.utcnow()
    start = end - timedelta(days=lookback_days)
    rows = await adapter.get_candles(
        exchange="NSE",
        symboltoken=stock_code,
        interval="day",
        from_date=start.strftime("%Y-%m-%dT09:00:00.000Z"),
        to_date=end.strftime("%Y-%m-%dT16:00:00.000Z"),
        stock_code=stock_code,
    )
    parsed = [p for p in (_parse_row(r) for r in rows or []) if p is not None]
    store.replace(symbol=symbol, rows=parsed)
    return len(parsed)


async def run_backfill(
    *,
    symbols: tuple[str, ...] = PILOT_UNDERLYINGS,
    lookback_days: int = 900,
    force: bool = False,
    sleep_sec: float = 1.0,
    adapter: Any | None = None,
    store: Any | None = None,
) -> dict[str, int]:
    """Backfill each symbol not already in the store (unless force). Returns
    {symbol: row_count} for symbols actually fetched this run."""
    if store is None:
        from backend.quant.analytics.daily_price_history_store import DailyPriceHistoryStore

        store = DailyPriceHistoryStore()
    if adapter is None:
        from backend.integrations.icici_direct.market_data import get_market_data_adapter

        adapter = get_market_data_adapter()
        await adapter.ensure_instruments()

    results: dict[str, int] = {}
    existing = set(store.symbols())
    for i, symbol in enumerate(symbols):
        if symbol.upper() in existing and not force:
            continue
        count = await backfill_symbol(
            symbol=symbol, adapter=adapter, store=store, lookback_days=lookback_days
        )
        results[symbol.upper()] = count
        if i < len(symbols) - 1:
            await asyncio.sleep(sleep_sec)
    return results


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=None, help="Comma-separated symbols (default: pilot universe)")
    parser.add_argument("--lookback-days", type=int, default=900)
    parser.add_argument("--force", action="store_true", help="Refetch even if already stored")
    parser.add_argument("--sleep-sec", type=float, default=1.0)
    args = parser.parse_args()

    symbols = (
        tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
        if args.symbols
        else PILOT_UNDERLYINGS
    )

    from backend.config_env import load_project_env
    from backend.integrations.credential_vault import load_icici_direct_credentials

    load_project_env()
    load_icici_direct_credentials()

    results = await run_backfill(
        symbols=symbols,
        lookback_days=args.lookback_days,
        force=args.force,
        sleep_sec=args.sleep_sec,
    )
    if not results:
        print("Nothing fetched — all symbols already backfilled (use --force to refetch).")
    for symbol, count in results.items():
        print(f"{symbol}: {count} daily closes")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
