# Vega Scalping IV Mean-Reversion Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce real, measured evidence (hit-rate + outcome distribution) for whether intraday IV actually mean-reverts after a −2σ dislocation — the untested assumption underlying vega scalping's entry signal.

**Architecture:** Add an implied-vol solver to invert Breeze's historical option premium candles into an IV series (Breeze has no historical-IV endpoint); backfill a small pilot universe's IV history into the existing `iv_history.json` store; replay that history through the same rolling z-score logic already used live to detect every −2σ trigger and classify its outcome (REVERTED / STOP_HIT / NO_REVERT_AT_CLOSE) per the strategy doc's own Rule 7; write the aggregate as a Markdown+JSON evidence report. Evidence-gathering only — no change to live entry/gating logic.

**Tech Stack:** Python (FastAPI backend), pytest (`asyncio_mode=auto`), existing Black-Scholes pricer (`backend/quant/pricing/bsm.py`), existing ICICI Direct Breeze integration.

## Global Constraints

- Evidence-gathering only — do not modify `backend/quant/signals/iv_zscore.py`'s `reject_vega` / entry-gating behavior (Design §Scope).
- Pilot universe stays small: 3–5 liquid symbols, ATM strike only, current expiry (Design §Scope).
- `backend/data/iv_history.json` schema (`SYMBOL|session_date` → `[{iv, ts}]`) must not change — the backfill writes through the existing `IvHistoryStore.append` (`backend/services/iv_history_store.py:33`).
- Vendor request shapes must come from Breeze docs, not be invented (`CLAUDE.md`) — the historicalcharts option-fields shape used here follows this codebase's existing `get_quotes`/`get_option_chain` field convention, but must be flagged as unverified against vendor docs (no existing caller in this repo exercises `historicalcharts` for options).
- Rate limits: ~100 calls/min, ~5000/day non-order APIs (`CLAUDE.md`) — backfill script must pace calls.
- Report must explicitly flag `insufficient_sample` (n < 30 events) rather than presenting a hit-rate as validated (Design §3–4).
- Tests must not require live Breeze credentials — fake the adapter/session per existing repo patterns.

---

## Task 1: Implied volatility solver

**Files:**
- Create: `backend/quant/pricing/implied_vol.py`
- Test: `backend/tests/quant/test_implied_vol.py`

**Interfaces:**
- Consumes: `BSMInputs`, `black_scholes_merton_price` from `backend/quant/pricing/bsm.py:36,129` (dataclass fields: `spot, strike, time_years, rate, dividend_yield, volatility, option_type` — all decimals, not percent; `option_type: Literal["call","put"]`).
- Produces: `implied_volatility(*, market_price, spot, strike, time_years, rate, dividend_yield, option_type, tol=1e-6, max_iter=100) -> float | None`, used by Task 4's backfill script.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/quant/test_implied_vol.py
"""Implied volatility solver unit tests."""

from __future__ import annotations

from backend.quant.pricing.bsm import BSMInputs, black_scholes_merton_price
from backend.quant.pricing.implied_vol import implied_volatility


def test_round_trip_atm_call():
    inputs = BSMInputs(
        spot=100.0, strike=100.0, time_years=30 / 365, rate=0.07,
        dividend_yield=0.0, volatility=0.20, option_type="call",
    )
    price = black_scholes_merton_price(inputs)
    iv = implied_volatility(
        market_price=price, spot=100.0, strike=100.0, time_years=30 / 365,
        rate=0.07, dividend_yield=0.0, option_type="call",
    )
    assert iv is not None
    assert abs(iv - 0.20) < 1e-4


def test_round_trip_put_various_moneyness():
    for strike in (80.0, 100.0, 120.0):
        inputs = BSMInputs(
            spot=100.0, strike=strike, time_years=10 / 365, rate=0.07,
            dividend_yield=0.0, volatility=0.35, option_type="put",
        )
        price = black_scholes_merton_price(inputs)
        iv = implied_volatility(
            market_price=price, spot=100.0, strike=strike, time_years=10 / 365,
            rate=0.07, dividend_yield=0.0, option_type="put",
        )
        assert iv is not None
        assert abs(iv - 0.35) < 1e-3


def test_price_below_intrinsic_bound_returns_none():
    # Deep ITM call (strike 50, spot 100): even near-zero vol prices well above this.
    iv = implied_volatility(
        market_price=0.0001, spot=100.0, strike=50.0, time_years=30 / 365,
        rate=0.07, dividend_yield=0.0, option_type="call",
    )
    assert iv is None


def test_zero_time_years_returns_none():
    iv = implied_volatility(
        market_price=5.0, spot=100.0, strike=100.0, time_years=0.0,
        rate=0.07, dividend_yield=0.0, option_type="call",
    )
    assert iv is None


def test_non_positive_price_returns_none():
    iv = implied_volatility(
        market_price=0.0, spot=100.0, strike=100.0, time_years=30 / 365,
        rate=0.07, dividend_yield=0.0, option_type="call",
    )
    assert iv is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/quant/test_implied_vol.py -v`
Expected: FAIL (`ModuleNotFoundError: backend.quant.pricing.implied_vol`)

- [ ] **Step 3: Write the implementation**

```python
# backend/quant/pricing/implied_vol.py
"""Implied volatility solver — inverts Black-Scholes price to volatility.

Breeze's historical market-data API exposes option premium candles, not
historical implied volatility, so this is the missing piece that turns a
historical premium series into an IV series (used by
backend/scripts/backfill_iv_history.py). Bisection over a fixed volatility
bracket; returns None rather than raising on a non-convergent or
arbitrage-violating price, matching how callers already treat unusable IV
inputs (backend/quant/signals/iv_zscore.py).
"""

from __future__ import annotations

import math
from typing import Literal

from backend.quant.pricing.bsm import BSMInputs, black_scholes_merton_price

_VOL_LO = 1e-4
_VOL_HI = 5.0


def implied_volatility(
    *,
    market_price: float,
    spot: float,
    strike: float,
    time_years: float,
    rate: float,
    dividend_yield: float,
    option_type: Literal["call", "put"],
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float | None:
    """Bisection-solve volatility such that BSM price == market_price.

    Returns None when market_price falls outside the price range spanned by
    the [_VOL_LO, _VOL_HI] bracket (no root — likely an arbitrage-violating
    or garbage quote), or the solver fails to converge within max_iter.
    """
    if market_price <= 0 or spot <= 0 or strike <= 0 or time_years <= 0:
        return None

    def _price_at(vol: float) -> float:
        return black_scholes_merton_price(
            BSMInputs(
                spot=spot,
                strike=strike,
                time_years=time_years,
                rate=rate,
                dividend_yield=dividend_yield,
                volatility=vol,
                option_type=option_type,
            )
        )

    lo, hi = _VOL_LO, _VOL_HI
    f_lo = _price_at(lo) - market_price
    f_hi = _price_at(hi) - market_price
    if math.isnan(f_lo) or math.isnan(f_hi):
        return None
    if f_lo > 0 or f_hi < 0:
        return None

    mid = (lo + hi) / 2.0
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        f_mid = _price_at(mid) - market_price
        if abs(f_mid) < tol or (hi - lo) < tol:
            return mid
        if f_mid > 0:
            hi = mid
        else:
            lo = mid
    return mid
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/quant/test_implied_vol.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/quant/pricing/implied_vol.py backend/tests/quant/test_implied_vol.py
git commit -m "feat: add implied-volatility solver for historical IV backfill"
```

---

## Task 2: `IvHistoryStore.all_series()`

**Files:**
- Modify: `backend/services/iv_history_store.py:12-61`
- Test: `backend/tests/test_iv_history_store.py` (new)

**Interfaces:**
- Consumes: existing `IvHistoryStore` (`store_path`, `append`, `series`, private `_read`).
- Produces: `IvHistoryStore.all_series() -> dict[str, list[float]]` — every stored `SYMBOL|session_date` key mapped to its cleaned (positive-only) IV list. Used by Task 5's report script to iterate all accumulated sessions (the store currently has no way to list what it holds beyond one `(symbol, session_date)` at a time).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_iv_history_store.py
"""IvHistoryStore unit tests — append/series/all_series."""

from __future__ import annotations

from backend.services.iv_history_store import IvHistoryStore


def test_append_and_series_roundtrip(tmp_path):
    store = IvHistoryStore(store_path=tmp_path / "iv_history.json")
    store.append(symbol="nifty", session_date="2026-08-01", ts_iso="2026-08-01T10:00:00+00:00", iv=0.21)
    store.append(symbol="nifty", session_date="2026-08-01", ts_iso="2026-08-01T10:05:00+00:00", iv=0.22)

    series = store.series(symbol="NIFTY", session_date="2026-08-01")
    assert series == [0.21, 0.22]


def test_append_ignores_non_positive_iv(tmp_path):
    store = IvHistoryStore(store_path=tmp_path / "iv_history.json")
    store.append(symbol="NIFTY", session_date="2026-08-01", ts_iso="t1", iv=0.0)
    store.append(symbol="NIFTY", session_date="2026-08-01", ts_iso="t2", iv=-0.1)
    assert store.series(symbol="NIFTY", session_date="2026-08-01") == []


def test_all_series_returns_every_key(tmp_path):
    store = IvHistoryStore(store_path=tmp_path / "iv_history.json")
    store.append(symbol="NIFTY", session_date="2026-08-01", ts_iso="t1", iv=0.21)
    store.append(symbol="BANKNIFTY", session_date="2026-08-01", ts_iso="t1", iv=0.30)
    store.append(symbol="BANKNIFTY", session_date="2026-08-02", ts_iso="t1", iv=0.31)

    all_series = store.all_series()
    assert set(all_series) == {"NIFTY|2026-08-01", "BANKNIFTY|2026-08-01", "BANKNIFTY|2026-08-02"}
    assert all_series["NIFTY|2026-08-01"] == [0.21]
    assert all_series["BANKNIFTY|2026-08-02"] == [0.31]


def test_all_series_on_empty_store_returns_empty_dict(tmp_path):
    store = IvHistoryStore(store_path=tmp_path / "does_not_exist.json")
    assert store.all_series() == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_iv_history_store.py -v`
Expected: `test_all_series_*` FAIL with `AttributeError: 'IvHistoryStore' object has no attribute 'all_series'`; the other two should already PASS (they exercise existing behavior — confirms no regression before the change).

- [ ] **Step 3: Add `all_series()`**

Add this method to `backend/services/iv_history_store.py`, directly below the existing `series` method (after line 61):

```python
    def all_series(self) -> dict[str, list[float]]:
        """Every stored ``SYMBOL|session_date`` key → its cleaned IV series."""
        data = self._read()
        out: dict[str, list[float]] = {}
        for key, rows in data.items():
            ivs: list[float] = []
            for r in rows if isinstance(rows, list) else []:
                try:
                    v = float(r.get("iv"))
                except (TypeError, ValueError, AttributeError):
                    continue
                if v > 0:
                    ivs.append(v)
            out[key] = ivs
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_iv_history_store.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/services/iv_history_store.py backend/tests/test_iv_history_store.py
git commit -m "feat: add IvHistoryStore.all_series() for cross-session replay"
```

---

## Task 3: Vega reversion validator

**Files:**
- Create: `backend/quant/analytics/__init__.py` (empty — new package; `backend/quant/` currently has `costs, gamma, pricing, risk, signals`, no `analytics`)
- Create: `backend/quant/analytics/vega_reversion_validator.py`
- Test: `backend/tests/quant/test_vega_reversion_validator.py`

**Interfaces:**
- Consumes: `compute_iv_zscore`, `vega_entry_signal` from `backend/quant/signals/iv_zscore.py:37,149` (note: `compute_iv_zscore(series, current_iv=None, ...)` computes mean/std over the *entire* series passed in, and when `current_iv` is omitted uses `series[-1]` as both the tested value and part of the mean/std baseline — this in-sample/self-referential behavior matches production, see `backend/services/quant_snapshot.py:125-130` which passes an `iv_series_intraday` that already includes the just-appended current point).
- Produces: `ReversionEvent` (frozen dataclass: `symbol: str, session_date: str, trigger_index: int, trigger_z: float, outcome: Literal["REVERTED","STOP_HIT","NO_REVERT_AT_CLOSE"], bars_to_resolution: int`), `find_reversion_events(series, *, symbol, session_date, min_observations=5, entry_z_threshold=-2.0, revert_z_threshold=-0.5, stop_z_threshold=-3.0) -> list[ReversionEvent]`, `ReversionAggregate` (frozen dataclass: `total_events, reverted, stop_hit, no_revert_at_close: int; reverted_pct, stop_hit_pct, no_revert_at_close_pct: float|None; insufficient_sample: bool; min_sample_size: int; per_symbol: dict[str, dict[str,int]]; bars_to_revert_distribution: list[int]`), `aggregate_reversion_events(events, *, min_sample_size=30) -> ReversionAggregate`. Used by Task 5's report script.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/quant/test_vega_reversion_validator.py
"""Vega-scalp IV mean-reversion evidence — outcome classification tests.

Fixture construction note: compute_iv_zscore is self-referential (the
tested point is part of its own mean/std baseline), so a single new
extreme point only pulls the window stats a little when the baseline is
large. All fixtures below use a 200-point baseline (mean=0.30, std=0.02
exactly, since [mean-std, mean+std] alternated has zero skew) so appended
points move z by a large, unambiguous margin — comfortably past each
threshold rather than sitting exactly on the boundary.
"""

from __future__ import annotations

from backend.quant.analytics.vega_reversion_validator import (
    ReversionEvent,
    aggregate_reversion_events,
    find_reversion_events,
)

_MEAN = 0.30
_STD = 0.02
_BASELINE = [_MEAN - _STD, _MEAN + _STD] * 100  # n=200, mean=0.30, std=0.02 exactly


def test_reverted_after_trigger():
    trigger = [_MEAN - 2.5 * _STD]  # z well past -2 once appended
    recover = [_MEAN]  # back at baseline mean -> z snaps back near 0
    series = _BASELINE + trigger + recover
    events = find_reversion_events(series, symbol="TEST", session_date="2026-08-01")
    assert len(events) == 1
    assert events[0].outcome == "REVERTED"
    assert events[0].trigger_z <= -2.0
    assert events[0].bars_to_resolution == 1


def test_stop_hit_after_trigger():
    trigger = [_MEAN - 2.5 * _STD]
    keep_falling = [_MEAN - 5.0 * _STD]  # pushes z well past -3
    series = _BASELINE + trigger + keep_falling
    events = find_reversion_events(series, symbol="TEST", session_date="2026-08-01")
    assert len(events) == 1
    assert events[0].outcome == "STOP_HIT"
    assert events[0].bars_to_resolution == 1


def test_no_revert_at_close_when_session_ends_mid_dislocation():
    trigger = [_MEAN - 2.5 * _STD]
    plateau = [_MEAN - 2.5 * _STD, _MEAN - 2.5 * _STD]  # neither reverts nor stops
    series = _BASELINE + trigger + plateau
    events = find_reversion_events(series, symbol="TEST", session_date="2026-08-01")
    assert len(events) == 1
    assert events[0].outcome == "NO_REVERT_AT_CLOSE"
    assert events[0].bars_to_resolution == len(series) - 1 - events[0].trigger_index


def test_trigger_at_last_bar_resolves_no_revert_with_zero_bars():
    series = _BASELINE + [_MEAN - 2.5 * _STD]
    events = find_reversion_events(series, symbol="TEST", session_date="2026-08-01")
    assert len(events) == 1
    assert events[0].outcome == "NO_REVERT_AT_CLOSE"
    assert events[0].bars_to_resolution == 0


def test_no_trigger_when_series_stays_near_mean():
    series = [0.30, 0.31, 0.29, 0.305, 0.295] * 4
    events = find_reversion_events(series, symbol="TEST", session_date="2026-08-01")
    assert events == []


def _fake_event(outcome: str) -> ReversionEvent:
    return ReversionEvent(
        symbol="TEST", session_date="2026-08-01", trigger_index=10,
        trigger_z=-2.1, outcome=outcome, bars_to_resolution=3,
    )


def test_aggregate_flags_insufficient_sample_below_threshold():
    events = [_fake_event("REVERTED") for _ in range(29)]
    aggregate = aggregate_reversion_events(events, min_sample_size=30)
    assert aggregate.total_events == 29
    assert aggregate.insufficient_sample is True


def test_aggregate_not_insufficient_at_threshold():
    events = [_fake_event("REVERTED") for _ in range(30)]
    aggregate = aggregate_reversion_events(events, min_sample_size=30)
    assert aggregate.insufficient_sample is False
    assert aggregate.reverted_pct == 1.0
    assert aggregate.stop_hit_pct == 0.0


def test_aggregate_per_symbol_breakdown():
    events = [
        ReversionEvent("A", "2026-08-01", 10, -2.1, "REVERTED", 1),
        ReversionEvent("A", "2026-08-02", 12, -2.4, "STOP_HIT", 2),
        ReversionEvent("B", "2026-08-01", 8, -2.2, "REVERTED", 1),
    ]
    aggregate = aggregate_reversion_events(events, min_sample_size=1)
    assert aggregate.per_symbol["A"] == {"REVERTED": 1, "STOP_HIT": 1, "NO_REVERT_AT_CLOSE": 0}
    assert aggregate.per_symbol["B"] == {"REVERTED": 1, "STOP_HIT": 0, "NO_REVERT_AT_CLOSE": 0}
    assert aggregate.bars_to_revert_distribution == [1, 1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/quant/test_vega_reversion_validator.py -v`
Expected: FAIL (`ModuleNotFoundError: backend.quant.analytics.vega_reversion_validator`)

- [ ] **Step 3: Write the implementation**

Create `backend/quant/analytics/__init__.py` (empty file).

```python
# backend/quant/analytics/vega_reversion_validator.py
"""Vega-scalp IV mean-reversion evidence — outcome classification & aggregation.

Replays a session's IV series through the same rolling z-score logic as
backend/quant/signals/iv_zscore.py to find every point where the live
-2sigma entry (vega_entry_signal) would have fired, then classifies what
happened next per Docs/Trading_Strategies.md Table VS-2 Rule 7 (stop at
3sigma/4sigma below mean) and same-day flattening. Pure functions, no I/O —
callers supply series already loaded from IvHistoryStore.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from backend.quant.signals.iv_zscore import compute_iv_zscore, vega_entry_signal

Outcome = Literal["REVERTED", "STOP_HIT", "NO_REVERT_AT_CLOSE"]

DEFAULT_MIN_OBSERVATIONS = 5
DEFAULT_ENTRY_Z = -2.0
DEFAULT_REVERT_Z = -0.5
DEFAULT_STOP_Z = -3.0
DEFAULT_MIN_SAMPLE_SIZE = 30


@dataclass(frozen=True, slots=True)
class ReversionEvent:
    symbol: str
    session_date: str
    trigger_index: int
    trigger_z: float
    outcome: Outcome
    bars_to_resolution: int


@dataclass(frozen=True, slots=True)
class ReversionAggregate:
    total_events: int
    reverted: int
    stop_hit: int
    no_revert_at_close: int
    reverted_pct: float | None
    stop_hit_pct: float | None
    no_revert_at_close_pct: float | None
    insufficient_sample: bool
    min_sample_size: int
    per_symbol: dict[str, dict[str, int]]
    bars_to_revert_distribution: list[int]


def find_reversion_events(
    series: Sequence[float],
    *,
    symbol: str,
    session_date: str,
    min_observations: int = DEFAULT_MIN_OBSERVATIONS,
    entry_z_threshold: float = DEFAULT_ENTRY_Z,
    revert_z_threshold: float = DEFAULT_REVERT_Z,
    stop_z_threshold: float = DEFAULT_STOP_Z,
) -> list[ReversionEvent]:
    """Replay one session's IV series, expanding-window (matches live semantics).

    At each index i, compute_iv_zscore(series[:i+1]) mirrors what the live
    entry gate saw at that point in time — it does not know the future. Once
    a trigger fires, later bars are resolved forward (REVERTED / STOP_HIT /
    NO_REVERT_AT_CLOSE) before scanning resumes for the next trigger, so
    overlapping triggers within one reversion episode collapse into a single
    event.
    """
    n = len(series)
    events: list[ReversionEvent] = []
    i = min_observations - 1
    while i < n:
        window = series[: i + 1]
        result = compute_iv_zscore(window, min_observations=min_observations)
        if not vega_entry_signal(result, entry_z_threshold=entry_z_threshold):
            i += 1
            continue

        trigger_index = i
        trigger_z = float(result.iv_z_score)  # usable => not None (vega_entry_signal checked)
        outcome: Outcome = "NO_REVERT_AT_CLOSE"
        resolution_index = n - 1
        j = i + 1
        while j < n:
            fwd = compute_iv_zscore(series[: j + 1], min_observations=min_observations)
            if fwd.usable and fwd.iv_z_score is not None:
                if fwd.iv_z_score >= revert_z_threshold:
                    outcome = "REVERTED"
                    resolution_index = j
                    break
                if fwd.iv_z_score <= stop_z_threshold:
                    outcome = "STOP_HIT"
                    resolution_index = j
                    break
            j += 1

        events.append(
            ReversionEvent(
                symbol=symbol,
                session_date=session_date,
                trigger_index=trigger_index,
                trigger_z=trigger_z,
                outcome=outcome,
                bars_to_resolution=resolution_index - trigger_index,
            )
        )
        i = resolution_index + 1
    return events


def aggregate_reversion_events(
    events: Sequence[ReversionEvent],
    *,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
) -> ReversionAggregate:
    total = len(events)
    reverted = sum(1 for e in events if e.outcome == "REVERTED")
    stop_hit = sum(1 for e in events if e.outcome == "STOP_HIT")
    no_revert = sum(1 for e in events if e.outcome == "NO_REVERT_AT_CLOSE")

    per_symbol: dict[str, dict[str, int]] = {}
    for e in events:
        bucket = per_symbol.setdefault(
            e.symbol, {"REVERTED": 0, "STOP_HIT": 0, "NO_REVERT_AT_CLOSE": 0}
        )
        bucket[e.outcome] += 1

    def _pct(count: int) -> float | None:
        return (count / total) if total > 0 else None

    return ReversionAggregate(
        total_events=total,
        reverted=reverted,
        stop_hit=stop_hit,
        no_revert_at_close=no_revert,
        reverted_pct=_pct(reverted),
        stop_hit_pct=_pct(stop_hit),
        no_revert_at_close_pct=_pct(no_revert),
        insufficient_sample=total < min_sample_size,
        min_sample_size=min_sample_size,
        per_symbol=per_symbol,
        bars_to_revert_distribution=[
            e.bars_to_resolution for e in events if e.outcome == "REVERTED"
        ],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/quant/test_vega_reversion_validator.py -v`
Expected: PASS (9 tests). If any of the numeric fixture tests (`test_reverted_after_trigger`, `test_stop_hit_after_trigger`, `test_no_revert_at_close_when_session_ends_mid_dislocation`) fail because the computed z lands on the wrong side of a threshold, print the actual `trigger_z` / intermediate z via a quick debug run and widen the fixture's multiplier (e.g. `2.5 * _STD` → `3.0 * _STD`) rather than changing the threshold constants — the qualitative structure (trigger, then recover / keep-falling / plateau) is what's under test.

- [ ] **Step 5: Commit**

```bash
git add backend/quant/analytics/ backend/tests/quant/test_vega_reversion_validator.py
git commit -m "feat: add vega-scalp IV reversion outcome classifier + aggregator"
```

---

## Task 4: Historical IV backfill script

**Files:**
- Create: `backend/scripts/backfill_iv_history.py`
- Test: `backend/tests/test_backfill_iv_history.py`

**Interfaces:**
- Consumes: `implied_volatility` (Task 1), `IvHistoryStore` (Task 2), `UniverseEnricher`, `select_preferred_expiry`, `expiry_to_breeze_iso`, `_expiry_to_date` from `backend/services/universe_enrichment.py` (gives ATM strike/expiry/`stock_code` resolution without hardcoding vendor-specific stock codes), `IciciDirectMarketDataAdapter` from `backend/integrations/icici_direct/market_data.py`.
- Produces: `run_backfill(*, symbols=PILOT_UNDERLYINGS, lookback_days=30, force=False, sleep_sec=0.75, adapter=None, store=None, instruments=None) -> BackfillStats`, `PILOT_UNDERLYINGS: tuple[str, ...]`, CLI `main()`.

**Caveat to preserve in the file's module docstring:** the `historicalcharts` option-specific request fields (`expiry_date`, `right`, `strike_price` alongside `interval`/`from_date`/`to_date`) follow this codebase's existing `get_quotes`/`get_option_chain` field-naming convention, but no existing caller in this repo exercises `historicalcharts` for options — verify against `https://api.icicidirect.com/breezeapi/documents/index.html#historicalcharts` before running against a live Breeze session.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_backfill_iv_history.py
"""backend/scripts/backfill_iv_history.py — script wiring tests (fake adapter, no network)."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from backend.integrations.icici_direct.instrument_master import InstrumentMaster
from backend.scripts.backfill_iv_history import PILOT_UNDERLYINGS, run_backfill
from backend.services.iv_history_store import IvHistoryStore


def _future_expiry(days: int = 10) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%d-%b-%Y")


def _fonse_zip(expiry: str) -> bytes:
    # Column shape mirrors the working fixture in backend/tests/test_universe_enrichment.py.
    fonse = (
        "Token,InstrumentName,ShortName,Series,ExpiryDate,StrikePrice,OptionType,"
        "LotSize,TickSize,CompanyName,ExchangeCode\n"
        f"30453,OPTSTK,RELIND,OPTION,{expiry},2800,CE,250,0.05,RELIANCE INDUSTRIES,RELIANCE\n"
        f"30454,OPTSTK,RELIND,OPTION,{expiry},2800,PE,250,0.05,RELIANCE INDUSTRIES,RELIANCE\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("FONSEScripMaster.txt", fonse)
        zf.writestr("NSEScripMaster.txt", "Token,ShortName,Series\n1,RELIANCE,EQ\n")
    return buf.getvalue()


class _FakeTick:
    def __init__(self, ltp: float) -> None:
        self.ltp = ltp


class _FakeClient:
    """Fakes the ICICI Direct API client's get_historical_charts."""

    def __init__(self, *, bar_times: list[datetime]) -> None:
        self.bar_times = bar_times
        self.calls: list[dict] = []

    async def get_historical_charts(self, params: dict) -> dict:
        self.calls.append(params)
        if params.get("exchange_code") == "NFO":
            rows = [{"datetime": t.isoformat(), "close": 42.0} for t in self.bar_times]
        else:
            rows = [{"datetime": t.isoformat(), "close": 2800.0} for t in self.bar_times]
        return {"Success": rows}


class _FakeSession:
    def __init__(self, client: _FakeClient) -> None:
        self._client = client

    async def ensure_session(self):
        return self._client


class _FakeMD:
    def __init__(self, *, session: _FakeSession, client: _FakeClient) -> None:
        self.session_manager = session
        self._client = client
        self.chain_calls = 0

    async def get_ltp(self, exchange: str, tradingsymbol: str, symboltoken=None):
        return _FakeTick(2800.0)

    async def get_option_chain(self, **kwargs):
        self.chain_calls += 1
        return [
            {
                "strike_price": 2800.0, "right": "Call", "ltp": 42.0,
                "best_bid_price": 41.5, "best_offer_price": 42.5,
                "total_quantity_traded": "12000", "open_interest": 30000,
                "spot_price": "2800", "stock_code": "RELIND",
            },
            {
                "strike_price": 2800.0, "right": "Put", "ltp": 40.0,
                "best_bid_price": 39.5, "best_offer_price": 40.5,
                "total_quantity_traded": "11000", "open_interest": 28000,
                "spot_price": "2800", "stock_code": "RELIND",
            },
        ]

    async def get_candles(self, *, exchange, symboltoken, interval, from_date, to_date, stock_code=None):
        payload = await self._client.get_historical_charts(
            {
                "stock_code": stock_code or symboltoken,
                "exchange_code": exchange,
                "interval": interval,
                "from_date": from_date,
                "to_date": to_date,
                "product_type": "cash",
            }
        )
        success = payload.get("Success")
        return list(success) if isinstance(success, list) else []


def _fixture_master() -> InstrumentMaster:
    master = InstrumentMaster()
    master.load_from_zip_bytes(_fonse_zip(_future_expiry(10)))
    return master


def test_pilot_universe_is_small():
    assert 3 <= len(PILOT_UNDERLYINGS) <= 5


@pytest.mark.asyncio
async def test_backfill_writes_iv_rows_within_call_budget(tmp_path):
    master = _fixture_master()
    bar_times = [datetime.now(timezone.utc) - timedelta(minutes=5 * i) for i in range(3)]
    client = _FakeClient(bar_times=bar_times)
    md = _FakeMD(session=_FakeSession(client), client=client)
    store = IvHistoryStore(store_path=tmp_path / "iv_history.json")

    stats = await run_backfill(
        symbols=("RELIANCE",), lookback_days=1, force=False, sleep_sec=0.0,
        adapter=md, store=store, instruments=master,  # type: ignore[arg-type]
    )

    assert stats.symbols_failed == 0
    assert stats.bars_written == 3
    assert md.chain_calls >= 1
    assert len(client.calls) == 2  # 1 option-premium call + 1 underlying-candle call

    written = store.series(symbol="RELIANCE", session_date=bar_times[0].date().isoformat())
    assert len(written) == 3


@pytest.mark.asyncio
async def test_backfill_rerun_without_force_is_idempotent(tmp_path):
    master = _fixture_master()
    bar_times = [datetime.now(timezone.utc)]
    client = _FakeClient(bar_times=bar_times)
    md = _FakeMD(session=_FakeSession(client), client=client)
    store = IvHistoryStore(store_path=tmp_path / "iv_history.json")

    await run_backfill(
        symbols=("RELIANCE",), lookback_days=1, force=False, sleep_sec=0.0,
        adapter=md, store=store, instruments=master,  # type: ignore[arg-type]
    )
    first = store.series(symbol="RELIANCE", session_date=bar_times[0].date().isoformat())

    stats2 = await run_backfill(
        symbols=("RELIANCE",), lookback_days=1, force=False, sleep_sec=0.0,
        adapter=md, store=store, instruments=master,  # type: ignore[arg-type]
    )
    second = store.series(symbol="RELIANCE", session_date=bar_times[0].date().isoformat())

    assert stats2.bars_written == 0
    assert second == first


@pytest.mark.asyncio
async def test_backfill_force_rewrites_even_if_present(tmp_path):
    master = _fixture_master()
    bar_times = [datetime.now(timezone.utc)]
    client = _FakeClient(bar_times=bar_times)
    md = _FakeMD(session=_FakeSession(client), client=client)
    store = IvHistoryStore(store_path=tmp_path / "iv_history.json")

    await run_backfill(
        symbols=("RELIANCE",), lookback_days=1, force=False, sleep_sec=0.0,
        adapter=md, store=store, instruments=master,  # type: ignore[arg-type]
    )
    stats2 = await run_backfill(
        symbols=("RELIANCE",), lookback_days=1, force=True, sleep_sec=0.0,
        adapter=md, store=store, instruments=master,  # type: ignore[arg-type]
    )
    assert stats2.bars_written == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_backfill_iv_history.py -v`
Expected: FAIL (`ModuleNotFoundError: backend.scripts.backfill_iv_history`)

- [ ] **Step 3: Write the implementation**

```python
# backend/scripts/backfill_iv_history.py
"""Backfill historical intraday IV into iv_history.json for a small pilot
universe (Docs/superpowers/specs/2026-08-02-vega-reversion-evidence-design.md).

Breeze does not expose historical implied volatility directly — only
historical option premium candles. This script fetches ATM-call premium
candles + underlying spot candles for each pilot symbol's current expiry,
and inverts each bar to IV via backend/quant/pricing/implied_vol.py, then
appends into the same iv_history.json store the live path writes
(backend/services/iv_history_store.py) — same schema, so the validator and
production iv_zscore.py don't need to know the data's origin.

CAVEAT: the option-specific historicalcharts request fields below
(expiry_date/right/strike_price alongside interval/from_date/to_date) follow
this codebase's existing get_quotes/get_option_chain field-naming
convention, but no existing caller in this repo exercises historicalcharts
for *options* — verify against
https://api.icicidirect.com/breezeapi/documents/index.html#historicalcharts
before running against a live Breeze session (CLAUDE.md: don't invent
vendor request shapes).

Usage (from repo root):
  python -m backend.scripts.backfill_iv_history [--force] [--lookback-days N]

Requires the same .env credentials as connect_icici_direct.py.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.quant.pricing.implied_vol import implied_volatility
from backend.services.iv_history_store import IvHistoryStore
from backend.services.universe_enrichment import (
    UniverseEnricher,
    _expiry_to_date,
    expiry_to_breeze_iso,
)

# Pilot universe — small on purpose (Design §Scope). NSE tradingsymbols; ATM
# strike / expiry / Breeze stock_code are resolved live per symbol via
# UniverseEnricher, not hardcoded, so this list never needs vendor-specific
# stock codes.
PILOT_UNDERLYINGS: tuple[str, ...] = ("NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK", "INFY")

CANDLE_INTERVAL = "5minute"
DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_SLEEP_SEC = 0.75
# Matches BSMInputs' decimal convention (bsm.py _as_decimal_rate); no live
# rates feed exists yet, so this is a fixed approximation like the OSS
# defaults elsewhere in the pricer.
RISK_FREE_RATE_PCT = 7.0
DIVIDEND_YIELD_PCT = 0.0


@dataclass
class BackfillStats:
    symbols_attempted: int = 0
    symbols_failed: int = 0
    bars_written: int = 0
    errors: list[str] = field(default_factory=list)


def _parse_close(row: Any) -> float | None:
    if not isinstance(row, dict):
        return None
    for key in ("close", "Close", "CLOSE", "c"):
        if key in row and row[key] is not None:
            try:
                v = float(row[key])
            except (TypeError, ValueError):
                return None
            return v if v > 0 else None
    return None


def _parse_bar_ts(row: Any) -> datetime | None:
    if not isinstance(row, dict):
        return None
    for key in ("datetime", "Datetime", "date", "Date"):
        raw = row.get(key)
        if not raw:
            continue
        text = str(raw).replace("Z", "+00:00").replace(" ", "T")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            continue
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


async def _fetch_option_premium_bars(
    adapter: Any,
    *,
    stock_code: str,
    expiry_iso: str,
    strike: float,
    from_date: str,
    to_date: str,
    sleep_sec: float,
) -> list[dict[str, Any]]:
    client = await adapter.session_manager.ensure_session()
    await asyncio.sleep(sleep_sec)
    payload = await client.get_historical_charts(
        {
            "stock_code": stock_code,
            "exchange_code": "NFO",
            "product_type": "options",
            "expiry_date": expiry_iso,
            "right": "call",
            "strike_price": str(int(strike)),
            "interval": CANDLE_INTERVAL,
            "from_date": from_date,
            "to_date": to_date,
        }
    )
    success = payload.get("Success")
    return list(success) if isinstance(success, list) else []


async def _fetch_underlying_bars(
    adapter: Any,
    *,
    stock_code: str,
    from_date: str,
    to_date: str,
    sleep_sec: float,
) -> list[dict[str, Any]]:
    await asyncio.sleep(sleep_sec)
    return await adapter.get_candles(
        exchange="NSE",
        symboltoken=stock_code,
        interval=CANDLE_INTERVAL,
        from_date=from_date,
        to_date=to_date,
        stock_code=stock_code,
    )


async def backfill_symbol(
    adapter: Any,
    store: IvHistoryStore,
    enricher: UniverseEnricher,
    *,
    symbol: str,
    lookback_days: int,
    force: bool,
    sleep_sec: float,
    stats: BackfillStats,
) -> None:
    stats.symbols_attempted += 1
    marks = await enricher.enrich_one(symbol)
    if marks is None or marks.expiry is None or marks.atm_strike is None:
        stats.symbols_failed += 1
        stats.errors.append(f"{symbol}: could not resolve ATM strike/expiry")
        return

    expiry_dt = _expiry_to_date(marks.expiry)
    expiry_iso = expiry_to_breeze_iso(marks.expiry)
    if expiry_dt is None or expiry_iso is None:
        stats.symbols_failed += 1
        stats.errors.append(f"{symbol}: unparseable expiry {marks.expiry!r}")
        return

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=lookback_days)
    from_date = start.strftime("%Y-%m-%dT03:45:00.000Z")
    to_date = now.strftime("%Y-%m-%dT10:00:00.000Z")
    stock_code = marks.stock_code or symbol

    try:
        option_bars = await _fetch_option_premium_bars(
            adapter, stock_code=stock_code, expiry_iso=expiry_iso,
            strike=marks.atm_strike, from_date=from_date, to_date=to_date,
            sleep_sec=sleep_sec,
        )
        underlying_bars = await _fetch_underlying_bars(
            adapter, stock_code=stock_code, from_date=from_date, to_date=to_date,
            sleep_sec=sleep_sec,
        )
    except Exception as exc:  # noqa: BLE001
        stats.symbols_failed += 1
        stats.errors.append(f"{symbol}: historical fetch failed: {exc}")
        return

    spot_by_ts: dict[str, float] = {}
    for row in underlying_bars:
        ts = _parse_bar_ts(row)
        close = _parse_close(row)
        if ts is not None and close is not None:
            spot_by_ts[ts.isoformat()] = close

    skip_sessions: dict[str, bool] = {}
    for row in option_bars:
        ts = _parse_bar_ts(row)
        premium = _parse_close(row)
        if ts is None or premium is None:
            continue
        session_date = ts.date().isoformat()
        if session_date not in skip_sessions:
            existing = store.series(symbol=symbol, session_date=session_date)
            skip_sessions[session_date] = bool(existing) and not force
        if skip_sessions[session_date]:
            continue

        spot = spot_by_ts.get(ts.isoformat())
        if spot is None:
            continue
        time_years = max((expiry_dt - ts).total_seconds(), 0.0) / (365.0 * 86400.0)
        if time_years <= 0:
            continue
        iv = implied_volatility(
            market_price=premium,
            spot=spot,
            strike=marks.atm_strike,
            time_years=time_years,
            rate=RISK_FREE_RATE_PCT / 100.0,
            dividend_yield=DIVIDEND_YIELD_PCT / 100.0,
            option_type="call",
        )
        if iv is None:
            continue
        store.append(symbol=symbol, session_date=session_date, ts_iso=ts.isoformat(), iv=iv)
        stats.bars_written += 1


async def run_backfill(
    *,
    symbols: tuple[str, ...] = PILOT_UNDERLYINGS,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    force: bool = False,
    sleep_sec: float = DEFAULT_SLEEP_SEC,
    adapter: Any | None = None,
    store: IvHistoryStore | None = None,
    instruments: Any | None = None,
) -> BackfillStats:
    if adapter is None:
        from backend.integrations.icici_direct.market_data import get_market_data_adapter

        adapter = get_market_data_adapter()
    store = store or IvHistoryStore()
    enricher = UniverseEnricher(market_data=adapter, instruments=instruments)
    stats = BackfillStats()
    for symbol in symbols:
        await backfill_symbol(
            adapter, store, enricher, symbol=symbol, lookback_days=lookback_days,
            force=force, sleep_sec=sleep_sec, stats=stats,
        )
    return stats


async def main() -> int:
    from backend.config_env import load_project_env
    from backend.integrations.credential_vault import load_icici_direct_credentials
    from backend.integrations.icici_direct.session_manager import get_session_manager

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    args = parser.parse_args()

    load_project_env()
    load_icici_direct_credentials()
    session_mgr = get_session_manager()
    if not session_mgr.credentials_ready():
        print(
            "Missing ICICI Direct credentials — see backend/scripts/connect_icici_direct.py",
            file=sys.stderr,
        )
        return 1

    stats = await run_backfill(lookback_days=args.lookback_days, force=args.force)
    print(f"attempted={stats.symbols_attempted} failed={stats.symbols_failed} bars_written={stats.bars_written}")
    for err in stats.errors:
        print(f"  error: {err}", file=sys.stderr)
    return 0 if stats.symbols_failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_backfill_iv_history.py -v`
Expected: PASS (4 tests). If `UniverseEnricher.__init__` rejects `instruments=None` implicitly resolving a *different* default than expected, or `stock_code_for_underlying("RELIANCE")` doesn't resolve to `"RELIND"` from the fixture, inspect `backend/integrations/icici_direct/instrument_master.py`'s `stock_code_for_underlying` / `list_options` and adjust the fixture's `ExchangeCode` column (last CSV column) — it must equal the symbol string passed to `run_backfill` (mirrors the proven `SBIN`/`STABAN` pairing in `backend/tests/test_universe_enrichment.py`).

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/backfill_iv_history.py backend/tests/test_backfill_iv_history.py
git commit -m "feat: add pilot-universe historical IV backfill script"
```

---

## Task 5: Evidence report generator

**Files:**
- Create: `backend/scripts/run_vega_reversion_validation.py`
- Test: `backend/tests/test_run_vega_reversion_validation.py`

**Interfaces:**
- Consumes: `find_reversion_events`, `aggregate_reversion_events` (Task 3), `IvHistoryStore.all_series()` (Task 2).
- Produces: `run(*, store=None) -> dict` (JSON-serializable aggregate payload), `render_markdown(payload: dict) -> str`, `main() -> int` writing `Docs/bot_health/vega_reversion_evidence.md` + `.json`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_run_vega_reversion_validation.py
"""run_vega_reversion_validation.py — report generation tests."""

from __future__ import annotations

from backend.scripts.run_vega_reversion_validation import render_markdown, run
from backend.services.iv_history_store import IvHistoryStore


def _seed_reverting_session(store: IvHistoryStore, *, symbol: str, session_date: str) -> None:
    mean, std = 0.30, 0.02
    baseline = [mean - std, mean + std] * 100
    trigger = [mean - 2.5 * std]
    recover = [mean]
    for i, iv in enumerate(baseline + trigger + recover):
        store.append(symbol=symbol, session_date=session_date, ts_iso=f"t{i}", iv=iv)


def test_run_reports_insufficient_sample_with_thin_data(tmp_path):
    store = IvHistoryStore(store_path=tmp_path / "iv_history.json")
    _seed_reverting_session(store, symbol="NIFTY", session_date="2026-08-01")

    payload = run(store=store)
    assert payload["total_events"] == 1
    assert payload["insufficient_sample"] is True
    assert payload["sessions_scanned"] == 1


def test_run_aggregates_across_multiple_sessions(tmp_path):
    store = IvHistoryStore(store_path=tmp_path / "iv_history.json")
    _seed_reverting_session(store, symbol="NIFTY", session_date="2026-08-01")
    _seed_reverting_session(store, symbol="BANKNIFTY", session_date="2026-08-01")

    payload = run(store=store)
    assert payload["total_events"] == 2
    assert payload["reverted"] == 2
    assert set(payload["per_symbol"]) == {"NIFTY", "BANKNIFTY"}


def test_render_markdown_flags_insufficient_sample():
    payload = {
        "generated_at": "2026-08-02T00:00:00+00:00",
        "sessions_scanned": 1,
        "total_events": 1,
        "reverted": 1,
        "stop_hit": 0,
        "no_revert_at_close": 0,
        "reverted_pct": 1.0,
        "stop_hit_pct": 0.0,
        "no_revert_at_close_pct": 0.0,
        "insufficient_sample": True,
        "min_sample_size": 30,
        "per_symbol": {"NIFTY": {"REVERTED": 1, "STOP_HIT": 0, "NO_REVERT_AT_CLOSE": 0}},
        "bars_to_revert_distribution": [1],
    }
    md = render_markdown(payload)
    assert "INSUFFICIENT SAMPLE" in md
    assert "NIFTY" in md


def test_render_markdown_omits_banner_when_sufficient():
    payload = {
        "generated_at": "2026-08-02T00:00:00+00:00",
        "sessions_scanned": 40,
        "total_events": 40,
        "reverted": 30,
        "stop_hit": 5,
        "no_revert_at_close": 5,
        "reverted_pct": 0.75,
        "stop_hit_pct": 0.125,
        "no_revert_at_close_pct": 0.125,
        "insufficient_sample": False,
        "min_sample_size": 30,
        "per_symbol": {},
        "bars_to_revert_distribution": [],
    }
    md = render_markdown(payload)
    assert "INSUFFICIENT SAMPLE" not in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_run_vega_reversion_validation.py -v`
Expected: FAIL (`ModuleNotFoundError: backend.scripts.run_vega_reversion_validation`)

- [ ] **Step 3: Write the implementation**

```python
# backend/scripts/run_vega_reversion_validation.py
"""Generate Docs/bot_health/vega_reversion_evidence.md (+ .json) from
accumulated iv_history.json, using
backend/quant/analytics/vega_reversion_validator.py.

Usage (from repo root):
  python -m backend.scripts.run_vega_reversion_validation
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from backend.quant.analytics.vega_reversion_validator import (
    aggregate_reversion_events,
    find_reversion_events,
)
from backend.services.iv_history_store import IvHistoryStore

REPORT_MD_PATH = Path(__file__).resolve().parents[2] / "Docs" / "bot_health" / "vega_reversion_evidence.md"
REPORT_JSON_PATH = REPORT_MD_PATH.with_suffix(".json")


def run(*, store: IvHistoryStore | None = None) -> dict:
    store = store or IvHistoryStore()
    all_series = store.all_series()
    events = []
    for key, series in all_series.items():
        symbol, session_date = key.split("|", 1)
        events.extend(find_reversion_events(series, symbol=symbol, session_date=session_date))
    aggregate = aggregate_reversion_events(events)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sessions_scanned": len(all_series),
        "total_events": aggregate.total_events,
        "reverted": aggregate.reverted,
        "stop_hit": aggregate.stop_hit,
        "no_revert_at_close": aggregate.no_revert_at_close,
        "reverted_pct": aggregate.reverted_pct,
        "stop_hit_pct": aggregate.stop_hit_pct,
        "no_revert_at_close_pct": aggregate.no_revert_at_close_pct,
        "insufficient_sample": aggregate.insufficient_sample,
        "min_sample_size": aggregate.min_sample_size,
        "per_symbol": aggregate.per_symbol,
        "bars_to_revert_distribution": aggregate.bars_to_revert_distribution,
    }


def _pct(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "n/a"


def render_markdown(payload: dict) -> str:
    lines = [
        "# Vega scalping — IV mean-reversion evidence",
        "",
        f"Generated: {payload['generated_at']}",
        f"Sessions scanned: {payload['sessions_scanned']}",
        "",
    ]
    if payload["insufficient_sample"]:
        lines += [
            f"> **INSUFFICIENT SAMPLE** — {payload['total_events']} -2sigma trigger "
            f"event(s) observed, below the {payload['min_sample_size']} needed for a "
            "meaningful hit-rate. Do not cite this as validated evidence yet.",
            "",
        ]
    lines += [
        "## Methodology",
        "",
        "Replays each session's intraday IV history through the same rolling "
        "z-score logic as `backend/quant/signals/iv_zscore.py` to find every "
        "point the live -2sigma entry would have fired, then classifies the "
        "outcome per `Docs/Trading_Strategies.md` Table VS-2 Rule 7 (stop at "
        "3sigma below mean) and same-day flattening: REVERTED (z >= -0.5 "
        "before stopping out), STOP_HIT (z <= -3.0 before reverting), or "
        "NO_REVERT_AT_CLOSE (neither, by session end).",
        "",
        "## Results",
        "",
        f"- Total -2sigma trigger events: {payload['total_events']}",
        f"- REVERTED: {payload['reverted']} ({_pct(payload['reverted_pct'])})",
        f"- STOP_HIT: {payload['stop_hit']} ({_pct(payload['stop_hit_pct'])})",
        f"- NO_REVERT_AT_CLOSE: {payload['no_revert_at_close']} "
        f"({_pct(payload['no_revert_at_close_pct'])})",
        "",
        "### Per symbol",
        "",
        "| Symbol | REVERTED | STOP_HIT | NO_REVERT_AT_CLOSE |",
        "|---|---|---|---|",
    ]
    for symbol, counts in sorted(payload["per_symbol"].items()):
        lines.append(
            f"| {symbol} | {counts.get('REVERTED', 0)} | "
            f"{counts.get('STOP_HIT', 0)} | {counts.get('NO_REVERT_AT_CLOSE', 0)} |"
        )
    lines += ["", "Raw aggregate: `vega_reversion_evidence.json`."]
    return "\n".join(lines) + "\n"


def main() -> int:
    payload = run()
    REPORT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD_PATH.write_text(render_markdown(payload), encoding="utf-8")
    REPORT_JSON_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {REPORT_MD_PATH}")
    print(f"wrote {REPORT_JSON_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_run_vega_reversion_validation.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/run_vega_reversion_validation.py backend/tests/test_run_vega_reversion_validation.py
git commit -m "feat: generate vega-scalp IV reversion evidence report"
```

---

## Task 6: Generate initial report, update backlog + strategy docs

**Files:**
- Modify: `Docs/bot_health/BACKLOG.md:23-25`
- Modify: `Docs/Trading_Strategies.md` (near line 573, the Vega Scalping Core Thesis paragraph)
- Create (generated, not hand-written): `Docs/bot_health/vega_reversion_evidence.md`, `Docs/bot_health/vega_reversion_evidence.json`

- [ ] **Step 1: Generate the initial evidence report from whatever real data exists today**

Run: `python -m backend.scripts.run_vega_reversion_validation`

This runs against the current (thin) `backend/data/iv_history.json` — expect an `INSUFFICIENT SAMPLE` report since real accumulated history is still only a couple of sessions. That's the correct, honest output at this point; it becomes the evidence trail's first entry. (Running `backend.scripts.backfill_iv_history` first, against live Breeze credentials, is a separate manual step outside this plan — Task 4 ships the tool; actually running it live requires the operator's `.env` credentials and is not part of an automated test run.)

- [ ] **Step 2: Update the P1 backlog bullet**

In `Docs/bot_health/BACKLOG.md`, replace the existing "No walk-forward/OOS replay evidence..." P1 bullet (lines 23-25) with:

```markdown
- [ ] No walk-forward/OOS replay evidence exists yet for SH-4 expectancy
  claims — blocked on the P0-1 item above producing real closed trades to
  replay against. (first seen 2026-08-02)
- [ ] Vega-scalp IV mean-reversion hit-rate is measured but evidence is thin:
  see `Docs/bot_health/vega_reversion_evidence.md` (generated by
  `backend.scripts.run_vega_reversion_validation`) — re-run after
  `backend.scripts.backfill_iv_history` accumulates more real sessions, and
  after live paper-trading accumulates its own `iv_history.json` history.
  Do not cite a hit-rate as validated while that report says
  `insufficient_sample`. (first seen 2026-08-02, evidence: `backend/quant/analytics/vega_reversion_validator.py`)
```

- [ ] **Step 3: Cross-reference the evidence path from the strategy doc**

In `Docs/Trading_Strategies.md`, immediately after the Core Thesis paragraph for Vega Scalping (the sentence ending "...revert toward its mean." — the one near "### Core Thesis" under "## Strategy 3: Vega Scalping"), add one line:

```markdown
Empirical hit-rate evidence for this assumption (measured, not assumed) is tracked in `Docs/bot_health/vega_reversion_evidence.md`, generated by `backend.scripts.run_vega_reversion_validation`.
```

Do not alter the existing "probabilistic, not a guarantee" framing elsewhere in the doc — this is additive only.

- [ ] **Step 4: Run the full backend test suite**

Run: `pytest -m "not integration"`
Expected: all tests pass, including the 5 new test files from Tasks 1-5.

- [ ] **Step 5: Commit**

```bash
git add Docs/bot_health/BACKLOG.md Docs/Trading_Strategies.md Docs/bot_health/vega_reversion_evidence.md Docs/bot_health/vega_reversion_evidence.json
git commit -m "docs: link vega-scalp IV reversion evidence report from backlog and strategy doc"
```

---

## Post-plan note (not a task — informational)

Running `backend.scripts.backfill_iv_history` against live Breeze requires:
1. Verifying the `historicalcharts` option-fields request shape against the vendor doc (flagged in Task 4).
2. `.env` ICICI Direct credentials + a registered static IP (per `CLAUDE.md`'s Breeze vendor constraints).

Until that's run (and/or live paper-trading accumulates enough sessions organically), `Docs/bot_health/vega_reversion_evidence.md` will keep reporting `insufficient_sample` — which is the intended, honest behavior, not a bug.
