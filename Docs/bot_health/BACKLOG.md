# Guruji_for_Bhale_Bullodu — Backlog

Findings are bucketed under the priority headings from
`.cursor/rules/must-fix-before-claiming-performance.mdc` (read fresh each
run — this file does not redefine that priority order, only tracks status
against it). Items outside that rule's scope go under "Other" and stay
deprioritized behind any open P0/P1 item.

## P0 — integrity of the trading loop

- [x] **Frontend never wires the real approve/reject endpoints, so a
  human operator has no discoverable way to act on a recommendation in
  `SUPERVISION_MODE=supervised` (prod default) — the P0-1 loop is closed
  in the backend but not operable end-to-end.** `frontend/src/app/recommendations/page.tsx`
  renders `RecommendationsLoader` → `RecommendationCard`
  (`frontend/src/components/recommendations/recommendation-card.tsx`), which
  is a pure read-only insight packet with zero approve/reject action — its
  footer literally reads "execution result attaches when `fully_autonomous`"
  with no button. `frontend/src/app/decisions/page.tsx` →
  `DecisionsLoader` (`frontend/src/components/decisions/decisions-loader.tsx:105-106`)
  still hardcodes the stale copy "read-only audit trail — no approval
  queue," even though `backend/routers/decisions.py` has shipped real
  `POST /{id}/approve` / `POST /{id}/reject` since the 2026-08-04 P0 fix,
  and the decisions table itself renders no action buttons. The only place
  `ApprovalCard` (`frontend/src/components/dashboard/approval-card.tsx`,
  which does call `approveDecision`/`rejectDecision`) is mounted is the
  per-decision detail route `frontend/src/app/decisions/[id]/page.tsx`,
  reachable only via a "Packet" link in the decisions table — not linked
  from `/recommendations` at all. Net effect confirmed live against prod
  2026-08-06 (`https://tradingbot1-production-a574.up.railway.app`,
  `GET /api/v1/bot/status` → `"supervision_mode":"supervised"`): even on a
  cycle that clears the confidence bar, there is no button anywhere in the
  primary `/recommendations` flow for an operator to open the trade, and
  the one page that has a working Approve button is undiscoverable without
  already knowing the decision ID / clicking through the audit table.
  Turning `SUPERVISION_MODE=fully_autonomous` would "fix" this but
  reintroduces the exact unsupervised-auto-execute risk P0-1 removed — the
  correct fix is wiring the existing `ApprovalCard` (or an equivalent
  action) into `/recommendations` and correcting the stale
  `decisions-loader.tsx` copy. (first seen 2026-08-06, evidence above)
  - **Resolved 2026-08-06**, evidence: `frontend/src/lib/utils.ts` adds
    `liveDecisionId()` (UTC-safe, matches
    `decision_log.py::_live_decisions`'s `dec_{symbol}_{day}` id exactly
    since both read the same response's `generated_at`).
    `RecommendationsPage` → `RecommendationsLoader` → `RecommendationsView`
    now thread `supervision_mode` (from `GET /bot/status`) and
    `generated_at` down to `RecommendationCard`
    (`frontend/src/components/recommendations/recommendation-card.tsx`),
    which now renders a "Review & approve" button linking straight to
    `/decisions/{id}` (the page hosting the real `ApprovalCard`) for every
    packet, whenever `supervisionMode !== "fully_autonomous"` and the
    packet hasn't already executed. `decisions-loader.tsx`'s stale
    "read-only audit trail — no approval queue" copy is corrected, and its
    per-row link now reads "Review & approve" for pending decisions
    (still "Packet" for acted-on ones) instead of a uniform, non-actionable
    "Packet" label. `npx tsc --noEmit` and `npm run build` both pass clean;
    no backend contract changed, so no new backend tests were needed for
    this half — verified the id-construction logic is behaviorally the
    inverse of `decision_log.py::_to_decision`'s id format by inspection
    (same `dec_{lower(symbol)}_{YYYYMMDD}` shape, both derived from the
    same `generated_at` value in the same response).

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
    `SUPERVISION_MODE` via a shared `backend/services/supervision_mode.py`
    accessor (default `supervised`, matching `Docs/architecture.md` §6.2.2's
    `supervised`/`semi_autonomous`/`fully_autonomous` vocabulary, also now
    used by `routers/bot.py`) and skips execution entirely on a passive
    `GET` unless `SUPERVISION_MODE=fully_autonomous` — fails closed on any
    other value including blank/unset/`semi_autonomous`/a typo — confirmed
    by `test_supervised_mode_skips_autonomous_execution`/
    `test_fully_autonomous_mode_still_executes`/
    `test_semi_autonomous_mode_skips_autonomous_execution`/
    `test_blank_or_unset_supervision_mode_skips_autonomous_execution`.
    `backend/routers/decisions.py`
    now exposes real `POST /{id}/approve` and `POST /{id}/reject`, backed
    by a new persisted `backend/services/decision_state.py` store (same
    restart-survival pattern as `kill_switch_state.py`), confirmed by
    `backend/tests/test_decisions.py` (4/4, including a happy-path approve
    that asserts a real position lands in `engine.ledger.positions`) and
    `backend/tests/test_decision_state.py` (3/3, including a simulated-
    restart test). **Not addressed by this fix:** `learning_store.json.outcomes`
    still holds only the 3 seeded records since this change doesn't produce
    or need a closed trade to verify wiring.
- [x] Exclude seed/demo records from `/learning` metrics — the other half
  of the original P0 approve/reject item (see the resolved wiring bullet
  above). (first seen 2026-08-02, still open 2026-08-05;
  **resolved 2026-08-05**, evidence:
  `backend/services/learning_service.py` `dashboard()` / `_module_stats()` /
  `retrieve_failure_matches()` / `_maybe_adapt()` filter via
  `is_seed_outcome`; `SEED_VERSION=3` neutralizes seed-derived module
  weights/equity; `PaperEngine.close_position` calls
  `LearningService.record_ledger_close` so real paper_sim closes feed §12;
  confirmed by `backend/tests/test_learning_seed.py` —
  `test_fresh_store_dashboard_excludes_seed_metrics`,
  `test_seeded_failures_do_not_penalize_confidence`,
  `test_paper_sim_close_feeds_learning_outcome`)
- [x] **Kill-switch armed state was an in-memory global, resetting to
  unarmed on every restart.** `backend/services/kill_switch_state.py` adds a
  small JSON-file-backed `KillSwitchState` (`backend/data/kill_switch_state.json`,
  same pattern as `learning_store.json`); `backend/routers/bot.py`'s
  `is_kill_switch_armed()` / `/bot/pause` / `/bot/resume` now read and write
  it instead of a module global, so the halt survives a restart. The
  redundant `_scheduler_mode` global (always mirrored the armed flag) was
  removed with it. (first seen 2026-08-02, evidence: `backend/routers/bot.py:24`
  `_kill_switch_armed = False`; resolved 2026-08-04, evidence:
  `test_armed_state_survives_simulated_process_restart`,
  `test_bot_router_reads_persisted_state`)
- [x] **One-trade lock / active-trade-id were in-memory globals, resetting
  on every restart and letting a second discretionary entry through while
  a position was still open.** `backend/services/trade_executor.py` now
  derives `is_one_trade_locked()` / `get_active_trade_id()` from the
  `paper_sim` open-trades ledger (`learning_store.json`, already disk-persisted
  by `learning_service.register_open_trade` / `record_outcome`) instead of
  module globals, so state survives a restart with no new persistence code.
  Seeded demo records are excluded via `is_seed_outcome` so the bundled
  fixture trade never blocks real entries. (first seen 2026-08-02, evidence:
  `backend/services/trade_executor.py:18-19` `_one_trade_locked = False`;
  resolved 2026-08-04, evidence: `trade_executor.get_active_trade_id`
  reads `get_learning_service().list_open_trades()`;
  `test_lock_survives_simulated_process_restart`,
  `test_seeded_demo_open_trade_does_not_lock`,
  `test_second_entry_blocked_while_one_trade_locked`)

## P1 — proof of edge

- [ ] No walk-forward/OOS replay evidence exists yet for SH-4 expectancy
  claims — blocked on the P0-1 item above producing real closed trades to
  replay against. (first seen 2026-08-02)
  - Narrower sub-item done 2026-08-04: GARCH(1,1) MLE-fit forecast accuracy
    (not P&L) has real walk-forward evidence —
    `Docs/bot_health/garch_mle_walk_forward_evidence.md` — 1,788 pooled
    out-of-sample days across NIFTY/BANKNIFTY/RELIANCE/HDFCBANK/INFY, fitted
    weights essentially tied with the fixed-weight fallback (50.7% win rate,
    indistinguishable mean QLIKE). `garch_forecast.enable_mle_fit` stays
    `false` on this evidence. Does not close this bullet — SH-4 P&L replay is
    still blocked on P0-1.
- [ ] No skew/term-structure regime filter module exists under
  `backend/quant` — India VIX level alone doesn't meet the rule's
  Definition of Done for this item. (first seen 2026-08-02, evidence:
  `grep -rli "skew\|term_structure" backend/quant` → no matches)

## P2 — tradeable quality & live safety

- [ ] Confirm whether existing cost/Greeks-limit modules
  (`backend/quant/costs/transaction_cost.py`,
  `backend/quant/risk/greeks_limits.py`,
  `backend/quant/gamma/hedge_optimizer.py`) feed an explicit delta/vega-target
  sizing calc in ranking, or whether that wiring still needs building.
  (first seen 2026-08-02, needs follow-up read)
- [ ] No fill/reconcile state machine found — required before any live
  micro-capital phase. (first seen 2026-08-02, evidence:
  `grep -rli "reconcile\|fill_state\|order_state" backend --include=*.py`
  excluding tests → no matches)

- [ ] **`_spot_ltp` sends the raw display symbol, not the ICICI stock_code, for
  non-index equities — live spot LTP fails for names whose Breeze short code
  differs from the NSE tradingsymbol.** `backend/services/universe_enrichment.py`
  `enrich_one()` (line 591) correctly resolves
  `stock_code = self._instruments.stock_code_for_underlying(und) or und` and
  passes it to `_fetch_option_chain_sides(stock_code=stock_code, ...)` (line 613)
  — but line 609 calls `self._spot_ltp(und, ...)` with the raw `und` (display
  symbol), not `stock_code`. `_spot_ltp` (line 510-538) only substitutes a
  mapped code for the 5 index underlyings (`_INDEX_SPOT_STOCK_CODE`); every
  other symbol's `fallbacks = [und]` — so any equity whose Breeze stock_code
  differs from its NSE tradingsymbol (option-chain fetch already assumes this
  is common, hence the `stock_code_for_underlying` lookup existing at all)
  will always fail spot LTP with a vendor "stock may not be available" error,
  even though the option chain for the same symbol fetches fine via the
  correct code. Directly matches the error pattern seen live 2026-08-06 on
  `https://trading-bot-1-pi.vercel.app/recommendations`: `RELIANCE spot: Check
  stock code:Stock may not be available...`, `ICICIBANK spot: Check stock
  code:...`, `HDFCBANK spot: Non-JSON response (503)` alongside a working
  option-chain fetch pattern (`chain_calls=24` succeeding while `spot_calls=5`
  and only 12/40 underlyings fully enriched). Because `_live_marks_ok()`
  (`strategy_coverage.py:53-58`) requires `snap.und_price.usable`, a failed
  spot fetch alone is enough to make a symbol ineligible for every strategy —
  this single-line bug is a plausible primary driver of the observed
  `eligible=0/40` coverage abort across all three strategies that cycle (spot
  fetch failing before the option chain result even matters for that name).
  Not yet fixed or test-covered; the BANKNIFTY 503 in the same error sample
  looks like a separate transient vendor issue (index code already correct),
  not this bug. **Fix:** pass `stock_code` (already resolved one line above)
  into `_spot_ltp` instead of `und` for the non-index branch. (first seen
  2026-08-06, evidence: `backend/services/universe_enrichment.py:591,609`)
  - Blocks generating real recommendations/trades in prod today, which in
    turn blocks accumulating the real closed-trade history P1 item 3 (OOS
    walk-forward) needs — even though P0 itself (approve/reject wiring) is
    fully Done per the items above.
  - **Resolved 2026-08-06**, evidence: `_spot_ltp()` now accepts an optional
    `stock_code` param and uses it (falling back to the raw symbol) as the
    primary lookup for every non-index underlying, mirroring the existing
    index-code fallback pattern; `enrich_one()` passes the already-resolved
    `stock_code` through. New test
    `test_equity_spot_uses_resolved_stock_code_first`
    (`backend/tests/test_universe_enrichment.py`) asserts RELIANCE's spot
    fetch hits `RELIND` (its real mapped code) before ever trying the raw
    `RELIANCE` string, and fails the test if it doesn't. Full backend suite:
    320 passed / 0 failed (was 319). Live-verified the mapping itself is
    correct against the real downloaded FONSEScripMaster:
    `INFY→INFTEC`, `RELIANCE→RELIND`, `HDFCBANK→HDFBAN`, `ICICIBANK→ICIBAN`
    all resolve correctly via `stock_code_for_underlying()`. A live
    `refresh=true` cycle run locally post-fix (2026-08-06, ~16:22 IST, after
    NSE market close) confirmed the primary spot attempt for INFY now uses
    the resolved code (no longer a raw-symbol "Check stock code" rejection
    on the first try) — but still returned only 6-8/40 live marks and the
    same `STRATEGY_COVERAGE_ABORT` outcome, because outside market hours
    Breeze's quote endpoint itself returns transient 503s regardless of
    which code is used. **Not yet confirmed:** whether this fix alone gets
    coverage over the 80%/`min_eligible_symbols=20` floor during live NSE
    market hours (09:15-15:30 IST) — needs a same-day intraday re-check,
    which this session couldn't run since market was already closed.

## Other — deferred behind open P0/P1

- [ ] RAG chat was shipped then un-shipped pending a Track B rebuild plan —
  not blocking, tracked for awareness only. (first seen 2026-08-02)

- [x] **Live recommendations empty on prod (marks=0):** Breeze optionchain
  calls send empty `right` and `strike_price`
  (`backend/services/universe_enrichment.py` → `get_option_chain` defaults),
  which the vendor rejects with "Either Right or Strike-Price cannot be empty."
  FAQ requires `right="call"` (or put) with empty strike for a side snapshot.
  (first seen 2026-08-03, evidence: prod analysis text +
  `backend/integrations/icici_direct/client.py:290-305`,
  [ICICI option-chain FAQ](https://www.icicidirect.com/faqs/fno/how-to-fetch-option-chain-of-any-stock-code-using-breeze-api);
  resolved 2026-08-03, evidence: `universe_enrichment.py` `_fetch_option_chain_sides`
  fetches `right=call` then `put`;
  `test_enrich_many_fetches_spot_and_chain` asserts both sides)

- [x] **Index spot LTP uses display names first:** `_spot_ltp` calls
  `get_ltp("NSE", "BANKNIFTY")` before falling back to Breeze codes
  (`CNXBAN` / `NIFFIN` / `NIFSEL`). Burns rate budget and surfaces 503 /
  "Stock may not be available" noise. (first seen 2026-08-03, evidence:
  `backend/services/universe_enrichment.py:454-481`;
  resolved 2026-08-03, evidence: `_spot_ltp` tries `_INDEX_SPOT_STOCK_CODE`
  first; `test_index_spot_uses_breeze_stock_code_first`)

- [x] **Coverage gate vs enrichment cap contradiction:** after
  `b64ebe1`, enrichment is capped at `max_symbols=40` /
  `generation_budget_sec=20`, but `strategy_coverage` still requires
  `eligible >= 50` **and** `coverage >= 80%` of scanned (~213). Even perfect
  enrichment of 40 names cannot publish. (first seen 2026-08-03, evidence:
  `backend/config/trading_parameters.defaults.json:36-51`,
  `backend/services/strategy_coverage.py:105`;
  resolved 2026-08-03, evidence: coverage denominator uses
  `enrich_stats.requested`; `min_eligible_symbols` default 20;
  `test_coverage_uses_attempted_denominator_under_enrichment_cap`)
