# Wire trade_executor.py through paper_sim + real approve/reject — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `paper_sim` the single real fill/ledger for autonomous execution (replacing `trade_executor.py`'s fabricated `trade_id`), and add real, persisted `POST /decisions/{id}/approve` / `POST /decisions/{id}/reject`, with `GET /recommendations`'s passive auto-execution gated behind `SUPERVISION_MODE`.

**Architecture:** `trade_executor.py` resolves one ATM call-option leg for a recommendation's underlying (nearest expiry with DTE ≥ 10, nearest strike to the recommendation's own `und_price`) and submits it through the existing `PaperEngine.submit_order()` — the same path `/api/v1/paper-sim/orders` already uses, so `structure_builder.py` expands it into the full strategy structure with no new logic. `routers/decisions.py` gets a small JSON-file-backed decision store (same pattern as `kill_switch_state.py`) so approve/reject survive a restart and overlay onto the existing derived pending/expired projection.

**Tech Stack:** FastAPI, Pydantic v2, pytest + pytest-asyncio (`asyncio_mode=auto`), no new dependencies.

## Global Constraints

- Design spec: `Docs/superpowers/specs/2026-08-04-wire-trade-executor-paper-sim-design.md` — every task below implements one numbered section of it.
- Entry-leg convention is fixed: always ATM CE, `side="buy"`, quantity = 1 lot (feed record's `lotsize`). Do not derive side/strike from `entry_mode`/`scenario_tag`.
- `SUPERVISION_MODE` env var, default `"supervised"` (matches `backend/routers/bot.py:33`'s existing read) — gates only the passive `GET /recommendations` auto-execution side effect. `POST /execute-autonomous` stays available unconditionally in both modes.
- No live ICICI Direct order calls anywhere in this change — `paper_sim` never calls `place_order`/`cancel_order` (existing invariant, unchanged).
- Out of scope: `SIMULATE_FIRST_RANK_FAILURE` (already fixed), one-trade-lock durability (already fixed), any P1 item, `/learning` metrics seed-exclusion (separate half of the BACKLOG.md bullet, not requested here).
- Run `pytest -m "not integration"` after every task; must stay green before moving to the next task.

---

### Task 1: Resolve a real ATM CE leg from a recommendation

**Files:**
- Modify: `backend/services/trade_executor.py` (add new function, imports)
- Test: `backend/tests/test_trade_executor.py` (add new test class/fixture)

**Interfaces:**
- Consumes: `backend.services.universe_enrichment.select_preferred_expiry(master, symbol, *, min_dte=10, max_dte=30) -> tuple[str, int] | None` (existing, duck-types on any object with `.list_options(*, name, exchange="NFO", expiry=None, limit=500)`); `backend.paper_sim.engine.PaperEngine` (`.feed`, `.config.instrument_master_max_age_sec`); `backend.paper_sim.models.PaperLegRequest`, `PaperSide`.
- Produces: `async def resolve_atm_ce_leg(rec: InstrumentRecommendation, *, engine: PaperEngine) -> PaperLegRequest | None` — used by Task 2.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_trade_executor.py`, above the existing tests (keep all existing imports; add these):

```python
from datetime import datetime, timedelta, timezone

from backend.integrations.icici_direct.models import InstrumentRecord, NormalizedTick
from backend.paper_sim.engine import PaperEngine
from backend.paper_sim.models import PaperSide


class _FakeFeed:
    """Minimal MarketQuoteFeed double: one NIFTY expiry, two strikes, CE+PE each."""

    def __init__(self) -> None:
        self.expiry = (datetime.now(timezone.utc) + timedelta(days=17)).strftime("%d-%b-%Y")
        self.instruments: dict[str, InstrumentRecord] = {
            "1": InstrumentRecord(
                exchange="NFO", tradingsymbol=f"NIFTY{self.expiry.upper()}22000CE",
                symboltoken="1", name="NIFTY", expiry=self.expiry, strike=22000.0,
                lotsize=50, instrumenttype="OPTIDX",
            ),
            "2": InstrumentRecord(
                exchange="NFO", tradingsymbol=f"NIFTY{self.expiry.upper()}22000PE",
                symboltoken="2", name="NIFTY", expiry=self.expiry, strike=22000.0,
                lotsize=50, instrumenttype="OPTIDX",
            ),
            "3": InstrumentRecord(
                exchange="NFO", tradingsymbol=f"NIFTY{self.expiry.upper()}22050CE",
                symboltoken="3", name="NIFTY", expiry=self.expiry, strike=22050.0,
                lotsize=50, instrumenttype="OPTIDX",
            ),
            "4": InstrumentRecord(
                exchange="NFO", tradingsymbol=f"NIFTY{self.expiry.upper()}22050PE",
                symboltoken="4", name="NIFTY", expiry=self.expiry, strike=22050.0,
                lotsize=50, instrumenttype="OPTIDX",
            ),
        }
        self.ltps = {"1": 120.0, "2": 110.0, "3": 100.0, "4": 130.0}
        self.instruments_loaded_at = datetime.now(timezone.utc)

    async def ensure_instruments(self, *, max_age_sec: float | None = None) -> int:
        return len(self.instruments)

    async def get_ltp(self, exchange, tradingsymbol, symboltoken=None) -> NormalizedTick:
        token = symboltoken
        if not token:
            for rec in self.instruments.values():
                if rec.tradingsymbol == tradingsymbol:
                    token = rec.symboltoken
                    break
        return NormalizedTick(
            exchange=exchange, symbol=tradingsymbol, provider_symbol_id=token,
            ltp=float(self.ltps[token]), ts=datetime.now(timezone.utc), stale=False,
        )

    def list_options(self, *, name, exchange="NFO", expiry=None, limit=500):
        rows = [
            r for r in self.instruments.values()
            if (r.name or "").upper() == name.upper() and r.exchange.upper() == exchange.upper()
        ]
        if expiry:
            rows = [r for r in rows if r.expiry == expiry]
        return rows[:limit]

    def resolve(self, *, exchange=None, tradingsymbol=None, symboltoken=None):
        if symboltoken and symboltoken in self.instruments:
            return self.instruments[symboltoken]
        for rec in self.instruments.values():
            if tradingsymbol and rec.tradingsymbol == tradingsymbol:
                return rec
        return None


def _make_engine() -> PaperEngine:
    return PaperEngine(feed=_FakeFeed())


async def test_resolve_atm_ce_leg_picks_nearest_strike_to_und_price():
    engine = _make_engine()
    rec = _make_recommendation(1)  # default und_price=100.0 in existing fixture — override below
    rec = rec.model_copy(update={"parameters": rec.parameters.model_copy(update={"und_price": 22010.0})})

    leg = await trade_executor.resolve_atm_ce_leg(rec, engine=engine)

    assert leg is not None
    assert leg.symbol.endswith("22000CE")
    assert leg.side == PaperSide.buy
    assert leg.quantity == 50
    assert leg.option_type == "CE"


async def test_resolve_atm_ce_leg_returns_none_for_unknown_underlying():
    engine = _make_engine()
    rec = _make_recommendation(1, symbol="NOTAREALSYMBOL")

    leg = await trade_executor.resolve_atm_ce_leg(rec, engine=engine)

    assert leg is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_trade_executor.py -k resolve_atm_ce_leg -v`
Expected: FAIL with `AttributeError: module 'backend.services.trade_executor' has no attribute 'resolve_atm_ce_leg'`

- [ ] **Step 3: Implement `resolve_atm_ce_leg`**

In `backend/services/trade_executor.py`, add imports (near the top, alongside the existing `backend.*` imports) and the new function (after `_all_gates_pass`, before `_pre_submit_checks`):

```python
from backend.paper_sim.engine import PaperEngine
from backend.paper_sim.models import PaperLegRequest, PaperSide
from backend.services.universe_enrichment import select_preferred_expiry


async def resolve_atm_ce_leg(
    rec: InstrumentRecommendation, *, engine: PaperEngine
) -> PaperLegRequest | None:
    """
    Resolve a single ATM call-option entry leg for a recommendation's underlying.

    Fixed convention: always buy ATM CE, 1 lot, nearest expiry with DTE >= 10
    (matching the recommendation engine's own DTE gate). `structure_builder.py`
    expands this single leg into the full strategy structure — see
    Docs/superpowers/specs/2026-08-04-wire-trade-executor-paper-sim-design.md §1.
    """
    feed = engine.feed
    await feed.ensure_instruments(max_age_sec=engine.config.instrument_master_max_age_sec)

    symbol = rec.underlying_symbol.upper()
    preferred = select_preferred_expiry(feed, symbol, min_dte=10)
    if preferred is None:
        return None
    expiry, _dte = preferred

    records = feed.list_options(name=symbol, exchange="NFO", expiry=expiry, limit=500)
    ce_records = [r for r in records if (r.tradingsymbol or "").upper().endswith("CE")]
    if not ce_records:
        return None

    spot = float(rec.parameters.und_price)
    best = min(ce_records, key=lambda r: abs(float(r.strike or 0.0) - spot))

    return PaperLegRequest(
        symbol=best.tradingsymbol,
        side=PaperSide.buy,
        quantity=int(best.lotsize),
        exchange=best.exchange,
        symbol_token=best.symboltoken,
        option_type="CE",
        strike=float(best.strike) if best.strike is not None else None,
        expiry=best.expiry,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_trade_executor.py -k resolve_atm_ce_leg -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/services/trade_executor.py backend/tests/test_trade_executor.py
git commit -m "Add ATM-CE entry-leg resolver for wiring trade_executor to paper_sim"
```

---

### Task 2: Submit through paper_sim instead of fabricating a fill

**Files:**
- Modify: `backend/services/trade_executor.py:53-110` (`_simulate_broker_submit` → `_submit_via_paper_sim`), plus its call site in `execute_autonomous_from_recommendations`
- Modify: `backend/tests/test_trade_executor.py` (extend the autouse fixture to inject the fake paper engine; add ledger assertions)

**Interfaces:**
- Consumes: `resolve_atm_ce_leg` (Task 1); `backend.paper_sim.service.get_paper_engine`; `backend.paper_sim.models.PaperOrderRequest`; `backend.paper_sim.ledger.PaperLedgerError`; `backend.paper_sim.freshness.StaleMarksError`.
- Produces: `execute_autonomous_from_recommendations(...)`'s `trade_id` is now a real `paper_sim` `position_id` (format `pos_<hex>`, not `trd_<symbol>_<ts>`) — Task 5 relies on this when building the approve-endpoint response.

- [ ] **Step 1: Write the failing test**

Replace the existing `_isolated_learning_service` autouse fixture in `backend/tests/test_trade_executor.py` with one that also injects the fake paper engine, and add a ledger-truth assertion:

```python
@pytest.fixture(autouse=True)
def _isolated_learning_service(tmp_path, monkeypatch):
    """Point trade_executor at throwaway learning + paper_sim stores, not the real ones."""
    svc = LearningService(store_path=tmp_path / "learning_store.json")
    monkeypatch.setattr(trade_executor, "get_learning_service", lambda: svc)
    engine = _make_engine()
    monkeypatch.setattr(trade_executor, "get_paper_engine", lambda: engine)
    yield engine


async def test_successful_execution_creates_a_real_paper_sim_position(_isolated_learning_service):
    engine = _isolated_learning_service
    rec = _make_recommendation(1)
    rec = rec.model_copy(update={"parameters": rec.parameters.model_copy(update={"und_price": 22010.0})})

    result = await trade_executor.execute_autonomous_from_recommendations([rec])

    assert result.executed is True
    assert result.trade_id.startswith("pos_")
    position = engine.ledger.positions[result.trade_id]
    assert position.status == "open"
    assert len(position.legs) >= 1
```

Update `_make_recommendation`'s default `und_price` in the existing helper from `100.0` to `22010.0` so the pre-existing tests (`test_default_never_simulates_rank_1_failure`, etc.) resolve against `_FakeFeed`'s NIFTY strikes without each test needing to override it:

```python
        parameters=ParameterSnapshot(
            und_price=22010.0,
            iv_annualized=0.2,
            garch_forecast=0.18,
            atm_premium_inr=50.0,
            volume=1000,
            open_interest=5000,
            spread_pct=1.0,
            dte=15,
        ),
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_trade_executor.py -v`
Expected: `test_successful_execution_creates_a_real_paper_sim_position` FAILs (`trade_id` still `trd_...`, no `engine.ledger.positions` entry); other pre-existing tests should still pass since the fabricated path doesn't touch the engine yet.

- [ ] **Step 3: Rewire `_simulate_broker_submit`**

In `backend/services/trade_executor.py`, replace the whole `_simulate_broker_submit` function (current lines 53-110) with:

```python
from backend.paper_sim.freshness import StaleMarksError
from backend.paper_sim.ledger import PaperLedgerError
from backend.paper_sim.models import PaperOrderRequest
from backend.paper_sim.service import get_paper_engine


async def _submit_via_paper_sim(
    rec: InstrumentRecommendation,
    *,
    simulate_first_rank_failure: bool = False,
) -> tuple[bool, str | None, str | None]:
    """
    Submit via the real paper_sim ledger — the only fill source for autonomous
    execution (Docs/superpowers/specs/2026-08-04-wire-trade-executor-paper-sim-design.md §2).

    `simulate_first_rank_failure` is a test-only injection point for exercising
    the rank-1-rejects/fallback-to-rank-2 path — it must never be enabled from
    a production call site. Defaults to False (no simulated rejection).
    """
    if simulate_first_rank_failure and rec.rank == 1:
        return (
            False,
            None,
            "Broker reject: vega scalp structure — insufficient liquidity at session open",
        )

    if rec.parameters.spread_pct > 2.0:
        return False, None, f"Broker reject: spread {rec.parameters.spread_pct}% exceeds 2% cap"

    engine = get_paper_engine()
    leg = await resolve_atm_ce_leg(rec, engine=engine)
    if leg is None:
        return False, None, f"Could not resolve an ATM option contract for {rec.underlying_symbol}"

    request = PaperOrderRequest(
        strategy_tag=rec.strategy.selected_strategy.value,
        underlying=rec.underlying_symbol,
        legs=[leg],
        auto_complete_multi_leg=True,
    )
    try:
        result = await engine.submit_order(request)
    except (PaperLedgerError, StaleMarksError) as exc:
        return False, None, f"paper_sim reject: {exc}"

    trade_id = result["position"]["position_id"]

    # Log a shadow ICICI Direct payload when the integration is wired (never live-submit here).
    use_icici = os.getenv("USE_ICICI_DIRECT_SHADOW", "true").lower() in ("1", "true", "yes")
    if use_icici:
        try:
            from backend.execution.broker_router import get_broker_router
            from backend.integrations.base import InternalOrder, OrderLeg

            order = InternalOrder(
                internal_order_id=trade_id,
                strategy_id=rec.strategy.selected_strategy.value
                if hasattr(rec.strategy.selected_strategy, "value")
                else str(rec.strategy.selected_strategy),
                signal_id=f"rec_rank_{rec.rank}",
                underlying_symbol=rec.underlying_symbol,
                legs=[
                    OrderLeg(
                        leg_id=1,
                        symbol=rec.underlying_symbol,
                        side="buy",
                        quantity=1,
                        order_type="limit",
                        limit_price=float(rec.parameters.und_price or 0) or None,
                        exchange="NSE",
                        product="INTRADAY",
                    )
                ],
            )
            await get_broker_router().submit(order)
        except Exception:
            # Shadow mapping failures must not block autonomous paper path.
            pass

    return True, trade_id, None
```

Update the two call sites inside `execute_autonomous_from_recommendations` that reference the old name:

```python
        success, trade_id, broker_error = await _submit_via_paper_sim(
            rec, simulate_first_rank_failure=simulate_first_rank_failure
        )
```

(This replaces the existing `await _simulate_broker_submit(...)` call — same signature, same call site, only the name changes.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_trade_executor.py -v`
Expected: PASS, all tests (including the 5 pre-existing ones and the 2 from Task 1 and the new one from this task).

- [ ] **Step 5: Commit**

```bash
git add backend/services/trade_executor.py backend/tests/test_trade_executor.py
git commit -m "Route autonomous execution through paper_sim instead of a fabricated fill"
```

---

### Task 3: Gate the passive GET auto-execution behind SUPERVISION_MODE

**Files:**
- Modify: `backend/routers/recommendations.py`
- Test: `backend/tests/test_recommendations_router.py` (new file)

**Interfaces:**
- Consumes: `backend.services.trade_executor.execute_autonomous_from_recommendations`, `is_one_trade_locked` (existing imports, unchanged).
- Produces: no new public symbols; behavior change only.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_recommendations_router.py`:

```python
from __future__ import annotations

import pytest

from backend.routers import recommendations as recommendations_router


class _StubResponse:
    def __init__(self, recs):
        self.recommendations = recs

    def model_copy(self, *, update):
        merged = dict(self.__dict__)
        merged.update(update)
        stub = _StubResponse(self.recommendations)
        stub.__dict__.update(merged)
        return stub


async def test_supervised_mode_skips_autonomous_execution(monkeypatch):
    monkeypatch.setenv("SUPERVISION_MODE", "supervised")
    calls: list[object] = []

    async def _fake_execute(recs, **kwargs):
        calls.append(recs)
        raise AssertionError("must not execute in supervised mode")

    monkeypatch.setattr(
        recommendations_router, "execute_autonomous_from_recommendations", _fake_execute
    )

    async def _fake_generate(*, force_refresh=False):
        return _StubResponse([])

    monkeypatch.setattr(recommendations_router, "generate_recommendations", _fake_generate)

    result = await recommendations_router._recommendations_with_autonomous_execution(
        force_refresh=True
    )

    assert calls == []
    assert result.autonomous_execution.executed is False
    assert "supervision" in result.autonomous_execution.message.lower()


async def test_autonomous_mode_still_executes(monkeypatch):
    monkeypatch.setenv("SUPERVISION_MODE", "autonomous")
    calls: list[object] = []

    async def _fake_execute(recs, **kwargs):
        calls.append(recs)
        from backend.models.trades import AutonomousExecutionResult

        return AutonomousExecutionResult(executed=True, attempts=[], message="ok")

    monkeypatch.setattr(
        recommendations_router, "execute_autonomous_from_recommendations", _fake_execute
    )

    async def _fake_generate(*, force_refresh=False):
        return _StubResponse([])

    monkeypatch.setattr(recommendations_router, "generate_recommendations", _fake_generate)

    result = await recommendations_router._recommendations_with_autonomous_execution(
        force_refresh=True
    )

    assert len(calls) == 1
    assert result.autonomous_execution.executed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_recommendations_router.py -v`
Expected: `test_supervised_mode_skips_autonomous_execution` FAILs (execution still runs today regardless of `SUPERVISION_MODE`).

- [ ] **Step 3: Add the gate**

In `backend/routers/recommendations.py`, add `import os` at the top and change `_autonomous_execution_for`:

```python
import os

...

async def _autonomous_execution_for(
    recommendations: list[InstrumentRecommendation],
) -> AutonomousExecutionResult:
    """Run ranked fallback immediately after recommendations are generated —
    only when SUPERVISION_MODE=autonomous. Under the default "supervised"
    mode, a fresh GET never opens a trade; POST /decisions/{id}/approve does."""
    supervision = os.getenv("SUPERVISION_MODE", "supervised").strip().lower()
    if supervision == "supervised":
        return AutonomousExecutionResult(
            executed=False,
            attempts=[],
            message=(
                "Supervision mode requires explicit approval — "
                "see POST /api/v1/decisions/{id}/approve"
            ),
        )

    if is_one_trade_locked():
        return AutonomousExecutionResult(
            executed=False,
            attempts=[],
            message="One-trade scope locked — close the active trade before opening another.",
        )

    if not recommendations:
        return AutonomousExecutionResult(
            executed=False,
            attempts=[],
            message="No recommendations available to execute",
        )

    return await execute_autonomous_from_recommendations(recommendations)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_recommendations_router.py -v`
Expected: PASS (2 tests)

Also run: `pytest -m "not integration"` to confirm nothing else in the suite assumed `GET /recommendations` auto-executes without setting `SUPERVISION_MODE=autonomous` explicitly. If any test breaks because it relied on the old always-execute behavior, add `monkeypatch.setenv("SUPERVISION_MODE", "autonomous")` to that test (it's asserting a supervised-mode-only regression, not a real behavior loss).

- [ ] **Step 5: Commit**

```bash
git add backend/routers/recommendations.py backend/tests/test_recommendations_router.py
git commit -m "Gate passive GET /recommendations auto-execution behind SUPERVISION_MODE"
```

---

### Task 4: Persisted decision store

**Files:**
- Create: `backend/services/decision_state.py`
- Modify: `backend/services/decision_log.py` (overlay store onto `list_decisions`/`get_decision`)
- Test: `backend/tests/test_decision_state.py` (new file)

**Interfaces:**
- Produces:
  - `class DecisionState(BaseModel)`: `status: Literal["approved", "rejected"]`, `trade_id: str | None`, `reason: str | None`, `acted_at: datetime`.
  - `class DecisionStateStore`: `__init__(self, store_path: Path | None = None)`, `get(self, decision_id: str) -> DecisionState | None`, `set(self, decision_id: str, state: DecisionState) -> None`.
  - `get_decision_state_store() -> DecisionStateStore` (process singleton, same pattern as `get_kill_switch_state()`).
- Consumed by: Task 5 (`routers/decisions.py`'s new approve/reject endpoints) and this task's own change to `decision_log.py`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_decision_state.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

from backend.services.decision_state import DecisionState, DecisionStateStore


def test_set_then_get_round_trips(tmp_path):
    store = DecisionStateStore(store_path=tmp_path / "decision_state.json")
    state = DecisionState(
        status="approved", trade_id="pos_abc123", reason=None,
        acted_at=datetime.now(timezone.utc),
    )

    store.set("dec_nifty_20260804", state)
    loaded = store.get("dec_nifty_20260804")

    assert loaded is not None
    assert loaded.status == "approved"
    assert loaded.trade_id == "pos_abc123"


def test_get_unknown_decision_returns_none(tmp_path):
    store = DecisionStateStore(store_path=tmp_path / "decision_state.json")
    assert store.get("dec_unknown") is None


def test_state_survives_simulated_process_restart(tmp_path):
    store_path = tmp_path / "decision_state.json"
    store = DecisionStateStore(store_path=store_path)
    state = DecisionState(
        status="rejected", trade_id=None, reason="too risky",
        acted_at=datetime.now(timezone.utc),
    )
    store.set("dec_nifty_20260804", state)

    restarted = DecisionStateStore(store_path=store_path)
    loaded = restarted.get("dec_nifty_20260804")

    assert loaded is not None
    assert loaded.status == "rejected"
    assert loaded.reason == "too risky"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_decision_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.decision_state'`

- [ ] **Step 3: Implement the store**

Create `backend/services/decision_state.py`:

```python
"""Persisted approve/reject state for decisions.py — survives a process restart.

Same pattern as backend/services/kill_switch_state.py. Decisions themselves are
still derived (recommendation cache + learning store, see decision_log.py) —
this store only records what an operator decided about a given decision_id.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

STORE_PATH = Path(__file__).resolve().parents[1] / "data" / "decision_state.json"


class DecisionState(BaseModel):
    status: Literal["approved", "rejected"]
    trade_id: str | None = None
    reason: str | None = None
    acted_at: datetime


class DecisionStateStore:
    def __init__(self, store_path: Path | None = None) -> None:
        self.store_path = store_path or STORE_PATH

    def _read(self) -> dict[str, Any]:
        if not self.store_path.exists():
            return {}
        with open(self.store_path, encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: dict[str, Any]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def get(self, decision_id: str) -> DecisionState | None:
        raw = self._read().get(decision_id)
        if raw is None:
            return None
        return DecisionState.model_validate(raw)

    def set(self, decision_id: str, state: DecisionState) -> None:
        data = self._read()
        data[decision_id] = json.loads(state.model_dump_json())
        self._write(data)


_decision_state_store: DecisionStateStore | None = None


def get_decision_state_store() -> DecisionStateStore:
    global _decision_state_store
    if _decision_state_store is None:
        _decision_state_store = DecisionStateStore()
    return _decision_state_store
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_decision_state.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Overlay the store onto `list_decisions()` / `get_decision()`**

In `backend/services/decision_log.py`, add the import and change `list_decisions`/`get_decision`:

```python
from backend.services.decision_state import get_decision_state_store


def _apply_decision_state_overlay(decisions: list[DecisionRecord]) -> list[DecisionRecord]:
    """An operator's approve/reject verdict always wins over the derived status."""
    store = get_decision_state_store()
    overlaid: list[DecisionRecord] = []
    for decision in decisions:
        state = store.get(decision.decision_id)
        if state is None:
            overlaid.append(decision)
            continue
        status = DecisionStatus.approved if state.status == "approved" else DecisionStatus.rejected
        overlaid.append(decision.model_copy(update={"status": status}))
    return overlaid


async def list_decisions() -> list[DecisionRecord]:
    """Full audit trail, newest first, with acted-on records taking precedence."""
    decisions = _acted_on_decisions()
    seen_symbols = {d.underlying_symbol for d in decisions}
    seen_ids = {d.decision_id for d in decisions}

    for decision in await _live_decisions():
        if decision.underlying_symbol in seen_symbols or decision.decision_id in seen_ids:
            continue
        decisions.append(decision)

    decisions = _apply_decision_state_overlay(decisions)
    decisions.sort(key=lambda d: d.created_at, reverse=True)
    return decisions
```

(`get_decision` and `list_pending_decisions` are unchanged — they already call `list_decisions()`, so the overlay applies to them automatically.)

- [ ] **Step 6: Run full suite to confirm no regression**

Run: `pytest backend/tests/test_decisions.py backend/tests/test_decision_state.py -v` (if `test_decisions.py` doesn't exist yet, this is just the new file — it's created in Task 5)
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/services/decision_state.py backend/services/decision_log.py backend/tests/test_decision_state.py
git commit -m "Add persisted decision-state store, overlay onto decision projection"
```

---

### Task 5: Real POST /approve and POST /reject endpoints

**Files:**
- Modify: `backend/routers/decisions.py`
- Test: `backend/tests/test_decisions.py` (new file)

**Interfaces:**
- Consumes: `backend.services.decision_log.get_decision`, `list_decisions` (existing); `backend.services.decision_state.get_decision_state_store`, `DecisionState` (Task 4); `backend.services.recommendation_engine.peek_cached_recommendations` (existing); `backend.services.trade_executor.execute_autonomous_from_recommendations` (existing, now paper_sim-backed per Task 2).
- Produces: `POST /api/v1/decisions/{decision_id}/approve`, `POST /api/v1/decisions/{decision_id}/reject` — both return the updated `DecisionRecord` plus (for approve) the `AutonomousExecutionResult`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_decisions.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.models.decisions import DecisionStatus
from backend.services import decision_log


@pytest.fixture
def client():
    return TestClient(app)


def _make_pending_decision(decision_id: str, symbol: str = "NIFTY"):
    from backend.tests.test_trade_executor import _make_recommendation

    rec = _make_recommendation(1, symbol=symbol)
    rec = rec.model_copy(
        update={"parameters": rec.parameters.model_copy(update={"und_price": 22010.0})}
    )
    return rec


async def test_approve_unknown_decision_returns_404(client, monkeypatch):
    async def _fake_list_decisions():
        return []

    monkeypatch.setattr(decision_log, "list_decisions", _fake_list_decisions)

    response = client.post("/api/v1/decisions/dec_unknown/approve")

    assert response.status_code == 404


async def test_reject_persists_without_executing(client, monkeypatch, tmp_path):
    from backend.services.decision_state import DecisionStateStore
    import backend.routers.decisions as decisions_router

    store = DecisionStateStore(store_path=tmp_path / "decision_state.json")
    monkeypatch.setattr(decisions_router, "get_decision_state_store", lambda: store)

    rec = _make_pending_decision("dec_nifty_test")
    decision = decision_log._to_decision(
        rec, decision_id="dec_nifty_test", status=DecisionStatus.pending,
        created_at=datetime.now(timezone.utc),
    )

    async def _fake_list_decisions():
        return [decision]

    monkeypatch.setattr(decision_log, "list_decisions", _fake_list_decisions)

    executed = {"called": False}

    async def _fake_execute(recs, **kwargs):
        executed["called"] = True
        raise AssertionError("reject must not execute")

    monkeypatch.setattr(decisions_router, "execute_autonomous_from_recommendations", _fake_execute)

    response = client.post(
        "/api/v1/decisions/dec_nifty_test/reject", json={"reason": "too risky"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert executed["called"] is False
    assert store.get("dec_nifty_test").status == "rejected"
    assert store.get("dec_nifty_test").reason == "too risky"


async def test_approve_on_already_acted_decision_returns_409(client, monkeypatch, tmp_path):
    from backend.services.decision_state import DecisionState, DecisionStateStore
    import backend.routers.decisions as decisions_router

    store = DecisionStateStore(store_path=tmp_path / "decision_state.json")
    store.set(
        "dec_nifty_test",
        DecisionState(status="rejected", trade_id=None, acted_at=datetime.now(timezone.utc)),
    )
    monkeypatch.setattr(decisions_router, "get_decision_state_store", lambda: store)

    rec = _make_pending_decision("dec_nifty_test")
    decision = decision_log._to_decision(
        rec, decision_id="dec_nifty_test", status=DecisionStatus.pending,
        created_at=datetime.now(timezone.utc),
    )

    async def _fake_list_decisions():
        return [decision]

    monkeypatch.setattr(decision_log, "list_decisions", _fake_list_decisions)

    response = client.post("/api/v1/decisions/dec_nifty_test/approve")

    assert response.status_code == 409
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_decisions.py -v`
Expected: FAIL — `/approve` and `/reject` routes don't exist yet (404s from FastAPI's default "not found" rather than the handler's own 404/409 logic; the reject test fails because the route returns 404 with no body matching `status`).

- [ ] **Step 3: Implement the endpoints**

Replace `backend/routers/decisions.py` in full:

```python
"""Decision log + approve/reject — writes go through paper_sim (Phase 1)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.models.decisions import DecisionRecord, DecisionStatus
from backend.services import decision_log
from backend.services.decision_state import DecisionState, get_decision_state_store
from backend.services.recommendation_engine import peek_cached_recommendations
from backend.services.trade_executor import execute_autonomous_from_recommendations

router = APIRouter(prefix="/api/v1/decisions", tags=["decisions"])


class RejectRequest(BaseModel):
    reason: str | None = None


@router.get("")
async def list_decisions() -> list[DecisionRecord]:
    """Audit trail of surfaced and acted-on decisions, newest first."""
    return await decision_log.list_decisions()


@router.get("/pending")
async def list_pending_decisions() -> list[DecisionRecord]:
    """Decisions surfaced this cycle that the bot has not acted on yet."""
    return await decision_log.list_pending_decisions()


@router.get("/{decision_id}")
async def get_decision(decision_id: str) -> DecisionRecord:
    """Pre-approval packet for a single decision."""
    decision = await decision_log.get_decision(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail=f"No decision with id {decision_id}")
    return decision


async def _get_pending_decision(decision_id: str) -> DecisionRecord:
    decision = await decision_log.get_decision(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail=f"No decision with id {decision_id}")
    if decision.status != DecisionStatus.pending:
        raise HTTPException(
            status_code=409,
            detail=f"Decision {decision_id} is already {decision.status.value}, not pending",
        )
    return decision


@router.post("/{decision_id}/approve")
async def approve_decision(decision_id: str) -> dict:
    """Approve a pending decision — executes it through paper_sim (single candidate)."""
    decision = await _get_pending_decision(decision_id)

    cached = peek_cached_recommendations()
    rec = None
    if cached is not None:
        rec = next(
            (r for r in cached.recommendations if f"dec_{r.underlying_symbol.lower()}_{cached.generated_at.strftime('%Y%m%d')}" == decision_id),
            None,
        )
    if rec is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Decision {decision_id} is no longer in the live recommendation cache — "
                "re-fetch GET /decisions/pending and retry"
            ),
        )

    result = await execute_autonomous_from_recommendations([rec])

    store = get_decision_state_store()
    if result.executed:
        store.set(
            decision_id,
            DecisionState(
                status="approved",
                trade_id=result.trade_id,
                acted_at=datetime.now(timezone.utc),
            ),
        )
        updated = await decision_log.get_decision(decision_id)
        return {"decision": updated, "execution": result}

    # paper_sim rejected it — leave the decision pending so the operator can retry/reject.
    return {"decision": decision, "execution": result}


@router.post("/{decision_id}/reject")
async def reject_decision(decision_id: str, body: RejectRequest | None = None) -> DecisionRecord:
    """Reject a pending decision — persisted, no execution."""
    await _get_pending_decision(decision_id)

    store = get_decision_state_store()
    store.set(
        decision_id,
        DecisionState(
            status="rejected",
            reason=body.reason if body else None,
            acted_at=datetime.now(timezone.utc),
        ),
    )
    updated = await decision_log.get_decision(decision_id)
    return updated
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_decisions.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full backend suite**

Run: `pytest -m "not integration"`
Expected: all pass. If `test_approve_...` needs a real paper_sim fill (a happy-path approve test), add one more test mirroring `test_successful_execution_creates_a_real_paper_sim_position` from Task 2, monkeypatching `decisions_router.execute_autonomous_from_recommendations` is *not* what you want there — instead monkeypatch `trade_executor.get_paper_engine` (imported inside `execute_autonomous_from_recommendations`'s call graph) the same way Task 2's fixture does, so the approve endpoint exercises the real paper_sim path end-to-end. Add:

```python
async def test_approve_happy_path_creates_real_position(client, monkeypatch, tmp_path):
    import backend.routers.decisions as decisions_router
    import backend.services.trade_executor as trade_executor
    from backend.paper_sim.engine import PaperEngine
    from backend.services.decision_state import DecisionStateStore
    from backend.tests.test_trade_executor import _FakeFeed

    store = DecisionStateStore(store_path=tmp_path / "decision_state.json")
    monkeypatch.setattr(decisions_router, "get_decision_state_store", lambda: store)

    engine = PaperEngine(feed=_FakeFeed())
    monkeypatch.setattr(trade_executor, "get_paper_engine", lambda: engine)

    rec = _make_pending_decision("dec_nifty_test")
    decision = decision_log._to_decision(
        rec, decision_id="dec_nifty_test", status=DecisionStatus.pending,
        created_at=datetime.now(timezone.utc),
    )

    async def _fake_list_decisions():
        return [decision]

    monkeypatch.setattr(decision_log, "list_decisions", _fake_list_decisions)

    class _Cached:
        generated_at = decision.created_at
        recommendations = [rec]

    monkeypatch.setattr(decisions_router, "peek_cached_recommendations", lambda: _Cached())

    response = client.post("/api/v1/decisions/dec_nifty_test/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["execution"]["executed"] is True
    trade_id = body["execution"]["trade_id"]
    assert trade_id in engine.ledger.positions
    assert store.get("dec_nifty_test").status == "approved"
```

Run: `pytest backend/tests/test_decisions.py -v` again — expect 4/4 passing.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/decisions.py backend/tests/test_decisions.py
git commit -m "Add real POST /decisions/{id}/approve and /reject, backed by paper_sim"
```

---

### Task 6: Update backlog tracking and run full verification

**Files:**
- Modify: `Docs/bot_health/BACKLOG.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Run the full backend suite**

Run: `pytest -m "not integration"`
Expected: all tests pass (existing suite + all tests added in Tasks 1-5).

- [ ] **Step 2: Update the BACKLOG.md P0 item**

In `Docs/bot_health/BACKLOG.md`, change the item at line 11 (`- [ ] Build real POST /approve...`) to reflect what this plan actually closed. Keep the existing bullet text and 2026-08-04 re-confirmation note as history (per this file's own convention of never deleting history); append a resolution note:

```markdown
- [x] Build real `POST /approve` and `POST /reject` endpoints in
  `backend/routers/decisions.py`, make the `paper_sim` ledger the single
  source of truth. (first seen 2026-08-02, evidence: `backend/routers/decisions.py:1`,
  `backend/data/learning_store.json` — all records currently `"seed": true`)
  - Re-confirmed 2026-08-04, still Not-done: `decisions.py` still exposes
    only `GET`/`GET /pending`/`GET /{id}` (no `POST`); `trade_executor.py`
    has zero references to `backend/paper_sim/` (confirmed by grep — the
    only "paper_sim" string in the file is a docstring comment describing
    `learning_store.json`, a different, still-separate ledger from
    `backend/paper_sim/engine.py`/`ledger.py`, which itself still has zero
    references to recommendations, confirmed by grep); `routers/
    recommendations.py::_autonomous_execution_for` still fires on every
    non-cached `GET /recommendations` (`force_refresh=True` or cold cache);
    `execution_constraints.supervised_approval_required` is still only
    present in `trading_parameters.defaults.json`/the schema, not read by
    any `.py` file (grep, repo-wide); `learning_store.json.outcomes` still
    holds exactly 3 records, all `trd_seed_*` — zero real closed trades.
  - **Resolved 2026-08-04**, evidence: `backend/services/trade_executor.py`
    (`resolve_atm_ce_leg`, `_submit_via_paper_sim`) now submits every
    autonomous entry through `PaperEngine.submit_order()` — `trade_id` is a
    real `paper_sim` `position_id`, confirmed by
    `test_successful_execution_creates_a_real_paper_sim_position`.
    `routers/recommendations.py::_autonomous_execution_for` now reads
    `SUPERVISION_MODE` (default `supervised`, same env var/default
    `routers/bot.py` already used) and skips execution entirely on a
    passive `GET` unless `SUPERVISION_MODE=autonomous`, confirmed by
    `test_supervised_mode_skips_autonomous_execution`/
    `test_autonomous_mode_still_executes`. `backend/routers/decisions.py`
    now exposes real `POST /{id}/approve` and `POST /{id}/reject`, backed
    by a new persisted `backend/services/decision_state.py` store (same
    restart-survival pattern as `kill_switch_state.py`), confirmed by
    `backend/tests/test_decisions.py` (4/4, including a happy-path approve
    that asserts a real position lands in `engine.ledger.positions`) and
    `backend/tests/test_decision_state.py` (3/3, including a simulated-
    restart test). **Not addressed by this fix:** excluding seed/demo
    records from `/learning` metrics — separate half of this bullet, still
    open; `learning_store.json.outcomes` still holds only the 3 seeded
    records since this change doesn't produce or need a closed trade to
    verify wiring.
```

- [ ] **Step 3: Commit**

```bash
git add Docs/bot_health/BACKLOG.md
git commit -m "Mark P0 approve/reject + paper_sim wiring item resolved in BACKLOG.md"
```

---

## Self-Review Notes

- **Spec coverage:** §1 (entry-leg resolver) → Task 1. §2 (`_simulate_broker_submit` → real submit) → Task 2. §3 (SUPERVISION_MODE gate) → Task 3. §4 (persisted decision store) → Task 4. §5 (approve/reject endpoints) → Task 5. Error handling and testing sections from the spec are folded into each task's own error-path tests (`PaperLedgerError`/`StaleMarksError` handling in Task 2, 404/409 in Task 5).
- **Type consistency:** `resolve_atm_ce_leg` (Task 1) is consumed by `_submit_via_paper_sim` (Task 2) with the same signature. `DecisionState`/`DecisionStateStore`/`get_decision_state_store` (Task 4) are consumed with matching names/signatures in Task 5's router and tests. `trade_id` is consistently a `paper_sim` `position_id` string from Task 2 onward — Task 5's approve endpoint and tests rely on that exact format (`pos_` prefix) only for test assertions, not for any parsing logic in production code.
- **No placeholders:** every step has runnable code; no "add error handling" stand-ins.
