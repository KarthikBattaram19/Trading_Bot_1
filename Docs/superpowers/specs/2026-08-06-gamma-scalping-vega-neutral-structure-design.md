# Rebuild gamma_scalping opening structure as a vega-neutral calendar spread — design

Status: approved, ready for implementation plan.

## Why

`Improve_Recoemmendation_Engine.md` §3.10 (P1 item 11) found that every
"gamma_scalping" position this bot opens today is not gamma scalping at all:
`backend/paper_sim/structure_builder.py`'s `_append_second_strike_option_pair`
adds CE+PE at a *second strike*, same side (`first.side`, always `BUY`), same
expiry as the entry leg — i.e. a second long straddle. `Docs/Trading_Strategies.md`
Table GS-4 defines gamma scalping as a same-strike, two-expiry structure: long
short-dated calls+puts, **short** longer-dated calls+puts sized to zero out
portfolio vega (mirrored into puts per the delta identity in step 4). What the
code builds today has no `SELL` leg anywhere and carries full unhedged long
vega — the opposite of the strategy's own Greek Profile Target (Table GS-2:
vega ≈ 0).

This spec closes §3.10 only. §3.12 (Table GS-8 term-structure no-inversion
gate) is explicitly deferred — it depends on this structure existing first,
per the audit's own priority ordering (P1 items 11 then 13).

## Scope

In scope:
1. Resolve a genuinely longer-dated expiry (config-driven minimum DTE gap
   from the near-dated leg).
2. Solve the short-leg quantity for the far-dated calls via BSM vega, so the
   near+far call pair is vega-neutral (GS-4 step 3).
3. Mirror that exact quantity into the far-dated put (GS-4 step 4) — not
   independently re-solved.
4. Fail closed (no fake structure) when a valid far expiry or a sane vega
   solve isn't available.

Out of scope:
- §3.12 (term-structure IV data model + GS-8 no-inversion gate) — separate
  follow-on item.
- §3.11 (vega-scalping stop/flatten enforcement in `automation.py`) —
  unrelated strategy, separate item.
- Any change to `strategy_selection.py`'s SH-4 gating — this spec only fixes
  *construction* of a structure that selection already decided to open.
- `PaperOrderRequest`/`PaperLegRequest` schema changes — no new fields cross
  the API boundary.
- Persisting residual Greeks on `PaperPosition` — log-only for this fix
  (`paper_sim/automation.py` already recomputes live position Greeks every
  cycle via `mark_strategy`, so the residual is re-derivable later).

## Design

### 1. What stays unchanged

`_append_opposite_option_at_strike` (the near-dated CE+PE pair, same side as
the entry leg) already matches GS-4 steps 1–2 exactly — same strike, same
expiry, `BUY` both legs. `build_intended_legs_from_entry`'s call to it for
`gamma_scalping` is untouched.

### 2. `_append_second_strike_option_pair` → `_append_vega_neutral_far_dated_pair`

Replaces the second call in `build_intended_legs_from_entry`'s
`gamma_scalping` branch. Signature grows one parameter,
`paper_sim_config: PaperSimConfig`, threaded from the one call site
(`engine.py:286`) via `self.config` — `engine.submit_order` is already
`async`, so `build_intended_legs_from_entry` becomes `async def` and that
call site adds `await`.

Steps, all against the entry leg's strike (`record.strike`):

1. **Resolve far expiry.** Enumerate listed expiries for the underlying via
   `feed.list_options` (same pattern as `universe_enrichment.select_preferred_expiry`),
   compute each expiry's DTE with the same date-diff convention used there.
   Pick the smallest-DTE expiry satisfying
   `dte_far >= dte_near + long_expiry_min_gap_days`
   (new config key, see §4). None found → `logger.warning`, return without
   appending anything (near-dated straddle only survives — §5).
2. **Fetch spot.** Resolve the underlying's NSE record and call
   `feed.get_ltp(...)` — identical to the `hedge_point` resolution already in
   `engine.py:309-319`.
3. **Compute vega.** Call `backend.quant.pricing.bsm.option_greeks()` twice
   (near-dated CE, far-dated CE), both at `strike=record.strike`,
   `spot=<step 2>`, `int_rate=paper_sim_config.risk_free_rate_pct`,
   `dividend_yield=paper_sim_config.dividend_yield_pct`,
   `volatility=paper_sim_config.default_iv_annual_pct` — the same flat-vol
   convention `automation.py:419-430` already uses for live position marking,
   so this fix introduces no second Greeks convention into the codebase.
   `days_to_expiry` per leg from step 1's DTEs.
4. **Solve far quantity.** `first.quantity`/`qty` is a **share** count
   (contracts × lotsize), not a lot count — convert before solving:
   `near_contracts = qty / near_record.lotsize` (near_record is the entry
   leg's own resolved record, lotsize already known from step 0 in the
   existing code path). `far_contracts = round(near_contracts * vega_near_call / vega_far_call)`,
   floored at 1. If `vega_far_call` is non-finite or ≈0 (far leg at/near
   expiry, or a degenerate BSM input), `logger.warning`, return without
   appending (same fallback as step 1).
5. **Append SELL far CE**, `far_contracts * far_record.lotsize` shares, at
   `record.strike`, far expiry.
6. **Append SELL far PE** at the *same* strike/expiry/quantity as step 5 —
   mirrored directly, not re-solved (GS-4 step 4's delta-identity shortcut).
7. **Log verification.** `logger.info` one line with near/far vega, solved
   quantities, and the resulting four-leg residual delta/vega (sum of all
   four legs' BSM Greeks, near legs signed `+1`, far legs signed `-1`) —
   satisfies GS-4 step 5's "verify all four Greeks numerically," log-only
   per scope.

Every early-return in steps 1 and 4 leaves `intended` exactly as it was after
`_append_opposite_option_at_strike` — i.e. the near-dated long straddle only.
This is a deliberate behavior change from today: today's fallback silently
added a second same-side straddle (more unhedged long vega); this fix's
fallback adds nothing further and logs why.

### 3. Helper reuse / additions

- A small local `_dte_from_expiry`-equivalent (mirroring
  `universe_enrichment.py`'s private helper — not imported, since that one is
  module-private and `structure_builder.py` should not reach into
  `services/` for a one-line date diff).
- `_find_matching_option` (existing) is reused unchanged to resolve the exact
  far CE/PE `InstrumentRecord` once strike/expiry/type are known.

### 4. Config addition

`backend/config/trading_parameters.defaults.json`, new key alongside the
existing `strategies.gamma_scalping.entry_signal` section (from §3.1's fix):

```json
"strategies": {
  "gamma_scalping": {
    "calendar_construction": {
      "long_expiry_min_gap_days": 28
    }
  }
}
```

`28` matches the source's own 35-DTE-vs-63-DTE reference pair (Table GS-1).
Read in `structure_builder.py` via the same `trading_parameters` config
loader already used by `strategy_selection.py` for the §3.1 thresholds.

### 5. Fallback behavior (explicit)

| Condition | Result |
|---|---|
| No expiry clears the min-gap window | 2-leg near-dated straddle only; `logger.warning` |
| Far-leg vega ≈ 0 / non-finite | 2-leg near-dated straddle only; `logger.warning` |
| Far CE/PE record not found in chain (liquidity/listing gap) | Whichever of the two far legs resolved is appended; missing one logged — same partial-append tolerance the existing `_append_opposite_option_at_strike`/`_find_matching_option` pattern already has (returns `None` silently today; this fix adds the warning log, doesn't change the partial-structure tolerance) |

No exception is raised in any of these paths — matches the file's existing
style (`build_intended_legs_from_entry` and its helpers never raise; the
caller's `missing_intended_legs`/`structure_complete` machinery already
handles a structure that ends up short of what was "intended").

## Data flow

```
entry fill (BUY near CE, 1 lot)
  -> _append_opposite_option_at_strike   [unchanged]
       -> BUY near PE, same strike/expiry/qty
  -> _append_vega_neutral_far_dated_pair [new]
       -> resolve far expiry (min DTE gap)
       -> spot = feed.get_ltp(underlying)
       -> vega_near, vega_far = bsm.option_greeks(...) x2
       -> far_contracts = round(near_contracts * vega_near/vega_far)
       -> SELL far CE, far_contracts * far_lotsize shares
       -> SELL far PE, same share quantity (mirrored)
       -> log residual delta/vega
intended = [BUY near CE, BUY near PE, SELL far CE, SELL far PE]
```

## Error handling

Covered in §5's table — every failure mode fails closed to a smaller,
already-gate-checked structure (the near-dated straddle), never to the
previous same-side double-straddle behavior. No new exception types; no
change to how `engine.submit_order` treats a structure that ends up smaller
than "intended" (existing `structure_complete`/`missing_intended_legs`
handling already covers a partially-built plan).

## Testing

New `backend/tests/test_structure_builder.py` (no test file exists for this
module today):

1. **Happy path.** `FakeFeed` with two expiries ≥ `long_expiry_min_gap_days`
   apart; assert the four resulting legs are BUY near CE, BUY near PE, SELL
   far CE, SELL far PE, all at the same strike; assert far quantity is
   derived from the vega ratio (not equal to near quantity by coincidence —
   pick fixture IVs/DTEs where the ratio isn't 1:1).
2. **Mirrored put quantity.** Far PE quantity exactly equals the solved far
   CE quantity — assert it's the *same* value, not independently recomputed
   (would catch a regression back toward re-solving both legs separately).
3. **No far expiry available.** `FakeFeed` with only one expiry (or all
   expiries within the gap) → result has exactly 2 legs (near straddle only),
   no `SELL` leg, no exception.
4. **Degenerate vega.** Far expiry at/near zero DTE → same 2-leg fallback.
5. **Residual check.** Sum of the four legs' BSM delta/vega (recomputed in
   the test via `bsm.option_greeks`, mirroring §2 step 7's math) is small
   relative to the unhedged (near-only) case's vega — proves the solve
   actually reduces net vega, not just that it runs without error.

Existing fixtures needing updates:
- `backend/tests/test_paper_sim_options_only.py` / `test_paper_sim.py` —
  gamma_scalping-tagged test cases' `FakeFeed`/`_RecordingAdapter`-style
  fakes need a second expiry's option chain added wherever they currently
  only stub one expiry, or those tests will hit the new "no far expiry"
  fallback and start asserting on a 2-leg result instead of 4-leg.
