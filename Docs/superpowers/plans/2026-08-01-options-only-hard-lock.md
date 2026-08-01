# Options-Only Hard Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hard-lock the bot so production, paper, signals, and recommendations only use Call/Put option structures — never cash underlying / stock hedge legs — and remove T11 dual-mode universe rules.

**Architecture:** Introduce one shared `OPTIONS_ONLY_REQUIRED` gate used by signals, recommendation engine, paper-sim open, and order-build paths. Drop T11 / index-exclude / cash-equity-require keys from schema + defaults. Keep stock-leg BSM only for OSS parity tests. Force strategy construction defaults to `options_only` / `four_leg_options`.

**Tech Stack:** Python 3 / FastAPI backend, JSON Schema + `trading_parameters.defaults.json`, pytest, Next.js frontend mocks/types, Markdown docs under `Docs/`.

**Spec:** `Docs/superpowers/specs/2026-08-01-options-only-hard-lock-design.md`

## Global Constraints

- Execution paths may only trade legs with `type` in `{call, put}` (`none` allowed only for empty OSS test slots).
- Reject code: `OPTIONS_ONLY_REQUIRED` (API HTTP 400 where applicable).
- No underlying price cap product rule; indices allowed when ATM / premium / liquidity pass.
- Do **not** remove stock branches from `backend/quant/pricing/bsm.py` or break `backend/tests/quant/test_oss_parity.py`.
- Do **not** stop fetching NSE/index LTP or option chains (`und_price` / `underlying_symbol` remain pricing inputs).
- Default rehedge method: `adjust_call_put_mix`. `increase_hedge` means options size-up only (no shares).
- ICICI Direct: still no market orders; no GTT; limit-only.

---

## File map

| File | Responsibility |
|---|---|
| `backend/execution/options_only.py` | Shared reject helpers + error code |
| `backend/schemas/trading_parameters.schema.json` | Remove T11*; constrain hedge/construction enums |
| `backend/config/trading_parameters.defaults.json` | Options-only defaults; drop T11* |
| `backend/services/signals.py` | Drop T11 gate; reject stock structures |
| `backend/services/recommendation_engine.py` | Always options-only; drop T11 / Scenario E stock flip |
| `backend/paper_sim/engine.py` | Reject cash-underlying legs on open |
| `backend/paper_sim/config.py` | Remove/repurpose `underlying_price_cap_inr` |
| `backend/paper_sim/automation.py` | Never emit `type=stock` rehedge legs; default method |
| `Docs/Trading_Parameters.md` (+ dependents) | Canonical product lock |
| `frontend/src/lib/mock-data.ts`, `positions-mock.ts`, `types/decisions.ts` | No stock legs in live UI fixtures |

---

### Task 1: Shared options-only gate

**Files:**
- Create: `backend/execution/options_only.py`
- Create: `backend/tests/test_options_only_gate.py`
- Modify (import only later tasks): callers in Tasks 3–5

**Interfaces:**
- Produces:
  - `OPTIONS_ONLY_REQUIRED: str = "OPTIONS_ONLY_REQUIRED"`
  - `class OptionsOnlyViolation(ValueError)` with `.code == OPTIONS_ONLY_REQUIRED`
  - `def leg_type(leg: Any) -> str`
  - `def assert_options_only_legs(legs: Sequence[Any]) -> None` — raises `OptionsOnlyViolation` if any leg type is `stock`
  - `def assert_options_only_strategy_config(*, hedge_method: str | None = None, construction: str | None = None) -> None` — raises if `hedge_method == "stock"` or `construction == "calls_stock"`
  - `def structure_is_options_only(legs: Sequence[Any] | None = None, *, hedge_method: str | None = None, construction: str | None = None) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_options_only_gate.py
import pytest
from backend.execution.options_only import (
    OPTIONS_ONLY_REQUIRED,
    OptionsOnlyViolation,
    assert_options_only_legs,
    assert_options_only_strategy_config,
    structure_is_options_only,
)

def test_rejects_stock_leg():
    with pytest.raises(OptionsOnlyViolation) as ei:
        assert_options_only_legs([{"type": "call"}, {"type": "stock"}])
    assert ei.value.code == OPTIONS_ONLY_REQUIRED

def test_allows_call_put():
    assert_options_only_legs([{"type": "call"}, {"type": "put"}])
    assert structure_is_options_only([{"type": "CALL"}, {"type": "Put"}]) is True

def test_rejects_stock_hedge_config():
    with pytest.raises(OptionsOnlyViolation):
        assert_options_only_strategy_config(hedge_method="stock")
    with pytest.raises(OptionsOnlyViolation):
        assert_options_only_strategy_config(construction="calls_stock")
    assert_options_only_strategy_config(hedge_method="options_only", construction="four_leg_options")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_options_only_gate.py -v`  
Expected: FAIL (module not found)

- [ ] **Step 3: Implement gate**

```python
# backend/execution/options_only.py
from __future__ import annotations
from typing import Any, Sequence

OPTIONS_ONLY_REQUIRED = "OPTIONS_ONLY_REQUIRED"

class OptionsOnlyViolation(ValueError):
    def __init__(self, message: str = "Call/Put legs only; stock/underlying legs are not allowed"):
        super().__init__(message)
        self.code = OPTIONS_ONLY_REQUIRED

def leg_type(leg: Any) -> str:
    if isinstance(leg, dict):
        raw = leg.get("type") or leg.get("option_type") or ""
    else:
        raw = getattr(leg, "type", None) or getattr(leg, "option_type", None) or ""
    return str(raw).strip().lower()

def assert_options_only_legs(legs: Sequence[Any]) -> None:
    for leg in legs:
        if leg_type(leg) == "stock":
            raise OptionsOnlyViolation()

def assert_options_only_strategy_config(
    *, hedge_method: str | None = None, construction: str | None = None
) -> None:
    if hedge_method is not None and str(hedge_method).strip().lower() == "stock":
        raise OptionsOnlyViolation("hedge_method=stock is not allowed (options-only hard lock)")
    if construction is not None and str(construction).strip().lower() == "calls_stock":
        raise OptionsOnlyViolation("construction=calls_stock is not allowed (options-only hard lock)")

def structure_is_options_only(
    legs: Sequence[Any] | None = None,
    *,
    hedge_method: str | None = None,
    construction: str | None = None,
) -> bool:
    try:
        if legs is not None:
            assert_options_only_legs(legs)
        assert_options_only_strategy_config(hedge_method=hedge_method, construction=construction)
    except OptionsOnlyViolation:
        return False
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_options_only_gate.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/execution/options_only.py backend/tests/test_options_only_gate.py
git commit -m "Add shared OPTIONS_ONLY_REQUIRED gate for Call/Put-only structures."
```

---

### Task 2: Schema + defaults — remove T11*; force options-only construction

**Files:**
- Modify: `backend/schemas/trading_parameters.schema.json`
- Modify: `backend/config/trading_parameters.defaults.json`
- Create: `backend/tests/test_trading_parameters_options_only_config.py`

**Interfaces:**
- Consumes: none from Task 1
- Produces: defaults with `strategies.simple_volatility.hedge_method = "options_only"`, `strategies.gamma_scalping.construction = "four_leg_options"`, `gamma_theta_breakeven.rehedge_method = "adjust_call_put_mix"`; no T11 keys under `option_universe_filters`

- [ ] **Step 1: Write the failing config test**

```python
# backend/tests/test_trading_parameters_options_only_config.py
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = json.loads((ROOT / "config" / "trading_parameters.defaults.json").read_text(encoding="utf-8"))

REMOVED = {
    "max_underlying_price",
    "max_underlying_price_applies_when",
    "exclude_index_underlyings",
    "require_cash_equity_underlying",
    "max_underlying_price_rationale",
    "excluded_index_underlying_symbols",
}

def test_t11_keys_removed_from_defaults():
    f = DEFAULTS["option_universe_filters"]
    for key in REMOVED:
        assert key not in f, key

def test_strategies_are_options_only():
    assert DEFAULTS["strategies"]["simple_volatility"]["hedge_method"] == "options_only"
    assert DEFAULTS["strategies"]["gamma_scalping"]["construction"] == "four_leg_options"
    assert DEFAULTS["gamma_theta_breakeven"]["rehedge_method"] == "adjust_call_put_mix"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_trading_parameters_options_only_config.py -v`  
Expected: FAIL (T11 keys still present / hedge_method still `stock`)

- [ ] **Step 3: Update schema**

In `option_universe_filters`:
- Remove from `required` and `properties`: `max_underlying_price`, `max_underlying_price_applies_when`, `exclude_index_underlyings`, `require_cash_equity_underlying`, `max_underlying_price_rationale`, `excluded_index_underlying_symbols`.
- Keep `underlying_price_currency` if still used for ATM/spot display comparisons; if unused elsewhere, keep it (spot still exists as A4).

In `SimpleVolatilityStrategy.hedge_method`: change to `"const": "options_only"` (or enum with only `options_only`).

In `GammaScalpingStrategy.construction`: change to `"const": "four_leg_options"`.

In `VegaScalpingStrategy`: add `"hedge_method": { "const": "options_only" }` so config cannot silently default to stock in code.

Bump schema/`defaults` `version` string (e.g. `1.7` or next).

- [ ] **Step 4: Update defaults JSON**

- Delete the REMOVED keys from `option_universe_filters`.
- Set `simple_volatility.hedge_method` → `"options_only"`.
- Set `gamma_scalping.construction` → `"four_leg_options"`.
- Set `vega_scalping.hedge_method` → `"options_only"` (add key).
- Set `gamma_theta_breakeven.rehedge_method` → `"adjust_call_put_mix"`.
- Keep `oss_global_params.default_stock_multiplier` and `nfo_lot_sizing.stock_leg_multiplier` with a comment in docs only (JSON has no comments — leave values for OSS parity loaders).

- [ ] **Step 5: Run config test**

Run: `pytest backend/tests/test_trading_parameters_options_only_config.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/schemas/trading_parameters.schema.json backend/config/trading_parameters.defaults.json backend/tests/test_trading_parameters_options_only_config.py
git commit -m "Force options-only trading parameter defaults and drop T11 keys."
```

---

### Task 3: Signals — drop T11; reject stock structures

**Files:**
- Modify: `backend/services/signals.py`
- Modify: `backend/tests/test_signals.py`

**Interfaces:**
- Consumes: `assert_options_only_strategy_config`, `OPTIONS_ONLY_REQUIRED` from Task 1; defaults from Task 2
- Produces: `evaluate_candidate` / `_retail_gates` without T11; `includes_underlying` default `False`; stock hedge inputs fail gates with `OPTIONS_ONLY_REQUIRED`

- [ ] **Step 1: Rewrite failing/obsolete tests**

Replace `test_evaluate_t11_fail_when_options_and_underlying` and `test_evaluate_t11_skipped_options_only` with:

```python
def test_evaluate_high_spot_options_only_still_eligible():
    """No T11: high spot is fine when premium/liquidity pass."""
    news = _neutral_news()
    inp = SignalComputeInputs(
        symbol="INFY",
        und_price=1680.0,
        option_iv_annual=0.20,
        garch_forecast_annual=0.30,
        includes_underlying=False,
        atm_premium_inr=210,
        volume=15200,
        open_interest=28000,
        spread_pct=1.1,
    )
    out = evaluate_candidate(inp, news=news)
    assert all(g["gate_id"] != "T11" for g in out["gates"])
    assert out["recommendation"] == "enter_long_vol"
    assert out["eligible"] is True

def test_evaluate_rejects_includes_underlying_stock_path():
    news = _neutral_news()
    inp = SignalComputeInputs(
        symbol="SBIN",
        und_price=812.0,
        option_iv_annual=0.22,
        garch_forecast_annual=0.30,
        includes_underlying=True,  # hard-lock violation
        atm_premium_inr=95,
        volume=22000,
        open_interest=35000,
        spread_pct=0.9,
    )
    out = evaluate_candidate(inp, news=news)
    assert out["gates_passed"] is False
    assert out["eligible"] is False
    oo = next(g for g in out["gates"] if g["gate_id"] == "OPTIONS_ONLY_REQUIRED")
    assert oo["passed"] is False
```

Update other tests that used `includes_underlying=True` to `False` unless they intentionally test the reject path.

Change `SignalComputeInputs.includes_underlying` default to `False` in the dataclass.

- [ ] **Step 2: Run targeted tests — expect fail on old T11 behavior**

Run: `pytest backend/tests/test_signals.py -v`  
Expected: FAIL until implementation matches

- [ ] **Step 3: Implement signal changes**

In `_retail_gates`:
- Delete the entire T11 / `max_underlying_price*` block.
- At the start, if `includes_underlying` is True, append a failing `GateResult(gate_id="OPTIONS_ONLY_REQUIRED", ...)`.
- Keep T1, T13–T15.

In `evaluate_candidate` / packet builders: stop reading removed config keys; do not call `_structure_uses_underlying` patterns.

- [ ] **Step 4: Run signals tests**

Run: `pytest backend/tests/test_signals.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/signals.py backend/tests/test_signals.py
git commit -m "Drop T11 from signals and reject stock-underlying evaluate paths."
```

---

### Task 4: Recommendation engine — always options-only

**Files:**
- Modify: `backend/services/recommendation_engine.py`
- Modify or create tests under `backend/tests/` that cover recommendations / gates (search existing: `test_recommendation*.py`)

**Interfaces:**
- Consumes: Task 1–2
- Produces: `_structure_uses_underlying` always `False`; `_prefer_options_only_for_high_spot` becomes no-op; `_evaluate_gates` has no T11; rationale text no longer mentions stock hedge / T11 cap

- [ ] **Step 1: Locate and update/add tests**

```bash
rg -n "T11|_structure_uses_underlying|_prefer_options_only|includes_underlying" backend/tests backend/services/recommendation_engine.py
```

Add/adjust a test that a candidate with `und_price=1680` and index symbol is **not** failed solely for T11 / index exclusion when premium/liquidity pass (other gates may still apply).

- [ ] **Step 2: Run those tests — expect fail**

- [ ] **Step 3: Implement**

- `_structure_uses_underlying(...)` → always `return False` (or delete callers and hardcode `includes_underlying=False`).
- `_prefer_options_only_for_high_spot(...)` → `return strategy, False` immediately (or delete).
- In `_evaluate_gates`: remove T11 block; optionally add `OPTIONS_ONLY_REQUIRED` pass gate documenting lock.
- Update narrative helpers around lines that mention T11 / Scenario E stock flip (`~668+`).
- Ensure recommendation packets never set hedge to stock.

- [ ] **Step 4: Run recommendation-related tests**

Run: `pytest backend/tests/ -k "recommendation or signals" -v`  
Expected: PASS for touched tests

- [ ] **Step 5: Commit**

```bash
git add backend/services/recommendation_engine.py backend/tests/
git commit -m "Lock recommendation engine to options-only constructions."
```

---

### Task 5: Paper-sim open path — reject cash underlying legs

**Files:**
- Modify: `backend/paper_sim/engine.py` (`_resolve_and_gate_legs`)
- Modify: `backend/paper_sim/config.py` (`underlying_price_cap_inr`)
- Modify: `backend/tests/` paper-sim tests that assert Part T spot cap / index+stock behavior
- Possibly: `backend/paper_sim/chain.py` index handling (do **not** block index underlyings for options-only)

**Interfaces:**
- Consumes: `assert_options_only_legs` / `OptionsOnlyViolation` / `OPTIONS_ONLY_REQUIRED` from Task 1
- Produces: open rejects any cash-underlying leg with `OPTIONS_ONLY_REQUIRED`; no spot-cap check

- [ ] **Step 1: Write failing paper-sim test**

```python
# e.g. backend/tests/test_paper_sim_options_only.py
import pytest
from backend.paper_sim.models import PaperLegRequest  # adjust to real import
from backend.execution.options_only import OPTIONS_ONLY_REQUIRED

@pytest.mark.asyncio
async def test_open_rejects_cash_underlying_leg(paper_engine_fixture):
    legs = [
        PaperLegRequest(exchange="NSE", symbol="SBIN", side="sell", quantity=100, option_type=None),
        # plus an option leg if required by API — use real model fields from Paper_Simulator.md
    ]
    with pytest.raises(Exception) as ei:  # PaperLedgerError wrapping OPTIONS_ONLY_REQUIRED
        await paper_engine_fixture.open_trade(underlying="SBIN", legs=legs)
    assert OPTIONS_ONLY_REQUIRED in str(ei.value)
```

Adapt to the real `open` / `submit` method signatures in `engine.py` and existing fixtures in `test_automation.py` / paper tests.

- [ ] **Step 2: Run test — expect fail**

- [ ] **Step 3: Implement engine gate**

At the top of `_resolve_and_gate_legs`, after receiving `legs`:

```python
from backend.execution.options_only import OPTIONS_ONLY_REQUIRED, OptionsOnlyViolation

# Reject any cash-underlying / stock hedge leg
if any(_is_cash_underlying_leg(leg) for leg in legs):
    raise PaperLedgerError(f"{OPTIONS_ONLY_REQUIRED}: Call/Put legs only; stock/underlying legs are not allowed")
```

Remove the block that rejects index underlyings when `includes_underlying` (lines ~153–161) and the spot-cap block (~239–252).

In `PaperSimConfig`: change `underlying_price_cap_inr` default to `0` and update description to “deprecated / unused under options-only hard lock”, **or** remove field and all references (`engine.py` health dict, `automation.py` checks). Prefer remove references and set default `0` if removal is wide; full field deletion is OK if all call sites updated.

Default `rehedge_method` → `"adjust_call_put_mix"`.

- [ ] **Step 4: Run paper-sim tests**

Run: `pytest backend/tests/test_paper_sim_options_only.py backend/tests/test_automation.py backend/tests/test_phase1_10_paper_stack.py -v`  
Expected: PASS (update any tests that opened stock legs or asserted ₹1000 cap)

- [ ] **Step 5: Commit**

```bash
git add backend/paper_sim/engine.py backend/paper_sim/config.py backend/tests/
git commit -m "Reject cash underlying legs in paper-sim open path."
```

---

### Task 6: Paper-sim automation — no stock rehedge legs

**Files:**
- Modify: `backend/paper_sim/automation.py` (`_position_greeks` stock branch ~385–395; rehedge methods ~504+)
- Modify: `backend/tests/test_automation.py`

**Interfaces:**
- Consumes: Task 5 config default `adjust_call_put_mix`
- Produces: Greeks builder skips NSE/BSE cash legs instead of appending `type=stock`; `increase_hedge` adjusts option quantities only; never submits NSE cash hedge orders

- [ ] **Step 1: Add/adjust test**

Assert automation tick / rehedge for an options-only position never creates a leg with `type == "stock"` and default config method is `adjust_call_put_mix`.

- [ ] **Step 2: Run — expect fail if stock still emitted**

- [ ] **Step 3: Implement**

In `_position_greeks`, replace the stock append branch:

```python
if ot is None and leg.exchange.upper() in {"NSE", "BSE"}:
    # Options-only hard lock: ignore residual cash legs; do not model as stock.
    continue
```

For `increase_hedge` method: ensure implementation increases **option** hedge size / call-put mix — if current code places NSE share orders, redirect to `adjust_call_put_mix` behavior or raise `OPTIONS_ONLY_REQUIRED`.

Update fixtures that set `rehedge_method="increase_hedge"` only if that path remains options-safe; otherwise switch fixtures to `adjust_call_put_mix`.

- [ ] **Step 4: Run automation tests**

Run: `pytest backend/tests/test_automation.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/paper_sim/automation.py backend/tests/test_automation.py
git commit -m "Stop modeling stock legs in paper-sim rehedge automation."
```

---

### Task 7: Docs — Trading_Parameters + dependents

**Files:**
- Modify: `Docs/Trading_Parameters.md` (bump version, e.g. 1.9)
- Modify: `Docs/Trading_Strategies.md`
- Modify: `Docs/architecture.md` (§2.3 and any T11 / dual-mode notes)
- Modify: `Docs/context.md`
- Modify: `Docs/Paper_Simulator.md`
- Modify: `Docs/edge_cases.md`
- Modify: `Docs/implementation_plan.md` (short locked decision note)
- Reference: `Docs/superpowers/specs/2026-08-01-options-only-hard-lock-design.md` §4

**Interfaces:**
- Consumes: locked decisions from spec
- Produces: docs that state options-only hard lock; no dual-mode T11 product rule

- [ ] **Step 1: Update `Trading_Parameters.md` per dependency map**

Apply every row in spec §4.1:
- Product banner near Part T: **Options-only hard lock — Call/Put legs only.**
- Remove Part T mode table dual-mode; delete T11/T11a–d/T9 stock-mode validation (or mark Removed).
- L5: delete Path A; keep Path B; `hedge_method` const `options_only`.
- M3: only four-leg; remove `calls_stock` / `stock_qty`.
- N5: `options_only` only.
- I18/I18a/L2.1a/M4.1a/N2.1a: remove.
- A5/A12/B15: stock = OSS/test-only, rejected in bot execution.
- Q1–Q3, Part R: rewrite critical paths.
- Document status: version + change line for options-only hard lock.

- [ ] **Step 2: Update dependent docs**

Search and replace dual-mode wording:

```bash
rg -n "options and its underlying|options\+underlying|calls_stock|hedge_method.*stock|max_underlying_price|T11" Docs/
```

Align each hit with the hard lock (except historical “Prior” changelog lines if useful).

- [ ] **Step 3: Spot-check consistency**

Confirm `Trading_Parameters.md` version note matches schema/defaults version narrative.

- [ ] **Step 4: Commit**

```bash
git add Docs/Trading_Parameters.md Docs/Trading_Strategies.md Docs/architecture.md Docs/context.md Docs/Paper_Simulator.md Docs/edge_cases.md Docs/implementation_plan.md
git commit -m "Document options-only hard lock across trading parameter dependents."
```

---

### Task 8: Frontend mocks / types cleanup

**Files:**
- Modify: `frontend/src/lib/mock-data.ts`
- Modify: `frontend/src/lib/positions-mock.ts` (if stock legs present)
- Modify: `frontend/src/types/decisions.ts` — keep `"stock"` in union only if OSS/display needs it; add comment that execution rejects stock; or narrow to `"call" | "put"` for recommendation types

- [ ] **Step 1: Find stock legs in frontend fixtures**

```bash
rg -n "type: \"stock\"|hedge_method.*stock|calls_stock" frontend/src
```

- [ ] **Step 2: Replace live recommendation/position mocks with Call/Put-only structures**

- [ ] **Step 3: Typecheck / lint if available**

Run: `cd frontend; npx tsc --noEmit` (or project’s usual check)  
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src
git commit -m "Remove stock hedge legs from frontend trading mocks."
```

---

### Task 9: Verification sweep

**Files:** none new — run suites

- [ ] **Step 1: Focused pytest**

```bash
pytest backend/tests/test_options_only_gate.py backend/tests/test_trading_parameters_options_only_config.py backend/tests/test_signals.py backend/tests/test_automation.py backend/tests/quant/test_oss_parity.py -v
```

Expected: all PASS; OSS parity still green with stock legs in fixtures.

- [ ] **Step 2: Grep for regressions**

```bash
rg -n "max_underlying_price|calls_stock|hedge_method.: .stock|options_and_underlying" backend/config backend/schemas backend/services backend/paper_sim
```

Expected: no live defaults/schema requiring those keys (OSS tests / changelog OK).

- [ ] **Step 3: Final commit only if Step 2 required doc/code fixups; otherwise done**

---

## Spec coverage checklist

| Spec requirement | Task |
|---|---|
| Hard lock Call/Put only | 1, 3, 4, 5, 6 |
| Universe: no spot cap; indices allowed | 2, 3, 4, 5, 7 |
| OSS stock math retained | 9 (parity suite) + non-goal |
| Remove T11 keys | 2, 3, 4, 7 |
| `OPTIONS_ONLY_REQUIRED` | 1, 3, 5 |
| Defaults `options_only` / `four_leg_options` / `adjust_call_put_mix` | 2, 6 |
| Docs dependents | 7 |
| Frontend mocks | 8 |

## Self-review notes

- No TBD placeholders in task steps.
- `includes_underlying` default flips to `False` in Task 3 — callers must be updated in the same task.
- Recommendation engine was an implied dependency of the spec’s “recommendation packet” gate; covered in Task 4.
- `increase_hedge` retained in schema enum but defaults to `adjust_call_put_mix`; Task 6 must make `increase_hedge` options-safe or map to options adjustment.
