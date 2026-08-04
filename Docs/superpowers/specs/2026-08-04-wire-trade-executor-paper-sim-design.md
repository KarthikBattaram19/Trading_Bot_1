# Wire trade_executor.py through paper_sim + real approve/reject — design

Status: approved, ready for implementation plan.

## Why

`.cursor/rules/must-fix-before-claiming-performance.mdc` P0 item 1 and
`Docs/bot_health/BACKLOG.md`'s open P0 item require: recommend → supervised
approve → `paper_sim` → learning as one real ledger (no fills outside
`paper_sim`), with breakers/supervision durable. A full-code audit
(`Improve_Recoemmendation_Engine.md` §4.1, cross-checked against the repo)
confirmed the concrete gap: `backend/services/trade_executor.py` fabricates a
`trade_id` string and never calls `backend/paper_sim/` (zero references,
confirmed by grep), and `backend/routers/decisions.py` is read-only with no
approve/reject write path. This spec closes exactly that gap — P0 item 1 only,
no P1/P2 work from the audit doc.

## Scope

In scope:
1. Resolve a real entry leg from a recommendation and submit it through the
   existing `paper_sim` engine/ledger instead of fabricating a fill.
2. Gate the passive `GET /recommendations` auto-execution side effect behind
   `SUPERVISION_MODE`.
3. Add real `POST /decisions/{id}/approve` and `POST /decisions/{id}/reject`
   to `routers/decisions.py`, backed by a small persisted decision store.

Out of scope (explicitly not touched by this change):
- `SIMULATE_FIRST_RANK_FAILURE` (already fixed 2026-08-04, §4.2 of the audit).
- One-trade-lock durability (§4.3) — `get_active_trade_id()` already reads
  from the persisted `learning_service` open-trades store, not an in-memory
  global; this spec does not re-verify or re-implement that.
- Any P1 item (calibration, SH-4 config thresholds, gamma-scalping structure
  correctness, vega-scalp stop/flatten enforcement).

## Design

### 1. Entry-leg resolver

New helper in `backend/services/trade_executor.py`: given an
`InstrumentRecommendation`, resolve the nearest-ATM CE contract for
`underlying_symbol` at the nearest expiry with DTE ≥ 10 (same floor the
recommendation engine's own gates already use), via
`get_paper_engine().feed` (chain/resolve/list_options — all already used by
`structure_builder.py` and `PaperEngine._resolve_and_gate_legs`). Quantity is
1 lot at the feed record's lotsize. Produces a single `PaperLegRequest`
(`side="buy"`, `option_type="CE"`).

This is a fixed convention (always ATM CE, buy, 1 lot) — not derived from
`rec.strategy.entry_mode` or scenario tag. `structure_builder`'s existing
`build_intended_legs_from_entry` already expands this single leg into the
full strategy structure (opposite-side ATM leg for simple_volatility/vega
strategies; four-leg shape for gamma_scalping) exactly as it does for the
manual `/paper-sim/orders` submission path — no new structure logic needed.

### 2. `_simulate_broker_submit` → real `paper_sim` submit

Replace the fabricated `trade_id = f"trd_..."` / `order_status="filled"`
unconditional-success path with:

```python
leg = resolve_entry_leg(rec)  # new helper, §1
if leg is None:
    return False, None, "Could not resolve an ATM option contract for <symbol>"

request = PaperOrderRequest(
    strategy_tag=rec.strategy.selected_strategy.value,
    underlying=rec.underlying_symbol,
    legs=[leg],
    auto_complete_multi_leg=True,
)
try:
    result = await get_paper_engine().submit_order(request)
except (PaperLedgerError, StaleMarksError, Exception) as exc:
    return False, None, f"paper_sim reject: {exc}"

return True, result["position"]["position_id"], None
```

The existing shadow ICICI Direct broker-router call (`USE_ICICI_DIRECT_SHADOW`)
is unchanged — it remains a fire-and-forget observability shadow, not the
fill source; `paper_sim` is now the only fill source.

`trade_id` becomes the paper_sim `position_id`. It is still registered into
`learning_service.register_open_trade()` exactly as before — that registration
already survives restart (per `get_active_trade_id`'s existing docstring) —
now backed by a real ledger row instead of a bare string with no ledger
existence.

Pre-submit checks (`_pre_submit_checks`, gate/lock checks) are unchanged —
they run before this resolution and stay a fast, ledger-free rejection path.

### 3. SUPERVISION_MODE gate on the passive GET path

`routers/recommendations.py`'s `_recommendations_with_autonomous_execution`
(the function `GET /recommendations` calls on every fresh/refresh cycle)
reads `os.getenv("SUPERVISION_MODE", "supervised")` (same env var and same
default `bot.py` already uses). When supervised (the default), it skips
`_autonomous_execution_for(...)` entirely and returns
`AutonomousExecutionResult(executed=False, attempts=[], message="Supervision mode requires explicit approval — see POST /decisions/{id}/approve")`.
When `SUPERVISION_MODE=autonomous`, behavior is unchanged from today (auto-
executes top-3 on every fresh cycle) — now for real, through `paper_sim`.

`POST /execute-autonomous` is explicitly operator-triggered (not a passive
page-load side effect) and stays available in both modes, unchanged.

### 4. Persisted decision store

New small JSON-file-backed store in `backend/services/decision_log.py`,
same pattern as `backend/services/kill_switch_state.py` (survives restart).
Schema: `decision_id -> {status: "approved"|"rejected", trade_id: str | None,
reason: str | None, acted_at: datetime}`.

`list_decisions()` / `get_decision()` overlay this store on top of the
existing derived projection: if a decision_id has a stored `approved`/
`rejected` status, that status wins over the live-projection's
`pending`/`expired` computation (so an approved-then-TTL-expired decision
still reads as `approved`, and a rejected one never reappears as pending on
the next cycle for the same `decision_id`).

### 5. `POST /decisions/{id}/approve` and `POST /decisions/{id}/reject`

Both in `routers/decisions.py`:

- Look up the decision via `decision_log.get_decision(decision_id)`. 404 if
  unknown.
- 409 if its (store-overlaid) status is not `pending` — already acted on or
  expired; approve/reject only ever act on a currently-pending decision.
- **Approve:** re-resolve the source `InstrumentRecommendation` from the live
  recommendation cache (`peek_cached_recommendations()`) by matching
  `decision_id`/`underlying_symbol`; if the cache has rolled past it (cold
  cache, new cycle), 409 with a clear message to re-fetch `/decisions/pending`.
  Run `execute_autonomous_from_recommendations([rec])` — single-candidate,
  since the operator picked this exact one, so no rank-fallback to a
  different symbol. Persist `approved` + resulting `trade_id` (or, if
  `paper_sim` rejects it, surface the error in the response body without
  marking approved — decision stays `pending` so the operator can retry or
  reject). Response includes the `AutonomousExecutionResult`.
- **Reject:** persist `rejected` with the optional request-body `reason`. No
  execution. Response echoes the stored record.

## Data flow (approve path)

```
GET /decisions/pending          -> operator sees a pending decision
POST /decisions/{id}/approve    -> decision_log looks up live rec by id
                                 -> execute_autonomous_from_recommendations([rec])
                                 -> trade_executor resolves ATM CE leg (§1)
                                 -> PaperEngine.submit_order (§2) -> real ledger row
                                 -> learning_service.register_open_trade (unchanged)
                                 -> decision store: status=approved, trade_id=<position_id>
```

## Error handling

- Entry-leg resolution failure (no chain data, no matching expiry ≥ 10 DTE,
  feed error) → same `(False, None, error_message)` shape as today's
  broker-reject path, so the existing rank-fallback loop in
  `execute_autonomous_from_recommendations` is untouched.
- `paper_sim` gate failures (fresh-marks, pre-trade gate, capital caps) map
  to the same tuple shape via a caught `PaperLedgerError`/`StaleMarksError`,
  not an unhandled 5xx.
- Approve on a stale/rolled-past decision_id → 409, not a silent no-op or a
  fabricated fill.

## Testing

- `backend/tests/test_trade_executor.py` (existing file): add coverage for
  the entry-leg resolver (mock feed returns/doesn't return a contract), and
  update `_simulate_broker_submit` tests to assert it calls
  `PaperEngine.submit_order` and that a `PaperLedgerError` surfaces as a
  failed attempt (not an exception escaping to the caller).
- `backend/tests/test_recommendations_router.py` (existing or new): assert
  `GET /recommendations` does not call `execute_autonomous_from_recommendations`
  when `SUPERVISION_MODE=supervised` (default) and does when `=autonomous`.
- `backend/tests/test_decisions.py` (new): approve happy path creates a real
  `paper_sim` position and persists `approved`; reject persists without
  executing; approve/reject on a non-pending id returns 409; approve on an
  unknown id returns 404; decision store survives a fresh `decision_log`
  reload (restart-durability check, same style as kill-switch-state tests).
