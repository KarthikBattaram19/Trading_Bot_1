# Gamma Scalping Vega-Neutral Structure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the `gamma_scalping` opening structure in `backend/paper_sim/structure_builder.py` so it actually matches `Docs/Trading_Strategies.md` Table GS-4 — a same-strike, two-expiry calendar spread (long near-dated CE+PE, short far-dated CE+PE sized to zero portfolio vega) — instead of today's same-side, same-expiry double straddle.

**Architecture:** `structure_builder.py` gains one new async leg-construction helper that resolves a longer-dated expiry, computes near/far call vega via the existing `backend/quant/pricing/bsm.py` BSM Greeks (same flat-vol convention `paper_sim/automation.py` already uses for live position marking), solves the short quantity, and appends `SELL` legs. Everything fails closed to "near-dated straddle only" on any missing data — never to the old broken double-straddle.

**Tech Stack:** Python 3, FastAPI/Pydantic (`backend/paper_sim/models.py`), pytest + pytest-asyncio (`asyncio_mode=auto`).

## Global Constraints

- Options-only hard lock: no leg construction may ever produce a cash/NSE/BSE underlying leg (existing invariant in this file — do not weaken it).
- No new fields on `PaperOrderRequest`/`PaperLegRequest`/`PaperPosition` — this fix is log-only for residual Greeks observability (spec §2 step 7, "Out of scope").
- Reuse the existing flat-vol BSM convention (`PaperSimConfig.risk_free_rate_pct` / `.dividend_yield_pct` / `.default_iv_annual_pct`) — do not introduce a second Greeks/IV convention.
- Reuse the existing expiry-date parser (`backend.services.universe_enrichment._dte_from_expiry` / `_expiry_to_date`) — do not write a second date parser (this codebase has a documented history of exactly this bug class, e.g. the `candle_history.py` interval-string fix in `Improve_Recoemmendation_Engine.md` §3.13).
- Every new failure path must fail closed (append nothing further) and log a `logger.warning` — never raise, matching this file's existing style.
- Config default for the new min-gap threshold is `28` days (source: `Docs/Trading_Strategies.md` Table GS-1's 35-DTE-vs-63-DTE reference pair) and must be identical between the JSON default, the schema, and any in-code fallback (this codebase has a documented bug class from exactly this kind of drift — §3.8 of `Improve_Recoemmendation_Engine.md`, the `min_eligible_symbols` 50-vs-20 mismatch).

Spec: `Docs/superpowers/specs/2026-08-06-gamma-scalping-vega-neutral-structure-design.md`

---

### Task 1: Config key for the long-expiry minimum gap

**Files:**
- Modify: `backend/config/trading_parameters.defaults.json`
- Modify: `backend/schemas/trading_parameters.schema.json`
- Test: `backend/tests/test_trading_parameters_config.py` (create if it doesn't already assert full-file JSON validity; otherwise add to whichever existing test loads this file)

**Interfaces:**
- Produces: `trading_parameters.defaults.json` key path
  `strategies.gamma_scalping.calendar_construction.long_expiry_min_gap_days` = `28` (int), consumed by Task 3.

- [ ] **Step 1: Check whether a config-loading test already exists**

Run: `grep -rn "trading_parameters.defaults.json" backend/tests/*.py`

If a test already loads and `json.load()`s the defaults file (even indirectly via `load_trading_config()`), reuse it for Step 2 instead of creating a new file. If none exists, create `backend/tests/test_trading_parameters_config.py`.

- [ ] **Step 2: Write the failing test**

```python
"""Sanity checks on backend/config/trading_parameters.defaults.json."""

from __future__ import annotations

from backend.services.strategy_selection import load_trading_config


def test_gamma_scalping_calendar_construction_min_gap_days_present():
    cfg = load_trading_config()
    gap = cfg["strategies"]["gamma_scalping"]["calendar_construction"]["long_expiry_min_gap_days"]
    assert gap == 28
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest backend/tests/test_trading_parameters_config.py -v`
Expected: FAIL with `KeyError: 'calendar_construction'`

- [ ] **Step 4: Add the config key**

In `backend/config/trading_parameters.defaults.json`, inside the existing
`strategies.gamma_scalping` object (the one that already has `enabled`,
`gamma_entry_mode`, `construction`, `option_selection`, `entry_signal`), add
a new sibling key:

```json
      "calendar_construction": {
        "long_expiry_min_gap_days": 28
      },
```

Place it directly after the existing `"entry_signal": { ... }` block inside
`strategies.gamma_scalping` (before the block's closing `}`).

- [ ] **Step 5: Add the schema definition**

In `backend/schemas/trading_parameters.schema.json`, inside `$defs.GammaScalpingStrategy.properties` (the object that currently has `enabled`, `gamma_entry_mode`, `construction`, `option_selection`, `vega_neutral_tolerance`, `min_net_gamma`), add:

```json
        "calendar_construction": {
          "type": "object",
          "properties": {
            "long_expiry_min_gap_days": { "type": "integer", "minimum": 1 }
          }
        }
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest backend/tests/test_trading_parameters_config.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/config/trading_parameters.defaults.json backend/schemas/trading_parameters.schema.json backend/tests/test_trading_parameters_config.py
git commit -m "Add gamma_scalping.calendar_construction.long_expiry_min_gap_days config"
```

---

### Task 2: Far-expiry resolver

**Files:**
- Modify: `backend/paper_sim/structure_builder.py`
- Test: `backend/tests/test_structure_builder.py` (new file)

**Interfaces:**
- Consumes: `backend.services.universe_enrichment._dte_from_expiry(raw: str, *, now: datetime | None = None) -> int` (existing, reused as-is — do not reimplement).
- Produces: `_resolve_far_expiry(feed: Any, *, name: str, near_expiry: str | None, min_gap_days: int) -> tuple[str, int] | None` in `structure_builder.py`, consumed by Task 3.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_structure_builder.py`:

```python
"""Unit tests for backend/paper_sim/structure_builder.py's gamma_scalping
vega-neutral calendar-spread construction (Docs/Trading_Strategies.md Table GS-4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.integrations.icici_direct.models import InstrumentRecord, NormalizedTick
from backend.paper_sim.structure_builder import _resolve_far_expiry


def _expiry_str(days_from_now: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=days_from_now)
    return dt.strftime("%d-%b-%Y")


class _ChainFeed:
    """Minimal feed stub exposing only list_options, for resolver-level tests."""

    def __init__(self, records: list[InstrumentRecord]) -> None:
        self._records = records

    def list_options(self, *, name, exchange="NFO", expiry=None, limit=500):
        rows = [r for r in self._records if (r.name or "").upper() == name.upper()]
        return rows[:limit]


def _opt(expiry: str, strike: float, right: str, token: str) -> InstrumentRecord:
    return InstrumentRecord(
        exchange="NFO",
        tradingsymbol=f"SBIN{token}{right}",
        symboltoken=token,
        name="SBIN",
        expiry=expiry,
        strike=strike,
        lotsize=25,
        instrumenttype="OPTSTK",
    )


def test_resolve_far_expiry_picks_nearest_expiry_clearing_the_gap():
    near = _expiry_str(15)
    just_short = _expiry_str(15 + 27)  # gap 27 < 28, must be skipped
    far = _expiry_str(15 + 30)  # gap 30 >= 28
    farther = _expiry_str(15 + 60)  # gap 60 >= 28, but not nearest
    feed = _ChainFeed(
        [
            _opt(near, 500.0, "CE", "1"),
            _opt(just_short, 500.0, "CE", "2"),
            _opt(far, 500.0, "CE", "3"),
            _opt(farther, 500.0, "CE", "4"),
        ]
    )
    result = _resolve_far_expiry(feed, name="SBIN", near_expiry=near, min_gap_days=28)
    assert result is not None
    resolved_expiry, resolved_dte = result
    assert resolved_expiry == far


def test_resolve_far_expiry_returns_none_when_no_expiry_clears_the_gap():
    near = _expiry_str(15)
    only_short = _expiry_str(15 + 10)
    feed = _ChainFeed([_opt(near, 500.0, "CE", "1"), _opt(only_short, 500.0, "CE", "2")])
    result = _resolve_far_expiry(feed, name="SBIN", near_expiry=near, min_gap_days=28)
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_structure_builder.py -v`
Expected: FAIL with `ImportError: cannot import name '_resolve_far_expiry'`

- [ ] **Step 3: Implement `_resolve_far_expiry`**

In `backend/paper_sim/structure_builder.py`, add near the top (after the
existing imports, before `_SIMPLE_VOL_TAGS`):

```python
from backend.services.universe_enrichment import _dte_from_expiry
```

Then add the new function after `_find_matching_option` (end of file):

```python
def _resolve_far_expiry(
    feed: Any,
    *,
    name: str,
    near_expiry: str | None,
    min_gap_days: int,
) -> tuple[str, int] | None:
    """Nearest listed expiry with DTE >= near-leg DTE + ``min_gap_days``.

    Table GS-1: use a near/far separation comparable to the source's 35-DTE-
    vs-63-DTE reference pair; too small a gap leaves nothing to hedge with.
    """
    near_dte = _dte_from_expiry(near_expiry or "")
    records = feed.list_options(name=name, exchange="NFO", limit=5000)
    expiries: dict[str, int] = {}
    for rec in records:
        if not rec.expiry:
            continue
        dte = _dte_from_expiry(rec.expiry)
        key = rec.expiry
        if key not in expiries or dte < expiries[key]:
            expiries[key] = dte
    candidates = [
        (exp, dte) for exp, dte in expiries.items() if dte >= near_dte + min_gap_days
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[1], x[0]))
    return candidates[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_structure_builder.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/paper_sim/structure_builder.py backend/tests/test_structure_builder.py
git commit -m "Add far-expiry resolver for gamma_scalping calendar spread"
```

---

### Task 3: Vega-solved far-dated leg pair

**Files:**
- Modify: `backend/paper_sim/structure_builder.py`
- Test: `backend/tests/test_structure_builder.py`

**Interfaces:**
- Consumes: `_resolve_far_expiry` (Task 2); `backend.quant.pricing.bsm.BSMInputs.from_api(*, und_price, strike, days_to_expiry, int_rate, div_yield, volatility, option_type, day_count=365) -> BSMInputs` and `option_greeks(inputs: BSMInputs) -> dict[str, float]` (existing, unmodified); `backend.paper_sim.config.PaperSimConfig` fields `risk_free_rate_pct`, `dividend_yield_pct`, `default_iv_annual_pct` (existing); `_find_matching_option` (existing, unmodified).
- Produces: `async def _append_vega_neutral_far_dated_pair(intended, *, feed, first, record, underlying, qty, paper_sim_config, min_gap_days) -> None`, consumed by Task 4.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_structure_builder.py`:

```python
import pytest

from backend.paper_sim.config import PaperSimConfig
from backend.paper_sim.models import PaperLegRequest, PaperSide
from backend.paper_sim.structure_builder import _append_vega_neutral_far_dated_pair
from backend.quant.pricing.bsm import BSMInputs, option_greeks


SPOT = 500.0


class _FullFeed(_ChainFeed):
    """Adds resolve/get_ltp so the vega-solve path can run end to end."""

    def __init__(self, records: list[InstrumentRecord], *, underlying_token: str = "U1") -> None:
        super().__init__(records)
        self._underlying = InstrumentRecord(
            exchange="NSE",
            tradingsymbol="SBIN",
            symboltoken=underlying_token,
            name="SBIN",
            lotsize=1,
            instrumenttype="EQ",
        )

    def resolve(self, *, exchange=None, tradingsymbol=None, symboltoken=None):
        if tradingsymbol and tradingsymbol.upper() == "SBIN" and (exchange is None or exchange.upper() == "NSE"):
            return self._underlying
        for rec in self._records:
            if symboltoken and rec.symboltoken == symboltoken:
                return rec
            if tradingsymbol and rec.tradingsymbol.upper() == tradingsymbol.upper():
                return rec
        return None

    async def get_ltp(self, exchange, tradingsymbol, symboltoken=None):
        return NormalizedTick(
            exchange=exchange,
            symbol=tradingsymbol,
            provider_symbol_id=symboltoken or "U1",
            ltp=SPOT,
            ts=datetime.now(timezone.utc),
        )


def _entry_leg(expiry: str) -> tuple[PaperLegRequest, InstrumentRecord]:
    record = _opt(expiry, SPOT, "CE", "N1")
    leg = PaperLegRequest(
        symbol=record.tradingsymbol,
        side=PaperSide.buy,
        quantity=record.lotsize,
        exchange="NFO",
        symbol_token=record.symboltoken,
        option_type="CE",
        strike=SPOT,
        expiry=expiry,
    )
    return leg, record


@pytest.mark.asyncio
async def test_append_vega_neutral_far_dated_pair_appends_sell_legs():
    near_expiry = _expiry_str(15)
    far_expiry = _expiry_str(15 + 35)
    feed = _FullFeed(
        [
            _opt(near_expiry, SPOT, "CE", "N1"),
            _opt(near_expiry, SPOT, "PE", "N2"),
            _opt(far_expiry, SPOT, "CE", "F1"),
            _opt(far_expiry, SPOT, "PE", "F2"),
        ]
    )
    first, record = _entry_leg(near_expiry)
    intended: list[PaperLegRequest] = [first]

    await _append_vega_neutral_far_dated_pair(
        intended,
        feed=feed,
        first=first,
        record=record,
        underlying="SBIN",
        qty=first.quantity,
        paper_sim_config=PaperSimConfig(),
        min_gap_days=28,
    )

    assert len(intended) == 2
    far_legs = intended[1:]
    assert {lg.option_type for lg in far_legs} == {"CE", "PE"}
    for lg in far_legs:
        assert lg.side == PaperSide.sell
        assert lg.expiry == far_expiry
        assert lg.strike == SPOT

    # The two far legs must carry identical quantity (GS-4 step 4: mirror, not re-solve).
    assert far_legs[0].quantity == far_legs[1].quantity

    # Quantity must actually be vega-solved, not a 1:1 copy of the near leg's
    # quantity — same spot/strike/rate/yield/vol at two different DTEs always
    # gives a different vega, so a correct solve can't land back on 1:1 here.
    assert far_legs[0].quantity != first.quantity


@pytest.mark.asyncio
async def test_append_vega_neutral_far_dated_pair_skips_when_no_far_expiry():
    near_expiry = _expiry_str(15)
    feed = _FullFeed([_opt(near_expiry, SPOT, "CE", "N1"), _opt(near_expiry, SPOT, "PE", "N2")])
    first, record = _entry_leg(near_expiry)
    intended: list[PaperLegRequest] = [first]

    await _append_vega_neutral_far_dated_pair(
        intended,
        feed=feed,
        first=first,
        record=record,
        underlying="SBIN",
        qty=first.quantity,
        paper_sim_config=PaperSimConfig(),
        min_gap_days=28,
    )

    assert intended == [first]


@pytest.mark.asyncio
async def test_append_vega_neutral_far_dated_pair_skips_on_degenerate_vega(monkeypatch):
    """Even when a far expiry clears the min-gap check, a degenerate (~0)
    far vega must still fail closed to no-append, not a division blow-up
    or a nonsense quantity."""
    near_expiry = _expiry_str(15)
    far_expiry = _expiry_str(15 + 35)
    feed = _FullFeed(
        [
            _opt(near_expiry, SPOT, "CE", "N1"),
            _opt(near_expiry, SPOT, "PE", "N2"),
            _opt(far_expiry, SPOT, "CE", "F1"),
            _opt(far_expiry, SPOT, "PE", "F2"),
        ]
    )
    first, record = _entry_leg(near_expiry)
    intended: list[PaperLegRequest] = [first]

    import backend.paper_sim.structure_builder as sb

    real_option_greeks = sb.option_greeks

    def _fake_option_greeks(inputs):
        result = real_option_greeks(inputs)
        if inputs.time_years * 365.0 > 40:  # the far leg
            result = dict(result, vega=0.0)
        return result

    monkeypatch.setattr(sb, "option_greeks", _fake_option_greeks)

    await _append_vega_neutral_far_dated_pair(
        intended,
        feed=feed,
        first=first,
        record=record,
        underlying="SBIN",
        qty=first.quantity,
        paper_sim_config=PaperSimConfig(),
        min_gap_days=28,
    )

    assert intended == [first]


@pytest.mark.asyncio
async def test_append_vega_neutral_far_dated_pair_reduces_net_vega():
    """GS-4 step 5: the solved structure's net vega must be materially
    smaller than the unhedged near-only straddle's vega — proves the solve
    actually neutralizes vega, not just that it runs without error."""
    near_expiry = _expiry_str(15)
    far_expiry = _expiry_str(15 + 35)
    feed = _FullFeed(
        [
            _opt(near_expiry, SPOT, "CE", "N1"),
            _opt(near_expiry, SPOT, "PE", "N2"),
            _opt(far_expiry, SPOT, "CE", "F1"),
            _opt(far_expiry, SPOT, "PE", "F2"),
        ]
    )
    first, record = _entry_leg(near_expiry)
    intended: list[PaperLegRequest] = [first]
    cfg = PaperSimConfig()

    await _append_vega_neutral_far_dated_pair(
        intended,
        feed=feed,
        first=first,
        record=record,
        underlying="SBIN",
        qty=first.quantity,
        paper_sim_config=cfg,
        min_gap_days=28,
    )
    assert len(intended) == 3  # entry + 2 far legs

    near_dte = _dte_from_expiry(near_expiry)
    far_dte = _dte_from_expiry(far_expiry)

    def _vega(days: int, option_type: str) -> float:
        inputs = BSMInputs.from_api(
            und_price=SPOT,
            strike=SPOT,
            days_to_expiry=days,
            int_rate=cfg.risk_free_rate_pct,
            div_yield=cfg.dividend_yield_pct,
            volatility=cfg.default_iv_annual_pct,
            option_type=option_type,
        )
        return option_greeks(inputs)["vega"]

    near_lotsize = record.lotsize
    near_contracts = first.quantity // near_lotsize
    far_contracts = intended[1].quantity // record.lotsize

    unhedged_vega = near_contracts * (_vega(near_dte, "call") + _vega(near_dte, "put"))
    net_vega = unhedged_vega - far_contracts * (_vega(far_dte, "call") + _vega(far_dte, "put"))

    assert abs(net_vega) < abs(unhedged_vega) * 0.25
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_structure_builder.py -v`
Expected: FAIL with `ImportError: cannot import name '_append_vega_neutral_far_dated_pair'`

- [ ] **Step 3: Implement `_append_vega_neutral_far_dated_pair`**

In `backend/paper_sim/structure_builder.py`, add near the top:

```python
import logging
from math import isfinite

from backend.paper_sim.config import PaperSimConfig
from backend.quant.pricing.bsm import BSMInputs, option_greeks

logger = logging.getLogger(__name__)
```

(Merge with any existing imports rather than duplicating — `Any` is already
imported from `typing`; `PaperLegRequest`/`PaperSide` already imported from
`backend.paper_sim.models`.)

Add the function after `_resolve_far_expiry`:

```python
async def _append_vega_neutral_far_dated_pair(
    intended: list[PaperLegRequest],
    *,
    feed: Any,
    first: PaperLegRequest,
    record: Any,
    underlying: str | None,
    qty: int,
    paper_sim_config: PaperSimConfig,
    min_gap_days: int,
) -> None:
    """Short a longer-dated CE/PE pair sized to zero portfolio vega.

    Table GS-4 steps 3-4: solve the short-dated/long-dated call pair for
    vega neutrality first, then mirror the identical quantity into puts
    (delta identity in step 4's callout) rather than re-solving both sides
    independently.
    """
    strike = float(record.strike or 0.0)
    if strike <= 0:
        return
    name = (record.name or underlying or "").upper()

    near_dte = _dte_from_expiry(record.expiry or "")
    far = _resolve_far_expiry(feed, name=name, near_expiry=record.expiry, min_gap_days=min_gap_days)
    if far is None:
        logger.warning(
            "gamma_scalping calendar skip: no far expiry >= near_dte(%d)+%d days for %s",
            near_dte,
            min_gap_days,
            name,
        )
        return
    far_expiry, far_dte = far

    und_rec = feed.resolve(exchange="NSE", tradingsymbol=(underlying or name).upper())
    if und_rec is None:
        und_rec = feed.resolve(tradingsymbol=(underlying or name).upper())
    if und_rec is None:
        logger.warning("gamma_scalping calendar skip: no underlying spot record for %s", name)
        return
    tick = await feed.get_ltp(und_rec.exchange, und_rec.tradingsymbol, und_rec.symboltoken)
    spot = float(tick.ltp)
    if spot <= 0:
        return

    def _greeks(days: float, option_type: str) -> dict[str, float]:
        inputs = BSMInputs.from_api(
            und_price=spot,
            strike=strike,
            days_to_expiry=days,
            int_rate=paper_sim_config.risk_free_rate_pct,
            div_yield=paper_sim_config.dividend_yield_pct,
            volatility=paper_sim_config.default_iv_annual_pct,
            option_type=option_type,  # type: ignore[arg-type]
        )
        return option_greeks(inputs)

    near_call = _greeks(near_dte, "call")
    far_call = _greeks(far_dte, "call")
    vega_far = far_call["vega"]
    if not isfinite(vega_far) or abs(vega_far) < 1e-9:
        logger.warning(
            "gamma_scalping calendar skip: degenerate far vega (%s) for %s far_expiry=%s",
            vega_far,
            name,
            far_expiry,
        )
        return

    near_lotsize = max(int(record.lotsize or 1), 1)
    near_contracts = max(int(qty // near_lotsize), 1) if qty >= near_lotsize else 1
    far_contracts = max(round(near_contracts * near_call["vega"] / vega_far), 1)

    appended: list[PaperLegRequest] = []
    for want in ("CE", "PE"):
        pair = _find_matching_option(feed, name=name, expiry=far_expiry, strike=strike, option_type=want)
        if pair is None:
            logger.warning(
                "gamma_scalping calendar skip leg: no %s at strike=%.2f expiry=%s for %s",
                want,
                strike,
                far_expiry,
                name,
            )
            continue
        far_lotsize = max(int(pair.lotsize or near_lotsize), 1)
        leg = PaperLegRequest(
            symbol=pair.tradingsymbol,
            side=PaperSide.sell,
            quantity=far_contracts * far_lotsize,
            exchange=pair.exchange,
            symbol_token=pair.symboltoken,
            option_type=want,  # type: ignore[arg-type]
            strike=float(pair.strike) if pair.strike is not None else None,
            expiry=pair.expiry,
        )
        intended.append(leg)
        appended.append(leg)

    if len(appended) == 2:
        near_put = _greeks(near_dte, "put")
        far_put = _greeks(far_dte, "put")
        residual_delta = near_contracts * (near_call["delta"] + near_put["delta"]) - far_contracts * (
            far_call["delta"] + far_put["delta"]
        )
        residual_vega = near_contracts * (near_call["vega"] + near_put["vega"]) - far_contracts * (
            far_call["vega"] + far_put["vega"]
        )
        logger.info(
            "gamma_scalping calendar solve symbol=%s strike=%.2f near_dte=%d far_dte=%d "
            "vega_near_call=%.4f vega_far_call=%.4f near_contracts=%d far_contracts=%d "
            "residual_delta=%.4f residual_vega=%.4f",
            name,
            strike,
            near_dte,
            far_dte,
            near_call["vega"],
            vega_far,
            near_contracts,
            far_contracts,
            residual_delta,
            residual_vega,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_structure_builder.py -v`
Expected: PASS (6 passed — the 2 resolver tests from Task 2 plus the 4 new
tests in this task)

- [ ] **Step 5: Commit**

```bash
git add backend/paper_sim/structure_builder.py backend/tests/test_structure_builder.py
git commit -m "Add vega-solved far-dated leg pair for gamma_scalping calendar spread"
```

---

### Task 4: Wire into `build_intended_legs_from_entry`, remove the old double-straddle path

**Files:**
- Modify: `backend/paper_sim/structure_builder.py`
- Modify: `backend/paper_sim/engine.py:279-291`
- Modify: `backend/tests/test_paper_sim_options_only.py:129-139` (existing sync test → async)
- Test: `backend/tests/test_structure_builder.py`

**Interfaces:**
- Consumes: `_append_vega_neutral_far_dated_pair` (Task 3), `backend.services.strategy_selection.load_trading_config` (existing).
- Produces: `async def build_intended_legs_from_entry(*, strategy_tag, underlying, entry_legs, feed, paper_sim_config=None) -> list[PaperLegRequest]` — signature changes from sync to async and gains one optional kwarg; every existing caller must add `await`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_structure_builder.py`:

```python
from backend.paper_sim.structure_builder import build_intended_legs_from_entry


@pytest.mark.asyncio
async def test_build_intended_legs_gamma_scalping_produces_four_leg_calendar():
    near_expiry = _expiry_str(15)
    far_expiry = _expiry_str(15 + 35)
    feed = _FullFeed(
        [
            _opt(near_expiry, SPOT, "CE", "N1"),
            _opt(near_expiry, SPOT, "PE", "N2"),
            _opt(far_expiry, SPOT, "CE", "F1"),
            _opt(far_expiry, SPOT, "PE", "F2"),
        ]
    )
    first, _record = _entry_leg(near_expiry)

    intended = await build_intended_legs_from_entry(
        strategy_tag="gamma_scalping",
        underlying="SBIN",
        entry_legs=[first],
        feed=feed,
        paper_sim_config=PaperSimConfig(),
    )

    assert len(intended) == 4
    by_side = {PaperSide.buy: 0, PaperSide.sell: 0}
    for lg in intended:
        by_side[lg.side] += 1
    assert by_side[PaperSide.buy] == 2
    assert by_side[PaperSide.sell] == 2
    sell_expiries = {lg.expiry for lg in intended if lg.side == PaperSide.sell}
    assert sell_expiries == {far_expiry}
    buy_expiries = {lg.expiry for lg in intended if lg.side == PaperSide.buy}
    assert buy_expiries == {near_expiry}


@pytest.mark.asyncio
async def test_build_intended_legs_gamma_scalping_falls_back_to_straddle_only():
    near_expiry = _expiry_str(15)
    feed = _FullFeed([_opt(near_expiry, SPOT, "CE", "N1"), _opt(near_expiry, SPOT, "PE", "N2")])
    first, _record = _entry_leg(near_expiry)

    intended = await build_intended_legs_from_entry(
        strategy_tag="gamma_scalping",
        underlying="SBIN",
        entry_legs=[first],
        feed=feed,
        paper_sim_config=PaperSimConfig(),
    )

    assert len(intended) == 2
    assert all(lg.side == PaperSide.buy for lg in intended)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_structure_builder.py -v`
Expected: FAIL — `build_intended_legs_from_entry` is still sync and still calls the old `_append_second_strike_option_pair`, so the 4-leg test gets a `TypeError` (awaiting a non-coroutine) or the wrong leg shape.

- [ ] **Step 3: Rewrite `build_intended_legs_from_entry` and delete the old function**

In `backend/paper_sim/structure_builder.py`:

1. Delete `_append_second_strike_option_pair` entirely (lines 202-256 in the
   original file — the same-side second-strike straddle builder this whole
   fix replaces).
2. Add the import: `from backend.services.strategy_selection import load_trading_config`
3. Replace `build_intended_legs_from_entry` with:

```python
async def build_intended_legs_from_entry(
    *,
    strategy_tag: str | None,
    underlying: str | None,
    entry_legs: list[PaperLegRequest],
    feed: Any,
    paper_sim_config: PaperSimConfig | None = None,
) -> list[PaperLegRequest]:
    """
    Infer the bot's intended multi-leg opening plan from strategy + first entry.

    - simple_volatility / vega_scalping: long ATM CE + PE (add missing option side)
    - gamma_scalping: same-strike calendar spread — long near-dated CE+PE,
      short far-dated CE+PE sized to zero portfolio vega
      (Docs/Trading_Strategies.md Table GS-4)
    - If entry already has 2+ legs, treat that basket as the intended structure
    """
    if len(entry_legs) >= 2:
        return list(entry_legs)

    if not strategy_implies_multi_leg(strategy_tag):
        return list(entry_legs)

    norm = normalize_strategy_tag(strategy_tag)
    intended = list(entry_legs)
    if not entry_legs:
        return intended

    first = entry_legs[0]
    qty = int(first.quantity)

    if _is_cash_leg(first.exchange, first.symbol):
        return intended

    record = _resolve_option_record(feed, first, underlying)
    if record is None:
        return intended

    if norm in {"simple_volatility", "vega_scalping"}:
        _append_opposite_option_at_strike(
            intended,
            feed=feed,
            first=first,
            record=record,
            underlying=underlying,
            qty=qty,
        )
    elif norm == "gamma_scalping":
        _append_opposite_option_at_strike(
            intended,
            feed=feed,
            first=first,
            record=record,
            underlying=underlying,
            qty=qty,
        )
        cfg = load_trading_config()
        min_gap_days = int(
            cfg.get("strategies", {})
            .get("gamma_scalping", {})
            .get("calendar_construction", {})
            .get("long_expiry_min_gap_days", 28)
        )
        await _append_vega_neutral_far_dated_pair(
            intended,
            feed=feed,
            first=first,
            record=record,
            underlying=underlying,
            qty=qty,
            paper_sim_config=paper_sim_config or PaperSimConfig(),
            min_gap_days=min_gap_days,
        )

    return intended
```

- [ ] **Step 4: Update the one production call site**

In `backend/paper_sim/engine.py`, in `submit_order` (around line 286):

```python
        elif strategy_implies_multi_leg(request.strategy_tag):
            intended = await build_intended_legs_from_entry(
                strategy_tag=request.strategy_tag,
                underlying=request.underlying,
                entry_legs=list(request.legs),
                feed=self.feed,
                paper_sim_config=self.config,
            )
```

(Only the two lines change: add `await` and the new `paper_sim_config=self.config` kwarg. `submit_order` is already `async def`, so no other signature changes are needed.)

- [ ] **Step 5: Fix the now-broken synchronous test**

In `backend/tests/test_paper_sim_options_only.py`, `test_build_intended_legs_gamma_vega_never_include_cash` (around line 129) currently calls `build_intended_legs_from_entry` without `await`. Change it to:

```python
@pytest.mark.asyncio
async def test_build_intended_legs_gamma_vega_never_include_cash():
    feed = FakeFeed()
    for tag in ("gamma_scalping", "vega_scalping"):
        intended = await build_intended_legs_from_entry(
            strategy_tag=tag,
            underlying="SBIN",
            entry_legs=_single_ce_leg(),
            feed=feed,
        )
        assert all(not _is_cash_leg(lg.exchange, lg.symbol) for lg in intended)
        assert all(lg.exchange.upper() == "NFO" for lg in intended)
```

(Add the `@pytest.mark.asyncio` decorator and `async`/`await` — no other
change. `FakeFeed` here only has one expiry, so for the `gamma_scalping`
iteration this now exercises the new "no far expiry" fallback path and
returns 2 legs instead of 4; the test doesn't assert leg count, only the
cash-leg/exchange invariant, so it still passes unchanged otherwise.)

- [ ] **Step 6: Run full test file to verify it passes**

Run: `pytest backend/tests/test_structure_builder.py backend/tests/test_paper_sim_options_only.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add backend/paper_sim/structure_builder.py backend/paper_sim/engine.py backend/tests/test_paper_sim_options_only.py backend/tests/test_structure_builder.py
git commit -m "Wire vega-neutral calendar spread into gamma_scalping structure building"
```

---

### Task 5: Fix the end-to-end fixture that now needs a real far-dated expiry

**Files:**
- Modify: `backend/tests/test_paper_sim_options_only.py:143-169` (`test_gamma_auto_complete_succeeds_with_nfo_legs_only`)

**Interfaces:**
- Consumes: `FakeFeed` (from `backend.tests.test_paper_sim`, unmodified — this task does not touch the shared fixture class, only adds instruments to a local subclass).

This is the one existing end-to-end test that drives a full `gamma_scalping`
auto-complete through `PaperEngine.submit_order` and asserts on the final
4-leg structure. `FakeFeed`'s shared `SBIN28MAR24500CE`/`PE` instruments use
a literal, long-since-past expiry string (`"28MAR2024"`) that (a) doesn't
even match `_expiry_to_date`'s parseable formats and (b) — even if it did —
is now stale, so it would always fail the min-gap check and produce the
2-leg fallback instead of 4. Rather than touch the shared `FakeFeed` (used
by 40+ other assertions across multiple files that key off its exact
symbols/tokens), this task adds a local subclass with a realistic
relative-future near/far expiry pair, scoped to this one test.

- [ ] **Step 1: Write the updated test (replaces the existing one)**

In `backend/tests/test_paper_sim_options_only.py`, replace the existing
`test_gamma_auto_complete_succeeds_with_nfo_legs_only` (and the
`_single_ce_leg` helper stays as-is, still used by Task 4's test) with:

```python
from datetime import datetime, timedelta, timezone

from backend.integrations.icici_direct.models import InstrumentRecord


def _relative_expiry(days_from_now: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=days_from_now)
    return dt.strftime("%d-%b-%Y")


class _GammaCalendarFeed(FakeFeed):
    """FakeFeed + a real near/far expiry pair for SBIN 500-strike options,
    so the gamma_scalping vega-solve path has real data to work with."""

    def __init__(self) -> None:
        super().__init__()
        near = _relative_expiry(15)
        far = _relative_expiry(15 + 35)
        # Override the shared near-dated 500-strike CE/PE with a real DTE
        # (the base FakeFeed's literal "28MAR2024" doesn't parse as a real
        # date and is long past regardless).
        self.instruments["40123"] = self.instruments["40123"].model_copy(
            update={"expiry": near}
        )
        self.instruments["40124"] = self.instruments["40124"].model_copy(
            update={"expiry": near}
        )
        self.instruments["50001"] = InstrumentRecord(
            exchange="NFO",
            tradingsymbol="SBIN" + far.replace("-", "").upper() + "500CE",
            symboltoken="50001",
            name="SBIN",
            expiry=far,
            strike=500.0,
            lotsize=25,
            instrumenttype="OPTSTK",
        )
        self.instruments["50002"] = InstrumentRecord(
            exchange="NFO",
            tradingsymbol="SBIN" + far.replace("-", "").upper() + "500PE",
            symboltoken="50002",
            name="SBIN",
            expiry=far,
            strike=500.0,
            lotsize=25,
            instrumenttype="OPTSTK",
        )
        self.ltps["50001"] = 25.0
        self.ltps["50002"] = 24.0


@pytest.mark.asyncio
async def test_gamma_auto_complete_succeeds_with_nfo_legs_only():
    feed = _GammaCalendarFeed()
    engine = get_paper_engine(
        feed=feed,
        config=PaperSimConfig(slippage_bps=0),
        reset=True,
    )
    result = await engine.submit_order(
        PaperOrderRequest(
            strategy_tag="gamma_scalping",
            underlying="SBIN",
            auto_complete_multi_leg=True,
            legs=_single_ce_leg(),
        )
    )
    assert result["success"] is True
    completion = result["multi_leg_completion"]
    assert completion is not None
    assert completion["structure_complete"] is True
    position = result["position"]
    assert position["structure_complete"] is True
    assert len(position["legs"]) == 4
    for leg in position["legs"]:
        assert leg["exchange"] == "NFO"
    symbols = {leg["symbol"] for leg in position["legs"]}
    assert "SBIN" not in symbols
    sides = {leg["symbol"]: leg["side"] for leg in position["legs"]}
    near_legs = [s for s, side in sides.items() if s in {"SBIN28MAR24500CE", "SBIN28MAR24500PE"}]
    far_legs = [s for s in sides if s not in near_legs]
    assert len(near_legs) == 2
    assert all(sides[s] == "buy" for s in near_legs)
    assert len(far_legs) == 2
    assert all(sides[s] == "sell" for s in far_legs)
```

- [ ] **Step 2: Run test to verify it fails first (confirms it exercises the new code path)**

Run: `pytest "backend/tests/test_paper_sim_options_only.py::test_gamma_auto_complete_succeeds_with_nfo_legs_only" -v`

If Task 4 is already committed, this should already PASS at this point
(Tasks 2-4 implemented the production code first). If it fails, diagnose
against Task 3/4's implementation before proceeding — do not weaken this
test's assertions to make it pass.

- [ ] **Step 3: Run it to confirm PASS**

Run: `pytest "backend/tests/test_paper_sim_options_only.py::test_gamma_auto_complete_succeeds_with_nfo_legs_only" -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_paper_sim_options_only.py
git commit -m "Give gamma_scalping auto-complete test a real near/far expiry pair"
```

---

### Task 6: Full backend suite + stale double-straddle regression guard

**Files:**
- Test: `backend/tests/test_structure_builder.py`

**Interfaces:**
- Consumes: everything from Tasks 1-5.

- [ ] **Step 1: Add a regression guard against the old broken structure**

Add to `backend/tests/test_structure_builder.py` — this is the test that
would have caught `Improve_Recoemmendation_Engine.md` §3.10 directly, per
that document's own §6 test-coverage-gap table:

```python
@pytest.mark.asyncio
async def test_gamma_scalping_never_produces_same_side_second_strike_straddle():
    """Regression guard for Improve_Recoemmendation_Engine.md §3.10: the old
    implementation added a same-side (BUY), same-expiry second straddle at a
    different strike. The correct structure never has a second strike at
    all — only the entry strike, across two expiries."""
    near_expiry = _expiry_str(15)
    far_expiry = _expiry_str(15 + 35)
    feed = _FullFeed(
        [
            _opt(near_expiry, SPOT, "CE", "N1"),
            _opt(near_expiry, SPOT, "PE", "N2"),
            _opt(far_expiry, SPOT, "CE", "F1"),
            _opt(far_expiry, SPOT, "PE", "F2"),
        ]
    )
    first, _record = _entry_leg(near_expiry)

    intended = await build_intended_legs_from_entry(
        strategy_tag="gamma_scalping",
        underlying="SBIN",
        entry_legs=[first],
        feed=feed,
        paper_sim_config=PaperSimConfig(),
    )

    strikes = {lg.strike for lg in intended}
    assert strikes == {SPOT}
    assert not any(lg.side == PaperSide.buy and lg.expiry == far_expiry for lg in intended)
```

- [ ] **Step 2: Run the new test**

Run: `pytest backend/tests/test_structure_builder.py -v`
Expected: all PASS

- [ ] **Step 3: Run the full backend suite**

Run: `pytest -m "not integration"`
Expected: all PASS, no regressions in unrelated modules (this touches
`structure_builder.py` and `engine.py`, both shared by `simple_volatility`/
`vega_scalping` code paths — confirm those still pass unchanged).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_structure_builder.py
git commit -m "Add regression guard against the old same-side double-straddle structure"
```

---

### Task 7: Close out the audit tracker

**Files:**
- Modify: `Improve_Recoemmendation_Engine.md`

- [ ] **Step 1: Mark §3.10 and its two references resolved**

In `Improve_Recoemmendation_Engine.md`:
- In §3.10's heading, append ` — ✅ FIXED 2026-08-06` (matching the file's
  existing convention for resolved items, e.g. §3.1/§3.2/§3.4/§3.13).
- Add a `**Resolution:**` paragraph immediately after the existing finding
  text (do not delete the original finding — same "never delete history"
  convention the file states in its header), summarizing: far-dated
  calendar leg pair added via `_append_vega_neutral_far_dated_pair`,
  BSM-vega-solved quantity, mirrored puts, config-driven min DTE gap
  (`strategies.gamma_scalping.calendar_construction.long_expiry_min_gap_days`),
  fails closed to near-dated-straddle-only when data is missing, tests in
  `backend/tests/test_structure_builder.py`.
- In §2.2's mermaid diagram, move `F310` from the `HIGH` subgraph to a
  resolved-items note consistent with how `F313`/`F34` (already-fixed items)
  are annotated in that same diagram (their labels carry
  `— ✅ FIXED 2026-08-04` inline).
- In §8's priority-ordered mermaid diagram, no structural change needed —
  leave `P111` in place but note in the surrounding prose (the numbered list
  under the diagram, item 11) that it is done.

- [ ] **Step 2: Commit**

```bash
git add Improve_Recoemmendation_Engine.md
git commit -m "Mark §3.10 gamma_scalping calendar-spread fix resolved in audit tracker"
```
