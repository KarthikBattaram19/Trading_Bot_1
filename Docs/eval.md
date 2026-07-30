# Phase Evaluation Guide — Volatility Trading Bot

> **Authority:** `Docs/architecture.md` (v1.26+) §2.2, §6.2, §11.15, §17, §20.4, §21–§22  
> **Plan:** `Docs/implementation_plan.md`  
> **Context:** `Docs/context.md` §1–§2.5  
> **Edge cases:** `Docs/edge_cases.md`  
> **Created:** July 16, 2026  
> **Purpose:** Pass/fail evaluation for each implementation phase and Track B. Use before promoting modes, merging LLM gates, or enabling live `place_order`.

---

## 1. How to use this document

| Rule | Detail |
| ---- | ------ |
| **One phase at a time** | Do not start Phase *N+1* exit criteria until Phase *N* is **PASS** |
| **Evidence required** | Every gate needs a check type: *Automated* (CI/pytest), *Manual* (operator), *Soak* (time-boxed run), or *Doc* (signed checklist) |
| **P0 first** | Edge cases marked **P0** in `edge_cases.md` block phase exit if unproven |
| **No mode skip** | `EXECUTION_MODE`: `shadow` → `paper` → `live`. `SUPERVISION_MODE`: `supervised` → `semi_autonomous` → `fully_autonomous` (only after `paper`) |
| **Region** | Live inventory must be **`asia-south1`**; paper stack is Railway + Vercel |

### 1.1 Verdicts

| Verdict | Meaning |
| ------- | ------- |
| **PASS** | All Must-have gates green; P0 edge cases covered by test or signed chaos run |
| **CONDITIONAL** | Must-haves green; Should-haves deferred with dated follow-up (not allowed for Phase 4→5 or Track B→LLM gate) |
| **FAIL** | Any Must-have red, any live `place_order` on paper stack, or MCP registry still present |

### 1.2 Success metrics (paper — §2.2 / context §2.5)

Apply on closed trades with **`paper_conservative`** fills only (`edge_cases.md` PS-01).

| Metric | Target | Breach action |
| ------ | ------ | ------------- |
| Win rate (rolling 30-day) | ≥ 60% | Tighten filters; raise confidence |
| Profit factor | ≥ 1.5 | Reduce exposure; pause weak modules |
| Sharpe (annualized, rolling) | ≥ 1.5 | Adaptation cycle |
| Max drawdown | ≤ 10% of paper equity | Reduced-exposure / pause |
| Recovery factor | ≥ 2.0 | Resume when recovered |

**Soak rule (Phase 4):** Meet **at least one** full metric set above on a 2–4 week run *and* no critical auto-pause without root cause (architecture §22.4 / plan §7).

### 1.3 Cross-cutting integration DoD (all phases after 0.3)

From `implementation_plan.md` §10 — must remain true through Phase 5:

- [ ] No MCP registry, MCP feed routes, or MCP-labeled UI (`mcp_sources` → `feed_sources`)
- [ ] ICICI Direct supplies all marks used by `paper_sim` (and live later)
- [ ] ICICI Direct `place_order` only when `EXECUTION_MODE=live` on GCP
- [ ] `Market_News` pipeline produces `MarketNewsSummary` for recommendations / paper-sim
- [ ] Packets expose ICICI Direct feed health + `market_news` (not MCP ids)

### 1.4 Test homes (architecture §22.1 + edge_cases §21)

| Layer | Location | Blocks |
| ----- | -------- | ------ |
| Unit | `backend/tests/unit/` | Every push |
| Integration | `backend/tests/integration/` | Every push |
| OSS parity | `backend/tests/quant/test_oss_parity.py` | Merge (Q-19, CH-08) |
| RAG golden | `backend/tests/knowledge/` | Merge if faithfulness &lt; 0.85 (AI-05, CH-07) |
| Replay E2E | `backend/tests/e2e/` | Nightly (CH-06) |
| Chaos | `backend/tests/chaos/` | Phase 3–4 / Phase 5 gate |
| Paper soak | Railway + Vercel | Phase 4 → 5 |

---

## 2. Phase 0 — Scaffold & ICICI Direct data-only

**Goal:** Deployable API + ICICI Direct marks; **zero** `place_order`.  
**Modes:** `EXECUTION_MODE=shadow` default.  
**Deploy:** Local → Railway (`backend/`) + Vercel (`frontend/`).  
**ICICI Direct:** A0–A1 only.

### 2.1 Work-item checklist

| # | Criterion | Evidence | Must |
| - | --------- | -------- | ---- |
| 0.1 | Native local stack (`Docs/LOCAL_DEV.md`); Python + Node; optional native PG/Redis; Nixpacks/Buildpacks remotely | Manual: `scripts/dev/check-env.ps1` + `/health` (`local_containers_required: false`) | Yes |
| 0.2 | FastAPI scaffold; `GET /health` green; `.env.example` present | Automated + Manual | Yes |
| 0.3 | MCP registry removed; ICICI Direct + news feed status exposed; no `GET /feeds/mcp` | Code review + API smoke | Yes |
| 0.4 | ICICI Direct session manager + `POST .../broker/test` with secrets | Manual with real secrets (server-side only) | Yes |
| 0.5 | Instrument master + LTP REST → normalized ticks; on-demand marks | Manual / integration | Yes |
| 0.6 | `GET /api/v1/paper-sim/health` stub; shadow mode documented | API smoke | Yes |
| 0.7 | Frontend hits Railway API (`CORS_ORIGINS`, `NEXT_PUBLIC_*`) | Manual | Yes |
| 0.8 | UI shell: bot status, health, kill-switch placeholder | Manual vs `UI_Dashboard.md` | Yes |

### 2.2 Exit gates

| Gate | Pass when |
| ---- | --------- |
| **E0-A** | ICICI Direct marks refresh on Railway |
| **E0-B** | Grep/CI: no Breeze API `place_order` call path enabled |
| **E0-C** | News path stubbed but schema present |
| **E0-D** | `paper_sim` health reports `broker_place_order: false` (PS-12) |

### 2.3 Edge cases to prove (before exit)

| ID | Scenario | Required EO |
| -- | -------- | ----------- |
| A-01 / A-05 | Auth fail; secrets never logged | Pause discretionary path; no secret in logs |
| M-01 | `live` attempted on Railway | Reject; no `place_order` |
| INF-15 | Wrong CORS / API URL | UI broken only; document fix |
| S-12 | Scale-to-zero during session | Prefer min 1 always-on for later automation |
| SEC-01 | Credentials in frontend / git | Forbidden |

### 2.4 Sign-off

| Role | Date | Verdict | Notes |
| ---- | ---- | ------- | ----- |
| Operator | | PASS / FAIL | |

---

## 3. Phase 1 — Paper simulator + Market_News

**Goal:** End-to-end paper P&L with playbook + news gates.  
**Authority:** `Docs/Paper_Simulator.md`.  
**Modes:** `EXECUTION_MODE=paper` on Railway — **never** `live`.  
**ICICI Direct:** A0–A2 + **A3** shadow dry-run payloads (mandatory; no live submit).

### 3.1 Work-item checklist

| # | Criterion | Evidence | Must |
| - | --------- | -------- | ---- |
| 1.1 | Ledger: account, positions, fills, multi-leg orders, close | Integration + Manual P&amp;L | Yes |
| 1.1a | Post-entry multi-leg auto-complete without consent; same open-trade rules | Unit (`test_multi_leg_auto_complete`) | Yes |
| 1.2 | Marks from ICICI Direct LTP + scrip master; fresh-marks gate | Integration (MD-01) | Yes |
| 1.3 | Market_News ingest → `/paper-sim/news` + packet `market_news` | Integration + Manual | Yes |
| 1.4 | SH-4 selection with news overlay | Unit/integration (N-02–N-12) | Yes |
| 1.5 | GARCH / IV z-score + `POST /signals/evaluate` | Integration | Yes |
| 1.6 | γ–θ re-hedge automation (no LLM) | Integration + Manual | Yes |
| 1.7 | BSM + OSS parity smoke; cost model; pre-trade thresholds | Automated (Q-19) | Yes |
| 1.8 | ICICI Direct A2 WS (mandatory) | Manual freshness + unit tests | No |
| 1.9 | A3 shadow order payloads logged only (place/cancel/status) | Unit + API (`test_icici_a3_shadow`) | Yes |
| 1.10 | Railway config confirms `paper` not `live` | Config (`infra/env/railway.paper.env.example`) + M-01 guard tests (`test_phase1_10_paper_stack`) | Yes |

### 3.2 Exit gates

| Gate | Pass when |
| ---- | --------- |
| **E1-A** | Manual + automated paper trades update local P&amp;L |
| **E1-B** | News / SH-4 gates honored on automation path |
| **E1-C** | Zero `place_order`; capital caps ₹10L / ₹1L / leg enforced (R-11) |
| **E1-D** | Conservative slippage default for validation fills (PS-01) |
| **E1-E** | Lotsize / tick / cost gates reject bad orders (Q-04–Q-08) |

### 3.3 Edge cases to prove

| ID | Focus |
| -- | ----- |
| N-01, N-03, N-12 | News stale / crisis / IV z blocked |
| MD-05, MD-10, MD-14 | Bad LTP; GARCH gap; spot ≤ ₹1000 when options+underlying |
| PS-03, PS-05, PS-06, PS-11 | Multi-leg missing mark; capital-cap hedge; news kill vs re-hedge; multi-leg auto-complete under open rules |
| Q-05, Q-07 | Lotsize; `net_hedge_edge ≤ 0` |
| S-01, S-10 | Session window; IST / `Asia/Kolkata` |

### 3.4 Sign-off

| Role | Date | Verdict | Notes |
| ---- | ---- | ------- | ----- |
| Operator | | PASS / FAIL | |

---

## 4. Phase 2 — Supervised paper bot

**Goal:** Operator approves discretionary paper entries; mechanical hedges auto.  
**Modes:** `EXECUTION_MODE=paper`, `SUPERVISION_MODE=supervised`.  
**Prerequisite:** Track B golden eval **green** before enabling Groq discretionary gate (AI-06, plan 2.5).

### 4.1 Work-item checklist

| # | Criterion | Evidence | Must |
| - | --------- | -------- | ---- |
| 2.1 | Scheduler; ≥ 1 week shadow then paper single-module | Soak log (M-07) | Yes |
| 2.2 | Approve / Reject APIs; no auto-submit on timeout | Integration (SU-01) | Yes |
| 2.3 | Supervised cockpit (decision queue) | Manual vs `UI_Dashboard.md` | Yes |
| 2.4 | One-trade gate, circuit breakers, auto-pause, kill-switch | Integration + Manual | Yes |
| 2.5 | AI validator only if Track B PASS | CI faithfulness ≥ 0.85 | Yes |
| 2.6 | Live-path multi-leg builder polish; ICICI Direct multi-leg dry-run only (paper auto-complete = Phase 1.1a) | Integration | Yes |

Also required (architecture §21 Phase 2):

- [ ] Idempotency keys + symbol whitelist (R-13, R-12)
- [ ] `auto_resume=false` after auto-pause (R-19)
- [ ] WebSocket events + config audit trail
- [ ] Role-based auth on Approve (UI-04, SEC-06)

### 4.2 Exit gates

| Gate | Pass when |
| ---- | --------- |
| **E2-A** | Full market day supervised: Approve/Reject path works |
| **E2-B** | Kill-switch blocks new discretionary; hedges policy documented (R-09, SU-05) |
| **E2-C** | Second discretionary signal deferred (`deferred_one_trade_scope`) (SU-06) |
| **E2-D** | Re-gate on Approve if marks stale (SU-02) |
| **E2-E** | Promotion checklist artifact ready for Phase 3 (≥ 30 closed supervised trades target starts counting) |
| **E2-F** | Replay E2E decision log green (architecture §22.4 “Phase 2” style gate) |

### 4.3 Edge cases to prove

| ID | Focus |
| -- | ----- |
| SU-01–SU-07, SU-10 | Timeout, race, one-trade, hedge vs pending |
| R-01–R-09, R-18–R-19 | Breakers, kill-switch, no silent resume |
| AI-01–AI-07, AI-11 | Groq degrade; RAG skip; confidence; malformed JSON |
| UI-02 | No MCP copy in FeedStatusPanel |
| CH-05 | Duplicate tick idempotent |

### 4.4 Promotion checklist → Phase 3 (`supervised` → `semi_autonomous`)

| Check | Target | Status |
| ----- | ------ | ------ |
| Closed supervised paper trades | ≥ 30 | |
| Win rate / profit factor | Within §1.2 bands | |
| Unexplained gate bypasses | Zero | |
| Chaos CH-01–CH-04 | Green or deferred only to Phase 3 Must | Prefer before promote |
| Operator sign-off | Dated | |

API must **reject** promotion without checklist (M-03).

### 4.5 Sign-off

| Role | Date | Verdict | Notes |
| ---- | ---- | ------- | ----- |
| Operator | | PASS / FAIL | |

---

## 5. Phase 3 — Semi-autonomy on paper

**Goal:** High-confidence auto-submit + residual queue; learning + chaos hardening.  
**Modes:** `EXECUTION_MODE=paper`, `SUPERVISION_MODE=semi_autonomous`.

### 5.1 Work-item checklist

| # | Criterion | Evidence | Must |
| - | --------- | -------- | ---- |
| 3.1 | Promote only after §4.4 checklist | Doc + API audit | Yes |
| 3.2 | Auto-submit when confidence ≥ 0.85 and gates pass; else queue | Integration (SU-08, SU-09) | Yes |
| 3.3 | Learning engine, walk-forward, config rollback | Integration (L-01–L-07) | Yes |
| 3.4 | Chaos: stale ICICI Direct feed, Groq down, Redis loss | `tests/chaos/` (CH-01–CH-04, INF-03) | Yes |

Also:

- [ ] Multi-module only after ≥ 30 closed trades / module
- [ ] Failure memory + regime classifier wired
- [ ] Demotion path `semi` → `supervised` audited (M-04 behavior)

### 5.2 Exit gates

| Gate | Pass when |
| ---- | --------- |
| **E3-A** | Semi-auto paper metrics within §1.2 bands |
| **E3-B** | Override / residual-queue rate acceptable (operator-defined; document %) |
| **E3-C** | Demotion mid-session: no new entries; hedges continue; audit log |
| **E3-D** | Boundary: confidence 0.849 queues; 0.85+ may auto if gates pass |
| **E3-E** | Config rollback restores prior version; adaptation freeze under drawdown &gt; 5% (L-05) |

### 5.3 Edge cases to prove

| ID | Focus |
| -- | ----- |
| SU-08, SU-09 | Semi threshold |
| L-01–L-07, L-11 | Learning guards; conservative fills |
| CH-01–CH-04, INF-01–INF-02 | Chaos + leader lock |
| AI-02 | Groq &gt; 60s → Hedge-only |
| M-06 | Optimizer cannot `strategy_enabled=true` |

### 5.4 Promotion checklist → Phase 4 (`semi` → `fully_autonomous`)

| Check | Target | Status |
| ----- | ------ | ------ |
| Closed semi-auto paper trades | ≥ 30 | |
| Critical auto-pause without RCA | None during qualifying window | |
| Operator override rate | Low (document threshold) | |
| Chaos suite | Green | |
| Operator sign-off | Dated | |

### 5.5 Sign-off

| Role | Date | Verdict | Notes |
| ---- | ---- | ------- | ----- |
| Operator | | PASS / FAIL | |

---

## 6. Phase 4 — Full autonomy paper soak

**Goal:** Ranked fallback on **paper-sim only**; 2–4 week soak; live readiness doc — **no** live submit.  
**Modes:** `EXECUTION_MODE=paper`, `SUPERVISION_MODE=fully_autonomous`.

### 6.1 Work-item checklist

| # | Criterion | Evidence | Must |
| - | --------- | -------- | ---- |
| 4.1 | Ranked fallback #1→#2→#3 on paper-sim only | Integration (RF-01–RF-06) | Yes |
| 4.2 | 2–4 week soak vs §1.2 | Soak report | Yes |
| 4.3 | Live readiness doc; `PROCESS_ROLE` health split ready — still no live | Doc + health smoke | Yes |

Also:

- [ ] `SIMULATE_FIRST_RANK_FAILURE=false` for soak metrics (M-10); use true only for RF path test
- [ ] `paper_conservative` throughout soak (PS-01)
- [ ] Analytics dashboards usable; Chroma backup if Track B active
- [ ] New module under full-auto starts supervised / two-key (M-05) — verify policy

### 6.2 Exit gates

| Gate | Pass when |
| ---- | --------- |
| **E4-A** | Soak meets ≥ 1 complete §1.2 metric set |
| **E4-B** | Chaos green (CH-01–CH-08 as applicable) |
| **E4-C** | All ranks fail → no trade + full `attempts[]` log (RF-04) |
| **E4-D** | Double-fetch / SSR refresh does not double-submit (RF-07) |
| **E4-E** | Ranked fallback **null** when not fully autonomous (RF-01) |
| **E4-F** | Operator signs Phase 5 gate (M-08) |

### 6.3 Edge cases to prove

| ID | Focus |
| -- | ----- |
| RF-01–RF-09 | Fallback correctness |
| M-08, M-09 | Block live without soak; no paper→live ledger flip |
| PS-01, PS-11 | Conservative fills; adapter dry-run ≠ paper P&amp;L |
| INF-06 | `/health/bot` detects wedged scheduler |

### 6.4 Live readiness review (doc gate before Phase 5)

Confirm drafted and reviewed:

- [ ] GCP `asia-south1` inventory plan (`infra/cloud-inventory.yaml`)
- [ ] Static NAT egress + Breeze API IP registration plan
- [ ] Micro-size + §20.4.10 live gates
- [ ] Prefer re-start `supervised` on first live week (M-11)
- [ ] Market-hours deploy pause procedure (S-11)
- [ ] Chaos evidence attached

### 6.5 Sign-off (Phase 5 gate)

| Role | Date | Verdict | Notes |
| ---- | ---- | ------- | ----- |
| Operator | | PASS / FAIL | Blocks Phase 5 if FAIL |

---

## 7. Phase 5 — Live ICICI Direct on GCP

**Goal:** Micro-size live with ICICI Direct marks **and** orders; Market_News still gates SH-4.  
**Modes:** `EXECUTION_MODE=live` **only** on GCP; often re-start `supervised` then re-promote.  
**ICICI Direct:** A4–A6. **Region:** `asia-south1` (INF-14).

### 7.1 Work-item checklist

| # | Criterion | Evidence | Must |
| - | --------- | -------- | ---- |
| 5.1 | Cloud Run API + worker, Cloud SQL, Memorystore, Filestore, Cloud NAT static egress | Inventory + deploy smoke | Yes |
| 5.2 | Secrets → Secret Manager; static IP registered in Breeze API | Manual portal + INF-17 | Yes |
| 5.3 | Live place/cancel/status; multi-leg + rollback; rate limits | Gated e2e + Manual micro | Yes |
| 5.4 | Re-start supervised on live, then re-promote | Audit trail | Yes |
| 5.5 | Micro-size + live gates (§20.4.10); 50% paper ceilings (ML-12) | Config review + reject tests | Yes |
| 5.6 | A6: stub NSE quote paths removed; ICICI Direct sole marks + orders (MD-22) | Code review | Yes |
| 5.7 | Uptime monitor on `/health/bot`; market-hours deploy pause | Ops runbook | Yes |

### 7.2 Exit gates

| Gate | Pass when |
| ---- | --------- |
| **E5-A** | Micro-size live order round-trip + cancel/status |
| **E5-B** | Multi-leg: leg failure triggers rollback within `rollback_timeout_sec` (ML-01–ML-03) |
| **E5-C** | Static IP / SEBI reject → page operator; no blind retry (ML-05, SEC-02) |
| **E5-D** | `place_order` timeout → reconcile; no duplicate (ML-06) |
| **E5-E** | Canary week: one symbol, one module (ML-14); no hot adapt without soak (ML-13) |
| **E5-F** | Worker `max-instances=1`, leader lock proven (INF-01, INF-10) |
| **E5-G** | News SH-4 still gating live discretionary entries |

### 7.3 Edge cases to prove

| ID | Focus |
| -- | ----- |
| ML-01–ML-08, ML-12–ML-14 | Live multi-leg, rate, micro-size, canary |
| M-01, M-02, M-12 | Live only on GCP; paper never routes place_order |
| S-07–S-08, S-11 | Midnight JWT; pre-market login; deploy pause |
| A-01–A-04 | Auth lifecycle |
| X-01–X-04 | Ban/halt/corporate action/lot change awareness |

### 7.4 Sign-off

| Role | Date | Verdict | Notes |
| ---- | ---- | ------- | ----- |
| Operator | | PASS / FAIL | |

---

## 8. Track B — RAG / chat (parallel)

**Rule:** Must **not** block Phase 0–1. **Must** PASS before LLM-gated discretionary entries (Phase 2+).

### 8.1 Steps

| Step | Deliverable | Timing | Must before |
| ---- | ----------- | ------ | ----------- |
| **B1** | One PDF → Chroma → `POST /chat` + UI + golden eval CI | With Phase 0–1 | LLM gate off until B2 |
| **B2** | Remaining PDFs; faithfulness ≥ 0.85 | Before LLM trading | Phase 2.5 / AI validator |
| **B3** | Ask AI from decision cards | Phase 2 cockpit | Optional UX; still no secret leak |

### 8.2 Exit gates

| Gate | Pass when |
| ---- | --------- |
| **EB-A** | Chat returns cited answers; citations map to retrieved `chunk_id`s (AI-14) |
| **EB-B** | Golden eval CI faithfulness ≥ 0.85 (AI-05, CH-07) |
| **EB-C** | Empty Chroma / Chroma down → chat degrade; discretionary RAG gate fails closed (AI-13) |
| **EB-D** | Chatbot refuses API keys / broker secrets (A-07) |
| **EB-E** | Ask AI on stale packet warns / recomputes (SU-12) |
| **EB-F** | Separate chat vs decision prompt profiles (AI-12) |

### 8.3 Sign-off (required before Groq entry gating)

| Role | Date | Verdict | Notes |
| ---- | ---- | ------- | ----- |
| Operator | | PASS / FAIL | AI-06: FAIL forbids LLM gating |

---

## 9. Mode promotion scorecard (quick reference)

| Transition | Minimum evidence |
| ---------- | ---------------- |
| Shadow → Paper | ≥ 1 week shadow; zero pipeline errors (M-07) |
| Paper single → multi-module | ≥ 30 closed trades / enabled module; risk gates green |
| `supervised` → `semi_autonomous` | ≥ 30 closed supervised; §1.2 bands; checklist; API gate |
| `semi_autonomous` → `fully_autonomous` | ≥ 30 closed semi; low override; no critical unexplained pause |
| Paper soak → `live` | Phase 4 PASS; chaos green; GCP + micro-size + §20.4.10; signed E4-F |

---

## 10. Per-phase evaluation worksheet

Copy one block per review. Attach CI links, soak dashboards, and chaos logs.

### Template

```
Phase / Track: _______________
Date: _______________
Evaluator: _______________

Must-have gates:     __ / __ PASS
P0 edge cases proven: __ / __ 
CI (unit/int/OSS/RAG): PASS / FAIL
Chaos (if required):   PASS / FAIL / N/A
Soak metrics (if req): PASS / FAIL / N/A

Blocking issues:
1.
2.

Verdict: PASS / CONDITIONAL / FAIL
Next phase allowed: YES / NO
Follow-ups (with dates):
-
```

### Running log

| Phase | Date | Verdict | Blockers | Signed by |
| ----- | ---- | ------- | -------- | --------- |
| 0 | | | | |
| 1 | | | | |
| Track B | | | | |
| 2 | | | | |
| 3 | | | | |
| 4 | | | | |
| 5 | | | | |

---

## 11. Explicit non-goals (evaluation must not require)

Do not fail a phase for missing these — they are out of scope (`edge_cases.md` §20):

| Non-goal | Correct approach |
| -------- | ---------------- |
| ICICI Direct paper/sandbox API | Use `paper_sim` |
| MCP registry / MCP feed assignment | ICICI Direct + Market_News only |
| US brokers / US paper | Indian markets only |
| Bid/ask depth & partial fills in paper v1 | Document limitation (PS-10) |
| HFT hedge cadence | Retail cost gate |
| LLM in broker submit path | Quant + risk gates only |
| Auto-enable strategies / silent auto-resume | Operator control |
| Global US news as India regime | Ignore / down-weight (N-09) |

---

## 12. Maintenance

When phases, modes, ICICI Direct, news, or risk behavior change:

1. Update the matching phase section and scorecard in this file.
2. Align `Docs/implementation_plan.md` exits and `Docs/architecture.md` §21 / §22.4.
3. Add new **P0** edge cases to `Docs/edge_cases.md` (do not renumber existing IDs) and map them into the relevant phase § “Edge cases to prove”.
4. Every new P0 should land in unit, integration, or chaos tests before the phase can PASS.

---

*Companion to `Docs/implementation_plan.md` (build order), `Docs/architecture.md` §21–§22 (roadmap & CI), `Docs/context.md` (success metrics & modes), and `Docs/edge_cases.md` (scenario catalog).*
