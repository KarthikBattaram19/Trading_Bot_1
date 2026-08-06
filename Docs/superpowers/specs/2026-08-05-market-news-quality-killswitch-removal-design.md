# Market_News quality upgrade + kill-switch removal — design

Status: approved, ready for implementation plan.

## Why

Operator request: improve `Market_News.txt` so it drives higher-quality SH-4
gating (source trust, always-on ingestion across all market hours), and
remove all kill-switch mechanisms from the bot — both the narrow
Market_News-driven `kill_event` auto-flatten/auto-block, and the separate
global manual Kill Switch (disk-persisted arm/disarm, risk-gate block,
`/bot/pause`/`/bot/resume`, UI controls). Confirmed explicitly by the
operator after being shown that this contradicts `CLAUDE.md`'s existing P0
bullet ("enforce breakers/market-hours/kill-switch durably"); that bullet is
updated as part of this change so project docs stay consistent with the code.

Quant signals (GARCH, IV z-score) remain the primary edge; this change only
touches the news overlay and the kill/pause mechanisms layered on top of it.

## Scope

In scope:
1. Rewrite `Market_News.txt`: all 7 ingested sources in an explicit trust-tier
   priority list; workflow windows reframed as freshness labels (not a
   ranking penalty); remove kill-switch language.
2. `backend/services/market_news/curation.py` + `classifier.py`: make trust
   tiers the real ranking/weighting signal; stop windows from deprioritizing
   out-of-window sources.
3. Remove the Market_News-driven `kill_event` end to end (model field,
   `PostEntryAction`/`news_impact` value, forced block/flatten wiring in
   `strategy_selection.py` and `paper_sim/automation.py`), keeping post-shock
   tone as an informational tag that still flows through the existing
   `early_exit` path.
4. Remove the global manual Kill Switch end to end: `kill_switch_state.py`,
   its risk-gate/circuit-breaker/automation wiring, `/bot/pause` +
   `/bot/resume` endpoints (no replacement manual stop), and all frontend
   Kill Switch UI (button, status card, breaker text).
5. Update `Docs/Trading_Strategies.md` (Shared Kill Conditions bullet, SH-4
   news-overlay table), `backend/schemas/trading_parameters.schema.json` +
   `.defaults.json` (drop dead `kill_event` config key), and all affected
   tests.
6. Update `CLAUDE.md`'s P0 bullet to drop the kill-switch clause (keep
   breakers/market-hours) and annotate the resolved `BACKLOG.md` kill-switch
   item as superseded by this removal (dated 2026-08-05), not deleted.

Out of scope:
- The other Shared Kill Conditions unrelated to news/manual kill (liquidity
  collapse, hedge-leg unavailability, stale data, neutrality/greek-limit
  breach, thesis invalidation) — these stay exactly as they are.
- `garch_distorted` quant-driven blocking of SH-4 model trades — unaffected;
  only the news-driven block is removed.
- `regulatory_surprise` (SEBI-flag) handling — stays; it's a distinct macro
  flag, not part of the kill mechanism being removed.
- Any P1/P2 backlog items (walk-forward evidence, regime filters, delta/vega
  sizing) — untouched.

## Design

### 1. `Market_News.txt` rewrite

- `## For the AI trading bot / paper-sim` numbered list expands from 5 to all
  7 ingested sources (adds Pulse, CNBC TV18), grouped into explicit tiers:
  - Tier 1 (official/regulatory): NSE, SEBI
  - Tier 2 (wire, low-noise): Reuters
  - Tier 3 (general market press): Moneycontrol, Economic Times
  - Tier 4 (aggregator/TV): Pulse, CNBC TV18
- Add a short paragraph: all 7 sources are always ingested regardless of time
  of day; the workflow windows below describe when each source is *expected*
  to be fresh (for dashboard/staleness display only), not a ranking penalty.
- Remove "Unplanned earnings or news the setup was not designed to absorb →
  Shared Kill (`kill_event`)" and any other kill-switch/kill_event mention;
  replace with a line noting shock/crisis tone is still classified and shown
  (topic tag, bearish sentiment, macro flag) but no longer auto-flattens or
  blocks trades on its own.

### 2. `curation.py` / `classifier.py`

- `curation.py`: `bot_priority` (now all 7 sources, tier order) becomes the
  sole ranking key in `_rank_for_window` — sort by `(bot_priority index,
  time_published)`. Drop the `in_window` bucket that currently makes
  window-matching the dominant sort key ahead of priority. `windows` /
  `sources_for_window` stay for `paper_news_packet`'s `window_sources` display
  field only — no longer used to rank or penalize.
- `classifier.py`: add a per-source trust-tier weight (module-level dict
  mirroring the 4 tiers above) applied as a multiplier on each headline's
  contribution to `tone_scores` in `aggregate_packet_flags`, so tier-1/2
  sources dominate `dominant_tone` over tier-4 aggregator/TV noise when
  sources disagree.

### 3. Remove Market_News-driven `kill_event`

- `backend/models/recommendations.py`: remove `MarketNewsSummary.kill_event`
  (U10) field.
- `backend/services/market_news/classifier.py`: remove `kill_event` from
  `aggregate_packet_flags`'s return dict; remove the `post_shock →
  news_impact = "kill_event"` special case — post-shock still forces
  `dominant_tone = "bearish"` (existing sentiment behavior) and still adds
  `"post-shock"`/`"crisis_tone"` to `macro_risk_flags`, but `news_impact` now
  falls through the same bearish-tone branch as any other adverse headline
  (→ `"early_exit"` when applicable, same as today's non-shock bearish path).
- `backend/services/strategy_selection.py`: remove `"kill_event"` from the
  `PostEntryAction` literal and its branch in `post_entry_news_action`; remove
  the `news.kill_event` / `news.news_post_shock` checks from
  `news_blocks_model_trades` (regulatory-surprise blocking stays).

  > **Correction (2026-08-06, task 11):** the `news.news_post_shock` check in
  > `news_blocks_model_trades` did NOT ship and should not be removed — it is
  > intentional and stays. Only `kill_event` (the field/branch) was removed.
  > The governing rule clarified by the operator: news may still gate/decline
  > a NEW entry (`news_post_shock` included), but news must never close,
  > flatten, or modify an already-open position. `post_entry_news_action` and
  > `PaperAutomation.tick()`'s news-flatten block were removed entirely
  > instead of being narrowed — see
  > `.superpowers/sdd/2026-08-05-market-news-quality-killswitch-removal/task-11-report.md`.
  > A future reader should not "fix" `news_blocks_model_trades` toward this
  > stale bullet.
- `backend/paper_sim/automation.py`: remove `"kill_event"` from the
  flatten-trigger set and from `_last_signal`.
- `backend/services/market_news/service.py`: remove `kill_event` from
  `paper_news_packet`'s payload.
- Tests to update: `test_market_news.py`, `test_strategy_selection.py`,
  `test_automation.py`, `test_signals.py` (assertions referencing
  `kill_event` / `"kill_event"` news_impact).

### 4. Remove the global manual Kill Switch

- Delete `backend/services/kill_switch_state.py` and stop writing
  `backend/data/kill_switch_state.json`.
- `backend/routers/bot.py`: remove `is_kill_switch_armed()`, `/bot/pause`,
  `/bot/resume`; remove `kill_switch_armed` / `circuit_breakers_active`
  kill_switch entries from `/bot/status`'s payload. No replacement manual
  stop endpoint (operator confirmed: no manual stop needed).
- `backend/execution/risk_gate.py`: remove `kill_switch_armed` from
  `PreTradeContext` and its check in `evaluate_pre_trade_gate`.
- `backend/execution/circuit_breakers.py`: remove the `kill_switch` breaker
  id plumbing (`active_breaker_ids` docstring reference).
- `backend/paper_sim/engine.py`: remove the `is_kill_switch_armed` import/
  check feeding `PreTradeContext.kill_switch_armed`.
- `backend/paper_sim/automation.py`: remove `_is_kill_switch_armed`, the
  `"paused_kill_switch"` `AutomationState` value, and the skip-on-armed
  branch in the tick loop.
- Frontend: remove the Kill Switch button + `handleKillSwitch` +
  `kill-switch-glow` styling from `situational-bar.tsx`; remove the "Kill
  Switch Status" `StatCard` from `dashboard/page.tsx`; remove
  `kill_switch_armed` / kill_switch breaker handling from `risk/page.tsx`;
  update `types/decisions.ts`, `types/risk.ts`, `lib/mock-data.ts`,
  `lib/risk-mock.ts` to drop the field; remove the now-unused
  `.kill-switch-glow` rule from `globals.css`.
- Tests: delete `test_kill_switch_state.py`; update `test_risk_gate.py`,
  `test_automation.py`, `test_phase0.py`, `conftest.py`'s
  `_isolated_kill_switch_state` fixture (remove it and its usages).

### 5. Docs

- `Docs/Trading_Strategies.md`: remove the "an earnings or news event appears
  that the setup was not designed to absorb" line from Shared Kill
  Conditions; update the SH-4 news-overlay table's "Crisis / post-shock tone"
  and "Unplanned news..." rows to describe the new non-blocking, tagged-only
  behavior.
- `backend/schemas/trading_parameters.schema.json` +
  `backend/config/trading_parameters.defaults.json`: drop the `kill_event`
  key from `kill_conditions` (dead config, not read anywhere in the backend —
  confirmed by grep before this spec was written).
- `CLAUDE.md`: P0 bullet 1 drops "...kill-switch..." (keep breakers/
  market-hours enforcement language).
- `Docs/bot_health/BACKLOG.md`: append a dated note to the resolved
  kill-switch-persistence item marking it superseded — the mechanism was
  intentionally removed 2026-08-05 per operator decision — rather than
  deleting the historical record.

## Testing

- `pytest -m "not integration"` must pass after all removals — no orphaned
  imports of `kill_switch_state` or `kill_event` anywhere in `backend/`.
- Grep sweep for `kill_switch|kill_event|KillSwitch` across `backend/` and
  `frontend/src/` at the end of implementation should return zero matches
  outside historical `Docs/bot_health/BACKLOG.md` prose and this spec.
- Frontend: `npm run build` (or equivalent typecheck) in `frontend/` to catch
  any dangling references to removed fields/types.

## Risks / trade-offs (accepted by operator)

- This removes the bot's only durable, manual emergency-stop mechanism.
  `CLAUDE.md`'s P0 language is being changed alongside the code specifically
  so this isn't a silent regression against project policy — it's a
  documented, deliberate operator decision.
- Post-shock/crisis news no longer halts paper_sim automation or blocks new
  SH-4 entries; the bot continues trading/holding through such events on
  quant signals + the existing bearish-tone `early_exit` path alone.
