"""Minimum spacing between Breeze REST calls.

The scan-capacity model (backend/services/scan_capacity.py) budgets wall clock
and the ~5000/day vendor envelope assuming every call it counts is spaced at
`min_interval_ms`. That assumption is only honest if the calls are actually
paced — so both call families the model counts share this module:

- enrichment calls (spot LTP + option-chain sides) — paced per
  `UniverseEnricher` instance, interval from config;
- candle-history calls (daily closes + intraday RV) — paced by the module
  pacer below.

The two families run in *sequential phases* of one recommendation cycle
(enrich first, then history), so per-family pacing yields cycle-wide spacing.
NOT covered here: paper_sim automation mark refreshes and health probes —
those are funded by the remainder of the daily envelope outside
`breeze_daily_call_budget` and have their own cadences.
"""

from __future__ import annotations

import asyncio
import time

DEFAULT_MIN_INTERVAL_MS = 700.0


class AsyncRateLimiter:
    """Global minimum spacing between Breeze REST calls."""

    def __init__(self, min_interval_ms: float = DEFAULT_MIN_INTERVAL_MS) -> None:
        self._min_interval = max(0.05, float(min_interval_ms) / 1000.0)
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_at = now + self._min_interval


# Shared pacer for candle-history calls (fetch_daily_closes /
# fetch_realized_vol_intraday). One instance per process, same 700ms floor the
# capacity model assumes for `breeze_history_calls_per_symbol`.
history_pacer = AsyncRateLimiter(DEFAULT_MIN_INTERVAL_MS)
