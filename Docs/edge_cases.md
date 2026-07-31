# Edge Cases & Corner Scenarios

> **Authority:** `Docs/architecture.md` (v1.26+) · `Docs/implementation_plan.md`  
> **Supporting:** `Docs/Paper_Simulator.md`, `Docs/Trading_Strategies.md`, `Docs/Trading_Parameters.md`  
> **Created:** July 16, 2026  
> **Purpose:** Exhaustive catalog of corner scenarios and edge cases the system must handle (or explicitly refuse) across paper → live autonomy. Use for design reviews, chaos tests (`backend/tests/chaos/`), and phase gates.

**Legend**

| Severity | Meaning |
| -------- | ------- |
| **P0** | Must not trade blindly / must pause or reject |
| **P1** | Correct behavior required for soak / promotion |
| **P2** | Correctness / UX / ops; may degrade gracefully |

| Expected outcome (EO) shorthand |
| ------------------------------- |
| **Reject** — no new discretionary submit |
| **Pause** — `scheduler_mode=paused` (or reduced); `auto_resume=false` |
| **Hedge-only** — mechanical hedges OK; discretionary blocked |
| **Defer** — log + retry later / next rank / next session |
| **Flatten** — Shared Kill / abort open structure |
| **No-op** — log only; continue observe |

---

## 1. Mode & promotion axes

Cross-cutting: `EXECUTION_MODE` × `SUPERVISION_MODE` (§6.2.1–6.2.2, plan §3–8).

| ID | Scenario | EO | Sev | Refs |
| -- | -------- | -- | --- | ---- |
| M-01 | `EXECUTION_MODE=live` set on Railway / paper stack | Reject live path; refuse `place_order`; alert | P0 | plan §1.10, §8; arch §11.7, §17.0 |
| M-02 | `EXECUTION_MODE=paper` but submit routed to ICICI Direct adapter | Never call `place_order`; paper P&L only via `paper_sim` | P0 | §11.5, §11.7; Paper_Simulator |
| M-03 | Promote `SUPERVISION_MODE` without checklist (≥30 trades, §2.2 bands) | API reject promotion | P0 | §6.2.2 |
| M-04 | Demote `fully_autonomous` → `supervised` mid-session with open discretionary trade | No new entries; hedges continue; audit log | P0 | §6.2.2, §20.4.7 |
| M-05 | New module `strategy_enabled=true` while bot is `fully_autonomous` | New module starts under supervised / two-key for first 50 trades | P0 | §20.4.1 |
| M-06 | Optimizer tries to set `strategy_enabled=true` | Forbidden; operator-only | P0 | §12.5, §20.4.5 |
| M-07 | Shadow → paper with pipeline errors in shadow week | Block promotion | P1 | §6.2.1, plan Phase 2 |
| M-08 | Paper soak → live without chaos green / §2.2 soak | Block Phase 5 gate | P0 | §21.0, plan §7–8 |
| M-09 | Flip paper ledger into live positions (reuse paper fills as broker state) | Forbidden — separate GCP path | P0 | Paper_Simulator; §11.15 |
| M-10 | `SIMULATE_FIRST_RANK_FAILURE=true` left on in production soak | Force-false for soak metrics; only for fallback path validation | P1 | §6.4 |
| M-11 | Live first week without re-starting `supervised` | Prefer re-supervise then re-promote | P1 | §11.15, plan 5.4 |
| M-12 | `live_enabled=false` but `EXECUTION_MODE=live` | Treat as not live; block orders | P0 | §20.4.10 |

---

## 2. Market calendar & session gates

NSE / NFO default **09:15–15:30 IST**; news windows; ICICI Direct session expiry / session (§8.8, §11.9, §11.12).

| ID | Scenario | EO | Sev | Refs |
| -- | -------- | -- | --- | ---- |
| S-01 | Order tick outside 09:15–15:30 IST (no AMO opt-in) | Reject | P0 | §11.4, §11.12 |
| S-02 | Pre-open 09:00–09:15 / auction imbalance | Reject discretionary; do not treat auction prints as continuous LTP | P0 | §11.12 |
| S-03 | Post-close / after-market marks used for discretionary entry | Reject; allow mark-to-market for P&L only | P0 | §11.4 |
| S-04 | Weekend / exchange holiday (NSE calendar) | No trading loop; scheduler idle; health `degraded`/`ok` per config | P0 | §6.2 |
| S-05 | Special session (e.g. Muhurat) — shortened hours | Use configured session override; reject outside shortened window | P1 | §11.12 |
| S-06 | AMO variety without strategy `allow_amo` | Reject | P1 | §11.10, §11.12 |
| S-07 | Midnight IST (~00:00) JWT invalidation mid overnight carry | Session manager re-login; brief pause; no overnight JWT reuse | P0 | §11.9, §11.13 |
| S-08 | Pre-market login (08:45 IST) fails | Alert; no discretionary until Auth OK | P0 | §11.9, §11.13 |
| S-09 | News ingest only in wrong window (e.g. after-close sources used for pre-open gate) | Prefer windowed freshness; mark `source_freshness` stale for gate | P1 | §8.8.2 |
| S-10 | Clock / timezone: naive datetime treated as UTC instead of IST | Wrong DTE / session; must interpret OSS/eval in `Asia/Kolkata` | P0 | §8.5.2 |
| S-11 | Deploy during market hours without deploy-pause gate | Pause bot → deploy → verify `/health/bot` → resume | P0 | §17.5, §17.7, plan 5.7 |
| S-12 | Railway sleep / scale-to-zero during session | Keep min 1 always-on for paper automation | P0 | Paper_Simulator; plan Phase 0–1 |

---

## 3. Market data freshness & ICICI Direct feeds

| ID | Scenario | EO | Sev | Refs |
| -- | -------- | -- | --- | ---- |
| MD-01 | Single bound feed age > `stale_threshold_sec` | Block strategies bound to that feed; `alerts.stale_feed` | P0 | §8.7 |
| MD-02 | All feeds stale | Pause scheduler; operator resume required | P0 | §8.7 |
| MD-03 | 3 consecutive fetch failures | Exponential backoff; alert; treat as intermittent → escalate to stale | P0 | §8.7 |
| MD-04 | Invalid JSON / schema fail | Do not update Redis cache; `feed.error_count++` | P0 | §8.7 |
| MD-05 | Bid/ask crossed or zero LTP | Reject mark for pricing/gating; do not fill paper at 0 | P0 | §8.3, Paper_Simulator |
| MD-06 | WS disconnect mid-tick | Backoff reconnect; mark stale; block discretionary | P0 | §8.9.2, §11.13 |
| MD-07 | Missed WS heartbeat (~30s) | Treat connection unhealthy; stale path | P0 | §8.9.2, §11.9 |
| MD-08 | Duplicate tick / replay of same `tick_id` | Idempotent ignore; no second decision submit | P0 | §20.4.3, §20.4.8 chaos |
| MD-09 | Out-of-order ticks (older ts after newer) | Ignore older; keep last good | P1 | §8.4 |
| MD-10 | Gap in OHLCV / missing bars for GARCH | Mark `garch_distorted` or stand_aside; no blind GARCH entry | P0 | Paper_Simulator; §8.8 |
| MD-11 | Instrument master stale (lotsize/token changed) | Daily refresh; reject unresolved symboltoken | P0 | §8.9.1, §11.8 |
| MD-12 | Option chain incomplete (missing ATM strike) | Fail liquidity/ATM gates; no recommend | P1 | Part I / §6.4 |
| MD-13 | Index underlying bound to options+stock strategy | Reject — index excluded when stock/underlying legs present | P0 | §2.3, §8.2 |
| MD-14 | Spot ≤ ₹1000 gate when options+underlying; spot > ₹1000 | Reject (T11 / Part T) | P0 | §2.3; Paper_Simulator |
| MD-15 | Options-only on high-priced / index underlying | Allowed if ATM/premium/liquidity pass | P1 | §2.3 |
| MD-16 | SSRF: feed URL to private IP / non-allowlisted host | Fetcher reject | P0 | §8.7 |
| MD-17 | Feed response > 10 MB or timeout > 10s | Fail fetch; backoff | P1 | §8.7 |
| MD-18 | >1000 token×mode WS subscriptions | Cap; prefer one mode per token; share one WS | P0 | §8.9.2, §11.9 |
| MD-19 | 4th concurrent WS connection (>3 / client code) | Fail connect; reuse existing | P0 | §11.9 |
| MD-20 | REST LTP vs WS LTP diverge beyond threshold | Prefer fresher ts; if both stale → MD-01 | P1 | §8.9 |
| MD-21 | Replay mode accidentally active in live session | Hard config gate; never mix live submit + replay driver | P0 | §8.7 |
| MD-22 | Stub / simulated NSE quote paths still active after A6 | Remove; ICICI Direct sole marks | P0 | §11.15 A6, plan 5.6 |

---

## 4. Market_News & SH-4 strategy gates

| ID | Scenario | EO | Sev | Refs |
| -- | -------- | -- | --- | ---- |
| N-01 | News service stale / empty at open | Gate automated entries; expose freshness on packet | P0 | §8.8; plan 1.3 |
| N-02 | Earnings / company event + plain long-vega | Reject simple vol through event; prefer gamma + `earnings_gap_mode` | P0 | SH-4; §8.8.4 |
| N-03 | Post-shock / crisis tone; GARCH distorted | `stand_aside` / `blocked`; `block_model_trades` | P0 | §8.8.4; Paper_Simulator |
| N-04 | Unplanned news after entry (Shared Kill) | Flatten / abort (`kill_event`) | P0 | §8.8.4 |
| N-05 | Breaking news favorable after long-vol entry | Take profit / re-hedge aggressively — **do not widen stops** | P0 | §8.8.4 |
| N-06 | Quiet tape + adverse news after entry | Early exit / stop per rules | P1 | §8.8.4 |
| N-07 | Symbol-tagged adverse news vs open position | Prefer flatten / reduce; log `news_impact` | P1 | §8.8 |
| N-08 | Conflicting source tones (Reuters vs Moneycontrol) | Prefer ingestion priority order; surface disagreement in packet | P2 | §8.8.2 |
| N-09 | US/global news used as India regime truth | Explicit non-goal; ignore or down-weight | P1 | §8.8.1 |
| N-10 | SEBI circular / regulatory surprise flag | Macro risk flag → defer / block model trades | P1 | §8.8.3 |
| N-11 | Manual `POST /paper-sim/orders` bypasses news gate | Allowed as supervised override; automation must still honor gates | P1 | Paper_Simulator |
| N-12 | IV z ≤ −2 but news blocking | No vega entry | P0 | SH-4 |

---

## 5. Quant, OSS / BSM, Greeks, costs

| ID | Scenario | EO | Sev | Refs |
| -- | -------- | -- | --- | ---- |
| Q-01 | `eval_datetime ≥ expiration` | Option Greeks = 0; settle/expire path | P0 | §8.5.5 |
| Q-02 | DTE → 0 (expiry day) pin / gamma spike | Tighten gates; prefer flatten before close; no new discretionary near expiry unless strategy allows | P0 | playbook / Part H–J |
| Q-03 | `flat_volatility=false` but missing per-leg vol | Reject pricing / skip signal | P1 | §8.5.2–8.5.3 |
| Q-04 | Using OSS US `contract_multiplier=100` for NFO | Forbidden — use ICICI Direct `lotsize` | P0 | §8.5.2, §11.10 |
| Q-05 | Quantity not multiple of `lotsize` | Reject before broker | P0 | §11.4, §11.10 |
| Q-06 | Limit price off tick grid | Reject | P0 | §11.4 |
| Q-07 | `net_hedge_edge ≤ 0` (cost > gamma edge) | Skip hedge; log | P0 | §9.4, §11.4 |
| Q-08 | Wide bid-ask / illiquid strike | Fail liquidity gate; spread penalty; exclude recommend | P0 | §6.4, §9.4 |
| Q-09 | Zero / missing OI or volume | Fail Part I / liquidity | P1 | §6.4 packet |
| Q-10 | American vs European on high-div deep ITM call | Document approximation; prefer European NFO model | P2 | §8.5.7 |
| Q-11 | Display `per_share` with mixed leg sizes | Prefer `total` for risk gates | P2 | §8.5.5 |
| Q-12 | Unbounded legs accumulate until close | Cap only by capital/risk gates; ensure closure path exists | P1 | §8.5 |
| Q-13 | Stock leg without `und_price` | Reject | P0 | §8.5.3 |
| Q-14 | GARCH(1,1) with insufficient history | No cheap-vol entry; stand_aside | P1 | Paper_Simulator |
| Q-15 | IV z-score NaN / σ=0 | Reject vega frame | P1 | Part H |
| Q-16 | Regime = `unknown` or `high_vol_stress` | Reject discretionary | P0 | §11.4, §20.4.3 |
| Q-17 | Multi-module conflict | Highest-confidence wins; log dissent | P1 | §10.6 |
| Q-18 | Hedge frequency would require HFT-like churn | Retail-realistic cap; cost gate skips | P1 | §2.3, §9.4 |
| Q-19 | OSS parity fixture fails CI | Block merge | P0 | §22.1 |
| Q-20 | Expired catalog entry vs live chain expiry mismatch | Prefer ICICI Direct effective expiry; reject bad `expiration_id` | P1 | §8.5.4 |

---

## 6. AI / Groq / RAG / confidence

| ID | Scenario | EO | Sev | Refs |
| -- | -------- | -- | --- | ---- |
| AI-01 | Groq rate-limited | Retry ×3 exponential backoff | P0 | §10.6 |
| AI-02 | Groq unavailable > 60s | Degraded: Hedge-only; no cached LLM for new entries | P0 | §10.6, §20.4.6 |
| AI-03 | Quant enter + LLM reject | Skip; log `decision_dissent` | P0 | §10.6 |
| AI-04 | Quant enter + RAG insufficient context | Skip — no guessing | P0 | §10.6 |
| AI-05 | RAG faithfulness < 0.85 | Block discretionary (mandatory live) | P0 | §10.4, §20.4.6, Track B |
| AI-06 | Golden eval red but LLM gating enabled | Forbidden until Track B green | P0 | plan §9; §1.2 |
| AI-07 | Confidence < risk-gate threshold (e.g. 0.70) | Reject | P0 | §10.4, §11.4 |
| AI-08 | Win rate < 60% → auto-raise confidence +0.05 | Apply; fewer entries | P1 | §10.4 |
| AI-09 | Recommendation confidence < 0.80 | Exclude from top-3; note in `analysis_notes` | P0 | §6.4 |
| AI-10 | Failure-memory top-3 match | Penalize confidence −0.10 | P1 | §12.6 |
| AI-11 | LLM malformed / non-JSON decision output | Reject entry; log; do not parse loosely into submit | P0 | §10.1, §10.5 |
| AI-12 | Chat prompt accidentally used for decision | Separate prompt profiles; reject | P0 | §10.7 |
| AI-13 | Chroma down / empty corpus | Chat degrade; discretionary RAG gate fails → skip | P0 | §7, §20.4.6 |
| AI-14 | Citation hallucination (chunk_id not retrieved) | Fail faithfulness / reject decision | P1 | §7, §22 |
| AI-15 | Cached RAG TTL 5 min used after regime shock | Prefer invalidate on news kill / regime change | P1 | §10.6 |

---

## 7. Supervision, decision queue, one-trade scope

| ID | Scenario | EO | Sev | Refs |
| -- | -------- | -- | --- | ---- |
| SU-01 | `approval_timeout_min` (15) expires | **No** auto-submit; expire decision | P0 | §6.2.2 |
| SU-02 | Approve after marks moved / feeds went stale | Re-run pre-trade gate on approve; reject if fail | P0 | §6.3, §11.4 |
| SU-03 | Double Approve / double-click | Idempotent; second is no-op | P0 | §20.4.3 |
| SU-04 | Approve and Reject race | First wins; second conflict error | P0 | §6.2.2 APIs |
| SU-05 | Approve while kill-switch active | Reject | P0 | §11.4 |
| SU-06 | Second discretionary signal while one open | `deferred_one_trade_scope`; hedges exempt | P0 | §20.4.11 |
| SU-07 | Pending decision + new higher-confidence signal | Do not open second; optionally expire/supersede per policy (document); never two opens | P0 | §20.4.11 |
| SU-08 | Semi-auto: confidence ≥ 0.85 but gate fails | Residual queue or skip; no submit | P0 | §6.2.2 |
| SU-09 | Semi-auto: confidence < 0.85 | Queue for operator | P0 | §6.2.2 |
| SU-10 | Mechanical hedge while discretionary pending | Hedge may execute; does not consume one-trade slot wrongly | P0 | §10.6, §20.4.11 |
| SU-11 | Operator offline in `supervised` all day | Decisions expire; no trades — acceptable fail-safe | P1 | §6.2.2 |
| SU-12 | Ask AI on stale packet | Recompute or warn; do not approve on outdated explanation alone | P1 | UI / §7.7 |

---

## 8. Ranked fallback (fully autonomous)

| ID | Scenario | EO | Sev | Refs |
| -- | -------- | -- | --- | ---- |
| RF-01 | Ranked fallback while not `fully_autonomous` | `autonomous_execution` null; no inline submit | P0 | §6.4 |
| RF-02 | Rank #1 pre-submit gate fail | Try #2 then #3 | P0 | §6.4 |
| RF-03 | Rank #1 broker/paper reject | Try next; log `attempts[]` | P0 | §6.4 |
| RF-04 | All ranks fail | No trade; full attempt log | P0 | §6.4 |
| RF-05 | Fewer than 3 instruments ≥ 0.80 confidence | Top-k from eligible only; may be 0–2 | P1 | §6.4 |
| RF-06 | Zero eligible recommendations | Empty list; no execute | P0 | §6.4 |
| RF-07 | SSR refresh + client refresh double-submit same cycle | One-trade + idempotency must prevent duplicate | P0 | §6.4 timing |
| RF-08 | Client `useEffect` / timer execute (legacy) | Forbidden — execute only in GET cycle / explicit legacy POST | P0 | §6.4 |
| RF-09 | `SIMULATE_FIRST_RANK_FAILURE` validates #2 path | #2 succeeds; soak with flag off | P1 | §6.4 |
| RF-10 | Legacy `POST .../execute-autonomous` with stale list | Re-generate or re-gate; one-trade scope | P1 | §6.4 |

---

## 9. Risk gates, circuit breakers, auto-pause

| ID | Scenario | EO | Sev | Refs |
| -- | -------- | -- | --- | ---- |
| R-01 | Daily loss > 2% equity | Pause; alert | P0 | §11.4.1, §20.4.4 |
| R-02 | Drawdown > 10% equity | Reduced-exposure → pause if sustained | P0 | §2.2, §11.4.1 |
| R-03 | ≥ 5 consecutive losses | Discretionary pause; Hedge-only | P0 | §11.4.1 |
| R-04 | Max orders / hour (20) exceeded | Reject new; alert | P0 | §11.4.1 |
| R-05 | Max notional / trade > 5% BP | Reject or clip | P0 | §11.4.1 |
| R-06 | Max open positions exceeded | Reject discretionary; hedges exempt | P0 | §11.4.1 |
| R-07 | Broker reject rate > 10% / 1h | Pause all new orders | P0 | §11.4, §20.4.4 |
| R-08 | Bot error rate ≥ 5% / 1h | Reject | P0 | §11.4 |
| R-09 | Kill-switch | Reject all new; manage existing | P0 | §6.2, §20.4.7 |
| R-10 | Insufficient buying power / paper cash | Reject | P0 | §11.4; Paper_Simulator caps |
| R-11 | Capital: > ₹1L trade or leg / > ₹10L book | Reject | P0 | Trading_Strategies; Paper_Simulator |
| R-12 | Symbol not in whitelist | Reject | P0 | §11.4 |
| R-13 | Duplicate `(strategy_id, signal_hash, tick_id)` | Reject idempotent | P0 | §11.4, §20.4.3 |
| R-14 | Win rate drops > 15% vs 7d baseline in 20 trades | Reduced exposure | P1 | §20.4.4 |
| R-15 | P&L vs decision expectation diverge | Pause module | P1 | §20.4.4 |
| R-16 | Slippage / fill quality vs conservative model | Pause module; flag fill model | P1 | §20.4.4 |
| R-17 | Decision cycle latency > 2× baseline | Discretionary pause; Hedge-only | P1 | §20.4.4 |
| R-18 | Unhandled exception in trading path | Immediate Pause; Sentry | P0 | §20.4.4 |
| R-19 | Silent auto-resume after auto-pause | Forbidden (`auto_resume=false`) | P0 | §20.4.4 |
| R-20 | Greeks limits (`total_delta` / gamma / vega / theta) | Reject | P0 | §11.4 |
| R-21 | Raising breaker ceilings without audit | Require audit-logged API | P1 | §20.4.7 |

---

## 10. Paper simulator ledger & γ–θ automation

| ID | Scenario | EO | Sev | Refs |
| -- | -------- | -- | --- | ---- |
| PS-01 | `paper_optimistic` used for soak validation | Forbidden — `paper_conservative` required | P0 | §11.7, §20.4.8 |
| PS-02 | Fill at mid without slippage | Dev-only; not for §2.2 | P0 | §11.7 |
| PS-03 | Multi-leg paper order with missing LTP on one leg | Reject whole basket | P0 | Paper_Simulator |
| PS-04 | Reset account while positions open | Define: flatten or forbid reset until flat | P1 | `/reset` |
| PS-05 | Re-hedge when capital caps would breach | Skip hedge / reduce_options path; enforce caps | P0 | Part J; Paper_Simulator |
| PS-06 | Spot move ≥ breakeven but news kill active | Prefer kill/flatten over re-hedge | P0 | Paper_Simulator |
| PS-07 | Continuous re-hedge loop thrash (spot oscillating) | Cooldown / max `breakeven_paid_count`; cost gate | P1 | Part J |
| PS-08 | Automation running + kill-switch | Stop new entries/hedges per pause policy | P0 | §6.2 |
| PS-09 | Marks refresh fails mid-automation tick | Skip actions; mark degraded | P0 | Paper_Simulator `/marks/refresh` |
| PS-11 | Post-entry multi-leg auto-complete under same open rules | Completing legs re-gate freshness / lot / pre-trade / Part T / cumulative ₹1L; **no** second consent; reject if caps fail | P0 | Paper_Simulator; §11.7 |
| PS-10 | Partial fills / depth | v1 does **not** model — document limitation; live path separate | P2 | Paper_Simulator “Does not” |
| PS-11 | Adapter `paper` dry-run confused with paper-sim P&L | Prefer `/api/v1/paper-sim/*` for P&L | P0 | §11.7 |
| PS-12 | `broker_place_order: true` on paper health | Must be false | P0 | Paper_Simulator `/health` |

---

## 11. Multi-leg live execution & fills

| ID | Scenario | EO | Sev | Refs |
| -- | -------- | -- | --- | ---- |
| ML-01 | Leg 1 fills, leg 2+ fails | Rollback flatten leg 1 within `rollback_timeout_sec` (30s); `partial_fill_incident` | P0 | §11.7 |
| ML-02 | Rollback itself fails / partial residual | Alert; Pause; operator break-glass | P0 | §11.7 |
| ML-03 | Breeze API single-leg only — assume atomic basket | Do not; sequential + rollback | P0 | §11.7 |
| ML-04 | Order rate > ~9–10/s | Token-bucket throttle; never burst into SEBI reject | P0 | §11.11 |
| ML-05 | Static IP not registered / SEBI reject text | Page operator; **do not** blind retry | P0 | §11.11, §11.13 |
| ML-06 | `place_order` 503 / timeout after possible accept | Reconcile via order book / uniqueorderid; idempotency; no duplicate | P0 | §11.10, §20.4.3 |
| ML-07 | Fill via WS and poll both fire | Dedupe on orderid/fill id | P0 | §11.10 |
| ML-08 | Position sync desync vs broker | Prefer broker truth; pause discretionary until reconciled | P0 | §11.2, §11.13 |
| ML-09 | Modify/cancel race with fill | Handle terminal states; no double flatten | P1 | §11.8 |
| ML-10 | Product type `INTRADAY` forced square-off vs multi-day gamma book | Open decision — misconfig risk; gate overnight | P1 | §20.3 #17 |
| ML-11 | `ordertag` > 20 chars | Truncate/hash; must remain unique enough | P2 | §11.10 |
| ML-12 | Micro-size live gates violated | Reject; 50% of paper ceilings | P0 | §20.4.10 |
| ML-13 | Hot adaptation deploy on live without replay soak | Forbidden | P0 | §20.4.10 |
| ML-14 | Canary week: multi-symbol / multi-module | Forbidden first live week — one symbol, one module | P0 | §20.4.10 |

---

## 12. ICICI Direct auth & session

| ID | Scenario | EO | Sev | Refs |
| -- | -------- | -- | --- | ---- |
| A-01 | Login fail / bad or expired `API_Session` | Auth not OK; Pause discretionary; alert; refresh session via Breeze login URL | P0 | §11.9 |
| A-02 | `AB1011` / 401 mid-session | Re-auth; brief pause | P0 | §11.9 |
| A-03 | Refresh token expired → full re-login | Same as A-02 | P0 | §11.9 |
| A-04 | Explicit logout | Force re-auth; no trading | P0 | §11.9 |
| A-05 | API secret / session token logged | Forbidden — never log secrets | P0 | §11.9, §16 |
| A-06 | Frontend receives broker secrets | Forbidden | P0 | §5.2, §16 |
| A-07 | Chatbot asked for API keys | Refuse; redaction | P0 | §7.7, §11.12 |
| A-08 | Concurrent session / portal login conflict | Detect Auth fail; operator alert | P1 | §11.13 |

---

## 13. Process topology, Redis, Postgres, deploy

| ID | Scenario | EO | Sev | Refs |
| -- | -------- | -- | --- | ---- |
| INF-01 | Two workers without leader lock | Duplicate orders — **must** acquire `bot:leader` TTL 30s | P0 | §6.1.4, §17.7 |
| INF-02 | Leader lock lost mid-tick | Stop trading; exit non-zero / reacquire safely | P0 | §6.1.4 |
| INF-03 | Redis disconnect | Chaos: Pause; do not trade blindly | P0 | §20.4.8; plan 3.4 |
| INF-04 | Redis pub/sub drop → UI stale but bot trading | Bot continues if leader; UI shows degraded; alert | P1 | §6.1.4 |
| INF-05 | Postgres unavailable | Pause submits; fail health | P0 | §14 / NFR |
| INF-06 | `/health` OK but scheduler wedged (`missed_ticks≥2`) | `/health/bot` = `down`; external monitor pages | P0 | §6.1.4, §17.7 |
| INF-07 | `missed_ticks==1` or intentional pause | `degraded` | P1 | §6.1.4 |
| INF-08 | API + worker single process crash | Both down — reason for PROCESS_ROLE split | P0 | §17.7 |
| INF-09 | API load starves bot on `PROCESS_ROLE=all` | Promote split; or Pause discretionary under latency rule R-17 | P1 | §17.7 |
| INF-10 | Worker `max-instances>1` | Forbidden — must be 1 | P0 | §6.1.4 |
| INF-11 | Cloud Run CPU throttle on worker | CPU always allocated; min-instances=1 market hours | P0 | §6.1.4 |
| INF-12 | Cold start exceeds budget | Escalate to GCE if needed | P2 | §17.7 |
| INF-13 | Chroma/Filestore restart | Chat/RAG degrade; bot marks path independent | P1 | §17.8 |
| INF-14 | Wrong region (not `asia-south1`) for live | Forbidden for inventory | P0 | §17.8; workspace rule |
| INF-15 | CORS / wrong `NEXT_PUBLIC_API_URL` | UI broken; no trading impact if worker healthy | P1 | §17.0 |
| INF-16 | WebSocket idle timeout mid-session | Reconnect client; server state authoritative | P1 | Paper_Simulator |
| INF-17 | Secret Manager / Railway secret missing | Fail closed; no start trading | P0 | §11.12, §16 |

---

## 14. Learning & adaptation

| ID | Scenario | EO | Sev | Refs |
| -- | -------- | -- | --- | ---- |
| L-01 | Adapt with < 30 closed trades / module | Block tuning | P0 | §12.5 |
| L-02 | Single change > 20% (or weight > ±15%) | Block / clip | P0 | §12.5 |
| L-03 | Adaptation within 24h cooldown | Block | P1 | §12.5 |
| L-04 | Post-deploy win rate drops > 10% in 20 trades | Automatic rollback | P0 | §12.5 |
| L-05 | Deploy while drawdown > 5% | Freeze adaptation | P0 | §12.5, §20.4.5 |
| L-06 | Walk-forward fails / no replay-before-deploy | Block deploy | P0 | §12.5 |
| L-07 | RAG faithfulness red during adaptation | Block deploy | P0 | §12.5 |
| L-08 | Change > 10% without human ack (Phase 4+) | Require confirm | P1 | §12.5, §20.4.5 |
| L-09 | Learning mode pauses new trades mid-opportunity | Expected; hedges policy per mode | P1 | §6.2 |
| L-10 | Broken signal→P&L lineage | Block reweight until fixed | P1 | §12.7 |
| L-11 | Overfit to paper_optimistic history | Prevented by conservative fill default | P0 | §20.1 |

---

## 15. Frontend / operator UX

| ID | Scenario | EO | Sev | Refs |
| -- | -------- | -- | --- | ---- |
| UI-01 | Kill-switch network fail | Retry; show error; assume not paused until ACK — prefer optimistic UI + confirm from API | P0 | §20.4.7 |
| UI-02 | Decision card shows MCP / `mcp_sources` | Must use `feed_sources` | P1 | plan §1 |
| UI-03 | Recommendations SSR shows trade already opened | Display `autonomous_execution`; do not re-trigger | P0 | §6.4 |
| UI-04 | Operator role without Approve permission | 403 | P1 | §16.3 |
| UI-05 | Stale WS while REST healthy | Reconnect; poll fallback | P2 | §5.2 |
| UI-06 | Packet incomplete vs P1 checklist | UI flags missing sections; supervised should not approve incomplete | P1 | §6.4 |

---

## 16. Security & compliance

| ID | Scenario | EO | Sev | Refs |
| -- | -------- | -- | --- | ---- |
| SEC-01 | Credential in frontend bundle / git | Forbidden | P0 | §16 |
| SEC-02 | Live order from dynamic egress IP | SEBI reject — static NAT required on GCP | P0 | §11.11, plan 5.1–5.2 |
| SEC-03 | Algo-provider multi-client misuse | Out of scope — self-algo only | P1 | §11.11 |
| SEC-04 | SSRF via custom feed URL | Allowlist + private IP block | P0 | §8.7 |
| SEC-05 | Prompt injection via news text into LLM | Structured schemas; no tool access to broker from LLM | P1 | §10.2, §20.4.6 |
| SEC-06 | Operator session hijack Approve | Authn + audit trail | P0 | §16 |

---

## 17. India market microstructure (exchange / instrument)

Not all are first-class coded yet; treat as **required awareness** for gates and playbook kills.

| ID | Scenario | EO | Sev | Notes |
| -- | -------- | -- | ----- | ----- |
| X-01 | F&O ban / ASM / GSM / surveillance | Reject symbol; remove from whitelist | P0 | Align with ICICI Direct/NSE status |
| X-02 | Upper/lower circuit / trading halt on underlying | Stale/untradeable; Pause strategy | P0 | Freshness + session |
| X-03 | Corporate action (split, bonus, dividend) mid-trade | Kill / flatten; refresh instrument master | P0 | News topics + master |
| X-04 | Lot size change after position open | Hedge/close using new lot rules; no fractional | P0 | Instrument master |
| X-05 | Weekly vs monthly expiry mix in one structure | Explicit strategy rule; else reject | P1 | OSS catalog |
| X-06 | Assignment / exercise risk on short options (if ever short) | Prefer defined-risk; Shared Kill near expiry | P0 | Playbook |
| X-07 | Basis risk if marks vendor ≠ broker (future) | N/A while ICICI Direct sole; do not reintroduce dual feed | P0 | §8.9 |
| X-08 | Illiquid far OTM / zero volume | Liquidity gate fail | P0 | Part I |
| X-09 | Gap open through hedge breakeven | Re-hedge / flatten per γ–θ + news | P1 | Part J |
| X-10 | Budget / election / RBI event day | Macro flags → reduce or block | P1 | §8.8 |

---

## 18. Chaos & CI scenarios (mandatory)

From §20.4.8, §22.1, plan Phase 3.4.

| ID | Scenario | Required outcome |
| -- | -------- | ---------------- |
| CH-01 | Feed stale mid-tick | Pause / Reject — no blind trade |
| CH-02 | Groq timeout / down | Hedge-only degraded |
| CH-03 | Broker 503 | Pause / reconcile; no duplicate |
| CH-04 | Redis disconnect | Pause |
| CH-05 | Duplicate tick replay | Idempotent |
| CH-06 | Replay E2E decision log inconsistent | CI merge block |
| CH-07 | RAG faithfulness < 0.85 | CI merge block |
| CH-08 | OSS parity fail | CI merge block |

---

## 19. Phase-specific edge cases (implementation plan)

| Phase | Edge cases to prove before exit |
| ----- | -------------------------------- |
| **0** | ICICI Direct auth fail; no `place_order` possible; health without bot loop; CORS/WS wiring |
| **1** | News stale; SH-4 kill; lotsize reject; conservative slippage; γ–θ + capital cap; GARCH distorted |
| **2** | Approval timeout; one-trade defer; kill-switch; circuit breakers; idempotency; Track B green before LLM gate |
| **3** | Semi-auto threshold boundary (0.849 vs 0.85); demotion; chaos CH-01–CH-04; config rollback |
| **4** | All ranks fail; RF double-fetch; soak with conservative fills; `SIMULATE_FIRST_RANK_FAILURE=false` |
| **5** | Static IP; sequential multi-leg rollback; micro-size; re-supervise on live; market-hours deploy pause; A6 no stubs |
| **Track B** | Empty Chroma; faithfulness; Ask AI on decision card without leaking secrets |

---

## 20. Explicit non-goals (do not “fix” by inventing)

| Non-goal | Why |
| -------- | --- |
| ICICI Direct paper/sandbox API | Does not exist — use `paper_sim` |
| MCP registry / MCP feed assignment | Retired — ICICI Direct + Market_News only |
| US brokers / US paper | Indian markets only |
| Bid/ask depth & partial fills in paper v1 | Documented limitation |
| HFT hedge cadence | Retail constraints |
| LLM in broker submit path | Quant + risk gates only |
| Auto-enable strategies / silent auto-resume | Operator control |
| Global US news as India regime | §8.8 non-goal |

---

## 21. Traceability matrix (doc → test home)

| Area | Architecture | Suggested tests |
| ---- | ------------ | --------------- |
| Stale feeds / SSRF | §8.7 | `tests/integration/`, `tests/chaos/` |
| News / SH-4 | §8.8 | `paper_sim` signal evaluate tests |
| OSS / lotsize / IST | §8.5, §11.10 | `tests/quant/test_oss_parity.py` |
| Groq degrade | §10.6 | `tests/chaos/` |
| Risk / breakers / one-trade | §11.4, §20.4 | `tests/unit/execution/` |
| Ranked fallback | §6.4 | `tests/integration/recommendations/` |
| Multi-leg rollback | §11.7 | `tests/integration/execution/` |
| Leader lock / health | §6.1.4 | `tests/chaos/`, deploy smoke |
| Live gates | §20.4.10 | Phase 5 checklist (manual + gated e2e) |
| RAG faithfulness | §7, §22 | `tests/knowledge/` golden eval |

---

## 22. Maintenance

When changing autonomy, ICICI Direct, news, or risk behavior:

1. Update this file with new IDs (do not renumber existing IDs).
2. Add or extend a chaos/unit test for every new **P0**.
3. Keep `Docs/architecture.md` §20.4 / §22 and `Docs/implementation_plan.md` phase exits aligned.

---

*Derived from architecture §2–§22 (esp. §6, §8–§12, §17, §20.4) and implementation plan Phases 0–5 + Track B. Companion to `Docs/Paper_Simulator.md` for paper-path specifics.*
