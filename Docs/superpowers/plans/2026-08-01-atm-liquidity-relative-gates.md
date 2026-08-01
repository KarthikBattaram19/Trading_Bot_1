# ATM Liquidity Relative Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite high-liquidity gates so ATM volume must exceed 150% of its ≤20-session average, ATM OI must exceed 130% of its ≤20-session average, and max(CE,PE) spread must be &lt; 0.5%, with absolute floors vol≥2000 and OI≥20000 underneath.

**Architecture:** Add a pure liquidity evaluator plus a JSON EOD ATM history store. Universe enrichment snapshots today’s rolling-ATM `min(CE,PE)` volume/OI; signals and recommendation gates call the evaluator. Config/schema replace old absolute-only floors (1000 / 10000 / 2%).

**Tech Stack:** Python 3 / FastAPI backend, JSON Schema + `trading_parameters.defaults.json`, pytest, JSON file persistence under `backend/data/`, Markdown docs under `Docs/`.

**Spec:** `docs/superpowers/specs/2026-08-01-atm-liquidity-relative-gates-design.md`

## Global Constraints

- Scope: liquidity gates only (T13–T16 / T10 / L3.5–L3.7 / I1 / I20). Do **not** change T1–T8 premium/ATM selection.
- Aggregation: `atm_volume = min(CE_vol, PE_vol)`, `atm_oi = min(CE_oi, PE_oi)`, `spread_pct = max(CE_spread%, PE_spread%)`.
- Relative: `atm_volume > 1.5 × avg_vol`, `atm_oi > 1.3 × avg_oi` (strict `>`).
- Spread: `spread_pct < 0.5` (strict `<`; equality fails). Old `<= 2.0` comparison must not remain.
- Absolute floors: `atm_volume ≥ 2000`, `atm_oi ≥ 20000`.
- History: rolling ATM per session; averages use last ≤20 **prior** sessions; relative gates fail if `n < 10`.
- Today’s live marks are numerator only — **exclude today** from average denominator.
- Fail closed on missing CE/PE, missing vol/OI, non-positive bid/ask/mid, or zero averages.
- No new vendor historical OI API; bot-owned JSON store only.
- Do not implement the separate options-only hard lock in this plan.

---

## File map

| File | Responsibility |
|---|---|
| `backend/services/atm_liquidity.py` | Pure metrics + evaluator + reason codes |
| `backend/services/atm_liquidity_history.py` | JSON EOD store: upsert snapshot, load prior sessions |
| `backend/data/atm_liquidity_history.json` | Created at runtime (gitignored if not already); empty `{}` ok in tests via temp path |
| `backend/config/trading_parameters.defaults.json` | New floors, ratios, lookback keys; strategy option_selection mirrors |
| `backend/schemas/trading_parameters.schema.json` | Validate new keys |
| `backend/services/signals.py` | Use evaluator for T13/T13b/T14/T14b/T15 |
| `backend/services/recommendation_engine.py` | Same gate wiring |
| `backend/services/universe_enrichment.py` | Snapshot today’s ATM row after marks |
| `Docs/Trading_Parameters.md` | Canonical T10 / T13–T16 / L3.5–L3.7 / I1 / I20 |
| `Docs/Trading_Strategies.md` | Replace hardcoded 1000/10000/2% liquidity rule row if present |
| `backend/tests/test_atm_liquidity.py` | Evaluator unit tests |
| `backend/tests/test_atm_liquidity_history.py` | Store unit tests |

---

### Task 1: Config + schema defaults

**Files:**
- Modify: `backend/config/trading_parameters.defaults.json`
- Modify: `backend/schemas/trading_parameters.schema.json`
- Create: `backend/tests/test_atm_liquidity_config.py`

**Interfaces:**
- Produces config keys under `option_universe_filters` (and matching strategy `option_selection` floors/spread):
  - `min_volume: 2000`
  - `min_open_interest: 20000`
  - `max_spread_pct: 0.5`
  - `volume_vs_avg_min_ratio: 1.5`
  - `oi_vs_avg_min_ratio: 1.3`
  - `atm_history_lookback_days: 20`
  - `atm_history_min_days: 10`
  - `atm_liquidity_agg: "min_ce_pe"`
  - `spread_agg: "max_ce_pe"`

- [ ] **Step 1: Write the failing config test**

```python
# backend/tests/test_atm_liquidity_config.py
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = ROOT / "config" / "trading_parameters.defaults.json"

def test_liquidity_defaults_match_relative_gates_spec():
    cfg = json.loads(DEFAULTS.read_text(encoding="utf-8"))
    f = cfg["option_universe_filters"]
    assert f["min_volume"] == 2000
    assert f["min_open_interest"] == 20000
    assert f["max_spread_pct"] == 0.5
    assert f["volume_vs_avg_min_ratio"] == 1.5
    assert f["oi_vs_avg_min_ratio"] == 1.3
    assert f["atm_history_lookback_days"] == 20
    assert f["atm_history_min_days"] == 10
    assert f["atm_liquidity_agg"] == "min_ce_pe"
    assert f["spread_agg"] == "max_ce_pe"
    for key in ("simple_volatility", "gamma_scalping", "vega_scalping"):
        sel = cfg["strategies"][key]["option_selection"]
        assert sel["min_volume"] == 2000
        assert sel["min_open_interest"] == 20000
        assert sel["max_spread_pct"] == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_atm_liquidity_config.py -v`  
Expected: FAIL on old values (1000 / 10000 / 2.0) or missing ratio keys.

- [ ] **Step 3: Update defaults.json**

In `option_universe_filters` set the keys from Interfaces. In each strategy’s `option_selection`, set `min_volume=2000`, `min_open_interest=20000`, `max_spread_pct=0.5`. Bump `"version"` if the file uses a version field (e.g. `1.6` → `1.7`).

- [ ] **Step 4: Update schema.json**

Under `option_universe_filters.properties`, add:

```json
"volume_vs_avg_min_ratio": {
  "type": "number",
  "exclusiveMinimum": 0,
  "description": "T13b — current ATM volume must be > this × prior average."
},
"oi_vs_avg_min_ratio": {
  "type": "number",
  "exclusiveMinimum": 0,
  "description": "T14b — current ATM OI must be > this × prior average."
},
"atm_history_lookback_days": {
  "type": "integer",
  "minimum": 1,
  "description": "Max prior sessions in ATM volume/OI average."
},
"atm_history_min_days": {
  "type": "integer",
  "minimum": 1,
  "description": "Min prior sessions before relative volume/OI gates can pass."
},
"atm_liquidity_agg": {
  "type": "string",
  "const": "min_ce_pe"
},
"spread_agg": {
  "type": "string",
  "const": "max_ce_pe"
}
```

Add the new keys to `option_universe_filters.required`. Update `min_volume` / `min_open_interest` / `max_spread_pct` descriptions to mention absolute floors + relative/spread rules. Update strategy `option_selection` nested schemas if they hardcode old minimums.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/test_atm_liquidity_config.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/config/trading_parameters.defaults.json backend/schemas/trading_parameters.schema.json backend/tests/test_atm_liquidity_config.py
git commit -m "$(cat <<'EOF'
feat: raise liquidity floors and add relative ATM ratio config

EOF
)"
```

---

### Task 2: Pure ATM liquidity evaluator

**Files:**
- Create: `backend/services/atm_liquidity.py`
- Create: `backend/tests/test_atm_liquidity.py`

**Interfaces:**
- Produces:
  - Reason code constants: `ATM_HISTORY_TOO_SHORT`, `ATM_VOLUME_BELOW_AVG_RATIO`, `ATM_OI_BELOW_AVG_RATIO`, `ATM_SPREAD_TOO_WIDE`, `ATM_ABS_FLOOR_FAIL`, `ATM_LIQUIDITY_DATA_MISSING`
  - `@dataclass class AtmSideMarks: volume: int; open_interest: int; bid: float; ask: float`
  - `@dataclass class AtmLiquidityLive: ce: AtmSideMarks | None; pe: AtmSideMarks | None`
  - `@dataclass class AtmHistoryPoint: session_date: str; atm_volume: int; atm_oi: int`
  - `@dataclass class AtmLiquidityResult:` fields `liquidity_ok: bool`, `atm_volume: int`, `atm_oi: int`, `spread_pct: float`, `history_days: int`, `avg_vol: float | None`, `avg_oi: float | None`, `volume_vs_avg: float | None`, `oi_vs_avg: float | None`, `reason_codes: list[str]`, `abs_volume_ok: bool`, `rel_volume_ok: bool`, `abs_oi_ok: bool`, `rel_oi_ok: bool`, `spread_ok: bool`
  - `def spread_pct(bid: float, ask: float) -> float | None` — returns None if invalid; else `(ask-bid)/mid*100`
  - `def aggregate_atm_volume_oi(live: AtmLiquidityLive) -> tuple[int | None, int | None]` — `min` of both sides; None if either side missing/invalid
  - `def aggregate_spread_pct(live: AtmLiquidityLive) -> float | None` — max of CE/PE spreads; None if either invalid
  - `def evaluate_atm_liquidity(*, live: AtmLiquidityLive, prior: Sequence[AtmHistoryPoint], min_volume: int, min_open_interest: int, max_spread_pct: float, volume_vs_avg_min_ratio: float, oi_vs_avg_min_ratio: float, lookback_days: int = 20, min_history_days: int = 10) -> AtmLiquidityResult`

- [ ] **Step 1: Write failing unit tests**

```python
# backend/tests/test_atm_liquidity.py
from backend.services.atm_liquidity import (
    AtmHistoryPoint,
    AtmLiquidityLive,
    AtmSideMarks,
    evaluate_atm_liquidity,
    ATM_HISTORY_TOO_SHORT,
    ATM_SPREAD_TOO_WIDE,
)

def _side(vol, oi, bid, ask):
    return AtmSideMarks(volume=vol, open_interest=oi, bid=bid, ask=ask)

def _live(vol=3000, oi=25000, bid=99.0, ask=99.4):
    # spread ~0.40%
    s = _side(vol, oi, bid, ask)
    return AtmLiquidityLive(ce=s, pe=s)

def _prior(n, vol=2000, oi=20000):
    return [AtmHistoryPoint(session_date=f"2026-01-{i+1:02d}", atm_volume=vol, atm_oi=oi) for i in range(n)]

def _eval(live, prior, **over):
    kw = dict(
        live=live,
        prior=prior,
        min_volume=2000,
        min_open_interest=20000,
        max_spread_pct=0.5,
        volume_vs_avg_min_ratio=1.5,
        oi_vs_avg_min_ratio=1.3,
    )
    kw.update(over)
    return evaluate_atm_liquidity(**kw)

def test_passes_when_hot_vs_average_and_tight_spread():
    # Strict >: 3001 > 1.5*2000; 26001 > 1.3*20000; spread ~0.4% < 0.5
    live = _live(vol=3001, oi=26001, bid=100.0, ask=100.4)
    r = _eval(live, _prior(10, vol=2000, oi=20000))
    assert r.liquidity_ok is True
    assert r.history_days == 10
    assert r.abs_volume_ok and r.rel_volume_ok and r.abs_oi_ok and r.rel_oi_ok and r.spread_ok

def test_fails_at_exact_ratio_boundary():
    live = _live(vol=3000, oi=26000, bid=100.0, ask=100.4)  # exactly 1.5x / 1.3x
    r = _eval(live, _prior(10, vol=2000, oi=20000))
    assert r.rel_volume_ok is False
    assert r.liquidity_ok is False

def test_fails_when_history_shorter_than_10():
    r = _eval(_live(vol=5000, oi=50000), _prior(9))
    assert r.rel_volume_ok is False
    assert ATM_HISTORY_TOO_SHORT in r.reason_codes
    assert r.liquidity_ok is False

def test_fails_spread_at_half_percent():
    live = _live(vol=5000, oi=50000, bid=100.0, ask=100.5)  # 0.5% exactly
    r = _eval(live, _prior(10))
    assert r.spread_ok is False
    assert ATM_SPREAD_TOO_WIDE in r.reason_codes

def test_uses_min_ce_pe_and_max_spread():
    live = AtmLiquidityLive(
        ce=_side(5000, 40000, 100.0, 100.2),   # spread 0.2%
        pe=_side(2500, 22000, 50.0, 50.3),     # spread 0.6%
    )
    r = _eval(live, _prior(10, vol=1000, oi=10000))
    assert r.atm_volume == 2500
    assert r.atm_oi == 22000
    assert r.spread_pct == 0.6
    assert r.spread_ok is False

def test_abs_floor_still_required():
    live = _live(vol=1500, oi=15000, bid=100.0, ask=100.2)
    r = _eval(live, _prior(10, vol=500, oi=5000))  # ratios would pass but abs fail
    assert r.abs_volume_ok is False
    assert r.liquidity_ok is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_atm_liquidity.py -v`  
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `atm_liquidity.py`**

Implement Interfaces exactly. Evaluation logic:

```python
# pseudocode for evaluate_atm_liquidity
vol, oi = aggregate_atm_volume_oi(live)
sp = aggregate_spread_pct(live)
if vol is None or oi is None or sp is None:
    return failing result with ATM_LIQUIDITY_DATA_MISSING

prior_sorted = sorted(prior, key=lambda p: p.session_date)[-lookback_days:]
n = len(prior_sorted)
avg_vol = mean(p.atm_volume for p in prior_sorted) if n else None
avg_oi = mean(p.atm_oi for p in prior_sorted) if n else None

abs_volume_ok = vol >= min_volume
abs_oi_ok = oi >= min_open_interest
spread_ok = sp < max_spread_pct

rel_volume_ok = n >= min_history_days and avg_vol is not None and avg_vol > 0 and vol > volume_vs_avg_min_ratio * avg_vol
rel_oi_ok = n >= min_history_days and avg_oi is not None and avg_oi > 0 and oi > oi_vs_avg_min_ratio * avg_oi

liquidity_ok = abs_volume_ok and abs_oi_ok and rel_volume_ok and rel_oi_ok and spread_ok
# fill reason_codes for each failure
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_atm_liquidity.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/atm_liquidity.py backend/tests/test_atm_liquidity.py
git commit -m "$(cat <<'EOF'
feat: add ATM liquidity evaluator with relative volume and OI ratios

EOF
)"
```

---

### Task 3: JSON ATM history store

**Files:**
- Create: `backend/services/atm_liquidity_history.py`
- Create: `backend/tests/test_atm_liquidity_history.py`

**Interfaces:**
- Produces:
  - `DEFAULT_STORE_PATH: Path` → `backend/data/atm_liquidity_history.json`
  - `class AtmLiquidityHistoryStore:`
    - `__init__(self, store_path: Path | None = None)`
    - `def upsert_snapshot(self, *, underlying: str, expiry_key: str, session_date: str, atm_strike: float, atm_volume: int, atm_oi: int) -> None` — idempotent for same `(underlying, expiry_key, session_date)`
    - `def prior_points(self, *, underlying: str, expiry_key: str, before_date: str, lookback_days: int = 20) -> list[AtmHistoryPoint]` — sessions with `session_date < before_date`, newest lookback, chronological order
    - `def prune(self, *, keep_days: int = 60) -> None` — drop older than keep_days by calendar date vs max date in store (or vs `before_date` caller supplies)

JSON shape:

```json
{
  "SBIN|2026-08-28": [
    {"session_date": "2026-07-01", "atm_strike": 820.0, "atm_volume": 2100, "atm_oi": 22000}
  ]
}
```

Key = `f"{underlying.upper()}|{expiry_key}"`.

- [ ] **Step 1: Write failing store tests**

```python
# backend/tests/test_atm_liquidity_history.py
from pathlib import Path
from backend.services.atm_liquidity_history import AtmLiquidityHistoryStore

def test_upsert_idempotent_and_prior_excludes_today(tmp_path: Path):
    store = AtmLiquidityHistoryStore(tmp_path / "hist.json")
    for i in range(1, 12):
        store.upsert_snapshot(
            underlying="sbin",
            expiry_key="2026-08-28",
            session_date=f"2026-07-{i:02d}",
            atm_strike=800 + i,
            atm_volume=2000 + i,
            atm_oi=20000 + i,
        )
    # rewrite day 11
    store.upsert_snapshot(
        underlying="SBIN",
        expiry_key="2026-08-28",
        session_date="2026-07-11",
        atm_strike=999.0,
        atm_volume=9999,
        atm_oi=99999,
    )
    prior = store.prior_points(
        underlying="SBIN",
        expiry_key="2026-08-28",
        before_date="2026-07-11",
        lookback_days=20,
    )
    assert len(prior) == 10
    assert all(p.session_date < "2026-07-11" for p in prior)
    # include today in file but excluded from prior when before_date=today
    today_prior = store.prior_points(
        underlying="SBIN",
        expiry_key="2026-08-28",
        before_date="2026-07-12",
        lookback_days=20,
    )
    assert today_prior[-1].atm_volume == 9999
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_atm_liquidity_history.py -v`  
Expected: FAIL (module missing).

- [ ] **Step 3: Implement store**

Follow `LearningService` pattern: mkdir parent, read/write JSON atomically enough for single-process (`json.dump` to file). Normalize underlying to upper case.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_atm_liquidity_history.py -v`  
Expected: PASS

- [ ] **Step 5: Ensure `backend/data/` artifacts are gitignored if the project ignores similar JSON stores; do not commit live history files.**

- [ ] **Step 6: Commit**

```bash
git add backend/services/atm_liquidity_history.py backend/tests/test_atm_liquidity_history.py
git commit -m "$(cat <<'EOF'
feat: persist rolling ATM volume and OI session history

EOF
)"
```

---

### Task 4: Wire signals.py gates

**Files:**
- Modify: `backend/services/signals.py` (gate builder that currently emits T13/T14/T15 with `>=` / `<=`)
- Modify: `backend/tests/test_signals.py` (update fixtures that assumed old floors; add relative-history cases)
- Optionally extend `SignalComputeInputs` with `atm_history_prior: list[AtmHistoryPoint] | None` and/or CE/PE legs; if inputs only have aggregated `volume`/`open_interest`/`spread_pct`, add optional CE/PE fields — **prefer** passing `AtmLiquidityLive` + prior into the gate function.

**Interfaces:**
- Consumes: `evaluate_atm_liquidity`, `AtmLiquidityLive`, `AtmHistoryPoint`, config keys from Task 1
- Produces: GateResults with ids `T13`, `T13b`, `T14`, `T14b`, `T15` (and keep T1/T11 as they are in current file unless options-only plan already removed T11)

- [ ] **Step 1: Write/adjust failing signal tests**

Update any test that expects pass with volume=1000-ish or spread exactly at old 2%. Add:

```python
def test_signal_liquidity_requires_relative_ratios(monkeypatch):
    # Build SignalComputeInputs with CE/PE hot enough vs injected prior history
    # Assert packet gates include T13b/T14b and liquidity failure when history empty
    ...
```

If `SignalComputeInputs` currently lacks CE/PE, extend it:

```python
# fields to add (defaults None for backward compat in demos)
ce_volume: int | None = None
pe_volume: int | None = None
ce_open_interest: int | None = None
pe_open_interest: int | None = None
ce_bid: float | None = None
ce_ask: float | None = None
pe_bid: float | None = None
pe_ask: float | None = None
atm_history_prior: list[AtmHistoryPoint] | None = None
```

When CE/PE present, build `AtmLiquidityLive` from them; else synthesize both sides from aggregated `volume`/`open_interest`/`spread_pct` **only for demo stubs**, and still require prior history for `liquidity_ok`.

- [ ] **Step 2: Run targeted tests — expect FAIL**

Run: `pytest backend/tests/test_signals.py -v`  
Expected: FAIL on outdated expectations and/or missing relative gates.

- [ ] **Step 3: Replace T13–T15 block in signals gate builder**

```python
from backend.services.atm_liquidity import (
    AtmLiquidityLive,
    AtmSideMarks,
    evaluate_atm_liquidity,
)

# build live + prior from inp
result = evaluate_atm_liquidity(
    live=live,
    prior=inp.atm_history_prior or [],
    min_volume=int(f["min_volume"]),
    min_open_interest=int(f["min_open_interest"]),
    max_spread_pct=float(f["max_spread_pct"]),
    volume_vs_avg_min_ratio=float(f["volume_vs_avg_min_ratio"]),
    oi_vs_avg_min_ratio=float(f["oi_vs_avg_min_ratio"]),
    lookback_days=int(f.get("atm_history_lookback_days", 20)),
    min_history_days=int(f.get("atm_history_min_days", 10)),
)
gates.append(GateResult(
    gate_id="T13",
    label=f"Volume ≥ {f['min_volume']}",
    passed=result.abs_volume_ok,
    detail=str(result.atm_volume),
    parameter_ref="Trading_Parameters.md Part T — T13",
))
gates.append(GateResult(
    gate_id="T13b",
    label=f"Volume > {f['volume_vs_avg_min_ratio']}× {result.history_days}d avg",
    passed=result.rel_volume_ok,
    detail=f"vs_avg={result.volume_vs_avg}",
    parameter_ref="Trading_Parameters.md Part T — T13b",
))
gates.append(GateResult(
    gate_id="T14",
    label=f"Open interest ≥ {f['min_open_interest']}",
    passed=result.abs_oi_ok,
    detail=str(result.atm_oi),
    parameter_ref="Trading_Parameters.md Part T — T14",
))
gates.append(GateResult(
    gate_id="T14b",
    label=f"OI > {f['oi_vs_avg_min_ratio']}× {result.history_days}d avg",
    passed=result.rel_oi_ok,
    detail=f"vs_avg={result.oi_vs_avg}",
    parameter_ref="Trading_Parameters.md Part T — T14b",
))
gates.append(GateResult(
    gate_id="T15",
    label=f"Spread < {f['max_spread_pct']}% of mid",
    passed=result.spread_ok,
    detail=f"{result.spread_pct:.2f}%",
    parameter_ref="Trading_Parameters.md Part T — T15",
))
```

Ensure overall signal blocking still treats failed liquidity gates as block (existing `all gates pass` logic).

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest backend/tests/test_signals.py backend/tests/test_atm_liquidity.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/signals.py backend/tests/test_signals.py
git commit -m "$(cat <<'EOF'
feat: enforce relative ATM liquidity gates in signal evaluation

EOF
)"
```

---

### Task 5: Wire enrichment snapshot + recommendation engine

**Files:**
- Modify: `backend/services/universe_enrichment.py`
- Modify: `backend/services/recommendation_engine.py`
- Modify: `backend/tests/test_universe_enrichment.py`
- Modify: tests that construct recommend candidates with old liquidity assumptions

**Interfaces:**
- Consumes: `AtmLiquidityHistoryStore.upsert_snapshot`, `prior_points`, `evaluate_atm_liquidity`
- After ATM marks computed (existing `atm_strike`, CE/PE vol/OI), call upsert with IST session date (`YYYY-MM-DD`).
- When building candidate / evaluating gates, load `prior_points(..., before_date=today)` and run evaluator.

- [ ] **Step 1: Failing tests**

```python
from pathlib import Path
from backend.services.atm_liquidity_history import AtmLiquidityHistoryStore
from backend.services import universe_enrichment as ue

def test_enrichment_writes_atm_history_snapshot(tmp_path, monkeypatch):
    hist_path = tmp_path / "atm_liquidity_history.json"
    monkeypatch.setattr(ue, "ATM_HISTORY_STORE_PATH", hist_path)  # or inject store
    # Call the mark/enrich helper that resolves ATM CE/PE for a fixture chain
    # (reuse existing test fixtures in test_universe_enrichment.py).
    # After one enrich:
    store = AtmLiquidityHistoryStore(hist_path)
    prior = store.prior_points(
        underlying="SBIN",
        expiry_key="<expiry from fixture>",
        before_date="2099-01-01",
        lookback_days=20,
    )
    assert len(prior) >= 1
    # Second enrich same session_date must not duplicate rows
    n1 = len(prior)
    # re-run enrich...
    prior2 = store.prior_points(
        underlying="SBIN",
        expiry_key="<expiry from fixture>",
        before_date="2099-01-01",
        lookback_days=20,
    )
    assert len(prior2) == n1

def test_recommend_gates_include_t13b_t14b():
    from backend.services.recommendation_engine import _evaluate_gates, InstrumentCandidate
    # Build candidate with volume/OI above abs floors, spread < 0.5, empty history
    c = InstrumentCandidate(  # use real constructor fields from recommendation_engine
        symbol="SBIN",
        und_price=800.0,
        atm_premium_inr=100.0,
        volume=5000,
        open_interest=50000,
        spread_pct=0.3,
        dte=20,
        # plus any required fields — copy from existing recommend tests
    )
    gates = _evaluate_gates(c, cfg_with_new_liquidity_keys, includes_underlying=False)
    by_id = {g.gate_id: g for g in gates}
    assert "T13b" in by_id and by_id["T13b"].passed is False  # no history
    assert "T14b" in by_id and by_id["T14b"].passed is False
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest backend/tests/test_universe_enrichment.py -k atm_history -v` (and recommend gate test file you add/extend)

- [ ] **Step 3: Implement wiring**

In enrichment, after CE/PE metrics:

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from backend.services.atm_liquidity_history import AtmLiquidityHistoryStore

store = AtmLiquidityHistoryStore()  # or injected for tests
session_date = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
store.upsert_snapshot(
    underlying=symbol,
    expiry_key=str(expiry_raw),
    session_date=session_date,
    atm_strike=float(atm_strike),
    atm_volume=int(min(ce_vol, pe_vol)),  # only if both > 0; else skip upsert
    atm_oi=int(min(ce_oi, pe_oi)),
)
```

In `recommendation_engine._evaluate_gates`, replace T13–T15 with evaluator results like Task 4. Attach `history_days` / ratios in gate `detail`.

Update analysis note strings that say old floors if any.

- [ ] **Step 4: Run — expect PASS**

Run: `pytest backend/tests/test_universe_enrichment.py backend/tests/test_atm_liquidity.py backend/tests/test_atm_liquidity_history.py -v`  
Plus recommend/signal tests touched.

- [ ] **Step 5: Commit**

```bash
git add backend/services/universe_enrichment.py backend/services/recommendation_engine.py backend/tests/test_universe_enrichment.py
git commit -m "$(cat <<'EOF'
feat: snapshot ATM liquidity history and gate recommendations on ratios

EOF
)"
```

---

### Task 6: Docs alignment

**Files:**
- Modify: `Docs/Trading_Parameters.md` (T10, T13–T16, L3.5–L3.7, I1, I20, and any “volume ≥ 1000 / OI ≥ 10000 / spread ≤ 2%” liquidity definitions)
- Modify: `Docs/Trading_Strategies.md` row that hardcodes those numbers (rule “Trade only high-liquidity options”)
- Light touch: `Docs/architecture.md` / `Docs/context.md` only if they state the old floors as product rules

**Interfaces:** None (docs only). Spec remains source of design; Trading_Parameters is canonical catalog.

- [ ] **Step 1: Update Part T / T10 validation block**

Replace absolute-only T13–T15 with:

| # | Parameter | Value / Rule |
|---|---|---|
| T13 | Min ATM volume (absolute) | **2000** — `min(CE,PE)` |
| T13b | Volume vs 20d avg | current `> 150%` of mean prior ≤20 sessions (`n≥10`) |
| T14 | Min ATM OI (absolute) | **20000** — `min(CE,PE)` |
| T14b | OI vs 20d avg | current `> 130%` of mean prior ≤20 sessions (`n≥10`) |
| T15 | Max bid-ask spread | **&lt; 0.5%** — `max(CE,PE)` spread |
| T16 | High liquidity required | all of the above |

Update T10 code block accordingly. Update L3.5–L3.7 and I1/I20 text.

- [ ] **Step 2: Update Trading_Strategies.md liquidity rule**

Change the table row from `min volume (1000), min OI (10000), spread cap (2%)` to the new relative + floor + 0.5% wording.

- [ ] **Step 3: Commit**

```bash
git add Docs/Trading_Parameters.md Docs/Trading_Strategies.md Docs/architecture.md Docs/context.md
git commit -m "$(cat <<'EOF'
docs: redefine high-liquidity gates with relative ATM volume and OI

EOF
)"
```

---

### Task 7: Regression sweep

**Files:**
- Modify any remaining tests still asserting old floors (`test_phase0.py`, `paper_sim`, mocks) only as needed for green CI
- No new features

- [ ] **Step 1: Run focused suite**

Run:

```bash
pytest backend/tests/test_atm_liquidity_config.py backend/tests/test_atm_liquidity.py backend/tests/test_atm_liquidity_history.py backend/tests/test_signals.py backend/tests/test_universe_enrichment.py -v
```

Expected: PASS

- [ ] **Step 2: Fix any leftover failures** caused by defaults 2000/20000/0.5 without changing the product rules.

- [ ] **Step 3: Final commit if fixes needed**

```bash
git add -u
git commit -m "$(cat <<'EOF'
test: align fixtures with relative ATM liquidity gates

EOF
)"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|---|---|
| Volume > 150% of ≤20d avg | 2, 4, 5 |
| OI > 130% of ≤20d avg | 2, 4, 5 |
| Spread &lt; 0.5% via max(CE,PE) | 2, 4, 5 |
| Abs floors 2000 / 20000 | 1, 2 |
| min(CE,PE) aggregation | 2 |
| Rolling ATM series + bot JSON history | 3, 5 |
| Partial avg at n≥10; fail if n&lt;10 | 2 |
| Today excluded from denominator | 3, 2 |
| Config/schema/docs | 1, 6 |
| Reason codes | 2 |
| No vendor history API / no T1–T8 changes | Global + non-goals |

## Self-review notes

- Strict `>` for ratios and `<` for spread are explicit in Task 2 tests (exact 1.5 / 0.5 must fail).  
- Signals and recommend both call the same evaluator (DRY).  
- No placeholder steps; CE/PE field extension on `SignalComputeInputs` is specified for Task 4.
