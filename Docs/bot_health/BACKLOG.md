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
  **Superseded 2026-08-05:** the kill-switch mechanism itself (this
  persisted-state fix included) was removed entirely per operator decision —
  the bot now has no manual kill switch. See
  `Docs/superpowers/specs/2026-08-05-market-news-quality-killswitch-removal-design.md`.
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

- [ ] **P0-2 (a): `evaluate_risk_gate()` has zero callers — the market-hours,
  one-trade-scope and daily-loss checks it implements never execute on any
  submit path.** `grep -rn "evaluate_risk_gate\|RiskGateContext" backend/
  --include=*.py` excluding `risk_gate.py` itself returns **no matches** at
  all. The rule's Definition of Done requires these checks to "run inside the
  actual submit path ... verified by grep/trace, not only surfaced as
  dashboard metrics" — today they are not surfaced anywhere, they simply never
  run. Note this is distinct from `evaluate_pre_trade_gate()`, which *is*
  genuinely wired into the submit path (`backend/paper_sim/engine.py:223`,
  raising at `:235`) but only covers spread/liquidity/lotsize thresholds — not
  market hours, not daily loss. Compounding it, `RiskGateContext.one_trade_scope_clear`
  (`risk_gate.py:103`) is populated by **nobody** (grep, repo-wide), so even if
  `evaluate_risk_gate` were called, `risk_gate.py:402` would fall through to
  `status="skip"` rather than evaluate the one-trade rule. (The *effective*
  one-trade enforcement lives elsewhere and does work — `trade_executor.is_one_trade_locked()`
  at `trade_executor.py:38`, enforced at `:93`, ledger-derived and
  restart-safe — so this is a dead duplicate gate, not an open trading risk on
  its own.) (first seen 2026-08-07, evidence: `backend/execution/risk_gate.py:101-103,378-411`;
  zero-caller greps above)

- [ ] **P0-2 (b): circuit breakers / daily-loss are dashboard-only — exactly
  the failure mode the rule names.** `evaluate_circuit_breakers()` has one
  non-test caller, `backend/services/risk_snapshot.py:191`, which feeds
  `build_risk_snapshot()` → `GET /api/v1/risk/snapshot`
  (`backend/routers/risk.py:14-16`) and `bot_metrics_from_risk` →
  `GET /bot/status` (`backend/routers/bot.py:42`). Both are read-only display
  endpoints. No submit path consults them, so a breached daily-loss breaker
  renders red on the dashboard while `PaperEngine.submit_order` continues to
  accept entries. (first seen 2026-08-07, evidence: greps above)

- [ ] **P0-2 (c): the paper_sim open-position book is in-memory only and does
  not survive a restart.** `PaperLedger.positions` is a plain dict
  (`backend/paper_sim/ledger.py:30`), and
  `grep -rln "json.dump\|\.write_text\|open(" backend/paper_sim/*.py` returns
  **no files** — there is no disk persistence anywhere in the package. The
  rule requires "a killed/restarted process resumes with the same open
  positions it had before the restart"; today it resumes with an empty ledger.
  Worse, this desyncs from `learning_store.json`, which *is* persisted and
  *does* still list the trade as open — so after a restart
  `trade_executor.is_one_trade_locked()` correctly reports a position open
  while `PaperLedger` has no record of it, leaving an orphaned lock with no
  closeable position behind it. (first seen 2026-08-07, evidence:
  `backend/paper_sim/ledger.py:30`; no-persistence grep above)

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
- [ ] Runtime Breeze call accounting: `scan_capacity.py` budgets *scheduled*
  cycles only. On-demand generations (`GET /recommendations?refresh=true`,
  approvals forcing a fresh cycle, post-restart cadence resets) each spend
  ~160 uncounted paced calls, and paper_sim automation/health calls are
  budgeted by assumption (envelope remainder), not measurement. Wanted: a
  per-day call counter at the adapter layer with a scheduler-status surface,
  so envelope pressure is observed rather than modeled. (first seen
  2026-08-08, evidence: adversarial review of `a363c67`, finding 6)

- [x] **The 40-symbol enrichment budget was filled by a 12-name hardcoded
  allowlist + alphabetical order, with no liquidity ranking** — the majority
  of the ~180-name NSE F&O universe was never enriched, every cycle, and a
  handful of enrichment failures among the 40 attempted could tip strategy
  coverage below the 80%/20 floor. (first seen 2026-08-03 as §3.9 of
  `Docs/Improve_Recoemmendation_Engine.md`; **resolved 2026-08-06**, evidence:
  `AtmLiquidityHistoryStore.latest_liquidity_by_underlying()`
  (`backend/services/atm_liquidity_history.py`) returns each underlying's most
  recent ATM volume+OI across any expiry_key as an ADV proxy; new pure
  `_rank_symbols_for_enrichment()` (`backend/services/recommendation_engine.py`)
  keeps the explicit priority names first but orders the rest by that proxy
  descending. A cold store yields `0.0` for every symbol, so ordering is
  provably identical to the old alphabetical behavior until real sessions
  accumulate — asserted by
  `test_rank_symbols_for_enrichment_falls_back_to_alphabetical_with_no_history`.
  Tests in `backend/tests/test_atm_liquidity_history.py` and
  `backend/tests/test_recommendation_engine.py`. **Not addressed:** `max_symbols`
  is still 40 — this improves *which* 40 are chosen, it does not raise the cap.)

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

- [x] **No trades can occur unattended: recommendation cycles are purely
  request-driven, so on a day nobody opens the dashboard during NSE hours the
  bot generates zero recommendations, zero decisions, and zero trades.**
  Verified 2026-08-07 (21:45 IST) against prod after a full market day:
  `GET /decisions` → `[]`, `GET /learning/dashboard` → 0 real closed/open,
  `GET /paper-sim/positions` → `[]`, account untouched at ₹10,00,000. Grep
  confirms no scheduler exists (`scheduler|repeat_every|create_task` across
  `backend/` finds only the WS reconnect loop and `paper_sim/automation.py`'s
  γ–θ re-hedge for already-open positions) — generation runs only inside
  `GET /recommendations` on a cold 90s cache or `refresh=true`. Combined with
  `SUPERVISION_MODE=supervised` (human must click Approve) this means the
  post-P0 pipeline has never been exercised end-to-end in live market hours;
  the pending intraday coverage re-check (see `_spot_ltp` item above) has the
  same root cause: someone/something must trigger a cycle between 09:15–15:30
  IST. **Fix options:** a lightweight in-process scheduler (market-hours-gated)
  that refreshes recommendations every few minutes, or an external cron hitting
  `GET /recommendations?refresh=true` during NSE hours. Also worth noting:
  `/decisions` is derived from the in-process recommendation cache
  (`decision_log.py::_live_decisions` → `peek_cached_recommendations`) plus
  acted-on trades — un-acted-on packets vanish from the log 90s after the
  cycle, so there is no durable record of whether any packet was ever
  published intraday. (first seen 2026-08-07, evidence: prod probes above;
  `backend/services/decision_log.py:238-274`)
  - **Resolved 2026-08-07** (Monday-trade branch), evidence: new
    `backend/services/trading_scheduler.py` (`TradingScheduler`) auto-started
    from a new FastAPI lifespan in `backend/main.py` (`SCHEDULER_AUTOSTART`
    env, default on). During `entry` phase (09:20–14:30 IST per new
    `session_schedule` config + `backend/services/market_session.py`) it runs
    `run_recommendation_cycle(force_refresh=True)` every
    `scheduler.recommendation_cadence_sec` (900s) unless one-trade-locked,
    ensures the paper_sim γ–θ automation loop is running, blocks new entries
    14:30–15:15, and during `flatten` (15:15–15:30) closes every open
    position via `PaperEngine.close_position` (the learning-fed path) with
    per-tick retries — closing the "no exit rule in code" gap (§3.11's
    session-close half) as well. Ops surface: `GET/POST /api/v1/scheduler/
    status|start|stop|tick`. Companion fixes shipped together: coverage-gate
    arithmetic made satisfiable (max_symbols 40→15, generation_budget_sec
    20→90, response_cache_ttl_sec 90→900 so approve/auto-exec never sees a
    cold cache, min_coverage_ratio 0.80→0.60, min_eligible_symbols 20→6 —
    owner-approved 2026-08-07); bootstrap confidence floor 0.70-until-first-
    real-close (`backend/services/confidence_floor.py`, auto-reverts to 0.80);
    boot reconciliation for the restart lock-deadlock
    (`backend/services/ledger_reconciliation.py`). Tests:
    `test_market_session.py`, `test_trading_scheduler.py`,
    `test_scheduler_full_day.py` (full fake-clock Monday: open 09:25 →
    locked → flatten retry on StaleMarksError → closed 15:17 → 1 real
    learning outcome, lock released, floor reverts), `test_main_lifespan.py`,
    `test_ledger_reconciliation.py`, `test_confidence_floor.py`,
    `test_trading_parameters_config.py` (new schema↔defaults validation —
    also fixed pre-existing schema drift for `gamma_theta_breakeven` and
    `strategies.gamma_scalping.entry_signal`). Full suite 355 passed.
    **Still open:** durable decision/packet log (un-acted packets still
    expire with the response cache), NSE holiday
    calendar (weekday-only check), paper_sim ledger persistence (P0-2c),
    vega IV z-score stop (§3.11's other half). See `Docs/DAILY_RUNBOOK.md`.
  - **Superseded in part 2026-08-08 — forced-trade scaffolding removed.** The
    owner called off the "one trade on Monday 2026-08-10" mandate: forcing a
    trade was distorting the engine it was supposed to validate, and giving
    the `recommendation-engine-analyst` a loosened baseline to grade against.
    The scheduler, `market_session.py`, `recommendation_cycle.py`,
    `ledger_reconciliation.py` and the EOD flatten (real capability) all stay.
    Removed: `bootstrap_min_confidence` 0.70 and the whole
    `backend/services/confidence_floor.py` module (0.80 now applies from the
    first cycle), the `MIN_RECOMMENDATION_CONFIDENCE` env lever, and the
    hand-set `max_symbols` / `min_eligible_symbols`. Replaced by
    `backend/services/scan_capacity.py`: the scan cap is **derived** from the
    paced call budget (`min(enrich wall-clock, history wall-clock,
    daily-envelope)` = 20 underlyings at 6 worst-case enrich calls/symbol) and
    the eligible floor is always `ceil(0.80 × cap)` = 16 — not a config key;
    its presence is rejected. `validate_scan_capacity()` runs at boot AND per
    cycle (config is re-read from disk each cycle) and refuses an
    unsatisfiable configuration. Runtime obeys the model: enrichment and
    history get separate deadlines (70/30 split), history calls are paced via
    `breeze_pacing.py`, and the scheduler's cadence fallback shares the
    model's 900s constant. `min_coverage_ratio` restored to 0.80; 3360
    calls/day inside the ~5000/day Breeze envelope. (Hardened 2026-08-08
    evening after an adversarial code review found the first cut was a model
    the runtime didn't obey — unenforced budget split, unpaced history calls,
    divergent cadence fallbacks, boot-only validation, understated
    calls/symbol, and a still-tunable eligible floor.) Root cause of the original emptiness recorded honestly: the
    0.80-of-20 gate was never too strict — a 20s budget could not finish
    40 symbols × 5 paced calls × 700ms (~140s), so every scan truncated and
    nothing raised. Tests: `test_scan_capacity.py` (9, incl. a regression
    that the old 40-in-20s config now fails boot),
    `test_trading_parameters_config.py` rewritten. Full suite 404 passed.

## Other — deferred behind open P0/P1

- [ ] RAG chat was shipped then un-shipped pending a Track B rebuild plan —
  not blocking, tracked for awareness only. (first seen 2026-08-02)

- [x] **Frontend had no CI coverage at all** — `.github/workflows/backend-ci.yml`
  is path-filtered to `backend/**`, so every `frontend/` change (including the
  P0 approve/reject wiring) merged with no automated typecheck or build.
  (first seen 2026-08-06; **resolved 2026-08-06**, evidence:
  `.github/workflows/frontend-ci.yml` runs `npm ci` → `npx tsc --noEmit` →
  `npm run build`, path-filtered to `frontend/**`; first green run
  `31119791215`. Deliberately no lint step — the repo has no ESLint config, so
  `next lint` drops into an interactive prompt and would hang the job rather
  than fail it; a comment in the workflow marks where to add it once a config
  lands. `NEXT_PUBLIC_API_URL` is pinned to a placeholder because
  `frontend/.env.local` is gitignored — without it `useMockData()` flips true
  and CI would compile the mock path instead of the live one prod uses.)

- [x] **CI actions emitted a Node-20 deprecation warning on every run.**
  (first seen 2026-08-06; **resolved 2026-08-07**, evidence: bumped
  `actions/checkout@v4→v5`, `actions/setup-node@v4→v5`,
  `actions/setup-python@v5→v6` — note setup-python@v5 was itself the flagged
  action, so v6 is the minimum fix there, not v5. Confirmed each target major
  declares `using: node24` and still accepts every input the workflows pass.
  First clean runs: Backend CI `31143370053`, Frontend CI `31143370059` —
  neither carries the deprecation annotation.)
  - Also added `workflow_dispatch:` to both workflows after a GitHub Actions
    incident (2026-08-06/07) left runs wedged: queued 8h, with the API
    reporting them "queued" on status but "completed" on cancel, so they could
    neither finish nor be re-run — and because both workflows are
    path-filtered, an empty commit could not retrigger them either. CI is now
    manually runnable: `gh workflow run backend-ci.yml`.

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
