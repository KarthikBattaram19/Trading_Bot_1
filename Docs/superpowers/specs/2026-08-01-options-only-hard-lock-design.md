# Options-Only Hard Lock — Design Spec

| Field | Value |
|---|---|
| Date | 2026-08-01 |
| Status | Approved for implementation planning |
| Approach | Docs-first product lock (Approach 1) |
| Canonical catalog | `Docs/Trading_Parameters.md` |

## 1. Goal

Lock the volatility-trading bot so it **only** constructs, recommends, paper-trades, and live-submits **option structures** (Call/Put legs). There is **no** path that trades the cash underlying / stock hedge.

`und_price` and `underlying_symbol` remain **market-data and pricing inputs** (BSM, ATM selection, GARCH, feeds). They are not tradeable instruments in this product.

## 2. Locked decisions

| Decision | Choice |
|---|---|
| Enforcement | **Hard lock** — reject any `type=stock` leg and any stock/cash-share hedge path |
| Universe | **No** underlying price cap; cash equities **and** index underlyings allowed if ATM / premium / liquidity gates pass |
| OSS stock math | Keep in BSM + OSS parity / unit tests only — never construct or submit stock legs in prod/paper/signals/recommend/broker |
| T11 / cash-equity-only keys | **Remove** as product rules from docs, schema, defaults, and signal evaluation |

## 3. Product rules

1. Allowed tradeable leg types in execution paths: `call`, `put` only (`none` reserved for empty OSS slots in tests).
2. Reject if any of:
   - any leg has `type=stock`
   - `hedge_method=stock`
   - `gamma_construction=calls_stock` (or equivalent “calls + stock” construction)
   - hedge path would buy/sell NSE/BSE cash shares
3. Stable reject code: `OPTIONS_ONLY_REQUIRED` (API HTTP 400 where applicable; signal gate fail otherwise).
4. Spot ≤ ₹1000 is **not** a product rule. Index exclusion for “cannot stock-hedge” is **not** a product rule.
5. Re-hedge must neutralize via **options** (`reduce_options`, `adjust_call_put_mix`, or options-only meaning of size-up). Never add/remove stock shares.

## 4. `Trading_Parameters.md` dependency map

### 4.1 Remove or rewrite (stock / dual-mode)

| Area | IDs / keys | Action |
|---|---|---|
| Part A | A5 notes on stock-mode T11; A12 `default_stock_multiplier` as live hedge | Clarify spot is feed-only; stock multiplier = OSS/test-only |
| Part A14 | `default_stock_multiplier` / stock hedge rows | Drop live use; note test-only if retained for OSS |
| Part B | B6 enum still lists `stock` for OSS; B14–B15 stock rules | Document: rejected in bot execution; OSS parity only |
| Part G | G8 borrow for short stock; G13 `und_price` T11 note | Retarget borrow to short options if needed; remove T11 |
| Part I | I4 short-stock borrow; I18 / I18a; I21 underlying-cap gate | Remove cap gates; retarget borrow |
| Part J | J4 `increase_hedge` if it implied stock | Default rehedge = `adjust_call_put_mix`; keep `reduce_options`; document `increase_hedge` as options size-up only (no shares) |
| Part L | L2.1a; L5 Path A (calls+stock); L5.1 `stock`; L5.4 `stock_qty`; L9 scenario E dual-mode | Options-only path only |
| Part M | M3 calls+stock; M3.6 `stock_qty`; M3.12 `calls_stock`; M4.1a | Force `four_leg_options` |
| Part N | N2.1a; N5.1 `stock` | Options-only hedge only |
| Part O | Borrow / financing cost rows tied to stock hedge | Drop or retarget |
| Part P | P1.5 hedge construction allowing stock | Options-only quantities |
| Part Q / R | Dual-mode critical paths; “stock hedge leg optional” | Rewrite to options-only |
| Part T | Mode table; T11, T11a–d; T9 validation | Remove; document options-only universe |

### 4.2 Keep (still required without trading underlying)

- A1–A4, A6–A11 (valuation, spot mark, rates, vol, NFO lot sizing)
- A5 / G11 / G12 — symbol + feeds for chain and spot marks
- B* for call/put legs; D expiration catalog; E BSM; H GARCH; U news
- T1–T6, T7–T8, T10, T13–T16 — ATM, premium < ₹300, liquidity
- Strategy signal/exit parameters (L/M/N) that do not require stock legs

### 4.3 Downstream docs

Update the same product rule in:

- `Docs/Trading_Strategies.md`
- `Docs/architecture.md` (incl. §2.3 tradeable-universe wording)
- `Docs/context.md`
- `Docs/Paper_Simulator.md`
- `Docs/edge_cases.md`
- `Docs/implementation_plan.md` (note the lock)

## 5. Code & config surfaces

| Surface | Change |
|---|---|
| `backend/schemas/trading_parameters.schema.json` | Remove T11* / index-exclude / cash-equity-require keys; constrain strategy `hedge_method` to `options_only`; constrain gamma `construction` to `four_leg_options`; keep leg `type` enum including `stock` for OSS parity fixtures — services reject stock in all execution paths |
| `backend/config/trading_parameters.defaults.json` | Drop removed keys; set `hedge_method=options_only`, `construction=four_leg_options`; default rehedge to `adjust_call_put_mix` |
| `backend/services/signals.py` | Remove T11 evaluation; add hard stock-leg / stock-hedge reject |
| `backend/paper_sim/*` | Reject stock legs on open; never emit stock on rehedge |
| Live order builder / broker adapter paths | Same reject before ICICI Direct submit |
| Frontend types / mocks | Stop shipping stock legs as recommended live structures |
| `backend/quant/pricing/bsm.py` + `backend/tests/quant/test_oss_parity.py` | **Keep** stock-leg pricing for parity |

### Central gate

```
allowed_leg_types = {call, put}  # none only for empty OSS slots in tests
if any(leg.type == "stock") or hedge_method == "stock" or construction == "calls_stock":
    reject(OPTIONS_ONLY_REQUIRED)
```

Apply at: signal evaluate → recommendation packet → paper open → live order build.

## 6. Errors

| Code | When | HTTP (API) |
|---|---|---|
| `OPTIONS_ONLY_REQUIRED` | Stock leg or stock hedge/construction requested | 400 |

Message: structure must use Call/Put legs only; stock/underlying legs are not allowed.

## 7. Tests

- Signal + paper-sim: reject stock legs and stock hedge config.
- Remove/rewrite T11 options+underlying tests (keys gone).
- Keep OSS parity tests that include stock legs (pricing-only).
- Schema/defaults load: no T11 keys; strategies default to options-only / four-leg.
- Optional: index underlying (e.g. NIFTY) is **not** rejected solely for being an index when other gates pass.

## 8. Non-goals

- Removing stock branches from BSM / OSS parity fixtures.
- Stopping NSE/index LTP or option-chain feeds.
- Implementing new strategy families beyond existing three, rewritten to options-only constructions.
- GTT or other out-of-scope broker features.

## 9. Rollout order

1. This spec committed and reviewed.
2. Implementation plan via writing-plans skill.
3. Schema + defaults.
4. Signals / paper-sim / order-build gates + tests.
5. Docs (`Trading_Parameters.md` first, then dependents).
6. Frontend mocks/types cleanup.
7. Focused pytest: signals, paper-sim, OSS parity.

## 10. Success criteria

- No production or paper path can open or recommend a stock/underlying leg.
- Indices may pass universe filters when ATM / premium / liquidity pass.
- Spot ≤ ₹1000 does not appear as an enforced live product rule in config or signal gates.
- Docs and schema agree: options-only hard lock.
