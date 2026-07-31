# Project Context: AI-Assisted Volatility Trading Bot

> **Source documents:** `Docs/Problem_Statement.txt`, `Docs/Strategy_Ingestion_Pipeline.txt`, `Docs/OSS (1).xlsm`, `Docs/OSS_Guide (1).pdf`, `Docs/Volatility Trading.pdf`, `Docs/Gamma Scalping.pdf`, `Docs/Vega Scalping.pdf`, `Docs/Trading_Strategies.pdf`, `Docs/Trading_Strategies.md`, `Docs/Trading_Parameters.md`, `Docs/UI_Dashboard.md`, `Docs/Paper_Simulator.md`, `Market_News.txt`, `architecture.md`  
> **Last synthesized:** July 31, 2026 (v3.8 — G11–G12 feed-bound universe = all ICICI Direct NSE F&O underlyings; prior v3.7: OSS Iron Condor valuation **2024-01-04 10:35 IST**; Railway+Vercel paper; GCP `asia-south1` live)

---

## 1. Executive Summary

This project aims to design and build a **continuously learning volatility trading bot** tailored for **retail-scale deployment**. Discretionary execution follows a deliberate path: **supervised → semi-autonomous → fully autonomous** (`SUPERVISION_MODE`)—see `architecture.md` §6.2.2, §6.4, §20.4.11, and **§21**. Phase 2 defaults to **supervised** operator approval on `paper_sim`; full autonomy is the end state after paper evidence, not the day-one default. It bridges the gap between institutional-grade volatility strategies and retail constraints by combining:

- **Statistical Arbitrage** (cointegration-based pair trading)
- **Volatility Trading** (HV, IV, term structure, smile/skew analysis)
- **Gamma Scalping** (dynamic delta hedging)
- **Vega Scalping** (implied volatility exposure management)

The bot operates end-to-end: **fetch live data → ingest & normalize → analyze → decide → (approve if supervised) → execute → monitor → learn → adapt**. It is not a passive recommendation tool—it **executes trades via broker adapters** once signals pass quant, AI, and risk gates, subject to the active supervision mode. In `fully_autonomous`, the **recommendations screen** auto-opens rank #1 and falls back to #2, then #3 on broker failure in the same request cycle (`architecture.md` §6.4). **`EXECUTION_MODE`** ramps deliberately (`shadow` → `paper` → `live`) before broker submit is enabled (§6.2.1). Mechanical hedges (delta drift, stop-loss) remain **always automated** (`architecture.md` §10.6). **One trade at a time** limits blast radius (§20.4.11).

**Primary performance objective:** achieve and sustain a **high success ratio**—measured by win rate, profit factor, Sharpe ratio, and controlled drawdowns—through disciplined quant models, AI reasoning, and a closed-loop learning system that improves with every trade cycle.

A **Retrieval-Augmented Generation (RAG)** pipeline ingests four domain PDFs—`Docs/Volatility Trading.pdf`, `Docs/Gamma Scalping.pdf`, `Docs/Vega Scalping.pdf`, and `Docs/Trading_Strategies.pdf`—into ChromaDB. That knowledge layer powers (1) a **user chatbot** in the final frontend UI and (2) Groq-grounded validation/explanations for discretionary trades. **Quant modules generate signals; Groq (LLM) validates discretionary entries, explains decisions, and grounds reasoning in retrieved domain knowledge**—mechanical hedges (e.g., delta drift) follow rule-based fast paths without LLM latency (see `architecture.md` §10.6, §7.7).

**Live market data** for equities, options, indices, futures, and related instruments is fetched from **user-configured URL endpoints**—REST APIs, broker data URLs, CSV/JSON file endpoints, or streaming feeds—that the bot polls or pulls on a schedule during market hours. Normalized feeds drive quantitative modules and **refresh OSS trade inputs** (underlying price, option marks, implied volatility).

**India market sentiment** is curated per `Market_News.txt` (Architecture §8.8). Tone/topics/event flags overlay quant signals and drive strategy choice via `Trading_Strategies.md` Table SH-4. The in-house **paper simulator** (`Docs/Paper_Simulator.md`) rehearses the same playbook (signals, news gates, γ–θ re-hedge) on ICICI Direct marks with a local ledger before live ICICI Direct submit.

**Trade inputs** for option-based strategies follow the **Macroption Option Strategy Simulator (OSS)** model (`Docs/OSS (1).xlsm`, `Docs/OSS_Guide (1).pdf`): global Black–Scholes–Merton pricing parameters (valuation date/time, underlying price, continuously compounded dividend yield and interest rate, flat or per-leg volatility) plus an **ordered, unbounded list of legs** of type **Call, Put, or Stock (underlying)**—there is **no fixed leg-count limit**. The OSS workbook shows five leg rows for manual simulation; that is a spreadsheet layout constraint, not a system cap. A live strategy may **add legs over its lifecycle** (hedges, rolls, adjustments) until **successful trade closure**. Each leg has position size, expiration (options), strike (options), initial price, and optional per-leg contract multiplier and volatility override. Per-leg and portfolio-level **Price, Value, P/L, Delta, Gamma, Theta, Vega, and Rho** are computed by the pricing and Greeks engines using the same conventions as OSS.

**Third-party integrations** connect the bot to external systems required for strategy execution: **ICICI Direct Breeze API** for live marks and (later) orders, in-house **`paper_sim`** for paper rehearsal, and **live data feed URLs** bound to each strategy's underlying and instruments. All credentials and API keys remain server-side; integrations are configured at runtime via the backend API—not hard-coded.

The application is built as a **clearly separated frontend and backend**: the frontend provides monitoring, a **supervised decision queue** (Phase 3), recommendations, oversight, configuration, and the **RAG user chatbot** (`/chat`); the backend hosts the trading bot—all business logic, quantitative engines, RAG, market data ingestion, broker integration, and the continuous learning loop.

### 1.1 Implementation Status

| Area | Status |
|---|---|
| `architecture.md` v1.21 | Complete — authoritative technical reference; **§21 = paper-first roadmap** |
| `context.md` (this document) | Consolidated project context |
| `frontend/` scaffold | **In progress** — supervised cockpit, decisions queue, recommendations; chat UI planned (`Docs/UI_Dashboard.md`) |
| `backend/` scaffold | **In progress** — decisions API, recommendations API, bot status, supervision mode |
| `paper_sim` + ICICI Direct data-only | **Not started** — Phase 0–1 critical path |
| RAG ingestion pipeline (4 PDFs) | **Not started** — parallel Track B (does not block paper) |
| User chatbot (final UI) | **Not started** — Track B; needed before LLM-gated discretionary validation |
| Quant / execution / learning modules | **Not started** |

**Immediate priority:** Phase 0 — paper stack scaffold (ICICI Direct data-only marks + `paper_sim` + Railway/Vercel). See `architecture.md` §21.0–21.1. RAG chat is Track B, not the critical path.

### 1.2 Document Hierarchy

| Document | Role |
|---|---|
| **`architecture.md`** | Authoritative technical reference; **§21** is the build sequence; **§8.9 / §11** cover ICICI Direct Breeze API |
| **`context.md`** | Consolidated project context (this file) |
| **`Docs/Paper_Simulator.md`** | Paper rehearsal API & playbook behavior (Phase 0–1) |
| **Four RAG PDFs** | Authoritative RAG corpus (Track B) |
| **`Docs/Trading_Strategies.md`** | Strategy playbook (ops/UI); supervised-first execution assumptions — not primary RAG corpus |
| **`Docs/Trading_Parameters.md`** | Parameter catalog for OSS keys/thresholds — ops config, not RAG corpus |
| **`Docs/UI_Dashboard.md`** | Supervised cockpit UI specification (includes Ask AI → chat) |
| **`Docs/Problem_Statement.txt`** | Original academic scope; assistant/recommendation model — **superseded** by graduated bot; evolution summary in `architecture.md` **Appendix D** |
| **`DECISIONS.md`** | Living log of dated architectural decisions |

---

## 2. Problem Domain

### 2.1 Background

Volatility is one of the few market variables tradable **independently of price direction**. Professional quant firms and market makers exploit volatility inefficiencies through:

- Mathematical models
- Continuous portfolio rebalancing
- Option pricing theory
- Real-time market data

Retail traders face structural disadvantages:

| Constraint | Impact |
|---|---|
| Limited institutional-grade data | Weaker signal quality |
| Higher transaction costs | Erodes edge, especially for gamma scalping |
| Limited computational infrastructure | Cannot run HFT-style hedging |
| Lack of automated execution | Manual rebalancing lag |
| Manual portfolio management | Greeks drift between hedges |
| Inability to continuously hedge options | Gamma scalping profitability at risk |
| Limited access to quant research | Knowledge gap vs. institutions |

Advances in **AI, LLMs, RAG, algorithmic platforms, and broker APIs** create an opportunity to narrow this gap.

### 2.2 Core Problem

Develop a **continuously learning volatility trading bot** that identifies, evaluates, executes, manages, and adapts volatility-based trades at retail scale—using institutional-grade concepts without institutional infrastructure—and sustains a **high success ratio** through statistical rigor, AI-driven adaptation, and disciplined risk management. Discretionary entries follow **supervised → semi → autonomous**; Phase 3 starts with operator approval (`architecture.md` §6.2.2).

### 2.3 Bot Operating Model

The system runs as an **always-on trading agent** with the following lifecycle:

```
Observe (market data) → Analyze (quant + AI) → Decide (signal + sizing)
        → Approve (if SUPERVISION_MODE=supervised) → Execute (ICICI Direct / paper-sim)
        → Measure (P&L, win rate, Greeks) → Learn (update models & parameters)
        → Adapt (reweight strategies) → Observe ...
```

| Capability | Requirement |
|---|---|
| **Graduated supervision** | `SUPERVISION_MODE`: `supervised` (Phase 2 default on paper) → `semi_autonomous` → `fully_autonomous`; promote only after paper evidence (§6.2.2, §21) |
| **One trade at a time** | At most one pending or open discretionary entry per session (§20.4.11); mechanical hedges on existing positions exempt |
| **Graduated execution ramp** | `EXECUTION_MODE`: `shadow` (log only) → paper via **`paper_sim`** → `live` (ICICI Direct Breeze API); see §2.3.1 |
| **Continuous operation** | Runs on a schedule or event-driven loop during market hours |
| **Self-evaluation** | Tracks win rate, profit factor, Sharpe, drawdown after every trade and rolling window |
| **Self-adaptation** | Adjusts thresholds, pair selection, hedge frequency, and module weights based on outcomes (cannot auto-enable new modules) |
| **Human oversight** | Kill-switch, monitoring, configuration; per-trade approval in `supervised`; auto-pause on anomaly |

### 2.3.1 Execution Modes & Supervision Path

| `EXECUTION_MODE` | Broker submit | Purpose |
|---|---|---|
| **`shadow`** | No — log decisions and would-be ICICI Direct orders only | Validate full pipeline without capital risk (default at first deploy) |
| **`paper`** | No ICICI Direct sandbox — use in-house **`paper_sim`** (ICICI Direct marks + local fills) | Development and validation (MVP default after shadow week) |
| **`live`** | Yes — ICICI Direct Breeze API `place_order` | Real NSE / BSE / NFO capital (micro-size first) |

**`EXECUTION_MODE` promotion path (required sequence):**

| Stage | Requirement before advancing |
|---|---|
| Shadow → Paper-sim (single module) | ≥ 1 week shadow run; zero pipeline errors; operator review |
| Paper-sim (single module) → Paper-sim (multi-module) | ≥ **30 closed trades** per enabled module; risk gates passing |
| Paper-sim (multi-module) → Paper-sim soak | All Phase 2 modules enabled; integration health green |
| Paper-sim soak → Live | 2–4 week soak passes §2.5 metrics; chaos tests pass; micro-size + circuit breakers |

| `SUPERVISION_MODE` | Discretionary entries | Operator role |
|---|---|---|
| **`supervised`** (Phase 2 default on paper) | Queue for Approve / Reject; expired decisions do not auto-submit | Per-trade approval |
| **`semi_autonomous`** | Auto-submit when confidence ≥ threshold; else queue | Async review + override |
| **`fully_autonomous`** | Auto-submit when all gates pass; ranked fallback #1 → #2 → #3 (§6.4) | Monitor-only |

**`SUPERVISION_MODE` promotion path (after `EXECUTION_MODE=paper`):**

| Stage | Requirement before advancing |
|---|---|
| `supervised` → `semi_autonomous` | ≥ 30 closed supervised paper trades; metrics within §2.5 bands; checklist sign-off |
| `semi_autonomous` → `fully_autonomous` | ≥ 30 closed semi-auto trades; low override rate; soak without critical auto-pause |

**Build sequence (authoritative — `architecture.md` §21):** Phase 0 scaffold → Phase 1 `paper_sim` playbook → Phase 2 supervised → Phase 3 semi → Phase 4 full-auto soak → Phase 5 ICICI Direct live on GCP. RAG chatbot is parallel Track B.

**Mechanical hedges** (delta drift, stop-loss, circuit-breaker closes) are **always automated** in every supervision mode. Fail-safe: auto-pause, drawdown breach, or kill-switch **pauses** new discretionary entries until operator resume. Full specification: `architecture.md` §6.2.1, §6.2.2, §6.4, §20.4.4.

### 2.4 Retail Constraints (Design Requirements)

All modules must account for:

- Capital limitations
- Transaction costs, bid-ask spreads, slippage
- Margin requirements
- Market data quality and coverage depend on the supplied URL endpoints (may lack full depth/L2)
- Paper trading execution via broker APIs (no live capital during development and validation)
- Position sizing constraints

### 2.5 High Success Ratio Targets

The bot is engineered to achieve and maintain a **high success ratio** across all active strategies. Success is measured holistically—not by win rate alone.

| Metric | Target (Paper Trading Phase) | Purpose |
|---|---|---|
| **Win rate** | ≥ 60% on closed trades (rolling 30-day) | Trade-level success frequency |
| **Profit factor** | ≥ 1.5 (gross profit / gross loss) | Reward-to-risk at portfolio level |
| **Sharpe ratio** | ≥ 1.5 (annualized, rolling) | Risk-adjusted return quality |
| **Max drawdown** | ≤ 10% of paper-sim equity | Capital preservation |
| **Recovery factor** | Net profit / max drawdown ≥ 2.0 | Resilience after losses |

The continuous learning loop optimizes toward these targets. When metrics fall below thresholds, the bot **automatically reduces exposure, pauses underperforming strategies, and triggers re-optimization** before resuming full operation.

### 2.6 Third-Party Integrations & Paper Trading Execution

The bot **must integrate with necessary third-party applications** to run strategies end-to-end. Integrations are **pluggable adapters** in the backend—operators configure connections at runtime; strategy logic never embeds vendor-specific code.

| Integration Type | Purpose | Examples (initial build) |
|---|---|---|
| **Broker (Indian markets)** | Order submission, fill tracking, position and balance sync | **ICICI Direct Breeze API** (sole broker — NSE / BSE / NFO) |
| **Paper rehearsal** | Virtual fills + P&L without `place_order` | In-house **`backend/paper_sim/`** (ICICI Direct LTP marks + local ledger) — `Docs/Paper_Simulator.md` |
| **Live data feed (URL)** | Real-time and near-real-time quotes, option chains, vol surfaces | ICICI Direct market-data REST / WS; optional third-party REST/CSV |
| **LLM provider** | Signal validation, RAG reasoning, adaptation | **Groq API** (`llama-3.3-70b-versatile`) |
| **Vector store** | Knowledge retrieval, failure memory, trade insights | **ChromaDB** (embedded local / HTTP server production) |

**Paper trading execution** uses the in-house **paper-sim** path (ICICI Direct marks + local fills)—ICICI Direct has **no** first-class paper/sandbox API. The full lifecycle—signal → order → fill → P&L → learning—runs without live capital during development and validation. See `architecture.md` §11.7.

**Design implications:**

- All order routing goes through the **ICICI Direct broker adapter**; the frontend never holds broker credentials or calls Breeze API directly
- Paper-sim mirrors live behavior (multi-leg fills, positions, buying power) using simulated capital and configurable slippage
- After a Phase 1 paper entry, the bot may **auto-complete** its intended multi-leg opening structure **without additional consent**, subject to the same open-trade rules (₹1L trade / leg, freshness, lotsize, Part T) — see `Paper_Simulator.md` and `architecture.md` §11.7
- Each **OSS strategy** declares or inherits **data feed URL bindings** for its underlying and option legs; the bot refuses to trade if required feeds are stale or unavailable
- Promoting paper-sim → live is an **explicit step** on the ICICI Direct adapter path (`EXECUTION_MODE=live` + risk gates), not a flip of the paper ledger
- Pre-trade risk gates (Greeks limits, position size, drawdown, feed freshness, transaction cost gate) must pass before any order reaches a broker adapter
- Paper fills use **conservative mode** by default (slippage + spread penalty) — broker optimistic fills are dev-only (`architecture.md` §11.7)
- Integration health (feed latency, broker connectivity, auth expiry) is monitored and surfaced on the frontend dashboard

### 2.7 Live Market Data Feeds (URL-Based)

Market data is **not hard-coded or bundled**. Operators register **URL-based live data feeds** as configurable inputs. Each URL points to an external endpoint for one or more instruments or data types.

**Design implications:**

- Operators provide URLs for every instrument and series required by active strategies (spot quotes, option chains, historical OHLCV, vol surfaces, index/futures for hedging)
- The bot **fetches live data on a schedule** (poll interval per URL) and optionally supports push/streaming endpoints where the provider supports them
- Heterogeneous formats (JSON, CSV, broker-specific schemas) are parsed and normalized into a unified internal schema
- Multiple URLs may run concurrently across asset classes; each URL entry supports auth (API key header, OAuth token, query param) stored server-side
- Quantitative modules and OSS marking consume the **normalized market data layer**—never raw URLs directly
- Live feeds **override OSS defaults**: `und_price`, per-leg `price`, and per-leg IV from option chains refresh strategy marks and Greeks before signals and execution
- **NFO lot sizing overrides OSS Y8=`100`**: each option leg’s effective multiplier and quantity step come from ICICI Direct instrument-master `lotsize` for that contract (`nfo_lot_sizing`)
- Stale or failed feeds block autonomous execution for strategies that depend on them

**Strategy ↔ feed binding:** The recommendation engine’s feed-bound universe (G11–G12) is **all NSE F&O underlyings** from ICICI Direct `FONSEScripMaster.txt` (SecurityMaster.zip), each auto-bound to NSE spot quotes + NFO option chain. When an OSS strategy is saved, the operator may still link explicit URLs; defaults resolve through the ICICI Direct adapter. If the strategy includes **stock/underlying** legs, the underlying must be cash equity with spot ≤ **INR 1000** (e.g. `SBIN`). **Options-only** strategies have **no** underlying price cap. The bot resolves bindings at runtime and validates feed freshness before each decision cycle.

### 2.8 Trade Input — Option Strategy Simulator (OSS) Model

All option-based trades are defined using a **multi-leg strategy table** aligned with the **Macroption Option Strategy Simulator** (`Docs/OSS (1).xlsm`, `Docs/OSS_Guide (1).pdf`). This is a **first-class input** alongside market data URLs and PDF knowledge.

**Canonical reference:** OSS main sheet layout — Area 1 (parameters), Area 2 (position legs), Area 3 (valuation), Area 4 (Greeks), Area 5 (per-leg custom settings).

#### Global Market Parameters (OSS rows 3–4)

| Field | OSS Cell | Description | Example |
|---|---|---|---|
| **Valuation Date** | C3 | Date for pricing, P/L, and Greeks (IST calendar day) | 2024-01-04 |
| **Valuation Time** | C4 | Time component (intraday pricing, **IST**) | 10:35:00 |
| **Und Price** | G4 | Underlying spot; same units as strike | 85.40 |
| **Div Yield** | J3 | Annualized, **continuously compounded** (%) | 2.60% |
| **Int Rate** | J4 | Risk-free rate, **continuously compounded** (%); tenor ≈ option life | 4.00% |
| **Volatility** | O4 | Annualized standard deviation (%); used when flat vol is on | 28.40% |
| **Flat Volatility** | Q3 | When checked, one vol for all legs; when off, per-leg vol in column Q | On |
| **Display Mode** | L4 | Show Values & Greeks **per share** or **total** position | Total |

**Notes from OSS Guide:**

- Dividend yield also models convenience yield (commodities) or the foreign rate in forex options (Garman–Kohlhagen).
- Volatility is standard deviation, not variance; vega is per **one percentage point** change in σ.
- Days to expiry (column D) = positive difference between leg expiration datetime and valuation datetime.

#### Leg Inputs (unbounded — OSS rows 8–16 are reference layout)

**Leg count:** There is **no maximum** on legs per strategy. The OSS workbook exposes five leg rows for spreadsheet what-if; this bot persists legs as an **unbounded ordered list**. A strategy may open with any number of legs and **accumulate more** until **successful closure** (net flat or all legs expired/settled). Leg order does not affect calculations.

Each leg selects a **Type**: `stock`, `call`, or `put` (`none` reserved for OSS empty-slot parity only).

| Field | OSS Col | Applies To | Description | Example |
|---|---|---|---|---|
| **Position** | B | All | Signed contracts/shares (+ long, − short) | +5 / −500 |
| **Expiration** | C | Call, Put | From expiration catalog (datetime when trading stops) | 21 Jun 2024 |
| **Days to Expiry** | D | Call, Put | Computed; do not overwrite | 169.24 |
| **Strike** | E | Call, Put | Same units as underlying price | 75.00 |
| **Type** | F | All | `stock`, `call`, `put` (`none` = OSS empty slot only) | Put |
| **Initial Price** | G | All | Entry price per share/unit; positive sign; may be empty for what-if | 3.60 |
| **Per-Leg Volatility** | Q | Call, Put | Override when flat vol is off | 28.4% |
| **Contract Multiplier** | S | All | Override; empty uses **NFO instrument `lotsize`** (India), never OSS US 100 | e.g. 65 |
| **Share Equivalent** | T | All | `position × effective_multiplier` (computed) | lots × lotsize |
| **Leg Name** | V | All | Display label, e.g. `+5 21Jun 75P` (computed) | +5 21Jun 75P |

**Stock legs** (covered calls, protective puts, delta hedges): no strike or expiration; position is shares (or contracts × multiplier for futures). Delta = +1 (long) or −1 (short); gamma, theta, vega, rho = 0.

**Contract multiplier:** resolve each option leg from ICICI Direct instrument-master **`lotsize`** for that NFO contract (per equity symbol). Do **not** copy the OSS workbook default of **100**. Stock legs use **1**. Per-leg override in column S when legs mix asset types. See `trading_parameters.defaults.json` → `nfo_lot_sizing`. If the strategy includes stock/underlying legs, the underlying must also satisfy spot ≤ INR 1000; options-only has no spot cap.

**Initial cash flow** (column H — computed):

```
initial_cf = −position × initial_price × effective_contract_multiplier
```

Negative = cash outflow (typical long premium); positive = cash inflow (typical short premium). Empty initial price ⇒ zero initial CF; P/L then equals position value.

#### Per-Leg & Strategy Outputs (computed — OSS columns I–P, row 18 totals)

| Column | Per Leg | Strategy Total (row 18) |
|---|---|---|
| **Price** (I) | Mark per share; stock = underlying price | — |
| **Value** (J) | `position × price × multiplier` | Sum of leg values |
| **P/L** (K) | `initial_cf + value` | Sum of leg P/L |
| **Delta** (L) | $ change per $1 underlying move | Sum |
| **Gamma** (M) | Δ change per $1 underlying move | Sum |
| **Theta** (N) | Price change per **one calendar day** | Sum |
| **Vega** (O) | Price change per **1 vol point** (1% σ) | Sum |
| **Rho** (P) | Price change per **1 rate point** (1% r) | Sum |

**Display mode:** In per-share mode, row 18 sums per-share figures (can mislead when leg sizes differ — prefer Total mode for mixed sizes). Price (column I) is always per share.

#### Expiration Catalog (OSS "Expirations" sheet)

Up to **24** expiration datetimes with configurable display formats. Each entry stores the **effective expiration** — when options stop trading / settlement is fixed — not necessarily the exchange label date. Intraday time is required (e.g. NFO weekly/monthly expiry settlement, converted to IST / operator timezone).

#### Pricing Model (OSS §8–9)

- **Model:** Black–Scholes–Merton (Merton 1973 dividend extension); European exercise assumption.
- **Formulas:** Standard `d₁`, `d₂`, call/put prices with `N(·)`; Greeks per OSS Guide chapter 9.
- **Expired legs:** Greeks = 0 when valuation datetime ≥ expiration datetime.

#### Reference Example — Iron Condor (from `OSS (1).xlsm`)

Global: `und_price = 85.40`, `div_yield = 2.6%`, `int_rate = 4.0%`, `volatility = 28.4%`, valuation **2024-01-04 10:35 IST** (`2024-01-04T10:35:00+05:30`; matches `OSS (1).xlsm` C3/C4).

| | Leg 1 (Put) | Leg 2 (Put) | Leg 3 (Call) | Leg 4 (Call) | **Total** |
|---|---|---|---|---|---|
| Position | +5 | −5 | −5 | +5 | — |
| Strike | 75 | 80 | 90 | 95 | — |
| Initial CF | −1,800 | +2,825 | +3,400 | −2,575 | **+1,850** |
| P/L | — | — | — | — | **+258.34** |
| Delta | — | — | — | — | **+0.81** |
| Gamma | — | — | — | — | **−2.93** |
| Theta | — | — | — | — | **+2.19** |
| Vega | — | — | — | — | **−28.18** |

#### Scenario Analysis (OSS chart — optional UI)

OSS supports parameter sweeps (underlying, vol, time, div yield, rate) with break-even, max-profit, and max-loss key points. The bot backend may expose `POST /api/v1/strategies/{id}/simulate` for pre-trade scenario checks; chart UI is optional in v1.

**Design implications:**

- Frontend **Option Strategy Simulator** mirrors OSS Areas 1–5 (yellow inputs, green outputs, grey labels) with **dynamic leg rows** (add/remove, no fixed cap)
- Backend `quant/pricing/` implements BSM per OSS formulas; `quant/greeks/` matches OSS Greek conventions
- `expiration_dates` catalog persisted separately; legs reference catalog IDs
- Risk gates enforce limits on **portfolio totals** (`total_delta`, `total_gamma`, `total_vega`, `total_theta`)
- Order builder expands legs (including stock hedges) into broker orders
- Gamma and vega modules consume leg-level and aggregate Greeks
- Live market data may override `und_price`, per-leg marks, and per-leg IV (disabling flat vol when chain IV available)

---

## 3. System Objectives

### 3.1 A. Knowledge Management (RAG Layer)

Process **four PDF resources** through a RAG pipeline (`architecture.md` §3.2, §7):

| # | Document | Path |
|---|---|---|
| 1 | **Volatility Trading** | `Docs/Volatility Trading.pdf` |
| 2 | **Gamma Scalping** | `Docs/Gamma Scalping.pdf` |
| 3 | **Vega Scalping** | `Docs/Vega Scalping.pdf` |
| 4 | **Trading Strategies** | `Docs/Trading_Strategies.pdf` |

The knowledge system must:

- Extract concepts and preserve mathematical formulas
- Index definitions and store trading methodologies
- Build semantic relationships across documents
- Retrieve relevant content during autonomous decision-making and the **user chatbot**

**User chatbot (final UI):** A permanent frontend surface at `/chat` that answers operator/trader questions with citations from the four PDFs. Also reachable via **Ask AI** on supervised decision cards. Chat explains and educates only—it never submits orders (`architecture.md` §7.7).

`Docs/Trading_Strategies.md` and `Docs/Trading_Parameters.md` remain operational references for bot config and OSS keys; they are **not** the primary RAG corpus.
### 3.2 B. Statistical Arbitrage Module

Quantitative capabilities:

- Cointegration testing
- Pair selection and risk-adjusted pair ranking
- Mean reversion analysis
- Spread construction
- Z-score calculation
- Entry and exit signal generation
- Position sizing

**Goal:** Identify statistically significant market inefficiencies suitable for retail-scale execution.

### 3.3 C. Volatility Analysis Module

Estimate and analyze:

- Historical Volatility (HV)
- Realized Volatility (RV)
- Implied Volatility (IV)
- Forward Volatility
- Volatility Term Structure
- Volatility Smile and Skew
- Volatility Surface

**Goal:** Classify options as underpriced, fairly priced, or overpriced relative to expected future volatility.

### 3.4 D. Gamma Scalping Module

Framework capabilities:

- Delta and Gamma calculation
- Dynamic hedge ratio computation
- Rebalancing frequency optimization
- Hedge cost estimation
- Theta decay analysis
- Profitability estimation (gamma gains vs. theta losses vs. transaction costs)
- **Hedge frequency optimizer** — minimum rebalancing interval where gamma P&L exceeds theta + costs (`architecture.md` §9.4)

**Goal:** Determine optimal hedging intervals and net profitability after retail transaction costs.

### 3.5 E. Vega Trading Module

Evaluate:

- Vega exposure
- IV expansion and contraction
- Event-driven volatility (earnings, macro events)
- Vega-neutral positioning

**Goal:** Exploit implied volatility changes while minimizing directional risk.

### 3.6 F. AI Decision Engine

**Quant leads; Groq validates.** Quant modules generate signals; rule-based fast paths handle mechanical hedges (delta drift, stop-loss). Groq (via Groq API) validates discretionary entries and produces audit explanations.

The LLM:

- Validates and ranks discretionary trading signals across strategy modules
- Interprets market conditions and volatility regimes in real time
- Validates trade decisions against RAG-retrieved domain knowledge (faithfulness ≥ 0.85 on golden eval set)
- Gates low-confidence discretionary trades—only high-conviction signals proceed; `/recommendations` surfaces only post-learning confidence ≥ **85%**
- Explains every decision for audit and frontend display (approval packet or autonomous log)
- Defers to quant + cost gate when LLM disagrees on mechanical hedges (`architecture.md` §10.6)

**Role:** Validation and explainability layer with RAG-grounded reasoning—not sole decision authority.

### 3.7 G. Risk Management

Comprehensive procedures:

- Portfolio Greeks (Delta, Gamma, Vega, Theta, **Rho**) — per-leg and strategy totals
- Position limits and stop-loss framework
- Maximum drawdown control
- Portfolio diversification
- Correlation monitoring

### 3.8 H. Third-Party Integrations — Live Data & Paper Execution

Integrate with **third-party applications** required for autonomous strategy execution:

**Live data feeds (URL-based):**

- Register data feed URLs per instrument and data type (quotes, option chains, OHLCV, vol surfaces)
- Fetch live/near-live data on configurable intervals during market hours
- Bind feed URLs to OSS strategies; refresh trade-input marks (`und_price`, leg prices, IV) from feeds
- Block or pause trading when bound feeds are stale, unavailable, or fail validation

**Paper rehearsal (execution):**

- Fill, modify, and close paper positions via **`paper_sim`** subject to `SUPERVISION_MODE` (§2.3.1) — ICICI Direct marks only; no `place_order`
- In `supervised`: wait for operator Approve before paper-sim submit
- In `fully_autonomous`: ranked recommendation fallback on the recommendations screen (#1 → #2 → #3)
- Track order status, fills, and open positions in the local paper ledger
- Sync virtual cash, equity, and holdings from **`paper_sim`** account state
- Auto-hedge gamma and delta exposure per strategy rules (mechanical path — all modes)
- Log all execution events for the learning loop and audit trail
- Enforce pre-trade risk checks before every paper order
- Pause discretionary execution when kill-switch is triggered, health metrics breach limits, or integrations are unhealthy

**Goal:** Observe → decide → (approve if needed) → execute loop on **`paper_sim`**, powered by live ICICI Direct marks / normalized feeds, feeding outcomes into the continuous learning loop before any ICICI Direct live submit.

### 3.9 I. Continuous Learning & Adaptation Engine

The bot must **learn from every trade** and adapt its behavior without manual reconfiguration.

**Learning inputs:**

- Trade outcomes (win/loss, P&L, slippage, fill quality)
- Rolling performance metrics (win rate, Sharpe, drawdown, profit factor)
- Market regime labels (low-vol, high-vol, trending, mean-reverting)
- Strategy module attribution (which module generated each signal and its hit rate)
- RAG-retrieved post-trade analysis (domain knowledge on what went wrong/right)

**Adaptation actions:**

| Trigger | Adaptation |
|---|---|
| Win rate drops below threshold | Tighten entry filters; increase signal confidence minimum |
| Drawdown exceeds limit | Reduce position sizes; pause highest-risk strategies |
| Cointegration breakdown detected | Remove pair from active universe; re-run pair selection |
| Vol regime shift | Reweight gamma vs. vega vs. stat arb module allocation |
| Hedge cost exceeds gamma profit | Adjust rebalancing frequency dynamically |
| Strategy module consistently underperforms | Lower its weight; promote better-performing modules |
| New market pattern identified | Update feature weights; store insight in knowledge base |

**Learning mechanisms:**

- **Walk-forward validation** — every parameter change validated on out-of-sample windows before deployment (not in-sample only)
- **Online performance tracking** — exponential moving averages of key metrics per strategy
- **Parameter optimization** — grid/Bayesian search (Optuna) on thresholds; min **30 closed trades** before tuning
- **Module weighting** — dynamic allocation across stat arb, gamma, vega based on recent Sharpe contribution
- **Failure memory** — losing trade contexts stored in ChromaDB `failure_memory`; retrieved pre-trade for discretionary entries (`architecture.md` §12.6)
- **Regime classifier** — **rule-based initially** (VIX percentile, HV/IV ratio, trend); ML/HMM in Phase 4
- **Adaptation guards** — max 20% parameter change per cycle; 24h cooldown; auto-rollback if metrics worsen (`architecture.md` §12.5)

**Goal:** Closed-loop system that improves success ratio over time without human intervention.

---

## 4. Research Questions

| # | Question |
|---|---|
| 1 | Can Statistical Arbitrage be effectively adapted for retail trading despite data and execution limitations? |
| 2 | Can Gamma Scalping remain profitable after transaction costs and manual hedging? |
| 3 | Under what market conditions does Vega Trading provide consistent risk-adjusted returns? |
| 4 | Can graduated AI decision-making (supervised → semi → autonomous) and continuous learning improve success ratio over static strategies? |
| 5 | How accurately can a RAG-based knowledge system retrieve quantitative trading concepts from domain-specific literature? |
| 6 | Can an integrated framework combining Statistical Arbitrage, Gamma Scalping, and Vega Trading outperform standalone approaches? |
| 7 | What adaptation mechanisms (parameter tuning, module reweighting, regime switching) most effectively sustain a high win rate? |
| 8 | Can the bot autonomously recover performance after drawdowns through self-adaptation without manual intervention? |

---

## 5. System Architecture

### 5.1 High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           FRONTEND (UI)                                 │
│  Bot Monitor · Decision Queue · Live P&L · Positions · Recommendations · Kill Switch · Config   │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │  REST / WebSocket API
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    BACKEND — TRADING BOT (graduated supervision)        │
│                                                                         │
│  Knowledge docs ──► RAG Pipeline ──► LLM Reasoning Engine               │
│  Live Data Feed URLs ──► Poll/Stream ──► Normalized Data Store          │
│       │ bind to OSS strategies → refresh trade-input marks              │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  Quantitative Engine + OSS Marking (live und_price, leg marks)  │   │
│  │  Stat Arb · Volatility · Gamma · Vega · Greeks · Risk Mgmt     │   │
│  └──────────────────────────────┬──────────────────────────────────┘   │
│                                 ▼                                       │
│         Decision Engine (AI + Signal Fusion + SUPERVISION_MODE)         │
│                                 │                                       │
│                                 ▼                                       │
│   Feed Freshness → Risk Gate → Approve/Queue/Auto-submit → Broker       │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
                    Third-Party Paper Trading Broker API
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              CONTINUOUS LEARNING & ADAPTATION LOOP                      │
│                                                                         │
│  Trade Outcomes → Performance Metrics → Regime Detection                │
│        → Parameter Optimization → Module Reweighting → Strategy Update  │
│        → Validated Config Deployed → Bot resumes with improved params   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Frontend / Backend Separation

The system is split into two clearly defined tiers with a strict responsibility boundary.

#### Frontend

The **frontend** is the trader-facing presentation layer. It contains no business logic, quantitative computation, or direct broker credentials.

| Responsibility | Details |
|---|---|
| **Dashboards** | Bot status, live P&L, win rate, Sharpe, drawdown, volatility regime, `EXECUTION_MODE` + `SUPERVISION_MODE` |
| **Decision queue** | Pre-approval packets; Approve / Reject / Ask AI (`supervised` primary — `Docs/UI_Dashboard.md`) |
| **Strategy views** | Active signals, module weights, adaptation history, **option strategy legs and Greeks table**, stat arb / gamma / vega exposure |
| **Bot monitoring** | Trade log, fill history, open positions, decision explanations, one-trade lock status |
| **Recommendations** | Top-3 ranked instruments with post-learning confidence ≥ **85%**; same-cycle auto-execute only when `fully_autonomous` (§6.4) |
| **Controls** | Kill-switch (pause bot), strategy enable/disable, risk limit overrides, supervision promotion, paper-sim account config |
| **AI assistant (user chatbot)** | Permanent `/chat` UI for RAG-powered Q&A over the four PDFs; on-demand trade/decision explanations; **Ask AI** from decision cards |
| **Configuration** | Live data feed URL registry, **strategy ↔ feed bindings**, **option strategy trade inputs**, **broker / third-party connection config**, learning parameters, success-ratio thresholds |

**Communicates with backend exclusively via:** REST API (CRUD, commands) and WebSocket (real-time quotes, order updates, alerts).

#### Backend

The **backend** is the single source of truth for all application logic, data, and external integrations.

| Responsibility | Details |
|---|---|
| **API layer** | REST + WebSocket endpoints consumed by the frontend |
| **RAG & LLM** | PDF ingestion, retrieval, reasoning, response generation |
| **Market data** | URL registry, **live feed fetch** (poll/stream), parse, normalize, cache, freshness checks, **strategy feed binding** |
| **Integrations** | Pluggable adapters for **ICICI Direct** (marks + live orders), **`paper_sim`**, data providers; credential vault; health monitoring |
| **Quantitative engine** | All strategy modules, signal generation, Greeks, risk checks |
| **Decision engine** | Signal fusion, rule fast path (hedges), Groq validation, confidence scoring, supervision routing (§6.2.2) |
| **Order management** | Build orders from bot signals, one-trade scope gate (§20.4.11), pre-trade risk gates, route to paper-sim or ICICI Direct |
| **Trade executor** | Approve path (`supervised`); high-confidence auto-submit (`semi_autonomous`); ranked fallback (`fully_autonomous`, §6.4) |
| **Broker adapter** | ICICI Direct Breeze API auth, live submit/cancel, poll/sync positions; paper path stays in `paper_sim` |
| **Learning engine** | Performance tracking, parameter optimization, module reweighting, regime adaptation |
| **Bot scheduler** | Market-hours loop: observe → analyze → decide → execute → learn |
| **Persistence** | Trade logs, configuration, analytics history, vector store |
| **Auth & secrets** | Broker API keys and credentials stored server-side only |

**The frontend never:**
- Holds broker API keys or credentials
- Performs quantitative calculations
- Calls broker APIs directly

### 5.3 Layer Breakdown

| Layer | Tier | Components | Output |
|---|---|---|---|
| **Presentation** | Frontend | Dashboards, recommendations, charts, **user chatbot**, config screens | User interactions, display |
| **API** | Backend | REST endpoints, WebSocket channels, request validation | Structured JSON responses, real-time events |
| **Knowledge** | Backend | PDF ingestion, OCR, chunking, embeddings, vector DB, semantic search, RAG | Retrieved context with citations |
| **Market Data** | Backend | URL configuration, HTTP fetch, parsing, validation, normalization, instrument mapping | Time-series and cross-sectional data |
| **Trade Input** | Backend + Frontend | Option strategy simulator: global params, multi-leg definitions, pricing, Greeks aggregation | Strategy objects with per-leg and total metrics |
| **Quantitative** | Backend | Cointegration, mean reversion, vol forecasting, Greeks, option pricing, signals, portfolio optimization | Numerical signals and metrics |
| **AI** | Backend | Groq signal validation, regime interpretation, RAG-grounded explanations | Validated trade decisions with confidence scores |
| **Execution** | Backend | Order builder, supervision routing, pre-trade risk checks, paper-sim / ICICI Direct adapter, fill tracking, position sync | Paper fills via `paper_sim`; live via ICICI Direct (approve or auto-submit by mode) |
| **Learning** | Backend | Outcome tracking, metric computation, parameter optimization, module reweighting, regime switching, failure memory | Updated strategy config deployed to bot |
| **Analytics** | Backend | Win rate, profit factor, Sharpe, drawdown, execution quality, per-module attribution | Performance reports and learning triggers |

### 5.4 Live Market Data Feeds & URL Registry

Live market data enters the system through **operator-configured URL endpoints**. This is a first-class input channel alongside OSS trade inputs and the PDF knowledge base.

**Supported input model:**

| Aspect | Specification |
|---|---|
| **Input type** | One or more URLs per instrument, data type, or feed provider |
| **Fetch mode** | Scheduled poll (`refresh_interval_sec`); streaming/WebSocket where supported |
| **Instruments** | Equities, options, indices, futures, and other instruments available from registered endpoints |
| **Configuration** | URLs registered via API/UI (not embedded in strategy code); auth credentials server-side |
| **Strategy binding** | Each OSS strategy links to required feed URLs (underlying quote, option chain, etc.) |
| **Output** | Normalized structures (quotes, OHLCV, option chains, IV surfaces) consumed by quant modules and OSS marking |

**Responsibilities of the market data layer:**

1. Accept and store URL mappings (instrument ↔ endpoint ↔ auth)
2. **Fetch live data** from external URLs on schedule with retries, backoff, and rate-limit handling
3. Parse heterogeneous response formats into a unified internal schema
4. Validate completeness, timestamps, and instrument identifiers; **reject stale data**
5. Expose normalized snapshots to stat arb, volatility, gamma, vega, Greeks, risk, and **OSS trade-input marking**
6. Report feed health (last success, latency, error count) to the bot scheduler and frontend
7. **Record normalized snapshots to Parquet** for replay testing and walk-forward backtests (`architecture.md` §8.7)
8. Validate every fetch with **JSON Schema** per `data_type`; enforce **SSRF protections** (domain allowlist, block private IPs)

**Feed adapters** (`backend/market_data/adapters/`): pluggable parsers (ICICI Direct, generic JSON, CSV) implementing a common `FeedAdapter` contract.

**Replay mode:** deterministic bot runs from recorded Parquet snapshots — enables offline CI and backtests without live market hours.

**Example URL registry configuration:**

```json
{
  "feeds": [
    {
      "feed_id": "feed_sbin_spot",
      "symbol": "SBIN",
      "asset_class": "Equity",
      "data_type": "quote",
      "url": "https://api.icicidirect.com/breezeapi/api/v1/quotes",
      "format": "json",
      "refresh_interval_sec": 15,
      "auth": { "type": "bearer", "credential_ref": "icici_direct_breeze" }
    },
    {
      "feed_id": "feed_sbin_chain",
      "symbol": "SBIN",
      "asset_class": "Equity Options",
      "data_type": "option_chain",
      "url": "https://api.icicidirect.com/breezeapi/api/v1/quotes",
      "format": "json",
      "refresh_interval_sec": 60,
      "auth": { "type": "bearer", "credential_ref": "icici_direct_breeze" }
    }
  ]
}
```

Register feeds for the underlyings the strategy will trade. **Default universe:** every NSE F&O underlying on ICICI Direct (`FONSEScripMaster.txt`) with G12 bindings `icici_direct:NSE:{symbol}:quotes` and `icici_direct:NFO:{stock_code}:option_chain`. For **options+underlying** structures, use cash-equity underlyings with spot ≤ INR 1000. For **options-only**, there is no underlying price cap.

**Example strategy ↔ feed binding:**

```json
{
  "strategy_id": "strat_001",
  "underlying_symbol": "SBIN",
  "data_feed_bindings": {
    "und_price": "icici_direct:NSE:SBIN:quotes",
    "option_chain": "icici_direct:NFO:STABAN:option_chain"
  }
}
```

### 5.6 Trade Input & Option Strategy Model

Option-based trades use the **Macroption OSS** input table (see §2.8). The data model has four layers:

```
Global Params (Valuation Date/Time, Und Price, Div Yield, Int Rate, Volatility, Flat Vol, Display Mode)
        │
        ▼
Expiration Catalog (up to 24 effective expiration datetimes — optional shared config)
        │
        ▼
Legs (unbounded list — Position · Expiration · Strike · Type [stock|call|put] · Initial Price · Per-Leg Vol · Contract Multiplier)
        │
        ▼
Computed (per-leg: Price, Value, P/L, Δ, Γ, Θ, ν, ρ; leg name; share equivalent)
        │
        ▼
Strategy Totals (Total CF, Value, P/L, ΣΔ, ΣΓ, ΣΘ, Σν, Σρ)
```

**Backend modules:**

| Module | Path | Role |
|---|---|---|
| Strategy model | `backend/quant/strategy/` | Unbounded leg list, type validation, aggregation, leg naming; legs may be added until trade closure |
| Expiration catalog | `backend/quant/strategy/expirations.py` | CRUD for effective expiration datetimes |
| Pricing | `backend/quant/pricing/` | BSM (Merton) mark-to-market, initial CF |
| Greeks | `backend/quant/greeks/` | Per-leg and total sensitivities (OSS conventions) |
| Simulation | `backend/quant/pricing/simulate.py` | Parameter sweeps, break-even / extrema (optional) |

**OSS parity:** `backend/tests/quant/test_oss_parity.py` validates BSM/Greeks against OSS workbook fixtures — CI gate on every push (`architecture.md` §8.5.12).

**Frontend:** Option Strategy Simulator screen mirroring OSS Areas 1–5 — global params row, **dynamic leg table** (add/remove rows, no fixed cap), per-leg custom settings (vol override, contract multiplier), computed valuation/Greeks columns, totals row, and optional scenario chart. Supports lifecycle adjustments until trade closure.

### 5.7 ICICI Direct Integration & Paper Simulator

The backend integrates with **ICICI Direct Breeze API** for NSE / BSE / NFO marks and (later) live orders. Paper rehearsal uses in-house **`paper_sim`** — not a broker sandbox. Adding another broker would mean a new adapter—no changes to quant or strategy logic—but this project is ICICI Direct only.

**Discretionary execution flow:**

```
Bot Scheduler: new market tick / interval
        │
        ▼
Feed Health Check: bound URLs fresh? ──no──► Skip strategy / alert
        │ yes
        ▼
Quant Engine: signal + cost gate (§9.4 architecture)
        │
        ▼
Decision: rule fast path (hedge) OR Groq validator (discretionary)
        │
        ▼
Pre-trade risk checks (Greeks limits, position size, drawdown, feed freshness, one-trade scope §20.4.11)
        │
        ▼
SUPERVISION_MODE (§6.2.2):
        ├─ supervised → decisions.pending → operator Approve / Reject
        ├─ semi_autonomous → auto-submit if confidence ≥ threshold; else queue
        └─ fully_autonomous → auto-submit; ranked fallback #1 → #2 → #3 (§6.4)
        │
        ▼
Submit path by EXECUTION_MODE:
        ├─ paper → paper_sim PaperLedger (ICICI Direct LTP ± slippage; no place_order)
        └─ live  → IciciDirectBrokerAdapter → Breeze place_order
        │
        ▼
Backend: sync position, update P&L, log outcome, emit WebSocket event
        │
        ▼
Learning Engine: update metrics → adapt if thresholds breached
```

**Broker / paper-sim responsibilities:**

| Function | Description |
|---|---|
| **Authentication** | Manage ICICI Direct API keys/tokens; refresh sessions |
| **Paper fills** | Multi-leg paper orders into local ledger at ICICI Direct LTP ± slippage |
| **Live order submission** | Market, limit, stop, and multi-leg orders via Breeze API when `EXECUTION_MODE=live` |
| **Order lifecycle** | Track pending → filled → cancelled/rejected states |
| **Position sync** | paper-sim local ledger, or poll/stream ICICI Direct positions when live |
| **Error handling** | Retry transient failures; surface rejections to frontend |
| **Abstraction** | Unified internal order/position schema independent of broker-specific formats |

**Paper trading constraints:**

- All execution during development and validation uses **paper-sim** (no ICICI Direct `place_order`) or **`shadow`** dry-run logs
- Default fill mode: **`paper_conservative`** — slippage + half-spread penalty on every fill (`architecture.md` §11.7)
- Optimistic mid fills (`paper_optimistic`) are dev-only; not used for success-ratio validation
- ICICI Direct is the sole broker; API specifics live in `backend/integrations/icici_direct/` (`architecture.md` §8.9, §11.8–11.15)

**Sole broker: ICICI Direct Breeze API** — Indian markets only (NSE / BSE / NFO). No US brokers. Paper rehearsal via `paper_sim` + adapter `shadow`; live via Breeze API.

| Provider | Paper / sandbox API | Data URLs | Role |
|---|---|---|---|
| **ICICI Direct** | **No** — use `paper_sim` + `shadow` | Yes (Breeze API REST / WS) | **Sole broker** |

**Integration requirements for the ICICI Direct broker adapter:**

- Server-side credential storage and daily session refresh (`API_Session` → `session_token`)
- Unified internal order/position schema independent of Breeze API payload format
- Idempotent order submission with client order IDs
- Position reconciliation loop (broker state vs. internal state)
- Graceful degradation when Breeze API is unavailable (pause bot, alert operator)

### 5.8 Continuous Learning Loop (Architecture)

The learning loop runs continuously alongside the trading bot, forming a **closed feedback system**.

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│ Trade        │────►│ Performance      │────►│ Threshold Check     │
│ Outcomes     │     │ Metrics Engine   │     │ (win rate, Sharpe,  │
└──────────────┘     └──────────────────┘     │  drawdown, etc.)    │
                                               └──────────┬──────────┘
                                                          │
                    ┌─────────────────────────────────────┘
                    │ metrics below target?
                    ▼
         ┌──────────────────────┐
         │ Adaptation Engine    │
         │ · param optimization │
         │ · module reweighting │
         │ · regime switch      │
         │ · pair universe refresh│
         │ · hedge freq adjust  │
         └──────────┬───────────┘
                    │
                    ▼
         ┌──────────────────────┐
         │ Walk-Forward         │
         │ Backtest Validation  │
         └──────────┬───────────┘
                    │ passes?
                    ▼
         ┌──────────────────────┐
         │ Deploy Updated Config│──────► Bot resumes with improved parameters
         └──────────────────────┘
```

**Bot scheduler modes:**

| Mode | Behavior |
|---|---|
| **Active** | Full trading loop during market hours; discretionary path follows `SUPERVISION_MODE` (§6.2.2); one trade at a time (§20.4.11) |
| **Learning** | Paused trading; running optimization and backtest validation |
| **Reduced exposure** | Trading at lower size after metric breach; recovering |
| **Paused** | Kill-switch active; no new orders; existing positions managed |

---

## 6. Strategy Ingestion Pipeline (RAG Architecture)

> The quality of the RAG system depends primarily on the **ingestion pipeline**, not the LLM. Trading books contain equations, tables, Greeks, diagrams, and domain terminology that must be preserved accurately. Full specification: `architecture.md` §7. User chatbot: `architecture.md` §7.7.

### 6.0 RAG Corpus (Authoritative)

| Document ID | File |
|---|---|
| `doc-vol-trading` | `Docs/Volatility Trading.pdf` |
| `doc-gamma` | `Docs/Gamma Scalping.pdf` |
| `doc-vega` | `Docs/Vega Scalping.pdf` |
| `doc-trading-strategies` | `Docs/Trading_Strategies.pdf` |

### 6.1 Pipeline Stages

```
PDF Documents (4 RAG sources)
      │
      ▼
PDF Extraction Engine
      │
      ▼
Document Normalization
      │
      ▼
Mathematical Formula Detection
      │
      ▼
Table & Figure Extraction
      │
      ▼
Semantic Document Chunking
      │
      ▼
Metadata Enrichment Pipeline
      │
      ▼
Embedding Generation
      │
      ▼
Vector Database
      │
      ▼
Hybrid Search (Dense + BM25)
      │
      ▼
Context Re-ranking
      │
      ▼
LLM Reasoning Engine (Groq)
      │
      ├──► User Chatbot (frontend /chat)
      └──► AI Decision Engine (trade validation)
```

### 6.2 Stage-by-Stage Specification

#### Stage 1: PDF Collection

- Assign each of the four PDFs a **unique identifier and version** for update tracking (`doc-vol-trading`, `doc-gamma`, `doc-vega`, `doc-trading-strategies`).
#### Stage 2: PDF Extraction

Preserve structure: headings, equations, tables, lists.

| Library | Strength |
|---|---|
| PyMuPDF (fitz) | Fast text extraction |
| pdfplumber | Table extraction |
| Unstructured | Mixed document layouts |
| Docling | AI-ready document parsing |
| Tesseract OCR | Scanned/image pages only |

Extract: titles, section headings, paragraphs, tables, equations, figure captions, page numbers.

#### Stage 3: Document Cleaning

- Remove headers/footers and repeated page numbers
- Fix broken line wraps
- **Preserve mathematical notation**
- Remove duplicate whitespace

#### Stage 4: Structural Parsing

Build document hierarchy: Chapter → Section → Subsection → Paragraph.

Store metadata: chapter, section, page, document title.

#### Stage 5: Semantic Chunking

- **Avoid fixed-size chunks**; split by meaning (definitions, derivations, examples)
- Target: **400–800 tokens** per chunk
- **10–20% overlap** between adjacent chunks

#### Stage 6: Metadata Enrichment

Each chunk carries rich, filterable metadata:

```json
{
  "document": "Gamma Scalping",
  "chapter": "Chapter 5",
  "section": "Dynamic Hedging",
  "page": 132,
  "topic": "Gamma",
  "difficulty": "Advanced",
  "greeks": ["Delta", "Gamma"],
  "asset_class": "Options",
  "strategy": "Gamma Scalping"
}
```

**Trading-specific enrichment fields:**

| Field | Example Values |
|---|---|
| Strategy | Statistical Arbitrage, Gamma Scalping, Vega Scalping, Volatility Trading |
| Concepts | Delta, Gamma, Vega, Theta, IV, HV, Cointegration, Z-score |
| Asset Class | Equity Options, Index Options, Futures |
| Mathematical Models | Black–Scholes, Ornstein–Uhlenbeck, Mean Reversion |
| Risk Category | Model Risk, Liquidity Risk, Execution Risk, Volatility Risk |
| Difficulty | Beginner, Intermediate, Advanced |

#### Stage 7: Embedding Generation

**Pinned production stack** (`architecture.md` §7):

| Role | Model |
|---|---|
| Embedding (primary) | **`bge-m3`** |
| Re-ranker | **`bge-reranker-large`** |
| Embedding (fallback) | `bge-large-en-v1.5` |

Do not use small/base BGE variants for this technical corpus.

#### Stage 8: Vector Database

**ChromaDB** is the sole vector store across all environments:

| Environment | Mode |
|---|---|
| Local development | Embedded `PersistentClient` (`CHROMA_PERSIST_DIRECTORY`) |
| Production / staging | Chroma HTTP on GCE persistent disk, Cloud Run + Filestore, or Chroma Cloud |

**Collections:** `knowledge_base`, `failure_memory`, `trade_insights`

**Hybrid retrieval:** Chroma dense search + application-layer BM25 (`rank_bm25`), fused via RRF; BM25 index rebuilt atomically after each ingest.

#### Stage 9: Hybrid Retrieval

Combine:

- **Semantic (vector) search** — conceptual similarity
- **Keyword (BM25) search** — exact term matching (e.g., "theta decay", "z-score")

#### Stage 10: Re-ranking

```
User Question → Top 50 Retrieved Chunks → Re-ranker → Top 5 Chunks → LLM
```

Use cross-encoder re-rankers (e.g., **bge-reranker-large**) for relevance scoring.

#### Stage 11: Prompt Construction

Include in every prompt:

- User question
- Retrieved context with citations (document, chapter, page, section)
- Structured context blocks per chunk

#### Stage 12: LLM Reasoning

The LLM must:

- Use only retrieved context where appropriate
- Explain equations clearly
- Compare concepts across documents
- Cite source document and page
- State when information is unavailable (no hallucination)

#### Stage 13: Response Generation

High-quality answers include:

- Direct answer
- Mathematical explanation (when relevant)
- Practical trading implications
- Risks and assumptions
- Source citations

#### Stage 14: Evaluation

| Metric | Purpose | CI Gate |
|---|---|---|
| Context Precision | Retrieved chunks are relevant | ≥ 0.80 |
| Context Recall | Important chunks are not missed | ≥ 0.75 |
| Faithfulness | Answer grounded in retrieved content | **≥ 0.85** (blocks RAG-gated trading) |
| Answer Relevance | Directly addresses the question | ≥ 0.80 |
| Citation Accuracy | Correct document/page references | ≥ 0.90 |

**Golden eval set:** 50–100 curated Q&A pairs sourced from the four RAG PDFs in `backend/knowledge/evaluation/golden_qa.jsonl` — run in CI on every ingest.

**Chunk regression tests:** equations, tables, Greek symbols preserved; no mid-equation splits.

Frameworks: **Ragas**, **DeepEval** — see `architecture.md` §7, §22.

### 6.3 User Chatbot (Final UI)

The RAG pipeline's primary human-facing consumer is the **user chatbot**:

| Item | Spec |
|---|---|
| Route | `frontend/` `/chat` |
| API | `POST /api/v1/chat` |
| Corpus | Four PDFs in §6.0 |
| Citations | Document + section + page on every answer |
| Ask AI | Pre-loads decision context from supervised cockpit |
| Safety | Explains only — never submits orders or holds credentials |

Full UX and contract: `architecture.md` §7.7.

---

## 7. Recommended Technology Stack

### 7.1 Frontend

| Component | Technology |
|---|---|
| Framework | **Next.js** (React) — recommended for production UI; Streamlit acceptable for early prototypes |
| Styling | Tailwind CSS + component library (e.g., shadcn/ui) |
| Charts | Lightweight Charts, Recharts, or TradingView widget |
| State / API client | React Query (TanStack Query) + WebSocket client |
| Auth (UI) | Session token from backend; no broker credentials in browser |

### 7.2 Backend

| Component | Technology |
|---|---|
| Language / runtime | **Python** |
| API framework | **FastAPI** (REST + WebSocket) |
| Live data feed ingestion | `httpx` / `aiohttp`; scheduled polling; optional WebSocket; pandas for normalization |
| Third-party integrations | Pluggable adapters (`backend/integrations/`); **ICICI Direct** Breeze API; credential vault |
| Broker integration | **ICICI Direct** sole broker; paper via **`paper_sim`** + `shadow`; live via Breeze API |
| Orchestration | Direct `chromadb` / `groq` clients; LangChain optional for chains only |
| PDF parsing | Docling + PyMuPDF + pdfplumber |
| Embeddings | **`bge-m3`** (primary); `bge-large-en-v1.5` fallback |
| Vector DB | **ChromaDB** (embedded local / HTTP server production) |
| Keyword search | BM25 (`rank_bm25` in application layer, fused with Chroma dense results) |
| Re-ranker | **`bge-reranker-large`** |
| LLM | **Groq API** (`groq` SDK) — `llama-3.3-70b-versatile` (primary) |
| Bot scheduler | APScheduler or Celery Beat (market-hours trading loop) |
| Learning / optimization | scikit-learn, Optuna; walk-forward backtester |
| Persistence | PostgreSQL (trades, config, analytics) + Redis (cache, bot state) + **Parquet** (replay/OHLCV) |
| Evaluation | Ragas + DeepEval + golden Q&A regression suite |

### 7.3 Cloud Infrastructure & Virtual Compute

Deployment is **phased**:

| Phase | Frontend | Backend | Data | Reference |
| ----- | -------- | ------- | ---- | --------- |
| **Paper** (validation / soak) | **Vercel** (`frontend/`) | **Railway** (`backend/`, `PROCESS_ROLE=all`) | Railway Postgres + Redis | `architecture.md` §17.0, `Docs/Paper_Simulator.md` |
| **Live** (after paper evidence) | **Cloud Run** | **Cloud Run** (API + worker) | Cloud SQL + Memorystore + Filestore Chroma | `architecture.md` §17.8, `infra/cloud-inventory.yaml` |

Local development uses a **native** Python + Node toolchain (`Docs/LOCAL_DEV.md`) — no Docker / Compose. Live inventory and provisioning: **`infra/cloud-inventory.yaml`**, **`infra/provision/PROVISIONING.md`**. Paper env templates: `infra/env/railway.paper.env.example`, `infra/env/vercel.paper.env.example`.

#### Paper deployment (Railway + Vercel)

| Tier | Platform | Role |
|---|---|---|
| Frontend | **Vercel** | Next.js dashboard; `NEXT_PUBLIC_API_URL` → Railway HTTPS |
| Backend | **Railway** (Nixpacks) | FastAPI + `paper_sim` + bot scheduler; secrets server-side only |
| PostgreSQL / Redis | Railway plugins | Paper ledger, config, cache, leader lock |
| `CORS_ORIGINS` | Railway var | Vercel app URL(s) |
| `EXECUTION_MODE` | Railway var | `paper` — never `live` on this stack |

#### Live deployment tiers (GCP)

| Tier | GCP product | Virtual compute ID | Role |
|---|---|---|---|
| Frontend | **Cloud Run** (Buildpacks from `frontend/`) | VC-FE-01 | Next.js dashboard, chat, kill-switch |
| Backend (MVP) | **Cloud Run** (Buildpacks) | VC-BE-01 | API + bot scheduler combined (`PROCESS_ROLE=all`) |
| Backend API (prod) | **Cloud Run** | VC-BE-02 | REST + WebSocket only (`PROCESS_ROLE=api`) |
| Backend worker (prod) | **Cloud Run** | VC-BE-03 | Bot scheduler loop (`PROCESS_ROLE=worker`, max-instances=1) |
| Vector DB (MVP) | **GCE** + persistent disk or **Chroma Cloud** | VC-BE-06 / external | Chroma HTTP server |
| Vector DB (prod) | **Cloud Run** + **Filestore** | VC-BE-04 | Chroma HTTP server, NFS-backed persistence |
| PostgreSQL | **Cloud SQL** | MS-DB-01 | Trades, config, analytics, learning history |
| Redis | **Memorystore for Redis** | MS-DB-02 | Market cache, bot state, pub/sub, leader lock |
| Container registry | **Artifact Registry** | PS-01 | OCI images from Cloud Buildpacks |
| Secrets | **Secret Manager** | PS-02 | API keys, DB credentials |
| Local dev | **Native installs** | VC-LOC-01 … 03 | Optional Postgres/Redis; embedded Chroma |

#### Environments

| Environment | Where | Services |
|---|---|---|
| Development | Local (`Docs/LOCAL_DEV.md`) | `npm run dev` + `uvicorn` (+ optional native PG/Redis) |
| Paper | **Vercel** + **Railway** (Nixpacks) | Frontend + backend (`paper_sim`) |
| Live / production | GCP `volatality-production` (`asia-south1`) | Cloud Run frontend + API + worker |

**Primary region (live GCP):** `asia-south1` (Mumbai — NSE / BSE / NFO, IST). Prefer low-latency Railway/Vercel regions for India sessions when available.

#### Sizing (paper Railway backend)

| Resource | Spec |
|---|---|
| Runtime | Single always-on Railway service (`PROCESS_ROLE=all`) |
| Postgres / Redis | Railway plugins (sized for paper soak) |
| Chroma | Optional embedded or small sidecar — full Filestore Chroma is live-only |

#### Sizing (live MVP backend Cloud Run)

| Resource | Spec |
|---|---|
| CPU | 2 |
| RAM | 4 GB |
| min-instances | 1 (always-on for bot) |
| cpu-throttling | disabled (`--no-cpu-throttling`) |
| Cloud SQL tier | db-f1-micro, 10 GB SSD |
| Memorystore | Basic, 1 GB |
| Chroma (MVP) | GCE e2-small + 20 GB PD, or Chroma Cloud |

#### Local virtual compute

No Compose. See **`Docs/LOCAL_DEV.md`**.

| Service | Port / path | Connection |
|---|---|---|
| API / UI | 8000 / 3000 | `uvicorn` + `npm run dev` |
| PostgreSQL (optional) | 5432 | `LOCAL_INFRA=native` → `postgresql+psycopg://volatality:volatality_dev@localhost:5432/volatality` |
| Redis (optional) | 6379 | `LOCAL_INFRA=native` → `redis://localhost:6379/0` |
| ChromaDB | disk | `CHROMA_PERSIST_DIRECTORY=./backend/data/chroma` (embedded) |

#### Secrets & env templates

| Location | Purpose |
|---|---|
| Railway variables (paper) | `GROQ_API_KEY`, `DATABASE_URL`, `REDIS_URL`, ICICI Direct data keys, `CORS_ORIGINS`, `EXECUTION_MODE=paper` |
| Vercel env (paper) | `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL` only |
| Secret Manager (live) | `GROQ_API_KEY`, `DATABASE_URL`, `REDIS_URL`, broker keys |
| Cloud Run env vars (live) | `GROQ_MODEL`, `CHROMA_HOST`, `CORS_ORIGINS`, `PROCESS_ROLE` |
| `infra/env/railway.paper.env.example` | Paper backend template |
| `infra/env/vercel.paper.env.example` | Paper frontend template |
| `infra/env/gcp.staging.env.example` | Staging Cloud Run variable template |
| `infra/env/gcp.production.env.example` | Production Cloud Run variable template |

**Estimated paper infrastructure cost:** typically low tens of USD/month (Railway + Vercel hobby/pro; excludes Groq). **Estimated live MVP cost:** ~$95–150/month (Cloud Run + Cloud SQL + Memorystore + GCE Chroma; excludes Groq). Filestore-backed Chroma adds ~$200+/mo (1 TB minimum).

#### Provisioning checklist

**Paper (do first):**
- [ ] Railway: Postgres + Redis + `backend/` deploy; `GET /health` and `/api/v1/paper-sim/health` pass
- [ ] Vercel: `frontend/` deploy; `NEXT_PUBLIC_*` point at Railway URL
- [ ] Railway `CORS_ORIGINS` set to Vercel URL(s)
- [x] `EXECUTION_MODE=paper`; no ICICI Direct `place_order` on Railway

**Live (after paper soak):**
- [ ] GCP project in `asia-south1`: Cloud SQL, Memorystore, VPC connector, backend + frontend Cloud Run
- [ ] Chroma persistence (GCE e2-small, Chroma Cloud, or Filestore)
- [ ] Secrets in Secret Manager; Cloud Run service accounts granted `secretAccessor`
- [ ] Frontend `NEXT_PUBLIC_*` URLs point to backend API Cloud Run service
- [ ] `CORS_ORIGINS` set to frontend Cloud Run URL on backend
- [ ] Health checks passing (`/health`, `/health/bot` when split)
- [ ] Production: API + worker split before 99% uptime claim (§17.7)
- [ ] Static egress IP for ICICI Direct order APIs (`architecture.md` §11.11, §17.8)

### 7.4 Resolved Architectural Decisions

| Decision | Choice | Reference |
|---|---|---|
| Primary broker (MVP) | **ICICI Direct** (NSE / BSE / NFO only) | `architecture.md` §11.5, §11.8–11.15, §20.3 |
| Vector store | **ChromaDB** | `architecture.md` §7, §14.4 |
| Embeddings / reranker | **bge-m3** + **bge-reranker-large** | `architecture.md` §7 |
| Orchestration | Direct clients; LangChain optional | `architecture.md` §20.3 |
| Historical data | **Parquet** (replay) + PostgreSQL (metadata) | `architecture.md` §14.4 |
| Regime classifier (initial) | **Rule-based** | `architecture.md` §20.3 |
| Multi-leg orders | **Phase 1 (paper_sim auto-complete)**; live sequential+rollback Phase 5 | `architecture.md` §11.7 |
| LLM authority | **Quant leads; Groq validates** | `architecture.md` §10.2, §10.6 |
| Execution autonomy | **Graduated** — `SUPERVISION_MODE` supervised → semi → fully autonomous; `EXECUTION_MODE` shadow → paper → live | `architecture.md` §6.2.1, §6.2.2, §6.4 |
| One trade at a time | **1** discretionary entry per session (§20.4.11) | `architecture.md` §20.4.11 |
| Cloud compute platform | **Paper:** Railway + Vercel · **Live:** GCP (Cloud Run + Cloud SQL + Memorystore, `asia-south1`) | `architecture.md` §17.0, §17.8 |

---

## 8. Expected Challenges

The framework must explicitly handle:

| Category | Challenges |
|---|---|
| **Market Data** | Feed URL availability, stale data, format heterogeneity, auth/rate limits; quality depends on third-party providers |
| **Infrastructure** | No HFT capability; cloud compute sized for retail-scale polling (§7.3) |
| **Execution** | Broker API rate limits, order rejections, paper-vs-live fill differences, multi-leg option order complexity |
| **Third-Party Integration** | ICICI Direct auth expiry, Breeze API instability, schema drift, position sync latency, data provider outages |
| **Capital** | Margin constraints, position sizing limits |
| **Liquidity** | Option liquidity, overnight gap risk |
| **Model Risk** | Volatility regime changes, cointegration breakdowns, overfitting, adaptation instability |
| **Learning Loop** | Overfitting to recent data, parameter churn, false confidence from short winning streaks |
| **RAG Quality** | Bad ingestion → bad AI validation; mitigated by golden eval CI gate (faithfulness ≥ 0.85) |
| **LLM Dependency** | Groq latency/outages; mitigated by rule fast path + degraded quant-only mode |
| **Success Ratio** | Win rate alone is insufficient; must balance profit factor and drawdown; conservative paper fills required |
| **Gamma Scalping** | Frequent hedge adjustments, dynamic IV changes |

---

## 9. Expected Deliverables

1. **AI-powered RAG system** built from the four reference PDFs (`Volatility Trading`, `Gamma Scalping`, `Vega Scalping`, `Trading_Strategies`)
2. **User chatbot** in the final frontend UI (`/chat`) — RAG Q&A with citations; Ask AI from decision cards (`architecture.md` §7.7)
3. **Live data feed integration layer** — URL registry, scheduled polling/streaming, strategy ↔ feed binding, freshness validation, normalization for OSS marking and quant modules
4. **Quantitative analytics engine** for statistical arbitrage and volatility analysis
5. **Gamma and Vega modules** for exposure estimation and autonomous hedging
6. **Trading bot** — end-to-end signal generation with supervised decision queue (Phase 2), then semi / full autonomy after promotion (`architecture.md` §21)
7. **Continuous learning & adaptation engine** — performance tracking, parameter optimization, module reweighting, regime switching
8. **Backend API server** — FastAPI with REST/WebSocket, hosting the bot, RAG, quant engines, learning loop, and broker adapter
9. **Frontend application** — supervised cockpit (decision queue), live metrics, recommendations, kill-switch, adaptation history, and **RAG user chatbot** (`Docs/UI_Dashboard.md`)
10. **Integration layer** — ICICI Direct adapter (marks + live orders), in-house **`paper_sim`** (paper P&L), and live data providers (URL feeds)
11. **Backtesting & walk-forward validation** — out-of-sample validation for every adaptation cycle
12. **Risk dashboards** — win rate, Greeks, drawdowns, profit factor, scenario analyses
13. **Testing & CI suite** — unit, integration, RAG golden eval, OSS parity, replay E2E (`architecture.md` §22)
14. **Documentation** — assumptions, methodologies, limitations; `DECISIONS.md` living log
15. **Cloud infrastructure** — paper on Railway Nixpacks + Vercel (§17.0); live on Google Cloud Platform (Cloud Run via Buildpacks, Cloud SQL, Memorystore, `asia-south1`); native local toolchain; inventory in `infra/cloud-inventory.yaml` (§7.3)

---

## 10. Success Criteria

The bot succeeds when it can:

- [ ] Reliably retrieve and apply domain knowledge from the four PDFs via RAG; **faithfulness ≥ 0.85** on golden eval set
- [ ] Ship **user chatbot** at `/chat` with citations; Ask AI from supervised decision cards works end-to-end
- [ ] Register live data feed URLs and bind feeds to OSS strategies; fetch and normalize quotes and option chains during market hours
- [ ] Integrate with **ICICI Direct** for live marks + (later) order execution; use **`paper_sim`** for paper P&L and position sync rehearsal
- [ ] OSS parity tests pass — backend BSM/Greeks match OSS reference fixtures
- [ ] Operate end-to-end bot in **`supervised`** with Approve / Reject; kill-switch functional
- [ ] **One trade at a time** gate enforced (§20.4.11); dashboard shows active discretionary trade and lock status
- [ ] **`EXECUTION_MODE` shadow → paper-sim ramp** validated before ICICI Direct live submit enabled
- [ ] **`SUPERVISION_MODE` promotion path** documented and checklist-gated (supervised → semi → fully autonomous)
- [ ] Sustain **win rate ≥ 60%** on a rolling 30-day window of closed trades (conservative fill mode)
- [ ] Achieve **profit factor ≥ 1.5** and **Sharpe ratio ≥ 1.5** in paper trading
- [ ] Keep **max drawdown ≤ 10%** of paper-sim equity
- [ ] Automatically detect performance degradation and adapt strategy parameters without manual intervention
- [ ] Validate every adaptation through **walk-forward backtest** before deploying updated config
- [ ] Operate as a fully functional end-to-end bot: observe → analyze → decide → (approve) → execute → learn → adapt
- [ ] Frontend and backend operate as clearly separated tiers; frontend provides decision queue, monitoring, kill-switch, and chatbot
- [ ] Deliver transparent, explainable decision logs for every trade
- [ ] Complete **2–4 week paper soak test** meeting at least one success metric (Phase 4 gate — before any live)

---

## 11. Design Principles

### 11.1 RAG as Domain Knowledge Engine

Treat RAG not as a document search tool but as a **searchable quantitative knowledge base** supporting:

- Strategy development
- Trader education
- Explainable AI-driven decisions

Example queries the enriched metadata should support:

- "Show all sections discussing Gamma and Theta together."
- "Compare Vega risk across the Volatility Trading and Vega Scalping books."
- "Find every equation related to cointegration tests."
- "Summarize practical limitations of gamma scalping for retail traders."

### 11.2 Live Data Feeds via URL Endpoints

Market data and trade-input marks are decoupled from strategy logic. Operators register **live data feed URLs** (broker data APIs, third-party quote endpoints, CSV/JSON files) and **bind them to OSS strategies**. The ingestion layer fetches on schedule, validates freshness, and normalizes data so quantitative modules and OSS marking operate on a consistent internal representation. Discretionary execution requires healthy, up-to-date feeds for every bound strategy.

### 11.3 ICICI Direct & Paper Simulator Integrations

The bot integrates with external systems through **pluggable backend adapters**—never via frontend credentials. Initial build targets **`paper_sim`** for paper P&L, **ICICI Direct** for live marks (and later orders), and **URL-based data providers** for quotes and option chains. See §2.6, §5.7, and `architecture.md` §8.6, §11.

### 11.4 Option Strategy Trade Inputs

Option trades are expressed as **multi-leg strategies** aligned with the **Macroption OSS** (`Docs/OSS (1).xlsm`, `Docs/OSS_Guide (1).pdf`): global BSM parameters, optional flat or per-leg volatility, contract multipliers, and an **unbounded leg list** of type **call, put, or stock**—with **no fixed leg-count limit**. Strategies may **add legs over the trade lifecycle** (hedges, rolls, adjustments) until **successful closure**. The bot does not accept ad-hoc single-field order inputs—it validates, prices (BSM-Merton), and risk-checks the full strategy table (global params → legs → computed Greeks → totals) before broker submission. Stock legs support covered calls, protective puts, and delta hedges. See §2.8 and `architecture.md` §8.5.

### 11.5 Frontend / Backend Boundary

The frontend is a **thin client**: it renders data, captures user intent (including Approve / Reject), and calls backend APIs. All computation, data storage, broker communication, and secret management live in the backend. This separation ensures security (no broker keys in the browser), testability (backend testable independently), and flexibility (frontend can be swapped or extended without touching quant logic).

### 11.6 Supervised → Semi → Autonomous

The system is a **fully functional trading bot** that runs during market hours. Discretionary entries follow **`SUPERVISION_MODE`**: Phase 2 defaults to **`supervised`** on `paper_sim` (operator Approve / Reject on pre-approval packets). Promote to **`semi_autonomous`** then **`fully_autonomous`** only after paper evidence and checklist sign-off (`architecture.md` §21 Phases 2–4). **Mechanical hedges** execute without a discretionary path in every mode. **`EXECUTION_MODE`** ramps from `shadow` → `paper` (`paper_sim`) → `live` (ICICI Direct, Phase 5 only). Auto-pause and circuit breakers pause new discretionary entries until operator resume.

### 11.7 Continuous Learning as Core Capability

Learning is not an afterthought—it is a **first-class architectural component**. The bot treats every trade as training data. Performance metrics are computed continuously; adaptation is triggered automatically when success-ratio targets are at risk. No strategy parameter is static over the long term.

### 11.8 High Success Ratio by Design

Success is engineered through layered defenses:

1. **Signal quality** — multi-module confirmation, AI confidence gating, RAG validation
2. **Risk management** — pre-trade Greeks checks, position limits, stop-losses, drawdown circuit breakers
3. **Adaptation** — automatic parameter tuning and module reweighting when metrics degrade
4. **Validation** — walk-forward backtest before every config deployment
5. **Recovery** — reduced-exposure mode after drawdown; automatic resume when metrics recover
6. **Transaction costs** — spread, commission, slippage in every gamma hedge and stat-arb gate

### 11.9 Paper Trading First

All execution during development and validation uses in-house **`paper_sim`** (ICICI Direct marks + local ledger) or adapter **`shadow`** dry-run logs. ICICI Direct has **no** paper/sandbox API. Promote to `EXECUTION_MODE=live` only after paper-sim soak + supervision checklist (**Phase 5**). Default fill mode is **conservative** (§2.6). **This is the critical path** — see `architecture.md` §21.0–21.1.

### 11.10 Quant Leads, LLM Validates

Quant modules and rule-based fast paths own signal generation and mechanical hedges. Groq validates discretionary entries, explains decisions, and grounds reasoning in RAG. The LLM never sits in the order submission path.

### 11.11 Validate Before You Trust

No RAG-gated trading until the golden eval suite passes CI thresholds (faithfulness ≥ 0.85). Ingestion quality—not LLM choice—determines RAG effectiveness. Track B may run in parallel with Phase 0–1 but must be green before LLM gates in Phase 2+.

### 11.12 Paper Vertical Slice First

Build Phase 0–1 (ICICI Direct data-only → `paper_sim` fills → P&L → SH-4/news/γ–θ) before autonomy or live capital. RAG chat (Track B) is parallel, not blocking. Full sequence: Phase 0 → 1 → 2 supervised → 3 semi → 4 full-auto soak → 5 live (`architecture.md` §21).

### 11.13 Vision Statement

> The ultimate goal is to build a **continuously learning volatility trading bot** that sustains a **high success ratio** at retail scale, progressing from **paper rehearsal → supervised → semi-autonomous → fully autonomous → live**. Phase 2 starts with operator approval on `paper_sim`; autonomy is earned after paper evidence. **`EXECUTION_MODE`** ramps from shadow logging to paper-sim, then ICICI Direct live on GCP only. **One trade at a time** limits blast radius. By combining domain playbooks with RAG-grounded AI reasoning, statistical modeling, broker execution, and a closed-loop adaptation engine, the system aims to make sophisticated volatility trading **self-improving, explainable, and consistently profitable**—without requiring institutional infrastructure, while maintaining kill-switch and circuit-breaker safeguards throughout.

---

## 12. Source Document Inventory

### 12.1 RAG Corpus (ingested into ChromaDB)

| Document | Path | Domain | Key Topics |
|---|---|---|---|
| Volatility Trading | `Docs/Volatility Trading.pdf` | Vol surface | HV, IV, RV, term structure, smile, skew, vol forecasting |
| Gamma Scalping | `Docs/Gamma Scalping.pdf` | Dynamic hedging | Delta, gamma, theta, hedge ratios, rebalancing, transaction costs |
| Vega Scalping | `Docs/Vega Scalping.pdf` | IV exposure | Vega, IV expansion/contraction, event vol, vega-neutral positioning |
| Trading Strategies | `Docs/Trading_Strategies.pdf` | Consolidated playbook | Cross-strategy rules, entry/exit, scenario management, supervised assumptions |

### 12.2 Operational & schema references (not primary RAG corpus)

| Document | Domain | Key Topics |
|---|---|---|
| `Docs/Trading_Strategies.md` | Strategy playbook (ops/UI) | Same domain as PDF playbook; editable runbooks |
| `Docs/Trading_Parameters.md` | Parameter catalog | OSS keys, thresholds, hedge sizing, risk limits |
| **OSS (1).xlsm** + **OSS_Guide (1).pdf** | Trade input schema | Multi-leg strategy table, BSM pricing, Greeks, contract multipliers, expiration catalog, scenario chart |
| `Docs/Statistical Arbitrage by Cointegration.pdf` | Pairs trading (module reference) | Cointegration tests, mean reversion, z-scores — available for future RAG expansion; not in v1.19 corpus |

---

## 13. Glossary of Key Terms

| Term | Definition |
|---|---|
| **HV** | Historical Volatility — past price movement |
| **IV** | Implied Volatility — market's expectation embedded in option prices |
| **RV** | Realized Volatility — actual volatility over a period |
| **Greeks** | Sensitivities of option price to underlying variables (Δ, Γ, ν, Θ, ρ) |
| **Cointegration** | Statistical relationship where a linear combination of non-stationary series is stationary |
| **Z-score** | Standardized deviation of spread from mean; used for entry/exit signals |
| **Gamma Scalping** | Buying/selling underlying to offset delta changes and capture gamma profits |
| **Vega Scalping** | Trading changes in implied volatility |
| **RAG** | Retrieval-Augmented Generation — LLM answers grounded in retrieved documents |
| **BM25** | Keyword-based ranking function for lexical search |
| **Paper Trading** | Simulated trading via in-house **paper-sim** (ICICI Direct marks + local ledger)—no real money; ICICI Direct has no sandbox API |
| **Data Feed URL** | Configured endpoint the bot polls or streams for live market data (quotes, chains, OHLCV) |
| **Strategy Feed Binding** | Mapping from an OSS strategy to the feed URLs that supply its underlying price and option marks |
| **Third-Party Adapter** | Pluggable backend module connecting the bot to an external app (broker, data provider) |
| **Broker Adapter** | ICICI Direct adapter that translates internal OSS orders to Breeze API calls and syncs positions |
| **Feed Freshness** | Maximum age of market data before the bot blocks execution for dependent strategies |
| **Trading Bot** | Agent that observes, analyzes, decides, executes, learns, and adapts; supervision path supervised → semi → fully autonomous |
| **`EXECUTION_MODE`** | `shadow` \| `paper` (paper-sim) \| `live` — controls whether orders reach ICICI Direct (§2.3.1) |
| **`SUPERVISION_MODE`** | `supervised` \| `semi_autonomous` \| `fully_autonomous` — who authorizes discretionary entries (§2.3.1) |
| **Graduated Supervision** | Promote supervised → semi → fully autonomous only after paper evidence |
| **Autonomous Execution** | End-state mode: discretionary entries auto-submit when gates pass; ranked fallback (§6.4) |
| **Ranked Fallback** | In `fully_autonomous`, recommendations screen tries rank #1, then #2, then #3 on failure among confidence ≥ **85%** names (§6.4) |
| **One Trade at a Time** | At most one open discretionary entry per session; new signals deferred until close (§20.4.11) |
| **Continuous Learning** | Closed-loop system that updates strategy parameters and module weights based on trade outcomes and performance metrics |
| **Success Ratio** | Composite measure of bot performance: win rate, profit factor, Sharpe ratio, and drawdown control |
| **Win Rate** | Percentage of closed trades with positive P&L |
| **Profit Factor** | Gross profit divided by gross loss across all closed trades |
| **Kill Switch** | Frontend control that immediately pauses trading and prevents new order submission |
| **Adaptation Cycle** | Sequence of metric breach → optimization → backtest validation → config deployment |
| **Rho** | Sensitivity of option price to interest rate changes |
| **Option Strategy Simulator (OSS)** | Macroption multi-leg trade input UI and BSM pricing reference (`Docs/OSS (1).xlsm`) |
| **Flat Volatility** | When enabled, one global σ applies to all option legs; when off, per-leg vol overrides |
| **Contract Multiplier** | Shares/lots per option contract — **NFO `lotsize` per symbol** from ICICI Direct master (not OSS US 100); scales value, CF, and Greeks totals |
| **Stock Leg** | Underlying position (long/short) within a multi-leg strategy; delta ±1, other Greeks zero |
| **Effective Expiration** | Datetime when option stops trading / settlement is fixed — used for time-to-expiry |
| **Initial CF** | Initial cash flow at trade entry; `−position × initial_price × multiplier` (debit negative) |
| **Sharpe Ratio** | Risk-adjusted return metric used in performance evaluation |
| **ChromaDB** | Vector database for RAG knowledge, failure memory, and trade insights |
| **Golden Eval Set** | Curated Q&A pairs with expected citations; CI gate for RAG quality |
| **Walk-Forward Validation** | Out-of-sample backtest: train on window N, validate on window M, roll forward |
| **Replay Mode** | Deterministic bot run using recorded Parquet market snapshots |
| **Paper Conservative Fill** | Slippage + spread penalty applied to paper fills for realistic P&L |
| **Rule Fast Path** | Mechanical hedges execute via quant rules without Groq latency |

---

*This document is the consolidated project context for the Volatility Trading Bot. For implementation details, see **`architecture.md` v1.16** (authoritative technical reference).*
