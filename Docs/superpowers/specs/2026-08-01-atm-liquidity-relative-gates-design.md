# ATM Liquidity Relative Gates — Design Spec

| Field | Value |
|---|---|
| Date | 2026-08-01 |
| Status | Approved for implementation planning |
| Approach | Config + enrichment gate + JSON EOD store (Approach 1) |
| Scope | Liquidity gates only (T13–T16 / related) |
| Canonical catalog | `Docs/Trading_Parameters.md` Part T / I / L |

## 1. Goal

Replace the project’s absolute-only definition of “high liquidity” with rules centered on:

1. **ATM volume > 150%** of the rolling 20-session average  
2. **ATM OI > 130%** of the rolling 20-session average  
3. **Bid–ask spread < 0.5%**

Absolute floors remain as a safety layer underneath. Premium, moneyness (T1–T8), and other non-liquidity Part T rules are unchanged.

## 2. Locked decisions

| Decision | Choice |
|---|---|
| Scope | **A** — liquidity gates only (T13–T16, T10, L3.5–L3.7, I1/I20, schema, defaults, enrichment, signals, recommend, docs mentions) |
| 20-day series | **Rolling ATM** — each session uses that day’s then-ATM strike; average those daily readings |
| CE/PE aggregation (volume & OI) | **`min(CE, PE)`** |
| Spread aggregation | **`max(CE_spread%, PE_spread%) < 0.5`** |
| Incomplete history | Use partial average when **≥ 10** and **&lt; 20** sessions; still require 150% / 130% vs that partial average |
| Absolute floors | Keep underneath relative rules: vol ≥ **2000**, OI ≥ **20000**; spread cap becomes **&lt; 0.5%** (replaces 2.0%) |
| History source | Bot-owned EOD snapshots (JSON under `backend/data/`) — no new vendor historical OI API |
| Implementation style | Approach 1 — evaluator + JSON store + config rewrite |

## 3. Product rules

### 3.1 Per-session ATM metrics

For underlying `U`, screening expiry `E`, session date `D`:

1. Select ATM strike `X*` via existing T7 (`closest_strike_to_spot`, tolerance 0).  
2. Read CE and PE volume, OI, bid, ask at `X*`.  
3. Compute:

```
atm_volume(D) = min(CE_vol, PE_vol)
atm_oi(D)     = min(CE_oi, PE_oi)
ce_spread%    = (ce_ask - ce_bid) / ce_mid * 100   # mid > 0, bid > 0, ask > 0
pe_spread%    = (pe_ask - pe_bid) / pe_mid * 100
spread_pct    = max(ce_spread%, pe_spread%)
```

Missing CE or PE, non-positive bid/ask/mid, or missing vol/OI → that metric fails (fail closed).

### 3.2 History window

- Store one snapshot row per `(underlying, expiry_key, session_date)` (idempotent overwrite for same date).  
- Lookback for averages: last **up to 20** completed sessions with valid `atm_volume` / `atm_oi`.  
- Let `n` = number of **prior** sessions used in the average (**exclude today’s live print** from the denominator so current-vs-average is not circular; today’s live marks are the numerator only).  
- If `n < 10`: relative volume and relative OI gates **fail**. Absolute floors alone do **not** make `liquidity_ok=true`.  
- If `10 ≤ n ≤ 20`:  

```
avg_vol = mean(atm_volume over n sessions)
avg_oi  = mean(atm_oi over n sessions)
```

### 3.3 Pass conditions (`liquidity_ok`)

All must pass:

| Gate | Condition |
|---|---|
| T13 absolute volume | `atm_volume ≥ 2000` |
| T13b relative volume | `n ≥ 10` and `avg_vol > 0` and `atm_volume > 1.50 × avg_vol` |
| T14 absolute OI | `atm_oi ≥ 20000` |
| T14b relative OI | `n ≥ 10` and `avg_oi > 0` and `atm_oi > 1.30 × avg_oi` |
| T15 spread | `spread_pct < 0.5` |
| T16 | `high_liquidity_required=true` ⇒ all of the above |

Strict inequalities for ratios and spread: equality at 150%, 130%, or 0.5% **fails**.

### 3.4 Multi-expiry

For structures that require near and far ATM legs (e.g. gamma), evaluate liquidity independently per required expiry; every required leg must pass.

## 4. Components & data flow

```
option chain marks
    → ATM strike (T7)
    → live atm_volume / atm_oi / spread_pct
    → snapshot writer (idempotent today’s row)
    → load last ≤20 prior sessions
    → liquidity evaluator
    → GateResults + liquidity_ok
    → signals / recommendation_engine
```

| Piece | Responsibility |
|---|---|
| JSON EOD store | Persist ATM daily series under `backend/data/` (e.g. `atm_liquidity_history.json`); retain ~60 days; averages use ≤20 |
| Snapshot writer | Called from universe enrichment (or EOD hook); writes today’s ATM `min(CE,PE)` vol/OI |
| Liquidity evaluator | Pure function: live marks + history + config → gate list + `liquidity_ok` |
| Config / schema | Defaults + JSON Schema keys for floors, ratios, lookback, min days, agg modes |
| Call sites | `universe_enrichment.py`, `signals.py`, `recommendation_engine.py` |
| Docs | `Trading_Parameters.md` (T10, T13–T16, L3.5–L3.7, I1, I20); update hardcoded 1000/10000/2% mentions in `Trading_Strategies.md` / architecture only where they define these gates |

## 5. Config keys (defaults)

| Key | Default | Notes |
|---|---|---|
| `min_volume` | `2000` | Absolute floor |
| `min_open_interest` | `20000` | Absolute floor |
| `max_spread_pct` | `0.5` | Pass if `spread_pct < max_spread_pct` |
| `volume_vs_avg_min_ratio` | `1.5` | Pass if current > ratio × avg |
| `oi_vs_avg_min_ratio` | `1.3` | Pass if current > ratio × avg |
| `atm_history_lookback_days` | `20` | Max sessions in average |
| `atm_history_min_days` | `10` | Min sessions before relative gates can pass |
| `atm_liquidity_agg` | `min_ce_pe` | Volume/OI aggregation |
| `spread_agg` | `max_ce_pe` | Spread aggregation |
| `high_liquidity_required` | `true` | Unchanged master switch |

Remove or stop treating former defaults (`min_volume=1000`, `min_open_interest=10000`, `max_spread_pct=2.0`) as the definition of liquid.

## 6. Errors / reason codes

| Code | When |
|---|---|
| `ATM_HISTORY_TOO_SHORT` | `n < atm_history_min_days` |
| `ATM_VOLUME_BELOW_AVG_RATIO` | current volume ≤ 1.50 × avg |
| `ATM_OI_BELOW_AVG_RATIO` | current OI ≤ 1.30 × avg |
| `ATM_SPREAD_TOO_WIDE` | `spread_pct ≥ 0.5` |
| `ATM_ABS_FLOOR_FAIL` | volume &lt; 2000 or OI &lt; 20000 |
| `ATM_LIQUIDITY_DATA_MISSING` | missing quotes / vol / OI / zero mid |

Gate payloads should expose `history_days`, `volume_vs_avg`, `oi_vs_avg`, `spread_pct` in detail fields for UI/debug.

## 7. Tests

- Ratio boundaries: just below / at / above 1.50 and 1.30; spread at 0.499 / 0.5 / 0.501.  
- `min(CE,PE)` and `max(spread)` aggregation.  
- History length 9 → relative fail; 10 and 20 → partial/full average used; today excluded from denominator.  
- Snapshot idempotency for same session date.  
- `avg_vol=0` or `avg_oi=0` → relative fail.  
- Signals/recommend: cannot pass liquidity on old 2%/1000/10000 alone.  
- Schema/defaults load with new keys and floors.

## 8. Non-goals

- External vendor historical OI/volume API.  
- Changing T1–T8 premium/ATM selection.  
- Broader options-only hard lock (separate spec).  
- Strategy signal logic beyond liquidity number references.

## 9. Rollout order

1. This spec reviewed.  
2. Implementation plan via writing-plans skill.  
3. Schema + defaults.  
4. History store + snapshot writer + evaluator + unit tests.  
5. Wire signals / enrichment / recommendation_engine.  
6. Docs (`Trading_Parameters.md` first, then dependent mentions).  
7. Focused pytest.

## 10. Success criteria

- Live/paper liquidity pass requires: abs floors (2000 / 20000) **and** volume > 150% of ≤20d avg **and** OI > 130% of ≤20d avg **and** spread &lt; 0.5%, with `n ≥ 10`.  
- Bot accumulates ATM daily history without a new market-data vendor.  
- Docs, schema, and gate labels no longer advertise vol≥1000 / OI≥10000 / spread≤2% as the high-liquidity definition.
