# System Architecture: AI-Assisted Volatility Trading Bot

> **Sources:** `context.md`, `Docs/Strategy_Ingestion_Pipeline.txt`, `Docs/Problem_Statement.txt`, `Docs/Volatility Trading.pdf`, `Docs/Gamma Scalping.pdf`, `Docs/Vega Scalping.pdf`, `Docs/Trading_Strategies.pdf`, `Docs/Trading_Strategies.md`, `Docs/Trading_Parameters.md`, `Docs/UI_Dashboard.md`, `Docs/Paper_Simulator.md`, `Docs/OSS (1).xlsm`, `Docs/OSS_Guide (1).pdf`, `Market_News.txt`, ICICI Direct Breeze API ([docs](https://api.icicidirect.com/breezeapi/documents/index.html))  
> **Version:** 1.27  
> **Last updated:** July 30, 2026 — Phase 1 post-entry multi-leg auto-complete without consent (same open-trade rules); prior: **No MCP registry** / ICICI Direct marks + orders; Market_News; spot ≤ INR 1000 for options+underlying

---

## Table of Contents

1. [Executive Overview](#1-executive-overview)
2. [Architectural Goals & Constraints](#2-architectural-goals--constraints)
3. [System Context](#3-system-context)
4. [High-Level Architecture](#4-high-level-architecture)
5. [Tier Architecture: Frontend & Backend](#5-tier-architecture-frontend--backend) — includes [§5.4 Repository Layout](#54-repository-layout-standalone-deployment-folders)
6. [Backend Service Architecture](#6-backend-service-architecture)
7. [Knowledge Layer: RAG & Strategy Ingestion Pipeline](#7-knowledge-layer-rag--strategy-ingestion-pipeline) — includes [§7.7 User Chatbot](#77-user-chatbot-final-ui-component)
8. [Market Data Layer](#8-market-data-layer) — includes [§8.5 Trade Input Model](#85-trade-input--option-strategy-model), [§8.6 Feed Binding](#86-live-feeds--strategy-url-binding), [§8.8 Market Sentiment & News](#88-market-sentiment--news-pipeline), [§8.9 ICICI Direct Market Data](#89-icici-direct-market-data-integration)
9. [Quantitative Engine](#9-quantitative-engine)
10. [AI Decision Engine](#10-ai-decision-engine)
11. [Execution Layer: ICICI Direct Broker Integration](#11-execution-layer-icici-direct-broker-integration) — includes [§11.8 Breeze API](#118-breeze-api-surface-map), [§11.9 Auth](#119-authentication--session-lifecycle), [§11.11 SEBI](#1111-sebi--compliance-constraints), [§11.15 A0–A6](#1115-icici-direct-implementation-phases-a0a6)
12. [Continuous Learning & Adaptation](#12-continuous-learning--adaptation)
13. [Analytics & Observability](#13-analytics--observability)
14. [Data Architecture](#14-data-architecture)
15. [API & Integration Contracts](#15-api--integration-contracts)
16. [Security Architecture](#16-security-architecture)
17. [Deployment Architecture](#17-deployment-architecture) — includes [§17.0 Paper Trading (Railway + Vercel)](#170-paper-trading-deployment-railway--vercel)
18. [Technology Stack](#18-technology-stack)
19. [Non-Functional Requirements](#19-non-functional-requirements)
20. [Risks, Trade-offs & Open Decisions](#20-risks-trade-offs--open-decisions) — includes [§20.4 Autonomy Risk Controls](#204-autonomy-risk-controls)
21. [Phased Implementation Roadmap](#21-phased-implementation-roadmap)
22. [Testing & CI Strategy](#22-testing--ci-strategy)

---



## 1. Executive Overview

This document defines the technical architecture for a **continuously learning volatility trading bot** designed for **retail-scale deployment**. The system combines institutional-grade quantitative strategies with modern AI (LLMs + RAG) to bridge the gap between professional volatility trading and retail constraints. Discretionary execution follows a deliberate path: **supervised → semi-autonomous → fully autonomous** (`SUPERVISION_MODE`, §6.2.2). Full autonomy is the end state, not the day-one default.

### 1.1 What the System Does

The bot operates end-to-end through a closed lifecycle:

```
Observe → Analyze → Decide → (Approve if supervised) → Execute → Measure → Learn → Adapt → Observe ...
```


| Capability                   | Description                                                                                                                                     |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| **Knowledge**                | Ingests four domain PDFs (`Volatility Trading`, `Gamma Scalping`, `Vega Scalping`, `Trading_Strategies`) into a searchable, metadata-rich vector knowledge base |
| **User chatbot**             | RAG-powered assistant in the final frontend UI for education, strategy Q&A, and on-demand trade/decision explanations with citations |
| **Market data**              | Fetches **live** instrument data from user-configured URL endpoints on schedule; binds feeds to OSS strategies                                  |
| **Market sentiment**         | Curated India news per `Market_News.txt`; regime / event flags drive strategy choice via `Trading_Strategies.md` (§8.8)    |
| **Third-party integrations** | Pluggable adapters for **ICICI Direct** (marks + live orders) and **data providers** (live feeds); credentials server-side                       |
| **Trade inputs**             | Multi-leg strategies via **Macroption OSS** schema (`Docs/OSS (1).xlsm`) — global BSM params, call/put/stock legs, contract multipliers, Greeks |
| **Quantitative analysis**    | Runs stat arb, volatility, gamma, vega, Greeks, and risk modules                                                                                |
| **Graduated decisions**      | LLM validates and ranks signals; discretionary entries require operator approval in `supervised`, high-confidence auto-submit in `semi_autonomous`, and ranked fallback auto-execute in `fully_autonomous` (§6.2.2, §6.4) |
| **Paper execution**          | In-house **`paper_sim`** — ICICI Direct LTP marks + local ledger fills; **no** Breeze API `place_order` (`Docs/Paper_Simulator.md`)                                                                        |
| **Self-improvement**         | Tracks performance, optimizes parameters, and reweights strategy modules                                                                        |




### 1.2 Architectural Stance


| Principle                              | Implication                                                                                                                                        |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Supervised → semi → autonomous**     | `SUPERVISION_MODE` starts at `supervised` (Phase 2 default on paper); promote only after validated paper performance (§6.2.2, §21). Mechanical hedges remain rule-based (§10.6) |
| **One trade at a time**                | At most one pending or open discretionary entry per session; limits blast radius if logic is wrong (§20.4.11)                                      |
| **Frontend/backend separation**        | All business logic, secrets, and broker communication live in the backend                                                                          |
| **RAG as domain knowledge engine**     | Ingestion quality determines AI reasoning quality—not the LLM alone                                                                                |
| **URL-decoupled live data**            | Strategies consume normalized live feeds, not hard-coded vendors; OSS marks refreshed from bound URLs                                              |
| **Pluggable third-party integrations** | Brokers and data providers added via adapters + runtime config; no vendor logic in quant modules                                                   |
| **Option-strategy trade inputs**       | All trades expressed as OSS multi-leg strategies: global BSM params, **unbounded legs** (call/put/stock) until trade closure, contract multipliers, flat or per-leg vol |
| **Paper trading first**                | Rehearse on in-house `paper_sim` (ICICI Direct marks + local ledger); promote to ICICI Direct `live` only after evidence (`Docs/Paper_Simulator.md`)                                                                    |
| **Continuous learning as first-class** | Every trade feeds the adaptation loop (§12)                                                                                                        |
| **Two graduated axes**                 | `EXECUTION_MODE` (`shadow` → `paper` via `paper_sim` → `live`) controls submit path; `SUPERVISION_MODE` controls who approves discretionary entries (§6.2.1–6.2.2, §20.4) |
| **Operator-in-the-loop by default**    | Phase 2 ships a supervised cockpit (`Docs/UI_Dashboard.md`); autonomy is earned via promotion checklist, not assumed |
| **Standalone deployable services**     | `frontend/` and `backend/` are independent folders, each with its own build and deploy config                                                      |
| **Phased deployment targets**          | **Paper:** backend **Railway** + frontend **Vercel** (§17.0); **Live:** full stack on **GCP** (Cloud Run, Cloud SQL, Memorystore) in `asia-south1` — inventory in `infra/cloud-inventory.yaml` (§17.8) |
| **Groq as LLM provider**               | All LLM reasoning (decision engine, RAG answers, enrichment) uses the **Groq API**                                                                 |
| **Quant leads, LLM validates**         | Mechanical hedges and threshold breaches execute via rules; Groq validates, explains, and gates discretionary entries                              |
| **Validate before you trust**          | No trade gating on RAG until the golden eval suite passes CI thresholds                                                                            |
| **Vertical slice first**               | Prove ICICI Direct marks → `paper_sim` fill → P&L before autonomy or live; RAG chat is parallel Track B (§21)                                                               |
| **Chatbot in final UI**                | The RAG user chatbot ships as a permanent frontend surface (`/chat`) on Track B, not a throwaway prototype                                                  |


> **Architecture evolution:** The original `Docs/Problem_Statement.txt` scoped a decision-support / recommendation framework. The current design builds a **real trading bot** with broker execution, but **starts supervised** and promotes to semi-autonomous then fully autonomous only after paper validation (§6.2.2). Ranked recommendation auto-execute (§6.4) is the `fully_autonomous` end state. See **Appendix D** for previous-vs-current comparison.



### 1.3 Implementation Status


| Area                                 | Status                                                               |
| ------------------------------------ | -------------------------------------------------------------------- |
| Architecture & context docs          | Complete (`architecture.md` v1.25 — includes ICICI Direct Breeze API; `context.md`, `Docs/`) |
| Cloud infrastructure spec            | Complete (paper: §17.0 Railway/Vercel; live: `infra/cloud-inventory.yaml`, §17.8) |
| `frontend/` scaffold                 | In progress — supervised cockpit, recommendations, kill-switch; chat UI planned (`Docs/UI_Dashboard.md`) |
| `backend/` scaffold                  | In progress — decisions API, recommendations API, bot status, supervision mode config           |
| `paper_sim` + ICICI Direct data-only        | **Not started** — Phase 0–1 critical path (§21)                      |
| RAG ingestion pipeline (4 PDFs)      | Not started — parallel Track B (§21.2); not a paper-trading blocker  |
| User chatbot (final UI)              | Not started — Track B; ship before LLM-gated discretionary validation |
| Quant / execution / learning modules | In progress — OSS BSM + parity CI (`backend/quant/pricing/bsm.py`, `tests/quant/test_oss_parity.py`); execution/learning not complete |


**Immediate priority:** Phase 0 — paper stack scaffold (§21.1): ICICI Direct **data-only** marks + `backend/paper_sim/` ledger + Railway/Vercel. RAG chatbot is **parallel Track B**, not the critical path.

---



## 2. Architectural Goals & Constraints



### 2.1 Primary Goals

1. Sustain a **high success ratio** measured holistically: win rate, profit factor, Sharpe ratio, and drawdown control
2. Retrieve and apply domain knowledge from the **four RAG PDFs** during autonomous decision-making and the **user chatbot**
3. Ship a **RAG-powered user chatbot** as part of the final frontend UI (education, strategy Q&A, decision explanations)
4. Operate during market hours with **graduated discretionary execution** (`supervised` → `semi_autonomous` → `fully_autonomous`); kill-switch, monitoring, and circuit breakers always apply (§6.2.2, §20.4)
5. Adapt strategy parameters automatically when performance degrades
6. Deliver explainable decision logs for every autonomous trade



### 2.2 Success Ratio Targets (Paper Trading Phase)


| Metric                             | Target          | Trigger Action When Breached                         |
| ---------------------------------- | --------------- | ---------------------------------------------------- |
| Win rate (rolling 30-day)          | ≥ 60%           | Tighten entry filters; raise confidence threshold    |
| Profit factor                      | ≥ 1.5           | Reduce exposure; pause underperforming modules       |
| Sharpe ratio (annualized, rolling) | ≥ 1.5           | Trigger adaptation cycle                             |
| Max drawdown                       | ≤ 10% of equity | Reduced-exposure mode; pause highest-risk strategies |
| Recovery factor                    | ≥ 2.0           | Resume full operation when recovered                 |




### 2.3 Retail Constraints (Design Requirements)

All modules must explicitly account for:

- Capital limitations and position sizing constraints (₹10L account / ₹1L per trade / ₹1L per leg — `Trading_Strategies.md`)
- **Tradeable universe — underlying price cap is mode-conditional:** When the bot trades **options and its underlying** (any `stock` leg / cash-share hedge), it may only select instruments whose `und_price` is ≤ **₹1000** (cash equity; index underlyings excluded in this mode). When the bot trades **options only** (Call/Put legs only), there is **no cap** on underlying price — high-priced equities and index underlyings may qualify if ATM / premium / liquidity gates pass (`Trading_Parameters.md` Part T; `max_underlying_price_applies_when=options_and_underlying`).
- Transaction costs, bid-ask spreads, and slippage
- Margin requirements
- Limited market depth (data quality depends on supplied URLs)
- No HFT infrastructure (hedge frequency must be retail-realistic)
- Paper trading execution during development and validation



### 2.4 Out of Scope (Initial Build)

- Live capital trading (architecture supports future switch via configuration)
- Institutional-grade L2/order-book infrastructure
- Fully automated live deployment without paper validation

---



## 3. System Context



### 3.1 External Actors & Systems

```mermaid
C4Context
    title System Context Diagram

    Person(trader, "Retail Trader / Operator", "Monitors bot, configures feeds & broker, kill-switch")
    
    System(bot, "Volatility Trading Bot", "Autonomous trading, RAG, quant analysis, learning")
    
    System_Ext(kb_docs, "Knowledge Base PDFs", "Volatility Trading, Gamma Scalping, Vega Scalping, Trading_Strategies")
    System_Ext(market_urls, "Live Data Feed URLs", "REST/CSV/JSON/WebSocket — quotes, chains, OHLCV")
    System_Ext(news_sources, "India Market News", "Curated per Market_News.txt — Reuters, Moneycontrol, ET, NSE, SEBI")
    System_Ext(broker, "ICICI Direct Breeze API", "NSE / BSE / NFO — quotes, orders, positions")
    System_Ext(llm_api, "Groq API", "LLM reasoning via Groq (e.g. Llama 3.3 70B)")
    System_Ext(embed_api, "Embedding / Reranker", "bge-m3, bge-reranker-large, or OpenAI")

    Rel(trader, bot, "Monitors, configures, kill-switch", "HTTPS / WSS")
    Rel(bot, kb_docs, "Ingests at build/refresh time")
    Rel(bot, market_urls, "Poll/stream live feeds", "HTTPS / WSS")
    Rel(bot, news_sources, "Ingest headlines & filings for sentiment", "HTTPS / file")
    Rel(bot, broker, "Orders, positions, balances", "REST / WebSocket")
    Rel(bot, llm_api, "Reasoning, validation", "HTTPS")
    Rel(bot, embed_api, "Embeddings, reranking", "HTTPS / local")
```





### 3.2 Source Document Inventory

**RAG corpus (ingested into ChromaDB `knowledge_base`):**


| Document ID              | File path                         | Domain                    | Key Concepts                                                                               |
| ------------------------ | --------------------------------- | ------------------------- | ------------------------------------------------------------------------------------------ |
| `doc-vol-trading`        | `Docs/Volatility Trading.pdf`     | Volatility trading        | HV/IV, term structure, smile/skew, vol surfaces, under/overpriced options                  |
| `doc-gamma`              | `Docs/Gamma Scalping.pdf`         | Gamma scalping            | Dynamic delta hedging, gamma/theta trade-off, hedge frequency, retail limitations          |
| `doc-vega`               | `Docs/Vega Scalping.pdf`          | Vega scalping             | IV exposure, vol regime trades, vega risk, smile/skew positioning                          |
| `doc-trading-strategies` | `Docs/Trading_Strategies.pdf`     | Consolidated playbook     | Cross-strategy rules, entry/exit, scenario management, supervised execution assumptions    |


**Operational references (not primary RAG corpus — used by bot config, OSS, and operators):**


| Document ID              | Title                                  | Domain                    | Key Concepts                                                                               |
| ------------------------ | -------------------------------------- | ------------------------- | ------------------------------------------------------------------------------------------ |
| `ref-trading-strategies` | `Docs/Trading_Strategies.md`           | Strategy playbook (MD)    | Same domain as PDF playbook; editable source for ops runbooks and UI copy; **authoritative for strategy selection (Table SH-4)** |
| `ref-trading-parameters` | `Docs/Trading_Parameters.md`           | Parameter catalog         | OSS global/leg params, signal thresholds, hedge sizing, execution/risk limits              |
| `ref-market-news`        | `Market_News.txt`                      | India news curation       | Source list + daily workflow for sentiment (§8.8) |
| `doc-oss`                | OSS (1).xlsm + OSS_Guide (1).pdf       | Trade input schema        | Multi-leg BSM pricing, Greeks, contract multipliers, expiration catalog, scenario analysis |


Each RAG PDF receives a **unique identifier and version** at ingestion time for update tracking and citation. The markdown playbook and parameter catalog remain authoritative for **bot configuration and OSS keys**; the four PDFs are authoritative for **RAG retrieval** (chatbot + AI decision grounding). **`Market_News.txt` is authoritative for which India news sources feed sentiment**.

---



## 4. High-Level Architecture



### 4.1 Logical Layer Model

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         PRESENTATION TIER (Frontend)                         │
│   Dashboards · Bot Monitor · Kill Switch · Config · AI Chat · Risk Views    │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │ REST + WebSocket
┌──────────────────────────────────▼───────────────────────────────────────────┐
│                           APPLICATION TIER (Backend)                           │
│                                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────────────────┐ │
│  │ API Gateway │  │ Bot Scheduler│  │ Auth & Config Service                 │ │
│  └──────┬──────┘  └──────┬───────┘  └─────────────────────────────────────┘ │
│         │                │                                                    │
│  ┌──────▼────────────────▼──────────────────────────────────────────────┐  │
│  │                    AUTONOMOUS DECISION ORCHESTRATOR                     │  │
│  └──────┬───────────────┬────────────────────┬───────────────────────────┘  │
│         │               │                    │                               │
│  ┌──────▼──────┐ ┌──────▼──────┐  ┌─────────▼─────────┐  ┌───────────────┐ │
│  │ Knowledge   │ │ Market Data │  │ Quantitative      │  │ Learning      │ │
│  │ (RAG)       │ │ Ingestion   │  │ Engine            │  │ Engine        │ │
│  └──────┬──────┘ └──────┬──────┘  └─────────┬─────────┘  └───────┬───────┘ │
│         │               │                    │                    │          │
│  ┌──────▼───────────────▼────────────────────▼────────────────────▼───────┐ │
│  │              AI Decision Engine (LLM + Signal Fusion)                   │ │
│  └──────────────────────────────┬─────────────────────────────────────────┘ │
│                                 │                                             │
│  ┌──────────────────────────────▼─────────────────────────────────────────┐ │
│  │  Execution: Order Builder → Pre-trade Risk Gate → Broker Adapter       │ │
│  └──────────────────────────────┬─────────────────────────────────────────┘ │
└─────────────────────────────────┼────────────────────────────────────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │ paper_sim / ICICI Direct live │
                    └─────────────┬─────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │  Continuous Learning Loop │
                    └───────────────────────────┘
```



### 4.2 Primary Data Flows

```mermaid
flowchart TB
    subgraph Inputs
        KB[Volatility Trading.pdf\nGamma Scalping.pdf\nVega Scalping.pdf\nTrading_Strategies.pdf]
        URLs[Market Data URLs]
        NEWS[Market_News.txt\ncurated India sources]
        PLAYBOOK[Trading_Strategies.md\nTable SH-4 / scenarios]
        Broker[paper_sim / ICICI Direct Breeze API]
    end

    subgraph Backend
        RAG[RAG Pipeline]
        MD[Market Data Layer]
        SENT[Sentiment Service §8.8]
        QE[Quantitative Engine]
        AI[AI Decision Engine]
        EX[Execution Layer]
        LE[Learning Engine]
        VDB[(Vector DB)]
        PG[(PostgreSQL)]
        Redis[(Redis)]
    end

    subgraph Frontend
        UI[Next.js UI]
    end

    KB --> RAG --> VDB
    URLs --> MD --> QE
    NEWS --> SENT
    SENT --> AI
    PLAYBOOK --> AI
    QE --> AI
    VDB --> AI
    AI --> EX --> Broker
    Broker --> LE
    EX --> LE
    LE --> QE
    LE --> AI
    Backend --> UI
    UI --> Backend
```





### 4.3 Bot Operating Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Observe
    Observe --> Analyze: market tick / interval
    Analyze --> Decide: signals + AI validation
    Decide --> Execute: confidence & risk gates pass
    Decide --> Observe: no trade
    Execute --> Measure: fill + P&L
    Measure --> Learn: update metrics
    Learn --> Adapt: thresholds breached
    Learn --> Observe: metrics healthy
    Adapt --> Observe: validated config deployed

    state Adapt {
        [*] --> Optimize
        Optimize --> Backtest
        Backtest --> Deploy: pass
        Backtest --> Optimize: fail
        Deploy --> [*]
    }
```



---



## 5. Tier Architecture: Frontend & Backend



### 5.1 Responsibility Boundary

```mermaid
flowchart LR
    subgraph Frontend["Frontend (Thin Client)"]
        D[Dashboards]
        M[Bot Monitor]
        K[Kill Switch]
        C[Config UI]
        A[AI Chat]
    end

    subgraph Backend["Backend (Single Source of Truth)"]
        API[REST + WebSocket API]
        BOT[Autonomous Bot]
        RAG[RAG + LLM]
        QUANT[Quant Engine]
        BROKER[Broker Adapter]
        LEARN[Learning Engine]
    end

    Frontend <-->|JSON / WSS| API
    API --> BOT
    BOT --> RAG
    BOT --> QUANT
    BOT --> BROKER
    BOT --> LEARN
```





### 5.2 Frontend Responsibilities


| Module                 | Responsibility                                                                                                                      | Backend Dependency       |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| **Bot dashboard**      | Live P&L, win rate, Sharpe, drawdown, regime label, `EXECUTION_MODE` + `SUPERVISION_MODE` | WebSocket + REST metrics |
| **Decision queue**     | Pre-approval packet cards; Approve / Reject / Ask AI (`supervised` primary; audit history in higher modes) | REST + `decisions.pending` WS (`Docs/UI_Dashboard.md`) |
| **Strategy views**     | Active signals, module weights, Greeks exposure                                                                                     | REST strategy state      |
| **Trade monitor**      | Trade log, fills, open positions, mechanical hedge activity                                                                         | WebSocket trade events   |
| **Recommendations**    | Top-3 ranked instruments with **complete insight packets** (P1 fields + score breakdown + strategy panels); only candidates with post-learning confidence ≥ **80%** (`min_recommendation_confidence`); same-cycle ranked fallback auto-execute only when `SUPERVISION_MODE=fully_autonomous` (§6.4, §13.2.1) | REST `GET /recommendations` |
| **Kill switch**        | Pause bot; prevent new orders                                                                                                       | REST command endpoint    |
| **Configuration**      | Live data feed URLs, **strategy ↔ feed bindings**, **option strategy trade inputs**, **third-party broker connections**, thresholds, **supervision promotion** | REST CRUD                |
| **AI assistant (user chatbot)** | RAG-powered Q&A over the four domain PDFs; on-demand trade/decision explanations; permanent final-UI surface at `/chat` | REST `POST /api/v1/chat` (§7.7) |
| **Adaptation history** | Parameter changes, backtest results                                                                                                 | REST learning logs       |


**Frontend must never:**

- Hold broker API keys or credentials
- Perform quantitative calculations
- Call broker APIs directly



### 5.3 Backend Responsibilities


| Service Domain            | Responsibility                                                                                              |
| ------------------------- | ----------------------------------------------------------------------------------------------------------- |
| **API layer**             | REST endpoints, WebSocket channels, request validation                                                      |
| **Bot scheduler**         | Market-hours loop: observe → analyze → decide → execute → learn                                             |
| **RAG & LLM**             | Ingestion, retrieval, Groq-powered reasoning, response generation                                           |
| **Market data**           | URL registry, **live feed polling/streaming**, parse, normalize, freshness validation, **strategy binding** |
| **Integrations**          | Third-party adapter registry: broker (paper), data providers; credential vault; health checks               |
| **Quantitative engine**   | All strategy modules, signal generation, Greeks, risk                                                       |
| **Decision orchestrator** | Signal fusion, AI validation, confidence scoring                                                            |
| **Order management**      | Order builder, pre-trade risk gates, broker routing                                                         |
| **Broker adapter**        | Auth, submit/cancel, position sync (ICICI Direct live; paper via `paper_sim`)                                                             |
| **Learning engine**       | Metrics, optimization, reweighting, regime adaptation                                                       |
| **Persistence**           | Trades, config, analytics, vector store coordination                                                        |
| **Auth & secrets**        | Broker keys, Groq API key—server-side only                                                                  |




### 5.4 Repository Layout (Standalone Deployment Folders)

The repository uses **two standalone top-level folders**—`frontend/` and `backend/`—each self-contained with its own dependencies, build configuration, and deployment target. This layout enables independent CI/CD: **paper** deploys to **Vercel** + **Railway** (§17.0); **live** deploys both folders as **Cloud Run** services via Cloud Build (§17.5, §17.8).

```
Project_Volatality_Trading_by_Cursor/
├── infra/                      # Cloud provisioning specs & env templates
│   ├── cloud-inventory.yaml    # Canonical GCP live inventory (§17.8)
│   ├── provision/
│   │   └── PROVISIONING.md     # Step-by-step GCP setup (Cloud Run, Cloud SQL, Memorystore)
│   ├── gcp/                    # Cloud Build triggers, Cloud Run service YAML (§17.8)
│   └── env/
│       ├── railway.paper.env.example   # Paper backend vars (Railway)
│       ├── vercel.paper.env.example    # Paper frontend vars (Vercel)
│       ├── gcp.staging.env.example
│       └── gcp.production.env.example
├── frontend/                   # → Paper: Vercel · Live: Cloud Run (Next.js)
│   ├── src/
│   │   ├── app/                # Next.js App Router pages
│   │   ├── components/         # UI components (dashboards, charts, chat)
│   │   ├── hooks/              # WebSocket, API hooks
│   │   ├── lib/                # API client, utils
│   │   └── types/              # Shared TypeScript types
│   ├── public/
│   ├── package.json
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── vercel.json             # Optional Vercel project config (paper)
│   └── cloudbuild.yaml         # Live: Cloud Buildpacks → Artifact Registry → Cloud Run
│
├── backend/                    # → Paper: Railway · Live: Cloud Run
│   ├── api/                    # FastAPI routers (REST + WebSocket)
│   ├── scheduler/              # Bot loop, market-hours orchestration
│   ├── knowledge/              # RAG ingestion + retrieval
│   ├── market_data/            # Live feed URL registry, poll scheduler, normalize, cache
│   ├── quant/                  # Strategy modules
│   ├── decision/               # Signal fusion, Groq LLM validation
│   ├── execution/              # Order builder, risk gate, broker adapter
│   │   ├── risk_gate.py
│   │   ├── circuit_breakers.py
│   │   └── auto_pause.py
│   ├── paper_sim/              # In-house paper ledger + automation (`Docs/Paper_Simulator.md`)
│   ├── integrations/           # Third-party adapter registry, credential vault, health checks
│   ├── learning/               # Metrics, optimization, adaptation
│   │   └── config_versioning.py
│   ├── analytics/              # Performance reports, attribution
│   ├── persistence/            # PostgreSQL models, Redis state
│   ├── config/                 # Environment, secrets, feature flags
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   ├── e2e/
│   │   └── chaos/              # §20.4.8 autonomy chaos scenarios
│   ├── scripts/
│   │   └── start_remote.sh     # Nixpacks / Buildpacks entrypoint (`backend.*` PYTHONPATH shim)
│   ├── main.py                 # FastAPI application entrypoint
│   ├── requirements.txt
│   ├── Procfile                # Buildpacks / Nixpacks process type
│   ├── nixpacks.toml           # Railway paper remote build (no Dockerfile)
│   ├── railway.toml            # Railway service config (paper)
│   ├── cloudbuild.yaml         # Cloud Buildpacks → Artifact Registry → Cloud Run (live)
│   └── .env.example
│
├── Docs/                       # Knowledge base docs, OSS references, and project docs
├── data/                       # Parquet replay archives (gitignored)
├── architecture.md
├── context.md
└── DECISIONS.md                # Living log of dated architectural decisions (§20.3)
```


| Folder      | Paper deploy target | Live deploy target         | Key Config Files                                                              |
| ----------- | ------------------- | -------------------------- | ----------------------------------------------------------------------------- |
| `frontend/` | **Vercel**          | **Cloud Run** (`VC-FE-01`) | `package.json`, `next.config.ts`, `vercel.json`; `cloudbuild.yaml` (Buildpacks, live) |
| `backend/`  | **Railway**         | **Cloud Run** (`VC-BE-*`)  | `nixpacks.toml`, `Procfile`, `railway.toml`, `requirements.txt`; `cloudbuild.yaml` (Buildpacks, live) |


**Cross-service communication (paper — Railway + Vercel):**

- Frontend reads `NEXT_PUBLIC_API_URL` (Vercel env, build-time) pointing to the Railway backend public URL
- Frontend opens WebSocket to `wss://<railway-host>/ws/...`
- Backend sets `CORS_ORIGINS` to the Vercel app URL(s) (and custom domain if any)
- No shared runtime code between folders; contract is the REST/WebSocket API (§15)

**Cross-service communication (live — GCP):** same contract with Cloud Run URLs / Load Balancing (§17.3–17.4).

---



## 6. Backend Service Architecture



### 6.1 Service Decomposition

The backend lives in the standalone `backend/` folder and is organized as a **modular monolith** for the initial build, with clear internal module boundaries that can be split into separate **processes** (not microservices) when uptime targets require it. MVP runs as a single Cloud Run service (`PROCESS_ROLE=all`: API + bot scheduler + all engines). Production uptime (§19) requires splitting into API and worker Cloud Run services from the same `backend/` folder (§6.1.4, §17.7).

```
backend/
├── api/                    # FastAPI routers (REST + WebSocket)
├── scheduler/              # Bot loop, market-hours orchestration
├── knowledge/              # RAG ingestion + retrieval
│   ├── ingestion/          # Markdown knowledge-doc pipeline stages 1–8
│   ├── vectorstore/        # ChromaDB client, collections, BM25 index
│   ├── retrieval/          # Hybrid search + reranking (stages 9–10)
│   └── evaluation/         # Ragas / DeepEval + golden_qa.jsonl (stage 14)
├── market_data/            # Live feed URL registry, poll scheduler, normalize, cache
│   ├── adapters/           # Per-provider feed parsers (§8.7)
│   └── replay/             # Parquet snapshot recorder + replay driver
├── quant/                  # Strategy modules
│   ├── stat_arb/
│   ├── volatility/
│   ├── gamma/
│   ├── vega/
│   ├── greeks/
│   ├── pricing/            # Black-Scholes pricing, implied vol, leg valuation
│   ├── strategy/           # Multi-leg strategy model, aggregation, P/L
│   └── risk/
├── decision/               # Signal fusion, Groq LLM validation, confidence
├── execution/              # Order builder, risk gate, broker adapter
│   ├── risk_gate.py
│   ├── circuit_breakers.py   # §11.4.1 portfolio breakers
│   ├── auto_pause.py         # §20.4.4 post-trade auto-pause
│   └── one_trade_scope.py    # §20.4.11 one discretionary entry per session
├── integrations/           # Third-party adapters, credential vault, health checks
├── learning/               # Metrics, optimization, adaptation
│   └── config_versioning.py  # §20.4.5 config snapshots + rollback
├── analytics/              # Performance reports, attribution
├── persistence/            # PostgreSQL models, Redis state
├── config/                 # Environment, secrets, feature flags
├── llm/                    # Groq client wrapper, prompts, model config
├── main.py                 # FastAPI entrypoint
├── Procfile                # Buildpacks / Nixpacks process type
├── nixpacks.toml           # Railway paper remote build
├── cloudbuild.yaml         # Cloud Buildpacks deploy config (live)
└── requirements.txt
```



### 6.1.1 Backend Deployment Configuration (`backend/`)

**Paper phase (default until live promotion):** Deploy `backend/` to **Railway** with **Nixpacks** (`EXECUTION_MODE=paper`), Railway Postgres + Redis add-ons, and `CORS_ORIGINS` set to the Vercel frontend URL(s). See §17.0 and `Docs/Paper_Simulator.md`.

**Live phase:** Deploy via Cloud Build **Buildpacks** → Artifact Registry → **Cloud Run** in `asia-south1` as below.

| File               | Purpose                                                                  |
| ------------------ | ------------------------------------------------------------------------ |
| `nixpacks.toml`    | Railway **Nixpacks** remote build (paper) — no Dockerfile; no local container runtime (`Docs/LOCAL_DEV.md`) |
| `Procfile`         | Process type for Nixpacks / Google Cloud Buildpacks                      |
| `scripts/start_remote.sh` | Remote entrypoint; shims `PYTHONPATH` for `backend.*` imports     |
| `railway.toml`     | Railway service / health / restart settings (paper; `builder = NIXPACKS`) |
| `cloudbuild.yaml`  | Cloud Buildpacks → Artifact Registry → Cloud Run (live)                  |
| `requirements.txt` | Python dependencies including `groq`, `fastapi`, `langchain`, `chromadb` |


**GCP managed services (live — same GCP project / VPC in `asia-south1`):**


| Service                                                     | GCP product                         | Role                                        |
| ----------------------------------------------------------- | ----------------------------------- | ------------------------------------------- |
| PostgreSQL 16                                               | **Cloud SQL for PostgreSQL**        | Trades, config, analytics, learning history |
| Redis 7                                                     | **Memorystore for Redis**           | Market data cache, bot state, pub/sub       |
| ChromaDB HTTP server                                        | **Cloud Run** + **Filestore** (NFS) | Vector store for RAG (persistent volume)    |
| Container images                                            | **Artifact Registry**               | `frontend`, `backend`, `chroma` images      |
| Secrets (`GROQ_API_KEY`, broker keys)                       | **Secret Manager**                  | Injected into Cloud Run at runtime          |


**Network (live):** Cloud Run services connect to Cloud SQL and Memorystore via **Serverless VPC Access connector** (private IP). Chroma is reachable on the VPC internal hostname. No database credentials in container images.

**Required backend environment variables (paper = Railway vars; live = Cloud Run + Secret Manager):**


| Variable                      | Source (paper / live)         | Description                                                    |
| ----------------------------- | ----------------------------- | -------------------------------------------------------------- |
| `GROQ_API_KEY`                | Railway secret / Secret Manager | Groq API authentication                                      |
| `GROQ_MODEL`                  | Service env                   | Model ID (e.g. `llama-3.3-70b-versatile`)                      |
| `DATABASE_URL`                | Railway Postgres / Secret Manager (Cloud SQL) | PostgreSQL connection string                 |
| `REDIS_URL`                   | Railway Redis / Secret Manager (Memorystore)  | Redis connection string                      |
| `CHROMA_HOST` / `CHROMA_PORT` | Service env                   | Chroma HTTP endpoint (optional on paper; required for live RAG)|
| `CHROMA_PERSIST_DIRECTORY`    | Service env (dev / paper)     | Embedded mode when no HTTP Chroma                              |
| `CORS_ORIGINS`                | Service env                   | Vercel URL(s) on paper; Cloud Run / custom domain on live      |
| `EXECUTION_MODE`              | Service env                   | `paper` on Railway; `live` only on GCP after promotion         |
| `ICICI_DIRECT_*` secrets         | Railway secret / Secret Manager | ICICI Direct Breeze API credentials (data on paper; orders on live) |
| `PROCESS_ROLE`                | Service env                   | Runtime role: `all` (default), `api`, or `worker` — see §6.1.4 |




### 6.1.2 Frontend Service Architecture (`frontend/`)

The frontend lives in the standalone `frontend/` folder. **Paper:** deploy to **Vercel** (Next.js native). **Live:** deploy to **Cloud Run** as a containerized Next.js app (standalone output). It is a thin client with no business logic.

```
frontend/
├── src/
│   ├── app/                    # App Router: dashboards, config, chat pages
│   ├── components/
│   │   ├── dashboard/          # P&L, win rate, Sharpe, drawdown widgets
│   │   ├── bot/                # Trade log, positions, kill-switch
│   │   ├── strategy/           # Option strategy simulator, legs, Greeks views
│   │   ├── chat/               # RAG-powered AI assistant
│   │   └── ui/                 # shadcn/ui primitives
│   ├── hooks/                  # useWebSocket, useBotStatus, useMetrics
│   ├── lib/
│   │   ├── api.ts              # REST client → Cloud Run backend API
│   │   └── ws.ts               # WebSocket client → Cloud Run backend API
│   └── types/                  # API response types
├── public/
├── package.json
├── next.config.ts              # output: 'standalone' for Cloud Run (Buildpacks)
├── cloudbuild.yaml             # Live: Cloud Buildpacks → Artifact Registry → Cloud Run
└── .env.example                # NEXT_PUBLIC_API_URL, NEXT_PUBLIC_WS_URL
```



### 6.1.3 Frontend Deployment Configuration (`frontend/`)

#### Paper — Vercel


| Setting              | Value                                                                 |
| -------------------- | --------------------------------------------------------------------- |
| **Platform**         | **Vercel**                                                            |
| **Build**            | Vercel: `npm ci` → `next build` (root `frontend/`)                    |
| **Scaling**          | Platform-managed CDN + serverless / Node runtime                      |
| **Custom domain**    | Optional via Vercel Domains                                           |


#### Live — Cloud Run (`VC-FE-01`)


| Setting              | Value                                                                 |
| -------------------- | --------------------------------------------------------------------- |
| **Platform**         | **Cloud Run** (`VC-FE-01`)                                            |
| **Build**            | Cloud Build: `npm run build` → **Cloud Buildpacks** → Artifact Registry |
| **Runtime**          | Next.js standalone server (`node server.js`)                          |
| **Scaling**          | `min-instances=0` (staging) / `min-instances=1` (production optional) |
| **Ingress**          | All traffic; HTTPS termination at Cloud Run / Load Balancer           |
| **Custom domain**    | Optional via Cloud Load Balancing + Cloud DNS (§17.8)                 |


**Required frontend environment variables (Vercel build env on paper; Cloud Run on live):**


| Variable              | Description                                                                 |
| --------------------- | --------------------------------------------------------------------------- |
| `NEXT_PUBLIC_API_URL` | Backend API URL — Railway HTTPS on paper; Cloud Run URL on live             |
| `NEXT_PUBLIC_WS_URL`  | Backend WebSocket URL — `wss://` Railway host on paper; Cloud Run on live   |




### 6.1.4 Process Roles & Health Endpoints

The same `backend/` codebase supports multiple runtime roles via `PROCESS_ROLE`, enabling a single-container MVP and a split-process production topology without code forks.

#### Process roles


| `PROCESS_ROLE`  | Starts                          | Start command                                          | Cloud Run service (production) |
| --------------- | ------------------------------- | ------------------------------------------------------ | ---------------------------- |
| `all` (default) | FastAPI + bot scheduler         | `uvicorn main:app` (scheduler started in app lifespan) | MVP: one `trading` service   |
| `api`           | FastAPI only (REST + WebSocket) | `uvicorn main:app`                                     | `trading-api`                |
| `worker`        | Bot scheduler loop only         | `python -m scheduler.run`                              | `trading-worker`             |


**Module ownership by role:**


| Module                                            | `api`                                | `worker`                    |
| ------------------------------------------------- | ------------------------------------ | --------------------------- |
| `api/` (routers, WebSocket)                       | ✓                                    | —                           |
| `scheduler/`, `quant/`, `decision/`, `execution/` | —                                    | ✓                           |
| `market_data/` (poll scheduler)                   | read via cache                       | ✓ (poll + normalize)        |
| `knowledge/retrieval`                             | ✓ (chat, explain)                    | ✓ (pre-trade RAG)           |
| `knowledge/ingestion`                             | trigger only (`POST /api/v1/ingest`) | runs job (or Celery worker) |
| `persistence/`, `integrations/`                   | ✓                                    | ✓                           |


**Inter-process communication:** Shared PostgreSQL + Redis. Bot events (trade fills, decision logs, status changes) publish on Redis pub/sub channel `bot:events`; the API subscribes and forwards to WebSocket clients.

#### Redis leader lock

Only one bot scheduler may run at a time. Before entering the trading loop, the worker acquires a Redis distributed lock:


| Key          | TTL                     | Purpose                                                                |
| ------------ | ----------------------- | ---------------------------------------------------------------------- |
| `bot:leader` | 30s (renewed each tick) | Prevents duplicate schedulers across replicas or misconfigured deploys |


If lock acquisition fails, the worker exits with a non-zero status (Cloud Run restarts the container; Cloud Monitoring alert fires). The `api` role never acquires this lock.

#### Health endpoints


| Endpoint                   | Role        | Purpose                                                                                      |
| -------------------------- | ----------- | -------------------------------------------------------------------------------------------- |
| `GET /health`              | all         | Aggregate liveness; role-aware (both sub-checks during market hours when `PROCESS_ROLE=all`) |
| `GET /health/api`          | api, all    | FastAPI process responsive                                                                   |
| `GET /health/bot`          | worker, all | Scheduler alive: last tick, mode, leader status                                              |
| `GET /health/integrations` | all         | Per-integration status (broker, feeds, Groq, Chroma) — existing                              |


`GET /health/bot` **response schema:**

```json
{
  "status": "ok",
  "scheduler_mode": "active",
  "last_tick_at": "2026-06-29T14:32:01Z",
  "last_trade_at": "2026-06-29T14:28:15Z",
  "expected_tick_interval_s": 60,
  "missed_ticks": 0,
  "leader": true
}
```

**Status rules:**


| `status`   | Condition                                                                                   |
| ---------- | ------------------------------------------------------------------------------------------- |
| `ok`       | Last tick within `expected_tick_interval_s`; `leader=true` (when role is `worker` or `all`) |
| `degraded` | `missed_ticks == 1`, or `scheduler_mode=paused` (intentional operator pause)                |
| `down`     | `missed_ticks >= 2`, `leader=false`, or scheduler process not running                       |


**Cloud Run startup / liveness probe path by role:**


| `PROCESS_ROLE` | HTTP probe path   | Cloud Run settings                                                           |
| -------------- | ----------------- | ---------------------------------------------------------------------------- |
| `all`          | `/health`         | `min-instances=1` during market hours; CPU always allocated (no CPU throttling) |
| `api`          | `/health/api`     | Stateless; scale `0–N` by request concurrency                                |
| `worker`       | `/health/bot`     | **`max-instances=1`**; `min-instances=1`; CPU always allocated               |


External uptime monitors (§17.7) should probe `/health/bot` on the worker service during market hours.

### 6.2 Bot Scheduler Modes


| Mode                 | Trigger                        | Behavior                                                                                      |
| -------------------- | ------------------------------ | --------------------------------------------------------------------------------------------- |
| **Active**           | Default during market hours    | Full trading loop; discretionary path follows `SUPERVISION_MODE` (§6.2.2); one trade at a time (§20.4.11) |
| **Learning**         | Adaptation cycle initiated     | Pause new trades; run optimization + backtest                                                 |
| **Reduced exposure** | Drawdown / metric breach       | Trade at lower size; recovering                                                               |
| **Paused**           | Kill-switch or critical breach | No new orders; manage existing positions                                                      |




### 6.2.1 Execution Modes (Graduated Autonomy)

Autonomy is **ramped deliberately** — not full broker submission on day one. Mode is stored in PostgreSQL `configuration` (API-adjustable, audit-logged); default at first deploy is `shadow`.


| `EXECUTION_MODE` | Submit path                                   | Purpose                                                    |
| ---------------- | --------------------------------------------- | ---------------------------------------------------------- |
| `shadow`         | **No** — log decisions and would-be ICICI Direct orders only | Validate full pipeline without capital risk                |
| `paper`          | **No** ICICI Direct sandbox — in-house **`paper_sim`** (ICICI Direct marks + local fills); adapter `paper` is dry-run only | Development and validation (MVP default after shadow week) |
| `live`           | Yes — ICICI Direct Breeze API `place_order`         | Real NSE / BSE / NFO capital (micro-size first); extra gates in §20.4.10 |


**Promotion path (required sequence):** paper rehearsal → supervised → semi → full autonomy → live


| Stage                                        | Requirement before advancing                                  |
| -------------------------------------------- | ------------------------------------------------------------- |
| Shadow → Paper-sim (single module)           | ≥ 1 week shadow run; zero pipeline errors; operator review    |
| Paper-sim (single module) → Paper-sim (multi-module) | ≥ **30 closed trades** per enabled module; risk gates passing |
| Paper-sim (multi-module) → Paper-sim soak    | All Phase 2 modules enabled; integration health green         |
| Paper-sim soak → Live                        | 2–4 week soak passes §2.2 metrics; chaos tests pass (§22.1); micro-size + circuit breakers |


Per-module enablement uses `strategy_enabled` flags in `configuration` — the optimizer may reweight modules but **cannot auto-enable** a new module (§20.4.6).

### 6.2.2 Supervision Modes (Supervised → Semi → Autonomous)

Discretionary entries follow a **second graduated axis** independent of `EXECUTION_MODE`. Paper fills require `EXECUTION_MODE=paper` (routed to **`paper_sim`**); ICICI Direct `place_order` requires `EXECUTION_MODE=live`. Who (or what) authorizes a discretionary entry is controlled by `SUPERVISION_MODE`.

**Default at Phase 2 (paper bot):** `SUPERVISION_MODE=supervised` on paper-sim — aligned with `Docs/Trading_Strategies.md` (Supervised Execution Runbook) and `Docs/UI_Dashboard.md`.


| `SUPERVISION_MODE` | Discretionary entries | Operator role | UI primary surface |
| ------------------ | --------------------- | ------------- | ------------------ |
| **`supervised`** | Queue for operator Approve / Reject; expired decisions do **not** auto-submit (`approval_timeout_min`, default 15) | Per-trade approval | Decision queue (`/decisions`) |
| **`semi_autonomous`** | Auto-submit when confidence ≥ `semi_auto_confidence_min` (default **0.85**) and all gates pass; otherwise queue | Async review + override / kill-switch | Mixed: auto-submit stream + residual queue |
| **`fully_autonomous`** | Auto-submit when all gates pass; recommendations screen uses ranked fallback #1 → #2 → #3 (§6.4) | Monitor-only (dashboards, alerts, kill-switch) | Recommendations + audit history |


| Aspect | Behavior |
| ------ | -------- |
| **Mechanical hedges** | Delta drift, stop-loss, and circuit-breaker closes **always** bypass the discretionary path — automated in every supervision mode (§10.6) |
| **Fail-safe on anomaly** | Auto-pause, drawdown breach, or kill-switch **pauses** new discretionary entries until operator resume (§20.4.4) |
| **Demotion** | Operator (or auto-pause policy) may demote `fully_autonomous` → `semi_autonomous` → `supervised` at any time; audit-logged |

**Promotion path (required sequence — after `EXECUTION_MODE=paper` / paper-sim is already enabled):**


| Stage | Requirement before advancing |
| ----- | ---------------------------- |
| `supervised` → `semi_autonomous` | ≥ **30 closed** supervised paper-sim trades; win rate / profit factor within §2.2 bands; zero unexplained gate bypasses; operator checklist sign-off |
| `semi_autonomous` → `fully_autonomous` | ≥ **30 closed** semi-auto trades; override rate below configured max; 2-week soak without critical auto-pause; operator checklist sign-off |
| Any mode → demote | Immediate on operator action, or automatic on repeated auto-pause / circuit-breaker trips (§20.4.4) |
| Full autonomy soak → `EXECUTION_MODE=live` | Separate ICICI Direct path; micro-size + §20.4.10 gates — not a flip of the paper ledger (`Docs/Paper_Simulator.md`) |

**Configuration keys:**

| Key | Default | Purpose |
| --- | ------- | ------- |
| `SUPERVISION_MODE` | `supervised` | Who authorizes discretionary entries |
| `approval_timeout_min` | `15` | Pending decision TTL in `supervised` (no auto-submit on expiry) |
| `semi_auto_confidence_min` | `0.85` | Minimum confidence for auto-submit in `semi_autonomous` |
| `EXECUTION_MODE` | `shadow` → `paper` (paper-sim) → `live` | Submit path: log-only → local ledger → ICICI Direct (§6.2.1) |
| `SIMULATE_FIRST_RANK_FAILURE` | `true` (dev) | paper-sim / adapter stub rejects rank #1 to validate fallback path (§6.4); relevant only in `fully_autonomous` |

**API:**

| Method | Endpoint | Purpose |
| ------ | -------- | ------- |
| `GET` | `/api/v1/bot/supervision` | Current `SUPERVISION_MODE` + promotion checklist status |
| `PUT` | `/api/v1/bot/supervision` | Promote / demote (audit-logged; checklist gates on promote) |
| `GET` | `/api/v1/decisions/pending` | Approval queue (`supervised` / residual `semi_autonomous`) |
| `POST` | `/api/v1/decisions/{id}/approve` | Operator approve → paper-sim or ICICI Direct submit |
| `POST` | `/api/v1/decisions/{id}/reject` | Operator reject → no submit; log reason |

### 6.3 Decision Orchestration Sequence

End-to-end bot cycle: **observe → analyze → decide → route by supervision mode → risk gate → execute → learn**. Boxes are color-coded by role; arrows show data / control flow.

```mermaid
flowchart TB
    %% ── Phase 1: Observe → Analyze → Decide ──
    subgraph P1["1. OBSERVE to ANALYZE to DECIDE"]
        direction LR
        S["Bot Scheduler<br/>market-hours loop"]
        MD["Market Data<br/>OHLCV / chains / vol surface"]
        Q["Quant Engine<br/>all strategy modules"]
        R["RAG Retrieval<br/>top-k chunks + citations"]
        AI["AI Decision Engine<br/>fuse signals + RAG"]
        DEC{"Decision packet<br/>action / confidence / explanation"}

        S -->|"fetch"| MD
        MD -->|"OHLCV + surface"| Q
        Q -->|"signals + metrics"| R
        R -->|"chunks + citations"| AI
        AI -->|"decision"| DEC
    end

    %% ── Phase 2: Route by signal type + SUPERVISION_MODE ──
    subgraph P2["2. ROUTE BY SIGNAL TYPE + SUPERVISION_MODE"]
        direction TB
        ROUTE{"Signal type<br/>+ SUPERVISION_MODE?"}

        subgraph SUP["Supervised — discretionary + risk pass"]
            direction LR
            WS1["WebSocket<br/>decisions.pending"]
            OP["Operator / Queue<br/>Approve or Reject"]
            SUP_OK{"Approved?"}
            SUP_NO["Emit decision log<br/>no trade"]
            WS1 --> OP --> SUP_OK
            SUP_OK -->|"rejected / expired"| SUP_NO
        end

        subgraph SEMI["Semi-autonomous — confidence at or above threshold"]
            SEMI_GO["Auto-submit path<br/>async operator review"]
        end

        subgraph FULL["Fully autonomous — discretionary + risk pass"]
            FULL_GO["Auto-submit path<br/>ranked fallback section 6.4"]
        end

        subgraph MECH["Mechanical hedge + risk pass"]
            MECH_GO["Hedge fast path<br/>rule-based"]
        end

        REJECT["Rejected / gate fail<br/>Emit decision log — no trade"]

        ROUTE -->|"supervised"| WS1
        ROUTE -->|"semi_autonomous"| SEMI_GO
        ROUTE -->|"fully_autonomous"| FULL_GO
        ROUTE -->|"mechanical hedge"| MECH_GO
        ROUTE -->|"rejected"| REJECT
    end

    %% ── Phase 3: Risk → Execute → Learn ──
    subgraph P3["3. RISK GATE to EXECUTE to LEARN"]
        direction LR
        RG["Risk Gate<br/>pre-trade + one-trade gate 20.4.11"]
        EX["Broker Adapter<br/>paper_sim / ICICI Direct"]
        FILL["Fill confirmation"]
        L["Learning Engine<br/>log outcome"]
        WS2["WebSocket<br/>trade / decision event"]

        RG -->|"Approved"| EX
        EX --> FILL
        FILL --> L
        L --> WS2
        EX -.->|"async trade event"| WS2
    end

    DEC --> ROUTE
    SUP_OK -->|yes| RG
    SEMI_GO --> RG
    FULL_GO --> RG
    MECH_GO --> RG
    SUP_NO --> WS2
    REJECT --> WS2

    %% ── Color classes ──
    classDef scheduler fill:#1e3a5f,stroke:#60a5fa,stroke-width:2px,color:#f0f9ff
    classDef market fill:#064e3b,stroke:#34d399,stroke-width:2px,color:#ecfdf5
    classDef quant fill:#4c1d95,stroke:#a78bfa,stroke-width:2px,color:#f5f3ff
    classDef rag fill:#7c2d12,stroke:#fb923c,stroke-width:2px,color:#fff7ed
    classDef ai fill:#831843,stroke:#f472b6,stroke-width:2px,color:#fdf2f8
    classDef decision fill:#312e81,stroke:#818cf8,stroke-width:3px,color:#eef2ff
    classDef route fill:#1e293b,stroke:#94a3b8,stroke-width:3px,color:#f8fafc
    classDef supervised fill:#1e40af,stroke:#93c5fd,stroke-width:2px,color:#eff6ff
    classDef semi fill:#0e7490,stroke:#67e8f9,stroke-width:2px,color:#ecfeff
    classDef full fill:#047857,stroke:#6ee7b7,stroke-width:2px,color:#ecfdf5
    classDef mech fill:#a16207,stroke:#fde047,stroke-width:2px,color:#fefce8
    classDef risk fill:#9a3412,stroke:#fdba74,stroke-width:2px,color:#fff7ed
    classDef broker fill:#134e4a,stroke:#2dd4bf,stroke-width:2px,color:#f0fdfa
    classDef learn fill:#365314,stroke:#a3e635,stroke-width:2px,color:#f7fee7
    classDef reject fill:#7f1d1d,stroke:#f87171,stroke-width:2px,color:#fef2f2

    class S scheduler
    class MD market
    class Q quant
    class R rag
    class AI ai
    class DEC,ROUTE decision
    class WS1,WS2,OP supervised
    class SUP_OK route
    class SEMI_GO semi
    class FULL_GO full
    class MECH_GO mech
    class RG risk
    class EX,FILL broker
    class L learn
    class SUP_NO,REJECT reject
```

**Legend**

| Color | Role |
| ----- | ---- |
| Blue / slate | Scheduler, routing diamonds, WebSocket / operator |
| Green | Market data, fully-autonomous path, broker fills |
| Purple | Quant engine |
| Orange | RAG retrieval |
| Pink | AI decision engine |
| Amber | Mechanical hedge fast path |
| Teal / cyan | Semi-autonomous path |
| Lime | Learning engine |
| Red | Reject / no-trade log |



### 6.4 Autonomous Recommendation Execution (Ranked Fallback)

The ranked-fallback path applies only when **`SUPERVISION_MODE=fully_autonomous`** and `EXECUTION_MODE` ∈ {`paper`, `live`} (paper-sim or ICICI Direct). In `supervised` and `semi_autonomous`, `GET /api/v1/recommendations` returns the top-3 list **without** inline submit (`autonomous_execution` is null / omitted); the operator uses the decision queue (or semi-auto stream) instead.

When fully autonomous, the **recommendations screen** triggers discretionary entry without operator approval. Recommendations are generated and the ranked fallback trade is opened **in the same request cycle** — initial page load (SSR) and client refresh both use a single `GET /api/v1/recommendations` call. There is **no deliberate delay** between rendering recommendations and opening a trade: no post-render client `useEffect`, no polling, and no timer between recommend and submit.

Only instruments with **post-learning confidence ≥ 80%** (`execution_constraints.min_recommendation_confidence`, default **0.80**) are eligible for the ranked list; the top-3 is taken from that filtered set.

**Ranked fallback algorithm:**

```
GET /api/v1/recommendations
        │
        ├─ Generate top 3 ranked instruments
        │
        └─ immediately run ranked fallback on that same list
        │
        ▼
Response: RecommendationResponse + autonomous_execution
        │
For rank in [1, 2, 3]:
        │
        ├─ Pre-submit checks (gates, blocked strategy, one-trade scope §20.4.11)
        │       └─ fail → log attempt, try next rank
        │
        ├─ Broker adapter: paper submit (§11.1)
        │       └─ reject → log attempt, try next rank
        │
        └─ success → lock one-trade scope, return trade_id, stop
        │
        ▼
All ranks failed → no trade opened; full attempt log returned
```

**Execution timing:**

| Event | Behavior |
| ----- | -------- |
| Initial page load (`/recommendations`) | Server fetches `GET /recommendations`; response includes recommendations **and** `autonomous_execution` before HTML is sent |
| "Refresh analysis" | Client calls `GET /recommendations`; updates recommendations **and** execution result in one state update |

**Frontend behavior (`frontend/src/components/recommendations/`):**

| Component | Responsibility |
| --------- | -------------- |
| `RecommendationsView` | SSR initial + client refresh: single fetch carries recommendations and execution together; hosts complete insight layout |
| `Top3Comparison` | At-a-glance comparison table (rank, strategy, score, confidence, IV vs GARCH, IV z, primary signal) |
| `RecommendationCard` | **Complete insight packet** per rank — tabbed Overview / Score / Gates / Logic trail / Plan & risks / P1 checklist; per-rank execution status |
| `StrategyInsightPanel` | Strategy-family panel (simple vol / gamma / vega) mirroring `UI_Dashboard.md` strategy panels |
| `AutonomousTradeExecutor` | Display-only panel for `autonomous_execution` returned with recommendations (no client-side execute trigger) |
| `FeedStatusPanel` / `NewsPanel` | Feed health + **Market_News**-driven sentiment overlay that informed ranking (§8.8) |

**Complete insight packet (per `InstrumentRecommendation`):**

Each of the top-3 cards exposes a full operator-facing packet aligned with `Trading_Parameters.md` Part P1 and ranking transparency:

| Section | Fields | Purpose |
| ------- | ------ | ------- |
| Header | `rank`, `underlying_symbol`, `confidence`, `score`, strategy badges, `why_this_rank` | Identity + why this rank vs peers |
| Market condition (P1.3) | `market_summary`, `parameters.*` (spot, IV, GARCH, z-score, premium, DTE, volume, OI, spread) | Regime / vol context |
| Strategy fit (SH-4) | `strategy.*`, `StrategyInsightPanel`, rejected alternatives | Why this strategy over others |
| Hedge (P1.5) | `hedge.method`, `greek_targets`, `structure_note` | Construction summary |
| Economics (P1.6) | `economics.*` (margin, budget cap, premium, slippage, edge note) | Retail INR sizing |
| Score breakdown | `score_breakdown` (base, strategy/liquidity boosts, spread penalty, components[]) | Transparent ranking |
| Gates | `parameter_gates[]` | T1–T16 / L3.3 pass-fail |
| Logic trail | `complete_logic[]` | Step-by-step decision audit |
| Plan & risks (P1.7–P1.9) | `exit_plan`, `event_risks[]`, `failure_modes[]` | Exit + what can break |
| P1 checklist | `insight_checklist[]` | Confirms packet completeness |

**Configuration:**

| Key | Default (current build) | Purpose |
| --- | ----------------------- | ------- |
| `SIMULATE_FIRST_RANK_FAILURE` | `true` (dev) | paper-sim / adapter stub rejects rank #1 to validate fallback path |
| `execution_constraints.min_recommendation_confidence` | **0.80** | Post-learning confidence floor — only instruments with confidence ≥ **80%** are recommended (top-3 is chosen from that set) |

Candidates that pass retail gates and strategy selection but fall below this floor are excluded from `recommendations[]` and called out in `analysis_notes`.

**API response schema (`RecommendationResponse`):**

| Field | Type | Description |
| ----- | ---- | ----------- |
| `recommendations` | `InstrumentRecommendation[]` | Top 3 ranked instruments, each with complete insight packet |
| `feed_sources` / `market_news` / `analysis_notes` | … | ICICI Direct feed health + **Market_News** sentiment context for the scan (§8.8–8.9) |
| `autonomous_execution` | `AutonomousExecutionResult?` | Ranked fallback result from the same request cycle (fully autonomous only) |

**`InstrumentRecommendation` insight fields (beyond identity/score):**

| Field | Type | Description |
| ----- | ---- | ----------- |
| `market_summary` | `string` | P1.3 market condition narrative |
| `score_breakdown` | `ScoreBreakdown` | Base / boosts / penalty / component lines |
| `hedge` | `HedgeInsight` | P1.5 method, Greek targets, structure |
| `economics` | `TradeEconomicsInsight` | P1.6 margin, budget, premium, slippage |
| `why_this_rank` | `string` | Peer-relative ranking explanation |
| `insight_checklist` | `string[]` | P1 completeness checklist for UI |
| `complete_logic` / `exit_plan` / `event_risks` / `failure_modes` | … | Decision trail + P1.7–P1.9 |

**`AutonomousExecutionResult` fields:**

| Field | Type | Description |
| ----- | ---- | ----------- |
| `executed` | `boolean` | Whether any rank opened a trade |
| `selected_rank` | `int?` | Winning recommendation rank (1–3) |
| `trade_id` | `string?` | Broker trade identifier on success |
| `underlying_symbol` | `string?` | Symbol of opened trade |
| `attempts` | `TradeAttemptResult[]` | Per-rank success/failure log |
| `message` | `string` | Human-readable summary |

**Implementation:** `backend/services/recommendation_engine.py`, `backend/models/recommendations.py`, `backend/services/trade_executor.py`, `backend/routers/recommendations.py` (`GET /recommendations` with inline execute); frontend `lib/api.ts`, `components/recommendations/*`.

**Legacy endpoint:** `POST /api/v1/recommendations/execute-autonomous` remains for explicit re-execution against a fresh recommendation set; the recommendations screen does **not** use it.

---



## 7. Knowledge Layer: RAG & Strategy Ingestion Pipeline

> **Core insight:** For this project, ingestion pipeline quality—not LLM choice—determines RAG effectiveness. The knowledge base is built from **four domain PDFs** (`Volatility Trading.pdf`, `Gamma Scalping.pdf`, `Vega Scalping.pdf`, `Trading_Strategies.pdf`). Equations, tables, Greeks, diagrams, and domain terminology must be preserved accurately.



### 7.1 Pipeline Overview

The knowledge layer is a **domain knowledge engine**, not a simple document search tool. It powers:

- **User chatbot** in the final frontend UI (education, strategy Q&A, decision explanations) — §7.7
- Autonomous trade validation against playbook methodology
- Post-trade analysis and failure memory
- Cross-document concept comparison

```
PDF Documents (4 RAG sources — §3.2)
      │
      ▼
┌─────────────────────┐
│ 1. PDF Collection   │  Assign doc_id + version
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ 2. PDF Extraction   │  Text, tables, equations, structure
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ 3. Normalization    │  Clean headers/footers; preserve math
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ 4. Formula & Table  │  Detect equations; extract tables
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ 5. Structural Parse │  Chapter → Section → Subsection
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ 6. Semantic Chunking│  400–800 tokens, 10–20% overlap
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ 7. Metadata Enrich  │  Trading-specific taxonomy
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ 8. Embedding Gen    │  bge-m3 or text-embedding-3-large
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ 9. Vector Database  │  ChromaDB
└─────────┬───────────┘
          ▼
    ─── Query Time ───
          ▼
┌─────────────────────┐
│10. Hybrid Retrieval │  Dense vectors + BM25
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│11. Re-ranking       │  bge-reranker-large → top 5
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│12. Prompt Build     │  Context + citations + question
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│13. LLM Reasoning    │  Grounded answers (Groq), no hallucination
└─────────────────────┘
```



### 7.2 Ingestion Stage Specifications



#### Stage 1: Document Collection


| Requirement       | Implementation                                                             |
| ----------------- | -------------------------------------------------------------------------- |
| Document registry | Central manifest: `doc_id`, title, file path, version, ingest timestamp    |
| Version tracking  | Re-ingest on version bump; deprecate old chunks or version-tag collections |
| Source documents  | Four PDFs in §3.2: `Volatility Trading.pdf`, `Gamma Scalping.pdf`, `Vega Scalping.pdf`, `Trading_Strategies.pdf` |



#### Stage 2: PDF Extraction


| Tool / approach      | Role                                      |
| -------------------- | ----------------------------------------- |
| **PyMuPDF (fitz)**   | Fast text extraction                      |
| **pdfplumber**       | Table extraction                          |
| **Unstructured**     | Mixed document layouts                    |
| **Docling**          | AI-ready document parsing                 |
| **Tesseract OCR**    | Scanned/image pages only                  |

**Extract and preserve:**

- Titles, section headings, paragraphs, lists
- Tables (as structured data + text representation)
- Mathematical equations and Greek symbols
- Figure captions and page numbers
- Section anchors for citation



#### Stage 3: Document Normalization


| Operation              | Rule                                                                        |
| ---------------------- | --------------------------------------------------------------------------- |
| Remove headers/footers | Strip repeated page headers, footers, and page numbers                      |
| Fix line wraps         | Rejoin hyphenated and soft-wrapped lines without breaking equations         |
| Preserve math          | Keep LaTeX-like and Unicode math notation intact                            |
| Whitespace             | Collapse duplicate spaces within lines; preserve list indentation           |



#### Stage 4: Structural Parsing

Build a document tree:

```
Document
 └── Chapter
      └── Section
           └── Subsection
                └── Paragraph | Table | Equation | List
```

**Structural metadata per node:**

- `document_title`, `chapter`, `section`, `subsection`, `page`, `heading_path`



#### Stage 5: Semantic Chunking


| Parameter   | Value                                      | Rationale                                        |
| ----------- | ------------------------------------------ | ------------------------------------------------ |
| Strategy    | Meaning-based splits                       | Avoid arbitrary 500-char cuts through equations  |
| Target size | 400–800 tokens                             | Balance context richness vs. retrieval precision |
| Overlap     | 10–20%                                     | Preserve continuity across chunk boundaries      |
| Boundaries  | Definition, derivation, example, procedure | Each becomes a coherent retrieval unit           |


**Anti-patterns to avoid:**

- Splitting mid-equation or mid-table row
- Merging unrelated topics from adjacent sections
- Fixed-size chunking without structural awareness



#### Stage 6: Metadata Enrichment

Each chunk carries **filterable, trading-specific metadata** enabling precise retrieval:

```json
{
  "chunk_id": "doc-gamma_ch5_dynamic-hedging_c003",
  "document_id": "doc-gamma",
  "document": "Gamma Scalping",
  "version": "1.0",
  "chapter": "Chapter 5",
  "section": "Dynamic Hedging",
  "page": 132,
  "heading_path": "Gamma Scalping > Chapter 5 > Dynamic Hedging",
  "topic": "Gamma",
  "difficulty": "Advanced",
  "strategy": "Gamma Scalping",
  "concepts": ["Delta", "Gamma", "Theta"],
  "asset_class": "Equity Options",
  "math_models": ["Black-Scholes"],
  "risk_category": ["Execution Risk", "Volatility Risk"],
  "content_type": "procedure",
  "has_table": false,
  "has_equation": true
}
```

**Enrichment taxonomy:**


| Field           | Example Values                                                           |
| --------------- | ------------------------------------------------------------------------ |
| `strategy`      | Gamma Scalping, Vega Scalping, Volatility Trading, Trading Strategies    |
| `concepts`      | Delta, Gamma, Vega, Theta, IV, HV, Cointegration, Z-score                |
| `asset_class`   | Equity Options, Index Options, Futures                                   |
| `math_models`   | Black–Scholes, Ornstein–Uhlenbeck, Mean Reversion                        |
| `risk_category` | Model Risk, Liquidity Risk, Execution Risk, Volatility Risk              |
| `difficulty`    | Beginner, Intermediate, Advanced                                         |
| `content_type`  | definition, derivation, example, procedure, risk_note                    |


**Enrichment approach:**

1. Rule-based tagging from section headings and keyword dictionaries
2. LLM-assisted classification for ambiguous chunks (batch, offline)
3. Human review queue for low-confidence tags (optional, Phase 2)



#### Stage 7: Embedding Generation

**Pinned production stack** (do not use small/base BGE variants for this corpus):


| Role                     | Model                           | Notes                                                  |
| ------------------------ | ------------------------------- | ------------------------------------------------------ |
| **Embedding (primary)**  | `bge-m3`                        | Dense + sparse support; strong on technical literature |
| **Re-ranker**            | `bge-reranker-large`            | Cross-encoder on top-50 candidates → top-5             |
| **Embedding (fallback)** | `bge-large-en-v1.5`             | English-only fallback if m3 unavailable                |
| **Cloud alternative**    | OpenAI `text-embedding-3-large` | Optional; not default                                  |



| Model                  | Use Case                                         |
| ---------------------- | ------------------------------------------------ |
| **jina-embeddings-v3** | Alternative for technical literature (eval only) |


**Embedding payload:** chunk text + structural prefix (e.g., `[Gamma Scalping > Chapter 5 > Dynamic Hedging]`) to improve retrieval context.

#### Stage 8: Vector Database

**ChromaDB** is the sole vector store across all environments. Deployment mode varies by target:


| Environment          | Mode                                                               | Rationale                                                              |
| -------------------- | ------------------------------------------------------------------ | ---------------------------------------------------------------------- |
| Local development    | Embedded `PersistentClient` (`CHROMA_PERSIST_DIRECTORY`)           | Zero-config prototyping; same API as production                        |
| Production / staging | Chroma HTTP server on Cloud Run with **Filestore NFS** volume, or Chroma Cloud | Durable storage across deploys; metadata filtering via `where` clauses |


**Python client:** `chromadb` (native) or LangChain `Chroma` vectorstore wrapper.

**Storage schema per vector:**

- Dense embedding vector (stored in Chroma collection)
- Full metadata payload (§7.2 Stage 6) — filterable via Chroma `where` / `where_document`
- Raw chunk text (document field)
- BM25 keyword index maintained in application layer (`rank_bm25` over chunk corpus) for hybrid retrieval (§7.3)

**Collections:**


| Collection       | Purpose                             |
| ---------------- | ----------------------------------- |
| `knowledge_base` | Primary chunks from the four RAG PDFs |
| `failure_memory` | Losing trade contexts for avoidance |
| `trade_insights` | Post-trade RAG analysis summaries   |



### 7.3 Query-Time Retrieval Architecture

```mermaid
flowchart LR
    Q[Query] --> QE[Query Expansion]
    QE --> HF[Metadata Filters]
    HF --> HS[Hybrid Search]
    HS --> V[Vector Search]
    HS --> B[BM25 Search]
    V --> F[Reciprocal Rank Fusion]
    B --> F
    F --> RR[Re-ranker: bge-reranker-large]
    RR --> TOP[Top 5 Chunks]
    TOP --> PB[Prompt Builder]
    PB --> LLM[LLM Reasoning]
```





#### Stage 9: Hybrid Retrieval


| Method             | Strength              | Example                                        |
| ------------------ | --------------------- | ---------------------------------------------- |
| **Dense (vector)** | Conceptual similarity | "dynamic hedging frequency optimization"       |
| **Sparse (BM25)**  | Exact terminology     | "theta decay", "z-score", "Ornstein-Uhlenbeck" |


**Fusion strategy:** Reciprocal Rank Fusion (RRF) or weighted linear combination.

**Metadata filtering (pre-retrieval):**

- Filter by `strategy`, `concepts`, `difficulty` when query intent is classified
- Example: "gamma scalping retail limitations" → `strategy=Gamma Scalping`, `risk_category=Execution Risk`



#### Stage 10: Re-ranking

```
User Question → Top 50 candidates → Cross-encoder reranker → Top 5 → LLM
```


| Component | Recommendation                       |
| --------- | ------------------------------------ |
| Re-ranker | `bge-reranker-large`                 |
| Input     | Query + chunk text pairs             |
| Output    | Relevance score; top-5 passed to LLM |




#### Stage 11: Prompt Construction

Every prompt includes structured context blocks:

```
## Context

### Source 1
- Document: Gamma Scalping
- Chapter: Chapter 5
- Section: Dynamic Hedging
- Page: 132
- Content: [chunk text]

### Source 2
...

## Question
[user or system query]

## Instructions
- Answer using retrieved context only
- Cite document, chapter/section, and page when available
- State clearly if information is unavailable
- Explain equations step by step when relevant
```



#### Stage 12: LLM Reasoning Requirements (Groq)

Responses are generated via the **Groq API** using the model configured in `GROQ_MODEL`. The LLM must:

- Ground answers in retrieved context
- Explain equations clearly
- Compare concepts across documents when asked
- Cite source document, section, and page
- **Refuse to guess** when context is insufficient

**Dual consumers:** The same retrieval stack serves (1) the **user chatbot** and (2) the AI Decision Engine during signal validation.



#### Stage 13: Response Generation Format

High-quality responses include:

1. Direct answer
2. Mathematical explanation (when relevant)
3. Practical trading implications
4. Risks and assumptions
5. Source citations (document, section, page)



#### Stage 14: RAG Evaluation


| Metric            | Purpose                       | Tool             | CI Gate (initial) |
| ----------------- | ----------------------------- | ---------------- | ----------------- |
| Context Precision | Retrieved chunks are relevant | Ragas            | ≥ 0.80            |
| Context Recall    | Important chunks not missed   | Ragas            | ≥ 0.75            |
| Faithfulness      | Answer grounded in context    | Ragas / DeepEval | ≥ 0.85            |
| Answer Relevance  | Addresses the question        | Ragas            | ≥ 0.80            |
| Citation Accuracy | Correct doc/section/page refs | Custom eval      | ≥ 0.90            |


**Golden evaluation dataset** (`backend/knowledge/evaluation/golden_qa.jsonl`):

- **50–100 curated Q&A pairs** sourced from the four RAG PDFs
- Categories: definitions, equations, cross-document comparisons, retail-limitation scenarios
- Each row: `question`, `expected_chunk_ids[]`, `expected_citations[]`, `strategy_filter` (optional)
- Run on every ingest and in CI; **block RAG-gated trading** if faithfulness falls below gate

**Chunk regression tests** (`backend/tests/knowledge/`):

- Assert equations and Greek symbols survive PDF extraction and chunking
- Assert tables retain row/column structure after chunking
- Assert no mid-equation or mid-table splits across chunk boundaries
- Golden-file fixtures for known sections (e.g., gamma scalping hedge rules, vol smile definitions)



### 7.4 RAG Integration Points


| Consumer               | Query Type                                   | Retrieval Profile                           |
| ---------------------- | -------------------------------------------- | ------------------------------------------- |
| **User Chatbot (UI)**  | Operator / trader Q&A                        | Full hybrid + rerank; top-5 chunks          |
| **AI Decision Engine** | Validate signal against playbook methodology | Filter by strategy + concepts; top-3 chunks |
| **Learning Engine**    | Post-trade failure analysis                  | Filter by strategy + risk_category          |
| **Failure Memory**     | Store losing trade context                   | Write to `failure_memory` collection        |




### 7.5 Example Metadata-Enabled Queries


| Query                                                           | Filters Applied                                                     |
| --------------------------------------------------------------- | ------------------------------------------------------------------- |
| "Sections discussing Gamma and Theta together"                  | `concepts: [Gamma, Theta]`                                          |
| "Compare Vega risk across Volatility Trading and Vega Scalping" | `strategy: [Volatility Trading, Vega Scalping]`, `concepts: [Vega]` |
| "Retail limitations of gamma scalping"                          | `strategy: Gamma Scalping`, `risk_category: Execution Risk`         |
| "Entry rules from Trading Strategies playbook"                  | `document_id: doc-trading-strategies`                               |



### 7.6 RAG Quality Assurance & Collection Lifecycle



#### Re-ingest versioning


| Event              | Action                                                                                |
| ------------------ | ------------------------------------------------------------------------------------- |
| Document version bump | Tag old chunks `deprecated=true` in metadata; ingest new version with `version` field |
| Re-ingest complete | Rebuild BM25 index from active (non-deprecated) chunks                                |
| Rollback           | Re-enable prior version collection; deprecate failed ingest                           |


**BM25 ↔ Chroma sync:** The application-layer BM25 corpus must be rebuilt atomically after every ingest job. Ingest job emits `ingest.complete` event; retrieval layer refuses queries until BM25 rebuild finishes.

#### Faithfulness enforcement

- Decision and chat prompts require **citation blocks** in structured output
- Post-generation check: every factual claim must map to a retrieved `chunk_id`
- Unfaithful or uncited responses downgrade confidence and block autonomous execution



### 7.7 User Chatbot (Final UI Component)

The **user chatbot** is a permanent product surface in the final frontend—not a throwaway Phase 1 prototype. It is the primary human-facing consumer of the RAG pipeline.

#### Purpose

| Use case | Description |
| --- | --- |
| **Domain education** | Ask questions about volatility trading, gamma scalping, vega scalping, and consolidated strategy rules |
| **Cross-document Q&A** | Compare concepts across the four PDFs with citations |
| **Decision deep-dive** | From the supervised cockpit, **Ask AI** pre-loads decision context into chat (`Docs/UI_Dashboard.md`) |
| **On-demand explanations** | Clarify Greeks, hedge logic, retail limitations, and playbook procedures |

#### Frontend placement

| Item | Specification |
| --- | --- |
| **Route** | `frontend/` App Router page at `/chat` |
| **Nav** | Always available in final UI alongside dashboard, decisions, recommendations, config |
| **Components** | `frontend/src/components/chat/` — message list, composer, citation chips, strategy filter |
| **Entry points** | Global nav; **Ask AI** on pre-approval packets; optional deep-link with `?decision_id=` |

#### Backend contract

| Endpoint | Role |
| --- | --- |
| `POST /api/v1/chat` | Accept user message (+ optional filters / decision context); return grounded answer + citations |
| `POST /api/v1/knowledge/ingest` | Operator-triggered re-ingest of the four PDFs |
| `GET /api/v1/knowledge/status` | Ingest version, chunk counts per `doc_id`, last eval scores |

**Request shape (illustrative):**

```json
{
  "message": "When should I rebalance a gamma scalp?",
  "session_id": "uuid",
  "filters": { "strategy": "Gamma Scalping" },
  "decision_id": null
}
```

**Response shape (illustrative):**

```json
{
  "answer": "...",
  "citations": [
    {
      "document_id": "doc-gamma",
      "document": "Gamma Scalping",
      "section": "Dynamic Hedging",
      "page": 132,
      "chunk_id": "doc-gamma_ch5_dynamic-hedging_c003"
    }
  ],
  "faithfulness_ok": true
}
```

#### UX requirements

- Stream or return complete answers with **visible citations** (document + section + page)
- Optional **strategy filter** chips (Volatility / Gamma / Vega / Trading Strategies)
- Clear empty and error states when retrieval is empty or faithfulness check fails
- Do **not** expose broker credentials, order submission, or kill-switch controls through chat
- Chat never executes trades; it explains and educates only

#### Relationship to bot autonomy

| Mode | Chatbot behavior |
| --- | --- |
| All `SUPERVISION_MODE` values | Chat available for education and review |
| `supervised` | **Ask AI** on decision cards opens chat with packet context |
| `semi_autonomous` / `fully_autonomous` | Chat remains available; does not gate mechanical hedges |

---


## 8. Market Data Layer



### 8.1 Design Principle

Market data is **decoupled from strategy logic**. Operators register **live data feed URL** endpoints; the ingestion layer polls or streams, validates freshness, parses, and normalizes data into a unified internal schema consumed by quantitative modules and **OSS trade-input marking**.

### 8.1.1 Component Architecture

```mermaid
flowchart TB
    CFG[URL Registry Config] --> SCHED[Feed Scheduler]
    SCHED --> FETCH[HTTP / WebSocket Fetcher]
    FETCH --> PARSE[Format Parser]
    PARSE --> VAL[Validator + Freshness Check]
    VAL --> NORM[Normalizer]
    NORM --> CACHE[Redis Cache]
    NORM --> STORE[Time-Series Store]
    CACHE --> QE[Quant Engine]
    CACHE --> OSS[OSS Marking Engine]
    STORE --> QE
    BIND[Strategy Feed Bindings] --> SCHED
    NORM --> REPLAY[Replay Recorder]
    REPLAY --> PARQUET[(Parquet Archive)]
```





### 8.2 Live Data Feed URL Registry

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
      "stale_threshold_sec": 60,
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
      "stale_threshold_sec": 120,
      "auth": { "type": "bearer", "credential_ref": "icici_direct_breeze" }
    }
  ]
}
```

Register feeds for tradeable underlyings. For strategies that include **stock/underlying** legs, restrict to cash equities with spot ≤ ₹1000. For **options-only** strategies there is no underlying price cap (Part T). Index symbols in ICICI Direct’s instrument master may be bound only to options-only discretionary strategies.

**Auth:** Credentials referenced by `credential_ref` are stored encrypted server-side (env / secret manager)—never in the frontend or strategy JSON.

### 8.3 Normalized Output Schemas


| Data Type         | Fields                                                 | Consumers                               |
| ----------------- | ------------------------------------------------------ | --------------------------------------- |
| **OHLCV**         | symbol, timestamp, open, high, low, close, volume      | Stat arb, vol analysis                  |
| **Quote**         | symbol, timestamp, bid, ask, last, volume              | OSS `und_price`, stock leg marks        |
| **Option chain**  | symbol, expiry, strike, type, bid, ask, IV, OI, greeks | Gamma, vega, vol surface, OSS leg marks |
| **Vol surface**   | symbol, expiry, strike, IV, moneyness                  | Volatility module                       |
| **Index/futures** | symbol, timestamp, price, volume                       | Hedging, stat arb                       |




### 8.4 Responsibilities

1. Accept and store live feed URL mappings (instrument ↔ endpoint ↔ auth)
2. **Poll or stream** feeds on `refresh_interval_sec` during market hours; support WebSocket where provider allows
3. Parse heterogeneous formats (JSON, CSV, broker-specific)
4. Validate completeness, timestamps, and instrument identifiers; **reject stale data** beyond `stale_threshold_sec`
5. Cache hot data in Redis; persist historical series in PostgreSQL or Parquet
6. Expose normalized snapshots via `MarketDataService` (not raw URLs to quant modules)
7. Emit feed health metrics (last fetch, latency, error rate) for bot gating and frontend dashboard
8. **Record normalized snapshots** to Parquet for replay testing and walk-forward backtests (§8.7)



### 8.7 Feed Adapter Contract & Replay Mode



#### Feed adapter interface (`backend/market_data/adapters/`)

Every data provider implements a common parser contract:

```python
class FeedAdapter(Protocol):
    provider: str  # e.g. "icici_direct", "generic_json", "csv"
    def parse(self, raw: bytes, feed_config: DataFeed) -> NormalizedSnapshot: ...
    def validate_schema(self, payload: dict) -> bool: ...
```


| Adapter        | Input Format                       | Output                     |
| -------------- | ---------------------------------- | -------------------------- |
| `icici_direct`    | ICICI Direct Breeze API REST / WS JSON  | Quote, OHLCV, option chain |
| `generic_json` | Configurable JSONPath mapping      | Normalized snapshot        |
| `csv`          | CSV with column mapping            | OHLCV                      |


**JSON Schema validation:** Every fetch is validated against a per-`data_type` schema before normalization. Invalid payloads increment `feed.error_count` and do not update the cache.

#### SSRF protections (fetcher)


| Rule              | Implementation                                                 |
| ----------------- | -------------------------------------------------------------- |
| Domain allowlist  | Only pre-registered hostnames per feed                         |
| Block private IPs | Reject `10.x`, `172.16–31.x`, `192.168.x`, `127.x`, link-local |
| Timeout           | Max 10s connect + read per request                             |
| Response size cap | Max 10 MB per fetch                                            |




#### Stale-feed circuit breaker


| Condition           | Behavior                                                                    |
| ------------------- | --------------------------------------------------------------------------- |
| Single feed stale   | Block execution for strategies bound to that feed; emit `alerts.stale_feed` |
| All feeds stale     | Pause bot scheduler; require operator resume                                |
| Intermittent errors | Exponential backoff on poll; alert after 3 consecutive failures             |




#### Replay mode


| Mode       | Use                                                                                                |
| ---------- | -------------------------------------------------------------------------------------------------- |
| **Live**   | Poll registered URLs during market hours                                                           |
| **Replay** | Read normalized snapshots from Parquet by timestamp; drive quant + decision loop deterministically |


Replay enables offline integration tests, walk-forward backtests, and CI without market-hours dependency. Snapshots stored at `data/replay/{symbol}/{date}.parquet`.

### 8.5 Trade Input & Option Strategy Model (OSS)

All bot trades are defined and evaluated using the **Macroption Option Strategy Simulator (OSS)** input model (`Docs/OSS (1).xlsm`, `Docs/OSS_Guide (1).pdf`). This is a **first-class input channel** alongside market data URLs: operators configure global Black–Scholes–Merton pricing parameters and an **ordered list of legs** (call, put, or stock) with **no fixed leg-count limit**; the backend pricing and Greeks engines compute per-leg and portfolio-level metrics using OSS conventions. The OSS workbook UI shows five leg rows for manual what-if simulation—that is a spreadsheet layout constraint, **not** a limit on this system. A live strategy may start with an opening structure and **add legs over its lifecycle** (hedges, rolls, adjustments) until the trade is **successfully closed** (all positions flat or expired).

#### 8.5.1 Input Categories

```mermaid
flowchart TB
    subgraph Global["Global Parameters (OSS rows 3-4)"]
        VD[Valuation Date]
        VT[Valuation Time]
        UP[Und Price]
        DY[Div Yield - continuous]
        IR[Int Rate - continuous]
        FV[Flat Volatility flag]
        VOL[Volatility - when flat]
        DM[Display Mode]
    end

    subgraph ExpCatalog["Expiration Catalog (OSS Expirations sheet)"]
        EXP1[Effective expiration datetime 1..24]
    end

    subgraph Legs["Legs 1..N (OSS rows 8-16 are reference layout)"]
        L1[Position · Exp · Strike · Type · Initial Price]
        L2[Per-leg Vol Q · Contract Mult S]
    end

    subgraph Computed["Computed (OSS cols I-P, row 18)"]
        PL[Per-leg: Price · Value · P/L · Greeks · Leg Name]
        TOT[Strategy Totals]
    end

    Global --> PRICING[BSM Pricing Engine]
    ExpCatalog --> Legs
    Legs --> PRICING
    PRICING --> Computed
    Computed --> QE[Quant Modules]
    Computed --> RISK[Risk Gate]
    Computed --> EXEC[Order Builder]
```





#### 8.5.2 Global Market Parameters

Top-level inputs for the entire strategy (OSS Area 1). Dividend yield and interest rate are **percent per annum, continuously compounded** (OSS Guide §5).


| Field                       | Key                           | Type    | OSS Ref | Description                                     | Example      |
| --------------------------- | ----------------------------- | ------- | ------- | ----------------------------------------------- | ------------ |
| Valuation Date              | `eval_date`                   | date    | C3      | Pricing / P/L / Greeks as-of date (IST calendar day) | `2024-01-04` |
| Valuation Time              | `eval_time`                   | time    | C4      | Intraday component for DTE (**IST**)            | `10:35:00`   |
| Underlying Price            | `und_price`                   | decimal | G4      | Spot; same units as strike                      | `85.40`      |
| Dividend Yield              | `div_yield`                   | percent | J3      | Continuous yield; also convenience/foreign rate | `2.60`       |
| Interest Rate               | `int_rate`                    | percent | J4      | Continuous risk-free rate; tenor ≈ option life  | `4.00`       |
| Flat Volatility             | `flat_volatility`             | boolean | Q3      | One σ for all legs vs per-leg override          | `true`       |
| Volatility                  | `volatility`                  | percent | O4      | Annualized σ (std dev); used when flat vol on   | `28.40`      |
| Display Mode                | `display_mode`                | enum    | L4      | `per_share` or `total` for Value/P/L/Greeks     | `total`      |
| Underlying Symbol           | `underlying_symbol`           | string  | —       | Ticker; spot ≤ ₹1000 required if strategy includes stock/underlying | `SBIN`       |
| Default Contract Multiplier | `default_contract_multiplier` | int/null| Y8      | **India:** null / unused — size from NFO `lotsize` | `null` (OSS US workbook uses `100` for parity only) |
| Contract Multiplier Source  | `contract_multiplier_source`  | enum    | —       | `nfo_instrument_lotsize` (India) vs `oss_workbook_default` | `nfo_instrument_lotsize` |


**Combined datetime:** API may accept `eval_datetime` (ISO 8601) as a convenience alias for `eval_date` + `eval_time`. For Indian markets (NSE / NFO), interpret naive clock fields in **`Asia/Kolkata` (IST)** — e.g. OSS parity fixture `2024-01-04T10:35:00+05:30`. Prefer explicit `+05:30` (or `Z` only after converting from IST) so DTE matches the workbook.

#### 8.5.3 Option & Stock Leg Inputs

**Leg count:** There is **no maximum** on the number of legs per strategy. The OSS workbook exposes five leg rows for spreadsheet simulation; this bot persists legs as an **unbounded ordered list** in PostgreSQL (`option_legs`). A strategy may open with any number of legs and **accumulate more**—delta hedges, rolls, protective adjustments—across the trade lifecycle until **successful closure** (net flat or all legs expired/settled). Leg order does not affect pricing math; `leg_id` is a stable sequential index for display and audit.

| Field               | Key                   | Type     | Applies   | Description                                           | Example               |
| ------------------- | --------------------- | -------- | --------- | ----------------------------------------------------- | --------------------- |
| Leg ID              | `leg_id`              | int      | All       | Sequential index within strategy (1, 2, 3, …)         | `1`                   |
| Position            | `position`            | int      | All       | Signed contracts/shares (+ long, − short)             | `5`                   |
| Expiration ID       | `expiration_id`       | uuid/int | Call, Put | Reference to expiration catalog entry                 | `exp_006`             |
| Expiration          | `expiration`          | datetime | Call, Put | Effective expiry (when trading stops)                 | `2024-06-21T16:15:00` |
| Days to Expiry      | `days_to_expiry`      | decimal  | Call, Put | Computed from eval datetime                           | `169.24`              |
| Strike              | `strike`              | decimal  | Call, Put | Strike price                                          | `75.00`               |
| Type                | `type`                | enum     | All       | `call`, `put`, `stock` (`none` reserved for OSS empty-slot parity only) | `put`                 |
| Initial Price       | `initial_price`       | decimal  | All       | Entry price per share; positive; optional for what-if | `3.60`                |
| Per-Leg Volatility  | `leg_volatility`      | percent  | Call, Put | Used when `flat_volatility = false`                   | `28.40`               |
| Contract Multiplier | `contract_multiplier` | int      | All       | Override; null → ICICI Direct NFO `lotsize` (India)      | equity `lotsize`      |
| Share Equivalent    | `share_equivalent`    | int      | All       | Computed: `position × effective_multiplier`           | `lots × lotsize`      |
| Leg Name            | `leg_name`            | string   | All       | Display label, e.g. `+5 21Jun 75P`                    | `+5 21Jun 75P`        |
| Initial Cash Flow   | `initial_cf`          | decimal  | All       | Computed (see below)                                  | `-1800`               |


**Stock legs:** No strike or expiration. Used for covered calls, protective puts, gamma-scalp hedges. Price = `und_price`. Delta = `+1` (long) or `−1` (short) per share; gamma, theta, vega, rho = `0`.

**Initial cash flow formula (OSS column H):**

```
effective_multiplier = leg.contract_multiplier
  ?? angel_instrument_master.lotsize(symbol)   # India paper + live (nfo_lot_sizing)
  ?? strategy.default_contract_multiplier      # OSS workbook / what-if only (US-style 100)
initial_cf = −position × initial_price × effective_multiplier
```

(Debit negative, credit positive. Empty `initial_price` ⇒ `initial_cf = 0`; P/L equals position value.)

#### 8.5.4 Expiration Catalog

Stored separately (OSS "Expirations" sheet); up to **24** entries per underlying or globally.


| Field              | Key                  | Type     | Description                                  |
| ------------------ | -------------------- | -------- | -------------------------------------------- |
| Expiration ID      | `expiration_id`      | uuid     | Primary key                                  |
| Effective Datetime | `effective_datetime` | datetime | When option stops trading / settlement fixed |
| Display Name 1     | `display_name_short` | string   | Combo label, e.g. `Jun 2024`                 |
| Display Name 2     | `display_name_leg`   | string   | Leg label fragment, e.g. `21Jun`             |
| Underlying Symbol  | `underlying_symbol`  | string   | Optional scope                               |


**Rule:** Use the **effective** expiration (trading cessation), not necessarily the exchange calendar label (OSS Guide §4).

#### 8.5.5 Per-Leg Calculated Outputs

Computed by `backend/quant/pricing/` and `backend/quant/greeks/` on each evaluation cycle:


| Field | Key     | OSS Col | Description                               |
| ----- | ------- | ------- | ----------------------------------------- |
| Price | `price` | I       | Mark per share; stock = `und_price`       |
| Value | `value` | J       | `position × price × effective_multiplier` |
| P/L   | `pnl`   | K       | `initial_cf + value`                      |
| Delta | `delta` | L       | $ change per $1 underlying move           |
| Gamma | `gamma` | M       | Δ change per $1 underlying move           |
| Theta | `theta` | N       | Price change per **one calendar day**     |
| Vega  | `vega`  | O       | Price change per **1 vol point** (1% σ)   |
| Rho   | `rho`   | P       | Price change per **1 rate point** (1% r)  |


**Display mode:** When `display_mode = per_share`, Value/P/L/Greeks columns show per-share figures except Price (always per share). Row 18 totals sum leg values — misleading when leg sizes differ; use `total` mode for mixed sizes.

**Expired options:** When `eval_datetime ≥ expiration`, option leg Greeks = 0.

#### 8.5.6 Strategy-Level Aggregates

Sums across active legs (`type ≠ none`) — OSS row 18:


| Field                   | Key                | Description             |
| ----------------------- | ------------------ | ----------------------- |
| Total Initial Cash Flow | `total_initial_cf` | Sum of leg `initial_cf` |
| Total Value             | `total_value`      | Sum of leg `value`      |
| Total P/L               | `total_pnl`        | Sum of leg `pnl`        |
| Total Delta             | `total_delta`      | Sum of leg `delta`      |
| Total Gamma             | `total_gamma`      | Sum of leg `gamma`      |
| Total Theta             | `total_theta`      | Sum of leg `theta`      |
| Total Vega              | `total_vega`       | Sum of leg `vega`       |
| Total Rho               | `total_rho`        | Sum of leg `rho`        |




#### 8.5.7 Pricing Model (Black–Scholes–Merton)

Aligned with OSS Guide §§8–9:


| Aspect    | Specification                                                           |
| --------- | ----------------------------------------------------------------------- |
| Model     | Black–Scholes–Merton (Merton 1973 dividend extension)                   |
| Exercise  | European (American ≈ European except deep ITM calls on high-div stocks) |
| Vol units | Annualized standard deviation (%)                                       |
| Vega      | Per 1 percentage point change in σ                                      |
| Rho       | Per 1 percentage point change in r                                      |
| Theta     | Per 1 calendar day forward                                              |
| Forex     | Foreign rate as `div_yield` (Garman–Kohlhagen equivalence)              |


**Core formulas** (σ, r, q as decimals; t = fraction of year):

```
d₁ = [ln(S₀/X) + t(r − q + σ²/2)] / (σ√t)
d₂ = d₁ − σ√t
Call = S₀e^(−qt)N(d₁) − Xe^(−rt)N(d₂)
Put  = Xe^(−rt)N(−d₂) − S₀e^(−qt)N(−d₁)
```

Implementation: `backend/quant/pricing/bsm.py` using standard normal CDF (OSS uses `NORM.DIST`).

#### 8.5.8 Reference Example — Iron Condor (from OSS workbook)


|                | Leg 1  | Leg 2  | Leg 3  | Leg 4  | **Total**   |
| -------------- | ------ | ------ | ------ | ------ | ----------- |
| **Type**       | Put    | Put    | Call   | Call   | —           |
| **Position**   | +5     | −5     | −5     | +5     | —           |
| **Strike**     | 75     | 80     | 90     | 95     | —           |
| **Initial CF** | −1,800 | +2,825 | +3,400 | −2,575 | **+1,850**  |
| **P/L**        | —      | —      | —      | —      | **+258.34** |
| **Delta**      | —      | —      | —      | —      | **+0.81**   |
| **Gamma**      | —      | —      | —      | —      | **−2.93**   |
| **Theta**      | —      | —      | —      | —      | **+2.19**   |
| **Vega**       | —      | —      | —      | —      | **−28.18**  |


**Global params:** `und_price = 85.40`, `div_yield = 2.6%`, `int_rate = 4.0%`, `volatility = 28.4%`, `eval_datetime = 2024-01-04T10:35:00+05:30` (IST; matches OSS cell C3/C4), `default_contract_multiplier = 100` (OSS US-style fixture only — live NFO uses instrument-master `lotsize`).

#### 8.5.9 Trade Input JSON Schema

```json
{
  "strategy_id": "strat_001",
  "name": "Iron Condor Example",
  "underlying_symbol": "DEMO",
  "global_params": {
    "eval_date": "2024-01-04",
    "eval_time": "10:35:00",
    "eval_datetime": "2024-01-04T10:35:00+05:30",
    "und_price": 85.40,
    "div_yield": 2.60,
    "int_rate": 4.00,
    "flat_volatility": true,
    "volatility": 28.40,
    "display_mode": "total",
    "default_contract_multiplier": 100,
    "_comment_multiplier": "OSS US workbook fixture only. India paper/live: omit or null; set contract_multiplier_source=nfo_instrument_lotsize and use ICICI Direct lotsize per symbol."
  },
  "legs": [
    {
      "leg_id": 1,
      "position": 5,
      "expiration_id": "exp_006",
      "expiration": "2024-06-21T16:15:00",
      "days_to_expiry": 169.24,
      "strike": 75.00,
      "type": "put",
      "initial_price": 3.60,
      "initial_cf": -1800.0,
      "leg_name": "+5 21Jun 75P"
    },
    {
      "leg_id": 2,
      "position": -5,
      "expiration_id": "exp_006",
      "strike": 80.00,
      "type": "put",
      "initial_price": 5.65,
      "initial_cf": 2825.0
    },
    {
      "leg_id": 3,
      "position": -5,
      "expiration_id": "exp_006",
      "strike": 90.00,
      "type": "call",
      "initial_price": 6.80,
      "initial_cf": 3400.0
    },
    {
      "leg_id": 4,
      "position": 5,
      "expiration_id": "exp_006",
      "strike": 95.00,
      "type": "call",
      "initial_price": 5.15,
      "initial_cf": -2575.0
    }
  ],
  "totals": {
    "total_initial_cf": 1850.0,
    "total_value": -1591.66,
    "total_pnl": 258.34,
    "total_delta": 0.806,
    "total_gamma": -2.934,
    "total_theta": 2.188,
    "total_vega": -28.181,
    "total_rho": 7.699
  }
}
```

**Stock leg example** (covered call fragment):

```json
{
  "leg_id": 1,
  "position": 1000,
  "type": "stock",
  "initial_price": 202.38,
  "contract_multiplier": 1,
  "initial_cf": -202380.0
}
```



#### 8.5.10 Data Flow & Module Integration


| Stage           | Component                      | Action                                                         |
| --------------- | ------------------------------ | -------------------------------------------------------------- |
| **Input**       | Frontend OSS simulator UI      | Yellow cells: global params + legs; per-leg vol/mult overrides |
| **Expirations** | `GET/POST /api/v1/expirations` | Manage effective expiration catalog                            |
| **Persist**     | `POST /api/v1/strategies`      | Store strategy + legs in PostgreSQL                            |
| **Mark**        | `quant/pricing/bsm.py`         | Re-price legs; stock legs = underlying                         |
| **Greeks**      | `quant/greeks/`                | Per-leg and total per OSS conventions                          |
| **Simulate**    | `POST .../simulate` (optional) | Parameter sweeps, B/E and extrema key points                   |
| **Analyze**     | Gamma / Vega / Vol modules     | Consume leg-level and total Greeks                             |
| **Risk**        | `quant/risk/`                  | Enforce limits on aggregate Greeks                             |
| **Execute**     | `execution/order_builder`      | Expand option + stock legs to broker orders                    |
| **Monitor**     | Frontend dashboard             | Leg table with live marks (green cells)                        |


**Override precedence:** Live market data overrides `und_price` and per-leg `price`; option-chain IV overrides per-leg `leg_volatility` (sets `flat_volatility = false` when leg IVs differ). Global params are defaults and what-if baselines.

#### 8.5.11 API Endpoints (Trade Input)


| Method | Endpoint                           | Purpose                                         |
| ------ | ---------------------------------- | ----------------------------------------------- |
| `POST` | `/api/v1/strategies`               | Create strategy from OSS trade input table      |
| `GET`  | `/api/v1/strategies/{id}`          | Retrieve strategy with computed legs and totals |
| `PUT`  | `/api/v1/strategies/{id}`          | Update global params or legs                    |
| `POST` | `/api/v1/strategies/{id}/mark`     | Recompute Price, Value, P/L, Greeks             |
| `GET`  | `/api/v1/strategies/{id}/greeks`   | Aggregate and per-leg Greeks                    |
| `POST` | `/api/v1/strategies/{id}/simulate` | Scenario sweep (underlying, vol, time, etc.)    |
| `GET`  | `/api/v1/expirations`              | List expiration catalog                         |
| `POST` | `/api/v1/expirations`              | Add/update effective expiration datetime        |




#### 8.5.12 OSS Parity Validation

Backend pricing and Greeks **must match OSS reference outputs** before any strategy is traded.


| Test                        | Source                          | Tolerance                          |
| --------------------------- | ------------------------------- | ---------------------------------- |
| Iron Condor totals (§8.5.8) | `Docs/OSS (1).xlsm`             | P/L and Greeks within 0.01%        |
| Per-leg BSM price           | OSS workbook yellow/green cells | ± $0.01 per share                  |
| Stock leg delta             | OSS convention                  | Exactly ±1 × position × multiplier |
| Theta units                 | OSS Guide §8                    | Per calendar day                   |


**CI gate:** `backend/tests/quant/test_oss_parity.py` runs on every push. Regression against exported OSS fixture JSON (`backend/tests/fixtures/oss/`).

### 8.6 Live Feeds & Strategy URL Binding

Each OSS strategy **binds** to the feed URLs that supply live marks for its underlying and option legs. Bindings are persisted with the strategy and validated before autonomous execution.

**Feed-bound universe (G11–G12):** The recommendation scanner does **not** use a fixed shortlist. It loads **all NSE F&O underlyings** from ICICI Direct’s daily `SecurityMaster.zip` → `FONSEScripMaster.txt` (~200+ names: OPTSTK / OPTIDX / FUTSTK / FUTIDX). Each underlying becomes a G11 `underlying_symbol` (NSE display ticker where available) with auto G12 bindings into the ICICI Direct adapter:

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

(`STABAN` is the Breeze `ShortName` / stock_code for SBIN on NFO.)

Legacy example (same shape; feed ids may use human-readable aliases in configs):

```json
{
  "strategy_id": "strat_001",
  "underlying_symbol": "SBIN",
  "data_feed_bindings": {
    "und_price": "feed_sbin_spot",
    "option_chain": "feed_sbin_chain"
  }
}
```

**Runtime flow:**

```
Feed Scheduler: poll bound URLs for active strategies
        │
        ▼
Normalizer: latest quote + option chain snapshot
        │
        ▼
OSS Marking: override und_price, leg prices, per-leg IV
        │
        ▼
Quant + Risk: signals and pre-trade checks use live marks
        │
        ▼
Broker Adapter: execute if feeds fresh + risk gates pass
```

**Execution gate:** If any bound feed is stale, unreachable, or fails validation, the bot **does not submit orders** for that strategy until feeds recover.


| Binding Key        | OSS Field Overridden                            | Typical Feed `data_type` |
| ------------------ | ----------------------------------------------- | ------------------------ |
| `und_price`        | Global `und_price`; stock leg `price`           | `quote`, `ohlcv`         |
| `option_chain`     | Per-leg `price`, `leg_volatility`               | `option_chain`           |
| `vol_surface`      | Global or per-leg vol for skew-aware strategies | `vol_surface`            |
| `hedge_instrument` | Hedging leg marks (cash equity / stock legs)    | `quote`, `ohlcv`         |


### 8.8 Market Sentiment & News Pipeline

Market sentiment is a **first-class input** to strategy selection. The project uses **`Market_News.txt`** as the authoritative curation guide for India market news ingestion, and **`Docs/Trading_Strategies.md`** as the authoritative mapping from sentiment / event regime → strategy family.

#### 8.8.1 Design principles

| Concern | Decision |
| ------- | -------- |
| Primary India quotes / chains | Owned by broker / NSE-bound feeds (§8.6, ICICI Direct) |
| News / sentiment overlay | **Curated India sources** from `Market_News.txt` — lower noise for NSE/BSE event risk |
| Strategy gating | Must align with playbook scenarios (earnings gap, post-shock, news shock after entry) in `Trading_Strategies.md`, not a generic global sentiment score |

#### 8.8.2 Curation source: `Market_News.txt`

`Market_News.txt` (project root) defines:

1. **Preferred monitors** — Moneycontrol (company-specific), NSE India (announcements/filings), The Economic Times – Markets (macro), Reuters India (fast factual), Pulse by Zerodha (consolidated headlines).
2. **Recommended daily workflow** for operators and for scheduled bot pulls:
   - **Pre-open (08:00–09:00 IST):** Reuters India, Economic Times Markets, CNBC TV18
   - **During market hours:** Moneycontrol Live, Pulse by Zerodha, NSE announcements
   - **After close:** Economic Times analysis, company earnings, FII/DII activity, sector performance
3. **Bot ingestion priority** (high quality / low noise → official disclosures → broader context):
   - Reuters
   - Moneycontrol
   - Economic Times
   - NSE corporate announcements
   - SEBI circulars

#### 8.8.3 Sentiment service responsibilities

Implement as `backend/services/market_news/` (or equivalent). Responsibilities:

1. Load / honor the source list and workflow windows from `Market_News.txt`.
2. Ingest headlines, summaries, and official filings into a normalized `MarketNewsSummary` (existing recommendation schema).
3. Classify each item for **tone** (bullish / neutral / bearish), **topics** (earnings, macro, corporate action, SEBI/regulatory, sector), and **symbol tags** where identifiable.
4. Emit **macro risk flags** used by recommendation ranking and pre-trade gates (e.g. elevated earnings coverage, post-shock / crisis tone, regulatory surprise).
5. Expose freshness for the UI `NewsPanel` and include the summary on `GET /api/v1/recommendations` (`market_news`).

**Explicit non-goals:** treating global US news tone as India regime truth; hard-coding vendor scrapers outside the `Market_News.txt` curation contract.

#### 8.8.4 How sentiment drives strategies (`Trading_Strategies.md`)

Quant signals (IV vs GARCH, intraday IV z-score, realized vol, days-to-earnings) remain primary. Sentiment **overlays and gates** those signals using the playbook — especially **Strategy Selection Guide**, **Cross-Strategy Scenario Map**, and **Table SH-4**.

```
Market_News headlines / filings
        │
        ▼
Sentiment normalize → dominant tone + topic flags + symbol tags
        │
        ▼
Cross with quant regime (IV, GARCH, IV z, RV, earnings calendar)
        │
        ▼
Trading_Strategies.md Table SH-4 / scenario rules
        │
        ▼
selected_strategy + entry_mode + news_impact + event_risks
```

| Market / news condition (from sentiment + calendars) | Playbook preference (`Trading_Strategies.md`) | Bot action |
| ---------------------------------------------------- | --------------------------------------------- | ---------- |
| Normal regime; IV < GARCH; no adverse event news | Simple volatility → gamma if IV path uncertain (SH-4) | Prefer `simple_volatility` / `cheap_vol_mode` |
| Earnings / company event imminent (news + calendar) | Gamma scalping; **avoid** plain long-vega through the event | `gamma_scalping` + `earnings_gap_mode`; reject simple vol through event |
| Intraday IV flush (−2σ) on liquid ATM; news not blocking | Vega scalping | `vega_scalping`; same-day flatten |
| IV already elevated; large realized swings; news confirms agitation | Gamma scalping | `gamma_scalping` + `high_realized_vol_mode` |
| Post-shock / crisis tone; models likely distorted | Reduce or **block** all model-driven vol trades until normalization | `blocked`; macro flag → kill / defer (Shared Kill Conditions, H11/K4-class) |
| Breaking news after a live long-vol entry | Favorable for long vega/gamma (Scenario B in Vega / black-swan in Simple Vol) | Take profit / re-hedge aggressively — do not widen stops |
| Quiet tape + bearish/drift news after entry | Theta / continued IV fall risk | Prefer early exit / stop per strategy rules |

**Shared kill alignment:** An earnings or news event the setup was not designed to absorb is a shared kill condition (`Trading_Strategies.md` Shared Kill Conditions). Sentiment flags that contradict the chosen scenario must abort or flatten — not “hope through” the event.

**Pre-approval packet:** Operator-facing recommendations must include market-condition summary and known event risks derived from this news layer (playbook Supervised Execution Runbook / Part P1).

#### 8.8.5 Implementation touchpoints


| Component | Role |
| --------- | ---- |
| `Market_News.txt` | Source list + workflow — ops-editable curation contract |
| `Docs/Trading_Strategies.md` | Strategy selection matrix (SH-4), scenarios, kill conditions |
| `Docs/Paper_Simulator.md` / `backend/paper_sim/` | **Paper rehearsal** of SH-4 + news gates + GARCH/IV z + γ–θ re-hedge (ICICI Direct marks, local ledger; no `place_order`) |
| Sentiment service | Normalize headlines → `MarketNewsSummary` |
| `recommendation_engine._select_strategy` | Apply SH-4 with news overlay (earnings, post-shock, symbol hits) |
| `GET /api/v1/paper-sim/news` + `/signals` | Paper path exposure of the same news + SH-4 recommendation packet |
| `NewsPanel` / `FeedStatusPanel` | Display sentiment + ICICI Direct / news source freshness on `/recommendations` and paper-sim views |
| `backend/services/market_news/` | Sentiment ingest per `Market_News.txt` — **not** an MCP server |


### 8.9 ICICI Direct Market Data Integration

ICICI Direct Breeze API is the **sole live feed provider** for NSE / BSE / NFO marks **and** the sole live order venue. There is **no MCP feed registry** in this project. Quant modules consume only normalized snapshots (§8.3); ICICI Direct-specific fields stay inside the adapter. India sentiment remains a separate owned path (§8.8).

#### 8.9.1 Feed binding for ICICI Direct

| Feed purpose | Source | Freshness |
| ------------ | ------ | --------- |
| Underlying LTP | WS quotes (`4.1!token`) or REST `quotes` | Sub-second (WS) / poll interval (REST) |
| Option marks | WS quotes on NFO tokens (same connection) | Same |
| Historical HV | Historical candle API | Batch / nightly |
| Instrument metadata | Scrip master cache (`SecurityMaster.zip`) | Daily refresh (~08:00 IST). **G11–G12 universe** = all unique NFO underlyings from `FONSEScripMaster.txt` |

Normalized tick schema (internal) — must not leak ICICI Direct fields into quant code:

```json
{
  "provider": "icici_direct",
  "exchange": "NFO",
  "symbol": "SBIN28MAR24500CE",
  "provider_symbol_id": "40123",
  "ltp": 12.55,
  "bid": 12.40,
  "ask": 12.70,
  "ts": "2026-07-11T10:15:01+05:30",
  "stale": false
}
```

#### 8.9.2 WebSocket Streaming 2.0 rules

- Prefer **one mode per token** (quotes `.{1}!` only — not market-depth `.{2}!`) to conserve the subscription quota.
- Share a single Socket.IO connection for market data across strategies (`https://livestream.icicidirect.com`).
- On disconnect: exponential backoff reconnect; mark feeds stale; risk gate blocks discretionary entries (§11.4).
- Tick decode (list → `NormalizedTick`) lives only inside `backend/integrations/icici_direct/market_data.py`; connection lifecycle in `ws_stream.py`.
- Auth: decode `session_token` from `customerdetails` as `base64(user_id:feed_token)` → Socket.IO `auth={"user","token"}` + `User-Agent` (see [Breeze docs](https://api.icicidirect.com/breezeapi/documents/index.html)).
- Market WS heartbeat ~**30s**; order-status WS on `livefeeds` ping/pong ~**10s** (when enabled — not required for A2 marks).

#### 8.9.3 Data ownership (no MCP registry)

| Concern | Owner | Notes |
| ------- | ----- | ----- |
| Quotes, LTP, option chain, historical candles | **ICICI Direct** market-data adapter (`backend/integrations/icici_direct/`) | Sole marks path for paper-sim and live |
| Live order submit / cancel / positions | **ICICI Direct** broker adapter (`IciciDirectBrokerAdapter`) | Only when `EXECUTION_MODE=live` |
| India sentiment / event flags | **`Market_News.txt` pipeline** (§8.8) | Independent of ICICI Direct; required for SH-4 overlay |
| Optional public NSE announcements | Direct HTTP ingest if needed | Complementary disclosures only — not a parallel quote bus |

**Explicit non-goal:** an assignable MCP server catalog (`mcp_registry`, `user-broker-feed`, `user-nse-india`, `user-market-news` as MCP ids). Feed health for the UI is reported from ICICI Direct session/WS freshness and the market-news service, not from MCP assignment status.

**Why ICICI Direct for this project:** native NSE / BSE / NFO coverage; same vendor for marks + execution reduces basis risk; REST + WS Streaming 2.0 fits §8.6; retail-friendly Breeze API. ICICI Direct is the **sole broker adapter** (Indian markets only).

---



## 9. Quantitative Engine



### 9.1 Module Overview

```mermaid
flowchart TB
    MD[Normalized Market Data] --> SA[Stat Arb Module]
    MD --> VOL[Volatility Module]
    MD --> GAM[Gamma Module]
    MD --> VEG[Vega Module]
    SA --> GREEKS[Greeks Engine]
    VOL --> GREEKS
    GAM --> GREEKS
    VEG --> GREEKS
    GREEKS --> RISK[Risk Management]
    SA --> SIG[Signal Aggregator]
    VOL --> SIG
    GAM --> SIG
    VEG --> SIG
    RISK --> SIG
```





### 9.2 Module Specifications



#### A. Statistical Arbitrage Module


| Capability                                      | Output                                           |
| ----------------------------------------------- | ------------------------------------------------ |
| Cointegration testing (Engle-Granger, Johansen) | Stationary spread identification                 |
| Pair selection & ranking                        | Risk-adjusted pair universe                      |
| Spread construction                             | Spread time series                               |
| Z-score calculation                             | Entry/exit signals                               |
| Mean reversion analysis                         | Half-life, Hurst exponent                        |
| Position sizing                                 | Kelly-fraction or fixed-fraction (retail-capped) |


**Retail adaptations:** Limit universe size; enforce minimum liquidity; account for transaction costs in signal threshold.

#### B. Volatility Analysis Module


| Capability               | Output                                         |
| ------------------------ | ---------------------------------------------- |
| HV / RV estimation       | Rolling realized vol                           |
| IV extraction            | From option chain                              |
| Term structure           | IV by expiry                                   |
| Smile / skew             | IV by moneyness                                |
| Vol surface construction | 3D vol grid                                    |
| Relative value           | Underpriced / fair / overpriced classification |




#### C. Gamma Scalping Module


| Capability                         | Output                          |
| ---------------------------------- | ------------------------------- |
| Delta / gamma calculation          | Per-position Greeks             |
| Dynamic hedge ratio                | Shares/contracts to hedge       |
| Rebalancing frequency optimization | Cost vs. gamma profit trade-off |
| Theta decay analysis               | Expected time decay             |
| Profitability estimation           | Net P&L after hedge costs       |


**Key retail constraint:** Hedge frequency must account for manual/API latency—not continuous HFT rebalancing.

**Hedge frequency optimizer** (`quant/gamma/hedge_optimizer.py`): computes minimum rebalancing interval where expected gamma P&L exceeds theta decay + transaction costs (§9.4). Output feeds the gamma module signal; does not rely on LLM.

#### D. Vega Trading Module


| Capability                       | Output                           |
| -------------------------------- | -------------------------------- |
| Vega exposure                    | Portfolio-level vega             |
| IV expansion/contraction signals | Entry/exit for vol trades        |
| Event-driven vol                 | Earnings / macro flags from **Market_News** sentiment (§8.8) + calendar |
| Vega-neutral positioning         | Hedge structure recommendations  |




#### E. Greeks Engine

Computes per-leg and portfolio-level sensitivities for every active strategy leg:


| Greek | Symbol | Scope                   |
| ----- | ------ | ----------------------- |
| Delta | Δ      | Per-leg + `total_delta` |
| Gamma | Γ      | Per-leg + `total_gamma` |
| Theta | Θ      | Per-leg + `total_theta` |
| Vega  | ν      | Per-leg + `total_vega`  |
| Rho   | ρ      | Per-leg + `total_rho`   |


**Inputs:** Global params (`und_price`, `div_yield`, `int_rate`, `volatility` or per-leg `leg_volatility`, `flat_volatility`, `eval_date`/`eval_time`) and leg definitions from §8.5 (including `stock` legs for hedging).

**Outputs:** Populated per-leg calculated fields and strategy `totals` object used by risk, gamma scalping, and vega modules.

Cross-gamma and vanna (Phase 2).

#### F. Risk Management Module


| Check                  | Threshold Type                                                                          |
| ---------------------- | --------------------------------------------------------------------------------------- |
| Position limits        | Per-symbol, per-strategy, portfolio                                                     |
| Greeks limits          | Max `total_delta`, `total_gamma`, `total_vega`, `total_theta`, `total_rho` per strategy |
| Stop-loss              | Per-trade and portfolio                                                                 |
| Max drawdown           | Circuit breaker                                                                         |
| Correlation monitoring | Diversification enforcement                                                             |
| Margin check           | Pre-trade buying power                                                                  |




### 9.3 Signal Output Schema

Signals reference a **strategy** (multi-leg trade input) and include both leg-level and aggregate metrics:

```json
{
  "signal_id": "sig_20260629_001",
  "strategy_id": "strat_001",
  "module": "gamma_scalping",
  "underlying_symbol": "SBIN",
  "action": "hedge",
  "confidence_raw": 0.78,
  "global_params": {
    "und_price": 500.00,
    "volatility": 28.00
  },
  "legs": [
    {
      "leg_id": 1,
      "type": "call",
      "position": 100,
      "strike": 500.00,
      "delta": 0.52,
      "gamma": 0.08,
      "theta": -420.0,
      "vega": 0.71,
      "rho": -40.0
    },
    {
      "leg_id": 2,
      "type": "put",
      "position": 114,
      "strike": 500.00,
      "delta": -0.52,
      "gamma": 0.07,
      "theta": -441.0,
      "vega": 0.72,
      "rho": -41.0
    }
  ],
  "totals": {
    "total_delta": 0.0,
    "total_gamma": 1.011,
    "total_theta": -861.0,
    "total_vega": 1.427,
    "total_pnl": 125.50,
    "expected_gamma_pnl": 125.50,
    "expected_theta_loss": -45.00,
    "estimated_hedge_cost": 12.00
  },
  "rationale": "Delta drift exceeds threshold; gamma profit exceeds theta + costs",
  "timestamp": "2026-06-29T14:30:00Z"
}
```



### 9.4 Transaction Cost Model & Hedge Economics

Every gamma hedge and stat-arb signal must net transaction costs before reaching the decision engine.


| Cost Component | Source                 | Default (configurable)                                |
| -------------- | ---------------------- | ----------------------------------------------------- |
| Commission     | Broker fee schedule    | ICICI Direct / NSE: brokerage + statutory charges (configurable) |
| Bid-ask spread | Live quote `bid`/`ask` | Half-spread per leg                                   |
| Slippage       | Conservative estimate  | 0.05% equity; 1–2% of option mid for illiquid strikes |
| Market impact  | Retail-capped          | Fixed bps by notional tier                            |


**Gamma hedge profitability gate:**

```
net_hedge_edge = expected_gamma_pnl − expected_theta_loss − total_transaction_cost
execute_hedge  = net_hedge_edge > min_edge_threshold AND |total_delta| > delta_threshold
```

`min_edge_threshold` and `delta_threshold` are configurable per strategy. The hedge optimizer (§9.2.C) uses this model to recommend rebalancing frequency.

**Stat arb gate:** Entry z-score threshold includes a cost buffer so expected mean-reversion profit exceeds round-trip costs.

---



## 10. AI Decision Engine



### 10.1 LLM Provider: Groq

All LLM operations use the **Groq API** via the `groq` Python SDK in `backend/llm/`. Groq provides low-latency inference suitable for the bot's decision cycle and RAG response generation.


| Use Case                      | Groq Integration                                               |
| ----------------------------- | -------------------------------------------------------------- |
| Signal validation & fusion    | `decision/` module calls Groq with fused signals + RAG context |
| RAG answer generation         | `knowledge/retrieval/` passes reranked chunks to Groq          |
| AI chat (frontend)            | `api/chat` endpoint proxies to Groq with retrieved context     |
| Metadata enrichment (offline) | Batch classification of ambiguous chunks during ingestion      |


**Recommended models (configurable via** `GROQ_MODEL`**):**


| Model                     | Use Case                                             |
| ------------------------- | ---------------------------------------------------- |
| `llama-3.3-70b-versatile` | Primary — decision engine, RAG answers, explanations |
| `llama-3.1-70b-versatile` | Fallback if primary unavailable                      |
| `mixtral-8x7b-32768`      | Fast path for simple classification tasks            |


**Groq client wrapper (**`backend/llm/groq_client.py`**):**

- Centralizes API key, model selection, retry logic, and rate-limit handling
- Enforces structured output schemas for decision JSON
- Logs token usage for cost monitoring



### 10.2 Role

The LLM (via Groq) is the bot's **reasoning and validation layer**—not the sole decision authority. Quant modules generate signals; rules handle mechanical actions; Groq validates discretionary entries and generates audit explanations.


| Responsibility                              | Owner                                              |
| ------------------------------------------- | -------------------------------------------------- |
| Signal generation                           | Quant modules                                      |
| Mechanical hedges (delta drift > threshold) | Rule-based fast path (§10.6)                       |
| Discretionary entries / module fusion       | Groq + confidence gating                           |
| Explainability & citations                  | Groq + RAG                                         |
| Execution                                   | Risk gate → broker adapter (no LLM in submit path) |


The LLM:

- Evaluates and ranks signals across strategy modules
- Validates trades against RAG-retrieved domain knowledge
- Interprets volatility regimes in real time
- Gates low-confidence discretionary trades (high-conviction proceeds to execution)
- Generates explainable decision logs for audit and frontend display



### 10.3 Signal Fusion Architecture

```mermaid
flowchart TB
    S1[Stat Arb Signal] --> FUSION[Signal Fusion]
    S2[Vol Signal] --> FUSION
    S3[Gamma Signal] --> FUSION
    S4[Vega Signal] --> FUSION
    NEWS[Market_News Sentiment §8.8] --> FUSION
    RAG[RAG Context] --> LLM[LLM Validator]
    PLAYBOOK[Trading_Strategies.md SH-4] --> LLM
    FUSION --> LLM
    LLM --> CONF[Confidence Score]
    CONF --> GATE{>= threshold?}
    GATE -->|yes| EXEC[Execution]
    GATE -->|no| LOG[Log + Skip]
```





### 10.4 Confidence Gating


| Input                     | Weight                                   | Calibration                          |
| ------------------------- | ---------------------------------------- | ------------------------------------ |
| Quant signal strength     | Base score from module                   | Normalized 0–1 per module            |
| Multi-module agreement    | +0.10 when 2+ modules align              | Fixed bonus                          |
| RAG validation            | ±0.15 based on methodology match         | Requires faithfulness ≥ 0.85         |
| Regime fit                | +0.05 when signal matches current regime | Rule-based regime classifier (§20.3) |
| Recent module performance | ±0.10 by rolling Sharpe contribution     | 30-day window                        |


**Default minimum confidence (discretionary execution / risk gate):** Configurable (e.g., 0.70); auto-raised by +0.05 when rolling win rate drops below 60%.

**Recommendations surface floor:** `execution_constraints.min_recommendation_confidence` defaults to **0.80**. Only instruments with post-learning confidence ≥ **80%** are recommended on `/recommendations` (§6.4). This is separate from (and typically stricter than) the discretionary risk-gate threshold above.

**Calibration:** Weights tuned on paper-trade history via offline analysis (`analytics/confidence_calibration.py`). No weight changes deploy without passing walk-forward validation (§12.5).

### 10.5 Decision Output Schema

```json
{
  "decision_id": "dec_20260629_001",
  "action": "execute",
  "selected_signal_id": "sig_20260629_001",
  "confidence": 0.82,
  "module_weights": {
    "stat_arb": 0.25,
    "volatility": 0.20,
    "gamma": 0.35,
    "vega": 0.20
  },
  "rag_citations": [
    { "document": "Gamma Scalping", "chapter": "Chapter 5", "page": 132 }
  ],
  "explanation": "Gamma hedge warranted: delta drift exceeds 0.1 threshold...",
  "regime": "low_vol_mean_reverting"
}
```



### 10.6 Decision Operating Modes

```mermaid
flowchart TB
    SIG[Quant Signal] --> TYPE{Signal Type?}
    TYPE -->|mechanical hedge| FAST[Rule Fast Path]
    TYPE -->|discretionary entry| LLM[Groq Validator]
    FAST --> COST{Cost gate pass?}
    COST -->|yes| EXEC[Execution]
    COST -->|no| SKIP[Log + Skip]
    LLM --> CONF[Confidence Score]
    CONF --> GATE{>= threshold?}
    GATE -->|yes| EXEC
    GATE -->|no| SKIP
    GROQ_DOWN[Groq Unavailable] --> DEGRADED[Quant-only degraded mode]
    DEGRADED --> MECH[Mechanical hedges only]
```





#### Rule-based fast path

Mechanical actions bypass Groq latency:


| Trigger            | Action           | LLM role             |
| ------------------ | ---------------- | -------------------- |
| `                  | total_delta      | > delta_threshold`   |
| Stop-loss breached | Close position   | Post-hoc explanation |
| Feed stale         | Block all orders | None                 |


Fast-path orders still pass pre-trade risk gate (§11.4) and transaction cost gate (§9.4).

#### Quant vs. LLM disagreement (tie-break rules)


| Scenario                                               | Resolution                                                                                 |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| Quant says hedge; RAG says avoid (retail cost concern) | Execute if cost gate passes; log RAG warning; raise confidence threshold +0.05 for 24h     |
| Quant says enter; LLM rejects                          | **Skip** — discretionary entries require LLM approval; log to `decision_dissent` (§20.4.6) |
| Quant says enter; RAG insufficient context             | **Skip** — no guessing                                                                     |
| Multi-module conflict                                  | Highest-confidence module wins; others logged as dissent                                   |




#### Groq fallback


| State                  | Behavior                                                                               |
| ---------------------- | -------------------------------------------------------------------------------------- |
| Groq rate-limited      | Retry with exponential backoff (3 attempts)                                            |
| Groq unavailable > 60s | **Degraded mode:** mechanical hedges only; pause discretionary entries; alert operator |
| Cached RAG             | Frequent validation queries cached in Redis (TTL 5 min)                                |




### 10.7 Prompt Profiles

Separate prompt templates in `backend/llm/prompts/` — do not share chat and decision prompts.


| Profile        | File                     | Output                     | Constraints                         |
| -------------- | ------------------------ | -------------------------- | ----------------------------------- |
| **Decision**   | `decision_validate.json` | Strict JSON schema (§10.5) | Max 512 tokens; citations required  |
| **Chat**       | `chat_answer.json`       | Markdown with citations    | Verbose allowed; faithfulness check |
| **Enrichment** | `metadata_classify.json` | Label JSON                 | Batch offline only                  |
| **Post-trade** | `failure_analysis.json`  | Structured failure summary | Writes to `failure_memory`          |


---



## 11. Execution Layer: ICICI Direct Broker Integration

The execution layer connects the bot to **ICICI Direct Breeze API** (NSE / BSE / NFO only) via a pluggable adapter. Strategy and quant code emit internal orders; the adapter translates them to Breeze API calls. Paper rehearsal uses in-house `paper_sim` (not a broker sandbox). Live data feeds: §8.6 / §8.9. Paper P&L: `Docs/Paper_Simulator.md`. External Breeze API reference: [api.icicidirect.com/breezeapi/documents](https://api.icicidirect.com/breezeapi/documents/index.html). Customer login: [secure.icicidirect.com/customer/login](https://secure.icicidirect.com/customer/login).

| Role | Capability |
| ---- | ---------- |
| **Execution** | Place / modify / cancel orders on NSE, BSE, NFO, BFO (and optionally MCX/CDS) |
| **Portfolio sync** | Holdings, positions, funds, order book, trade book |
| **Live marks** | LTP, quote, and WebSocket Streaming 2.0 for underlyings and option legs |
| **Historical bars** | Candle API for HV / vol-surface research inputs |

Quant modules, OSS trade inputs, risk gates, and supervision modes remain **broker-agnostic** (§11.2, §11.6). RAG chatbot, Groq decision logic, and frontend layouts stay outside this layer (§7, §10, `UI_Dashboard.md`).

```
Frontend (thin client)
        │ REST / WebSocket (bot APIs only)
        ▼
Backend
  ├── Market Data Layer (§8)  ←── IciciDirectMarketDataAdapter  (quotes, WS ticks)
  ├── Quant / AI / Risk
  ├── Execution Layer (§11)   ←── IciciDirectBrokerAdapter      (orders, positions)
  └── integrations/           ←── registry + credential vault
        │
        ▼
ICICI Direct Breeze API
  ├── REST  https://api.icicidirect.com/breezeapi/api/v1/...
  ├── Market WS  Breeze WebSocket (see Breeze docs)
  └── Order-status WS / postback (optional)
```

### 11.1 Discretionary Execution Flow

```
Bot Scheduler: market tick / interval
        │
        ▼
Feed Health Check: bound URLs fresh? ──no──► Skip strategy / alert
        │ yes
        ▼
Quant Engine + AI: signal + confidence (live marks from §8.6 / §8.9)
        │
        ▼
Pre-trade Risk Gate (Greeks, size, drawdown, health, feed freshness, one-trade scope §20.4.11)
        │
        ▼
[Discretionary] Supervision path (§6.2.2):
        ├─ supervised → emit decisions.pending; wait Approve / Reject
        ├─ semi_autonomous → auto-submit if confidence ≥ threshold; else queue
        └─ fully_autonomous → auto-submit; ranked recommendation fallback (§6.4)
        │
        ▼
Order Builder: construct order from OSS strategy legs
        │
        ▼
Submit path by EXECUTION_MODE (§6.2.1):
        ├─ paper  → paper_sim PaperLedger (ICICI Direct LTP ± slippage; no place_order)
        └─ live   → IciciDirectBrokerAdapter → Breeze place_order
        │
        ▼
Fill accepted → position sync + P&L update + WebSocket emit
        │
        ▼
Learning Engine: outcome logged
```



### 11.2 Broker Adapter Pattern

Implements the shared `BrokerAdapter` interface:

| Interface method | ICICI Direct mapping |
| ---------------- | ----------------- |
| `authenticate()` | Breeze login `API_Session` → `customerdetails` → store `session_token` |
| `submit_order(order)` | `POST .../order` (`place_order`) |
| `cancel_order(order_id)` | `DELETE .../order` (`cancel_order`) |
| `get_positions()` | Portfolio positions API |
| `get_account()` | Funds API |
| `get_order_status(order_id)` | Order list / order detail |

Market marks for the same connection live in `backend/integrations/icici_direct/market_data.py` (REST LTP/quote + WS Streaming 2.0) and feed the URL-binding / freshness gates in §8.6–8.9. **Do not** introduce an MCP registry for broker or news feeds.

#### Module layout

```
backend/
├── integrations/
│   └── icici_direct/
│       ├── __init__.py
│       ├── client.py              # Low-level HTTP + headers
│       ├── session_manager.py     # Login, refresh, midnight rotate
│       ├── instrument_master.py   # Token resolution + cache
│       ├── market_data.py         # REST LTP/quote + WS consumer
│       ├── order_mapper.py        # InternalOrder → place_order payload
│       ├── icici_direct_adapter.py   # BrokerAdapter implementation
│       └── models.py              # Pydantic DTOs
└── execution/
    └── broker_router.py           # Selects default ICICI Direct connection
```

```mermaid
classDiagram
    class BrokerAdapter {
        <<interface>>
        +authenticate()
        +submit_order(order)
        +cancel_order(order_id)
        +get_positions()
        +get_account()
        +get_order_status(order_id)
    }
    class IciciDirectBrokerAdapter {
        +authenticate()
        +submit_order(order)
        +cancel_order(order_id)
        +get_positions()
        +get_account()
        +get_order_status(order_id)
        +modify_order(order_id, patch)
    }
    class IciciDirectMarketDataAdapter {
        +subscribe(tokens, mode)
        +unsubscribe(tokens, mode)
        +get_ltp(exchange, symbol, token)
        +get_candles(...)
    }
    BrokerAdapter <|-- IciciDirectBrokerAdapter
    IciciDirectBrokerAdapter --> SessionManager
    IciciDirectBrokerAdapter --> InstrumentMaster
    IciciDirectMarketDataAdapter --> SessionManager
```



### 11.3 Internal Order Schema

Orders are built from strategy legs. Single-leg orders use one entry; multi-leg strategies produce a **basket** submitted to the broker adapter.

```json
{
  "internal_order_id": "ord_001",
  "strategy_id": "strat_001",
  "signal_id": "sig_20260629_001",
  "underlying_symbol": "SBIN",
  "mode": "shadow",
  "status": "pending",
  "legs": [
    {
      "leg_id": 1,
      "symbol": "SBIN28MAR24500CE",
      "type": "call",
      "side": "buy",
      "quantity": 25,
      "order_type": "limit",
      "limit_price": 12.00,
      "strike": 500.00,
      "expiration": "2024-03-28",
      "exchange": "NFO"
    },
    {
      "leg_id": 2,
      "symbol": "SBIN28MAR24500PE",
      "type": "put",
      "side": "buy",
      "quantity": 25,
      "order_type": "limit",
      "limit_price": 11.50,
      "strike": 500.00,
      "expiration": "2024-03-28",
      "exchange": "NFO"
    }
  ],
  "totals_at_submit": {
    "total_initial_cf": -587.50,
    "total_delta": 0.0,
    "total_gamma": 1.011,
    "total_vega": 1.427
  }
}
```



### 11.4 Pre-Trade Risk Gate Checklist


| Check                                | Default Threshold                                                | Fail Action                                           |
| ------------------------------------ | ---------------------------------------------------------------- | ----------------------------------------------------- |
| Bound data feeds fresh (§8.6)        | `stale_threshold_sec` per feed                                   | Reject order; pause strategy                          |
| Position limit not exceeded          | Config per symbol/strategy                                       | Reject order                                          |
| `                                    | total_delta                                                      | `                                                     |
| `                                    | total_gamma                                                      | `                                                     |
| `                                    | total_vega                                                       | `                                                     |
| `total_theta`                        | ≥ `min_theta` (max daily decay)                                  | Reject                                                |
| Drawdown below circuit breaker       | ≤ 10% equity                                                     | Reject; reduced-exposure mode                         |
| Bot health metrics within bounds     | Error rate < 5% / 1h                                             | Reject                                                |
| Kill-switch inactive                 | —                                                                | Reject all new orders                                 |
| Sufficient buying power              | —                                                                | Reject                                                |
| Confidence >= threshold (risk gate)  | ≥ 0.70 (configurable)                                            | Reject                                                |
| Recommendation surface floor (§6.4)  | Confidence ≥ `min_recommendation_confidence` (**0.80** default) after learning penalties | Exclude from top-3 recommendations                    |
| Transaction cost gate (§9.4)         | `net_hedge_edge > 0`                                             | Reject hedge                                          |
| RAG faithfulness (discretionary)     | ≥ 0.85                                                           | Reject entry                                          |
| Regime classifier known              | Not `unknown` / `high_vol_stress`                                | Reject discretionary entry                            |
| Broker reject rate (1h)              | < 10%                                                            | Reject all new orders; auto-pause (§20.4.5)           |
| Symbol whitelist                     | Symbol ∈ `allowed_symbols`                                       | Reject                                                |
| Market session                       | Within configured market hours                                   | Reject (unless strategy override)                     |
| Duplicate signal                     | No existing order for `(strategy_id, signal_hash, tick_id)`      | Reject (idempotency)                                  |
| One trade at a time (§20.4.11)       | No other open discretionary entry in session | Reject new discretionary signal; log as `deferred_one_trade_scope` |
| Discretionary submit                   | Quant + RAG + LLM + risk gates pass; one-trade scope clear; supervision path satisfied (§6.2.2, §20.4.11) | Reject / queue; log reason |
| Portfolio circuit breakers (§11.4.1) | All pass                                                         | Reject; may trigger auto-pause                        |
| Lot / tick size (ICICI Direct)              | Quantity multiple of `lotsize`; price on tick grid               | Reject before broker call                             |


Thresholds stored in PostgreSQL `configuration` table; adjustable via API without redeploy. All changes **audit-logged** (§20.4.8).

#### 11.4.1 Portfolio Circuit Breakers

Non-negotiable ceilings — **no single decision may override** these checks (`backend/execution/circuit_breakers.py`):


| Breaker                              | Default              | On breach                                                             |
| ------------------------------------ | -------------------- | --------------------------------------------------------------------- |
| Max daily loss                       | 2% of equity         | Pause bot until next session or manual resume                         |
| Max orders per hour                  | 20                   | Reject new orders; alert                                              |
| Max notional per trade               | 5% of buying power   | Reject or clip size                                                   |
| Max open positions                   | Config per portfolio | Reject new discretionary entries; hedges on existing positions exempt |
| Max concurrent discretionary entries | **1**                | Reject new discretionary signal (one trade at a time — §20.4.11)      |
| Max consecutive losses               | 5                    | Pause discretionary entries; mechanical hedges only                   |
| Drawdown circuit                     | ≤ 10% equity (§2.2)  | Reduced-exposure mode → pause if sustained                            |


Stored in `configuration.auto_pause_rules` and `configuration.circuit_breakers` JSON blobs; surfaced on frontend risk dashboard.

### 11.5 Broker (Indian Markets Only)


| Broker       | Paper path                                                   | Live Data            | Role                                                                 |
| ------------ | ------------------------------------------------------------ | -------------------- | -------------------------------------------------------------------- |
| **ICICI Direct** | **No** first-class paper/sandbox API — use `shadow` + **`paper_sim`** (`Docs/Paper_Simulator.md`) | Yes (Breeze API REST / WS) | **Sole broker** — NSE / BSE / NFO marks + live execution |


ICICI Direct is preferred because: (1) native NSE / BSE / NFO coverage, (2) same vendor for marks + execution (lower basis risk), (3) REST + WS Streaming 2.0 fits §8.6 / §8.9, (4) documented order, portfolio, and historical endpoints.



### 11.6 Third-Party Integration Framework

All external application connections follow a common **adapter + integration registry** pattern in `backend/integrations/` (broker / credential / health — **not** an MCP server catalog).

```mermaid
flowchart TB
    subgraph Integrations["backend/integrations/"]
        REG[Integration Registry]
        BA[Broker Adapters]
        DA[Data Provider Helpers]
        CV[Credential Vault]
        HC[Health Checker]
    end

    REG --> BA
    REG --> DA
    CV --> BA
    CV --> DA
    HC --> REG
    BA --> EXEC[Execution Layer]
    DA --> MD[Market Data Layer]
```




| Integration Class  | Adapter Interface             | Config Storage                   | Health Signals                       |
| ------------------ | ----------------------------- | -------------------------------- | ------------------------------------ |
| **Broker**         | `BrokerAdapter` (§11.2)       | `broker_connections` (encrypted) | Auth OK, order latency, reject rate  |
| **Live data feed** | URL registry + fetcher (§8.2) | `data_feeds` + `credential_ref`  | Last fetch, stale count, HTTP errors |
| **LLM (Groq)**     | `GroqClient`                  | Env / secret manager             | Rate limits, latency                 |


**Configuration example (broker connection):**

```json
{
  "connection_id": "icici_direct_01",
  "provider": "icici_direct",
  "mode": "live",
  "enabled": true,
  "credential_ref": "icici_direct_breeze",
  "default_for_execution": true,
  "settings": {
    "static_ipv4": "x.x.x.x",
    "exchanges_enabled": ["NSE", "BSE", "NFO"],
    "product_default": "INTRADAY",
    "variety_default": "NORMAL",
    "order_rate_limit_per_sec": 9,
    "ws_modes": ["LTP", "QUOTE"],
    "market_session": "NSE_EQ_FO"
  }
}
```

Secrets under `credential_ref` (Secret Manager / env): see §11.12.

**Design rules:**

- One active **default broker connection** per bot instance for execution (ICICI Direct only)
- Data feed URLs may share credentials with the broker (ICICI Direct market data + trading API) or use independent providers
- Adapters are **stateless**; connection state (tokens, session IDs) managed by credential vault with refresh
- Failed integration health triggers frontend alerts and may pause autonomous trading globally or per-strategy
- Adding a new third-party app = new adapter class + registry entry + config schema—no changes to quant or OSS logic



### 11.7 Multi-Leg Execution & Paper Fill Realism



#### Multi-leg order builder (`execution/order_builder.py`)


| Capability                          | Phase               | Behavior                                                |
| ----------------------------------- | ------------------- | ------------------------------------------------------- |
| Single-leg equity/options           | Phase 1 (paper) / Phase 2 (live path) | Direct submit                                           |
| Multi-leg spreads (2+ legs)         | **Phase 1 (paper_sim)** | Basket open **or** post-entry auto-complete of intended legs without extra consent; same open-trade gates; sequential + rollback on live is Phase 5 |
| Atomic multi-leg (broker-supported) | Phase 3+            | Single basket order where broker API allows             |


**Phase 1 — post-entry multi-leg without consent:** After a paper entry fills, if the bot's intended opening structure is multi-leg (`intended_legs` / strategy-inferred CE+PE or option+stock), remaining opening legs may be submitted **automatically without operator consent**. Completion **must** re-apply the same rules used for the first entry: fresh marks, lotsize multiples, pre-trade gate, Part T (when options+underlying), per-leg ₹1L, and **cumulative** max trade investment ₹1L (`opening_investment_inr`). This is distinct from γ–θ re-hedges (management). API: `POST /paper-sim/orders` (`auto_complete_multi_leg`, default true) and `POST /paper-sim/positions/{id}/complete-multi-leg`.

**Rollback:** If leg 2+ fails after leg 1 fills, attempt to flatten leg 1 within `rollback_timeout_sec` (default 30s); log as `partial_fill_incident`.

**Breeze API note:** `place_order` is **single-leg**. Use sequential submit + rollback unless a future basket API is adopted.

#### Paper fill realism

ICICI Direct has **no** first-class paper/sandbox API. Paper rehearsal uses in-house `backend/paper_sim/` (ICICI Direct marks + local fills — `Docs/Paper_Simulator.md`). Broker-adapter `shadow` / simulated fills must not assume mid-price optimism.


| Mode                           | Behavior                                                        |
| ------------------------------ | --------------------------------------------------------------- |
| `paper_optimistic`             | Mid-price fills (dev only — not for soak validation)            |
| `paper_conservative` (default) | Apply configurable slippage + half-spread penalty on every fill |


Conservative mode is required for success-ratio validation (§2.2). Document fill assumptions in every trade log.

#### Execution modes vs ICICI Direct


| Mode | ICICI Direct / paper behavior |
| ---- | -------------------------- |
| `shadow` | Full pipeline; **no** Breeze API `place_order`; log would-be orders; optional simulated fills with `paper_conservative` slippage |
| `paper` | **No** ICICI Direct paper/sandbox. Adapter `paper` is dry-run only. Real paper P&L uses **`backend/paper_sim/`** (ICICI Direct LTP + local ledger) |
| `live` | Real Breeze API `place_order` from static IP; full risk gates + supervision (micro-size first) — **Phase 5 only** |

**Decision (default):** ICICI Direct for **live market data** in Phases 0–1; rehearse on `paper_sim` under `EXECUTION_MODE=paper`; promote supervision on that path (Phases 2–4); then `EXECUTION_MODE=live` with micro-size on **GCP**. Prefer **`/api/v1/paper-sim/*`** over adapter `paper` dry-run logs. **Hosted paper:** Railway + Vercel (§17.0). Do **not** fold the paper ledger into `IciciDirectBrokerAdapter`.

Paper-sim v1 is the **playbook rehearsal path** (`Trading_Strategies.md` SH-4, `Market_News.txt` via §8.8, GARCH / IV z-score, γ–θ re-hedge). Supervision axis applies on paper-sim first (Phases 2–4), then again before any ICICI Direct live submit (Phase 5).

---

### 11.8 Breeze API Surface Map

Base host: `https://api.icicidirect.com/breezeapi/api/v1`

Customer login: https://secure.icicidirect.com/customer/login  
Breeze API login (daily `API_Session`): https://api.icicidirect.com/apiuser/login  
Docs: https://api.icicidirect.com/breezeapi/documents/index.html  
SDK: https://github.com/Idirect-Tech/Breeze-Python-SDK

#### Capability groups


| Group | Used for | Key endpoints (relative) |
| ----- | -------- | ------------------------ |
| **Auth** | Session | `customerdetails` (exchange `API_Session` → `session_token`) |
| **Orders** | Execution | `order` (place / modify / cancel / list), `trades` |
| **Portfolio** | Sync | `portfolioholdings`, `portfoliopositions`, `funds` |
| **Market Data API** | REST quotes | `quotes`, `optionchain` |
| **Historical API** | Research / HV | `historicalcharts` |
| **WebSocket** | Live ticks | `livestream.icicidirect.com` Socket.IO rate-refresh (A2); auth via decoded `session_token` |

**Out of scope:** GTT (`gttorder` place / order book / cancel / modify) — not used in this project.

#### Common request headers

| Header | Purpose |
| ------ | ------- |
| `X-AppKey` | Breeze app `api_key` |
| `X-SessionToken` | Post-`customerdetails` session token |
| `X-Timestamp` / `X-Checksum` | Request signing with `api_secret` |
| `Content-Type` | `application/json` |
| `Accept` | `application/json` |

#### Instrument identity

ICICI Direct / Breeze identifies instruments by **`stock_code`** (and related token fields), not only a display trading symbol.

| Field | Role |
| ----- | ---- |
| `exchange_code` | `NSE`, `BSE`, `NFO`, … |
| `stock_code` / `tradingsymbol` | e.g. `SBIN`, NFO option codes |
| `expiry_date` / `right` / `strike_price` | Required for F&O |

**Implication:** Adapter must maintain an **instrument master cache** (security master download / search) mapping OSS symbols → `(exchange, stock_code, lotsize, tick_size, expiry, right, strike)`.

---

### 11.9 Authentication & Session Lifecycle

#### Login flow

```
Operator stores: api_key, api_secret (vault)
Operator obtains daily API_Session via Breeze API login URL
        │
        ▼
Bot reads ICICI_DIRECT_SESSION_TOKEN (= API_Session)
        │
        ▼
POST/GET customerdetails (checksum-signed with api_secret)
        │
        ▼
Receive: session_token (+ customer id)
        │
        ▼
Credential vault (in-memory) — adapters stay "stateless" re: secrets
```

**Bot runtime uses daily `API_Session` + `customerdetails` exchange** (not PIN/TOTP). See `Docs/ICICI_Direct_Next_Steps.txt`.

#### Session rules

| Rule | Behavior |
| ---- | -------- |
| Session TTL | Treat `API_Session` / `session_token` as **same-day**; refresh via Breeze login URL when expired |
| Refresh | Obtain a new `API_Session` from https://api.icicidirect.com/apiuser/login then re-run `customerdetails` |
| Rate limit | Breeze combined ops ≈ **10/sec** — adapter enforces local limiter |
| Concurrent WS | Follow Breeze streaming limits in vendor docs |

#### Scheduler responsibilities

`backend/integrations/icici_direct/session_manager.py`:

1. Pre-market authenticate after operator refreshes `ICICI_DIRECT_SESSION_TOKEN` (e.g. 08:45 IST).
2. Mid-session health check; re-auth on 401 / session errors.
3. Next-day require fresh `API_Session`.
4. Never log raw `api_secret` / `session_token` / `API_Session`.

---

### 11.10 Order & Position Mapping

#### Internal → Breeze place_order

Internal multi-leg OSS orders (§11.3) map **per leg**:

| Internal field | ICICI Direct / Breeze field |
| -------------- | --------------- |
| side `buy` / `sell` | `action` `buy` / `sell` (lowercase) |
| order_type `market` / `limit` / `stop` | `order_type` `limit` / `stoploss` (Breeze has no true market orders — map market → aggressive limit) |
| quantity (shares / contracts) | `quantity` as string (respect `lotsize` for F&O) |
| limit_price | `price` |
| symbol + expiry + strike + right | resolve → `stock_code`, `exchange_code`, `expiry_date`, `right`, `strike_price` |
| product (intraday vs carry) | `product` `cash` / `futures` / `options` / `margin` |
| strategy tag | `user_remark` (short `signal_id` hash) |
| — | `validity` (`day`) |

F&O quantity must be a multiple of instrument `lotsize`. **Sizing rule (India):** effective OSS contract multiplier and order quantity step both come from that same per-contract `lotsize` — never from the OSS US workbook default of `100` (`trading_parameters.defaults.json` → `nfo_lot_sizing`). Adapter rejects legs that violate lot or tick size **before** risk-gate pass is wasted on a guaranteed broker reject.

#### Fill sync path

```
place_order → order_id
     │
     ├─► Order-status polling / streaming (preferred)
     └─► Poll order list (fallback)
     │
     ▼
Map fills → internal Position + P&L → learning engine
```

---

### 11.11 SEBI / Compliance Constraints

ICICI Direct Breeze API has tightened algo controls (SEBI retail algo participation guidance). Treat these as **hard infrastructure requirements**:

| Constraint | Architectural impact |
| ---------- | -------------------- |
| **Static IPv4 for order APIs** | **Live only (GCP):** Cloud Run / VM egress must use a **static outbound IP** (Cloud NAT / reserved IP) registered with the broker / Breeze portal as required. **Paper (Railway)** uses ICICI Direct data APIs only — no `place_order`, so static IP is not required on the paper stack |
| **Order rate limit** | Cap ≤ **~10 combined ops/sec**; adapter token-bucket enforces below broker cap |
| **Daily session expiry** | Session manager mandatory; no overnight `API_Session` reuse without refresh |
| **API key types** | Prefer production keys bound per Breeze app registration for order flow |
| **Algo provider vs self-algo** | This project assumes **self-coded retail algo** on the operator’s account — not multi-client algo-provider empanelment |

Non-order APIs (historical, some market data) may not require static IP; **all order-path traffic** must.

---

### 11.12 Configuration & Secrets

#### Secret Manager / env keys

| Secret | Usage |
| ------ | ----- |
| `ICICI_DIRECT_API_KEY` | Breeze app key (`X-AppKey` / checksum) |
| `ICICI_DIRECT_API_SECRET` | Breeze app secret (checksum signing) |
| `ICICI_DIRECT_SESSION_TOKEN` | Daily `API_Session` from Breeze API login |
| `ICICI_DIRECT_PUBLIC_IP` | Optional static egress IP override |

Frontend never receives these. Chatbot must not expose them (§7.7, §16).

#### Runtime config (PostgreSQL `broker_connections`)

- `provider = icici_direct`
- `default_for_execution` (single default per bot instance)
- Exchange whitelist, product defaults, rate limits, static IP metadata
- Audit-log every credential rotation and connection test (`POST /api/v1/config/integrations/broker/test`)

#### Market hours

Default session gate for NSE cash/F&O: **09:15–15:30 IST** (pre-open / post-close rules configurable). AMO variety allowed only when strategy explicitly opts in.

---

### 11.13 ICICI Direct Health, Observability & Failure Modes

| Signal | Source | On failure |
| ------ | ------ | ---------- |
| Auth OK | Session manager | Pause discretionary submit; alert |
| Order latency / reject rate | Adapter metrics | Reject-rate circuit (§11.4) |
| WS connected + last tick age | Market data adapter | Mark feeds stale; skip strategies |
| Static IP / SEBI reject text | Order response `text` | Page operator; do not retry blindly |
| Midnight session drop | Scheduler | Re-login; brief trading pause |

Expose via existing `GET /health/integrations` and integrations dashboard (§13).

---

### 11.14 Quick Reference Links

- Breeze API docs (vendor knowledge base): https://api.icicidirect.com/breezeapi/documents/index.html
- Orders: https://api.icicidirect.com/breezeapi/documents/index.html#order
- Portal: https://api.icicidirect.com/apiuser/login
- Cursor rule: `.cursor/rules/icici-direct-breeze-api.mdc`

---

### 11.15 ICICI Direct Implementation Phases (A0–A6)

Aligned with parent §21 (paper-first). ICICI Direct phases **A0–A2** ship early for marks; **A3** is shadow dry-run; **A4–A6** wait until Phase 5 (live).

| ICICI Direct phase | Parent §21 | Deliverable | `place_order`? |
| ----------- | ---------- | ----------- | ------------- |
| **A0** | Phase 0 | Cred vault + `session_manager` + connection test API | No |
| **A1** | Phase 0 | Instrument master cache + LTP REST → normalized ticks | No |
| **A2** | Phase 1 | WebSocket Streaming 2.0 consumer + feed freshness into §8.6 / §8.9 | No |
| **A3** | Phase 1–2 | `IciciDirectBrokerAdapter` place/cancel/status in `EXECUTION_MODE=shadow` (dry-run payloads logged) | No (log only) |
| **—** | Phase 1–4 | **`paper_sim`** path owns all paper P&L / autonomy promotion | No |
| **A4** | Phase 5 | Sequential multi-leg submit + rollback; wire supervised Approve → **live** submit | Yes (GCP) |
| **A5** | Phase 5 | Static IP Cloud NAT + live micro-size; order-status WS; production rate limiter | Yes |
| **A6** | Phase 5 | Drop simulated / stub NSE quote paths; ICICI Direct is the only live marks + order path; news remains §8.8 | Yes |

**Autonomy on paper (Phases 2–4) does not require A4–A6.** Dependencies: risk gates, supervision queue, and kill-switch must exist before **A4** live submit. Prefer re-starting `supervised` when first enabling live, then re-promote.

```
A0 → A1 → A2 ──► paper_sim playbook (Phase 1)
                │
                ├── supervised → semi → full-auto on paper (Phases 2–4)
                │
A3 (shadow dry-run) ──┐
                      └── A4 → A5 → A6  only after paper soak (Phase 5 / GCP)
```

---



## 12. Continuous Learning & Adaptation



### 12.1 Closed-Loop Architecture

```mermaid
flowchart TB
    TO[Trade Outcomes] --> PM[Performance Metrics]
    PM --> TC{Threshold Check}
    TC -->|healthy| OBS[Resume Observe]
    TC -->|breach| AE[Adaptation Engine]
    AE --> PO[Parameter Optimization]
    AE --> MW[Module Reweighting]
    AE --> RS[Regime Switch]
    AE --> PU[Pair Universe Refresh]
    AE --> HF[Hedge Freq Adjust]
    PO --> RB[Rolling Backtest]
    MW --> RB
    RS --> RB
    PU --> RB
    HF --> RB
    RB -->|pass| DEP[Deploy Config]
    RB -->|fail| AE
    DEP --> OBS
```





### 12.2 Learning Inputs


| Input                   | Source                                        |
| ----------------------- | --------------------------------------------- |
| Trade outcomes          | Broker adapter (win/loss, P&L, slippage)      |
| Rolling metrics         | Analytics engine                              |
| Regime labels           | Regime classifier                             |
| Module attribution      | Signal → outcome mapping                      |
| RAG post-trade analysis | Knowledge layer                               |
| Failure contexts        | Written to `failure_memory` vector collection |




### 12.3 Adaptation Triggers & Actions


| Trigger                   | Adaptation Action                                    |
| ------------------------- | ---------------------------------------------------- |
| Win rate < 60%            | Tighten entry filters; raise confidence minimum      |
| Drawdown > 10%            | Reduce position sizes; pause highest-risk strategies |
| Cointegration breakdown   | Remove pair; re-run pair selection                   |
| Vol regime shift          | Reweight gamma vs. vega vs. stat arb                 |
| Hedge cost > gamma profit | Adjust rebalancing frequency                         |
| Module underperforms      | Lower weight; promote better modules                 |
| New pattern identified    | Update feature weights; store in knowledge base      |




### 12.4 Learning Mechanisms


| Mechanism                   | Description                                                                         |
| --------------------------- | ----------------------------------------------------------------------------------- |
| Rolling backtest validation | Every parameter change validated via **walk-forward** windows (§12.5) before deploy |
| Online performance tracking | EMA of key metrics per strategy                                                     |
| Parameter optimization      | Grid / Bayesian (Optuna) on thresholds                                              |
| Module weighting            | Dynamic allocation by rolling Sharpe contribution                                   |
| Failure memory              | Store losing contexts in vector DB                                                  |
| Regime classifier           | Train/update; switch strategy presets per regime                                    |




### 12.5 Adaptation Safety Guards


| Guard                    | Rule                                                                                                                                    |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| Walk-forward validation  | Every parameter change validated on **out-of-sample** windows (train N days → test M days rolling), not just in-sample rolling backtest |
| Minimum sample size      | No parameter tuning until ≥ **30 closed trades** per module (configurable)                                                              |
| Maximum change per cycle | No single threshold/weight change > **20%** per adaptation cycle                                                                        |
| Cooldown                 | Minimum **24h** between adaptation cycles                                                                                               |
| Automatic rollback       | If post-deploy win rate drops > 10% within next **20 trades**, revert to prior config                                                   |
| RAG eval gate            | No adaptation deploy if RAG faithfulness on golden set < CI threshold                                                                   |
| Freeze on drawdown       | No adaptation deploy while equity drawdown > **5%**                                                                                     |
| Config versioning        | Every deploy stores prior config snapshot in `learning_history`; rollback via `POST /api/v1/learning/rollback`                          |
| Module weight cap        | Max **±15%** module weight change per cycle (stricter than generic 20% threshold rule)                                                  |
| No auto-enable modules   | Optimizer may reweight enabled modules only; `strategy_enabled` requires operator action                                                |
| Replay-before-deploy     | Walk-forward runs on **Parquet replay** windows before live/paper config deploy                                                         |
| Human ack (optional)     | Changes > **10%** to any threshold/weight may require operator confirm via UI (Phase 4+)                                                |




### 12.6 Failure Memory Retrieval Policy


| When                          | Query                             | Action                                                    |
| ----------------------------- | --------------------------------- | --------------------------------------------------------- |
| **Pre-trade (discretionary)** | Similar market context + strategy | Penalize confidence −0.10 if top-3 failure contexts match |
| **Post-trade (loss)**         | Trade outcome + signal snapshot   | Write structured summary to `failure_memory` collection   |
| **Adaptation cycle**          | Module + regime filter            | Surface recurring failure patterns to optimizer           |


Failure memory supplements — does not replace — quant signals and risk gates.

### 12.7 Signal → Outcome Attribution

Clean lineage required for module reweighting:

```
Signal → Decision → Order → Fill → Trade → P&L attribution
```

Stored in PostgreSQL: `signals.decision_id`, `orders.signal_id`, `fills.order_id`, `trades.fill_ids[]`, `analytics.module_attribution`. Every closed trade maps P&L back to originating module and strategy.

---



## 13. Analytics & Observability



### 13.1 Metrics Catalog


| Category               | Metrics                                           |
| ---------------------- | ------------------------------------------------- |
| **Trade performance**  | Win rate, profit factor, avg win/loss, expectancy |
| **Risk-adjusted**      | Sharpe, Sortino, max drawdown, recovery factor    |
| **Execution quality**  | Slippage, fill rate, time-to-fill                 |
| **Module attribution** | P&L and hit rate per strategy module              |
| **Greeks**             | Portfolio delta, gamma, vega, theta over time     |
| **RAG quality**        | Context precision, faithfulness (offline eval)    |
| **Bot health**         | Scheduler mode, last trade time, error rate       |




### 13.2 Frontend Dashboard Views


| View                          | Key Widgets                                                                                        |
| ----------------------------- | -------------------------------------------------------------------------------------------------- |
| **Recommendations (top-3)**   | **Complete insight packets** (§13.2.1): comparison strip, tabbed P1 packet per rank, feed/news, autonomous execution panel |
| **Integrations dashboard**    | Feed health, broker connection status, last fetch latency, stale feed alerts                       |
| **Option strategy simulator** | OSS Areas 1–5; **feed binding** selector per strategy; leg table with live marks from bound URLs   |
| Bot overview                  | Status, `EXECUTION_MODE`, scheduler mode, active circuit breakers, P&L, win rate, Sharpe, drawdown |
| Positions                     | Open positions, Greeks, unrealized P&L                                                             |
| Trade log                     | Autonomous decisions, fills, explanations, reject reasons                                          |
| Strategy breakdown            | Module weights, per-module performance, `strategy_enabled` flags                                   |
| Adaptation history            | Parameter changes, backtest results, config rollback                                               |
| Risk dashboard                | Greeks limits, exposure, circuit breaker status, auto-pause history                                |
| AI chat                       | RAG-powered Q&A                                                                                    |


### 13.2.1 Recommendations — Complete Insight UI

Route: `/recommendations`. Purpose: give the operator (or monitor in `fully_autonomous`) **full transparency** on why the bot ranked these three trades — not just symbols and scores.

**Layout (top → bottom):**

1. Header + refresh (same-cycle `GET /api/v1/recommendations`)
2. `AutonomousTradeExecutor` (when execution result present)
3. Feed status + **Market_News** sentiment overlay (§8.8)
4. Analysis notes
5. **Top-3 comparison table** (`Top3Comparison`)
6. **Complete insight packets** — one `RecommendationCard` per rank

**Per-rank tabs:** Overview · Score · Gates · Logic trail · Plan & risks · P1 checklist.

**Must surface (no silent omissions):**

- Why this rank vs peers (`why_this_rank`)
- Market condition + IV/GARCH/z-score parameters
- Strategy selection + rejected alternatives (Table SH-4)
- Score component breakdown
- Parameter gate pass/fail with refs
- Hedge construction + economics within INR 1,00,000 retail cap
- Exit plan, event risks, failure modes
- P1 completeness checklist

**Must not:** compute scores, GARCH, or Greeks in the browser — render backend packet only (`§5.2`).

**Sources:** `Trading_Parameters.md` Part P1; `Trading_Strategies.md` Pre-Approval Packet / Table SH-4; `UI_Dashboard.md` strategy panels (adapted for recommendation stage).

### 13.3 Logging & Audit Trail

Every autonomous decision logs:

- Input signals from all modules
- RAG context retrieved (chunk IDs + citations)
- LLM decision, confidence, explanation
- Risk gate result (per-check pass/fail with values)
- `config_snapshot_id` — which `configuration` version was active
- Order submitted (or rejection reason)
- Fill outcome and P&L

Decision logs are **append-only** for forensics (§20.4.9).

### 13.4 Alerting & External Notifications


| Alert                  | Trigger                                               | Channel                                                         |
| ---------------------- | ----------------------------------------------------- | --------------------------------------------------------------- |
| Drawdown breach        | Equity drawdown > 10%                                 | Email / Slack webhook                                           |
| Stale feed             | Feed stale > threshold                                | Dashboard + Slack                                               |
| Broker disconnect      | 3 consecutive auth/connection failures                | Slack + pause bot                                               |
| Groq degraded          | Fallback mode active > 5 min                          | Slack                                                           |
| Adaptation deployed    | Config change after validation                        | Audit log + dashboard                                           |
| Kill-switch activated  | Operator or auto-trigger                              | Immediate Slack + email                                         |
| Scheduler missed ticks | `missed_ticks >= 2` on `/health/bot`                  | Slack + auto-pause bot (§6.1.4)                                 |
| Daily loss breaker     | Daily loss > 2% equity                                | Slack + auto-pause (§11.4.1)                                    |
| Consecutive losses     | ≥ 5 consecutive losing trades                         | Slack + discretionary pause (§11.4.1)                           |
| Broker reject spike    | Reject rate > 10% in 1h                               | Slack + auto-pause all new orders                               |
| Win rate anomaly       | Win rate drops > 15% vs 7-day baseline in < 20 trades | Reduced-exposure mode (§6.2)                                    |
| Auto-pause triggered   | Any `auto_pause_rules` breach (§20.4.5)               | Slack + dashboard; **no auto-resume** unless `auto_resume=true` |
| Daily operator summary | End of market session                                 | Email / Slack: trades, P&L, drawdown, pauses, adaptations       |
| Unhandled exception    | Any uncaught error in trading path                    | Sentry + **immediate bot pause**                                |


Configured via `ALERT_WEBHOOK_URL` and `ALERT_EMAIL` env vars.

### 13.5 Observability Stack


| Layer           | Tool                                                                            | Metrics                                              |
| --------------- | ------------------------------------------------------------------------------- | ---------------------------------------------------- |
| Structured logs | JSON to stdout → **Cloud Logging** (Log Explorer)                               | Decision ID, signal ID, latency                      |
| Error tracking  | Sentry (optional)                                                               | Unhandled exceptions, broker errors                  |
| Metrics         | Prometheus-compatible `/metrics` endpoint                                       | Bot cycle latency, feed freshness, Groq tokens       |
| Health          | `GET /health`, `GET /health/api`, `GET /health/bot`, `GET /health/integrations` | Role-aware liveness; per-integration status (§6.1.4) |
| Dashboards      | Frontend + optional Grafana                                                     | P&L, Greeks, module attribution                      |


---



## 14. Data Architecture



### 14.1 Storage Topology

```mermaid
flowchart TB
    subgraph PostgreSQL
        STRATEGIES[option_strategies]
        LEGS[option_legs]
        EXPIRATIONS[expiration_dates]
        FEEDS[data_feeds]
        BROKERS[broker_connections]
        TRADES[trades]
        ORDERS[orders]
        POSITIONS[positions]
        CONFIG[configuration]
        CONFIG_AUDIT[configuration_audit]
        DECISIONS[decisions]
        DISSENT[decision_dissent]
        ANALYTICS[analytics_snapshots]
        LEARNING[learning_history]
        MDHIST[market_data_history]
    end

    subgraph Parquet
        REPLAY[replay_snapshots]
        OHLCV_HIST[ohlcv_archive]
    end

    subgraph ChromaDB
        KB[knowledge_base]
        FM[failure_memory]
        TI[trade_insights]
    end

    subgraph Redis
        CACHE[market_data_cache]
        STATE[bot_state]
        PUBSUB[pub_sub_events]
    end
```





### 14.2 Core Entity Relationships

```
Instrument (1) ──→ (N) MarketDataURL
Instrument (1) ──→ (N) ExpirationDate
OptionStrategy (1) ──→ (N) OptionLeg
OptionLeg (N) ──→ (0..1) ExpirationDate
OptionStrategy (1) ──→ (N) DataFeedBinding
DataFeed (1) ──→ (N) DataFeedBinding
Instrument (1) ──→ (N) DataFeed
BrokerConnection (1) ──→ (N) Order
OptionStrategy (1) ──→ (N) Signal
StrategyModule (1) ──→ (N) Signal
Signal (1) ──→ (0..1) Decision
Decision (1) ──→ (0..1) Order
Order (1) ──→ (0..N) OrderLeg
Order (1) ──→ (0..N) Fill
Fill (N) ──→ (1) Trade
Trade (N) ──→ (1) OptionStrategy
Trade (N) ──→ (1) StrategyModule
AdaptationCycle (1) ──→ (N) ConfigChange
```



### 14.3 Configuration Management


| Config Type                    | Storage                                                                                   | Mutability                           |
| ------------------------------ | ----------------------------------------------------------------------------------------- | ------------------------------------ |
| Environment secrets            | Env vars / secret manager                                                                 | Deploy-time                          |
| Strategy trade inputs          | PostgreSQL (`option_strategies`, `option_legs`, `expiration_dates`, `data_feed_bindings`) | Runtime (via API / OSS simulator UI) |
| Live data feeds                | PostgreSQL (`data_feeds`) + Redis cache                                                   | Runtime (via API)                    |
| Third-party broker connections | PostgreSQL (`broker_connections`, encrypted)                                              | Runtime (via API)                    |
| Strategy parameters            | PostgreSQL                                                                                | Runtime (via learning engine)        |
| Success ratio thresholds       | PostgreSQL                                                                                | Runtime (via API)                    |
| Broker connection              | PostgreSQL (encrypted)                                                                    | Runtime (via API) — see §11.6        |
| Bot mode (paper/live)          | PostgreSQL                                                                                | Runtime (feature flag)               |




### 14.4 Historical Data Storage


| Data Type                         | Store                        | Rationale                                         |
| --------------------------------- | ---------------------------- | ------------------------------------------------- |
| Trades, orders, config, analytics | PostgreSQL                   | Relational queries, ACID                          |
| Market data replay snapshots      | **Parquet** (`data/replay/`) | Columnar; efficient time-range reads for backtest |
| OHLCV long history                | **Parquet** per symbol       | Cheaper than Postgres rows at scale               |
| Hot cache                         | Redis                        | Latest quotes, bot state                          |
| Knowledge vectors                 | ChromaDB                     | Semantic retrieval                                |


Parquet files are written by the replay recorder (§8.7); metadata index in PostgreSQL `market_data_history`.

---



## 15. API & Integration Contracts



### 15.1 REST API Surface (Representative)


| Method | Endpoint                                      | Purpose                                                    |
| ------ | --------------------------------------------- | ---------------------------------------------------------- |
| `GET`  | `/api/v1/bot/status`                          | Bot mode, health, last activity, `EXECUTION_MODE`, `SUPERVISION_MODE` |
| `GET`  | `/api/v1/bot/supervision`                     | Supervision mode + promotion checklist status (§6.2.2) |
| `PUT`  | `/api/v1/bot/supervision`                     | Promote / demote `SUPERVISION_MODE` (audit-logged) |
| `POST` | `/api/v1/bot/kill-switch`                     | Pause trading                                                  |
| `POST` | `/api/v1/bot/pause`                           | Pause bot (alias for kill-switch)                          |
| `POST` | `/api/v1/bot/resume`                          | Resume from paused state                                   |
| `GET`  | `/api/v1/metrics`                             | Performance metrics                                        |
| `GET`  | `/api/v1/positions`                           | Open positions                                             |
| `GET`  | `/api/v1/trades`                              | Trade history                                              |
| `GET`  | `/api/v1/decisions`                           | Immutable decision log with explanations                   |
| `GET`  | `/api/v1/decisions/pending`                   | Approval queue (pre-approval packets)                      |
| `POST` | `/api/v1/decisions/{id}/approve`              | Operator approve → paper-sim or ICICI Direct submit (`supervised` / residual queue) |
| `POST` | `/api/v1/decisions/{id}/reject`               | Operator reject → no submit                                |
| `CRUD` | `/api/v1/config/market-data`                  | Live data feed URL registry                                |
| `CRUD` | `/api/v1/config/market-data/{feed_id}/health` | Feed freshness and fetch status                            |
| `CRUD` | `/api/v1/config/integrations/broker`          | Third-party broker connection config                       |
| `GET`  | `/api/v1/config/integrations/health`          | All integration health (feeds + broker)                    |
| `POST` | `/api/v1/config/integrations/broker/test`     | Test broker connection (paper)                             |
| `PUT`  | `/api/v1/strategies/{id}/feeds`               | Update strategy ↔ feed URL bindings (§8.6)                 |
| `CRUD` | `/api/v1/strategies`                          | Option strategy trade inputs (§8.5)                        |
| `POST` | `/api/v1/strategies/{id}/mark`                | Recompute leg prices and Greeks                            |
| `CRUD` | `/api/v1/config/strategy`                     | Strategy parameters                                        |
| `POST` | `/api/v1/chat`                                | RAG-powered user chatbot (four PDF corpus)                     |
| `GET`  | `/api/v1/learning/history`                    | Adaptation cycles                                          |
| `POST` | `/api/v1/knowledge/ingest`                    | Trigger re-ingestion of the four RAG PDFs (§3.2, §7)       |
| `GET`  | `/api/v1/knowledge/status`                    | Ingest versions, chunk counts, last golden-eval scores     |
| `GET`  | `/api/v1/recommendations`                     | Top-3 ranked instruments with complete insight packets; inline `autonomous_execution` only when `fully_autonomous` (§6.4, §13.2.1) |
| `POST` | `/api/v1/recommendations/execute-autonomous`  | Legacy explicit re-execute; only valid in `fully_autonomous` |




### 15.2 WebSocket Channels


| Channel      | Events                                                                 |
| ------------ | ---------------------------------------------------------------------- |
| `bot.status` | Mode changes (`EXECUTION_MODE`, `SUPERVISION_MODE`), health alerts |
| `trades`     | New fills, position updates, mechanical hedge activity             |
| `metrics`    | Rolling win rate, P&L, drawdown                                        |
| `decisions`  | Real-time decision log and trade events                                |
| `decisions.pending` | Pre-approval packets for operator queue (`supervised` / residual `semi_autonomous`) |
| `alerts`     | Risk breaches, adaptation triggers, **stale feed / broker disconnect** |




### 15.3 Internal Service Interfaces


| Interface                                    | Producer              | Consumer                   |
| -------------------------------------------- | --------------------- | -------------------------- |
| `MarketDataService.get(symbol, data_type)`   | Market data layer     | Quant modules, OSS marking |
| `IntegrationService.health()`                | Integrations registry | Bot scheduler, frontend    |
| `IntegrationService.get_broker()`            | Integrations registry | Execution layer            |
| `RAGService.retrieve(query, filters)`        | Knowledge layer       | AI engine, chat, learning  |
| `QuantService.run_all(market_snapshot)`      | Quant engine          | Decision orchestrator      |
| `DecisionService.evaluate(signals, context)` | AI engine             | Scheduler                  |
| `ExecutionService.submit(order)`             | Execution layer       | Scheduler                  |
| `LearningService.record_outcome(trade)`      | Learning engine       | Scheduler (post-fill)      |


---



## 16. Security Architecture



### 16.1 Threat Model Summary


| Asset            | Threat                        | Mitigation                                            |
| ---------------- | ----------------------------- | ----------------------------------------------------- |
| Broker API keys  | Exposure via frontend         | Server-side only; never sent to browser               |
| ICICI Direct secrets | Leak of API secret / session token | `ICICI_DIRECT_*` in Secret Manager only (§11.12); never log tokens; chatbot must not expose (§7.7) |
| Groq API key     | Leakage                       | `GROQ_API_KEY` in Secret Manager only; mounted to Cloud Run; never in frontend |
| Kill-switch      | Unauthorized bot pause/resume | Authenticated API; audit log                          |
| Market data URLs | SSRF via malicious URLs       | URL allowlist; sandboxed fetch; timeout limits        |
| User sessions    | Session hijacking             | HTTPS; secure cookies; token expiry                   |




### 16.2 Authentication Flow

```
Frontend → Backend API (session token / JWT)
Backend → ICICI Direct Breeze API (API key + daily API_Session → session_token, server-side — §11.9)
Backend → Groq API (`GROQ_API_KEY`, server-side only)
Backend → Market Data URLs (configured auth per endpoint; ICICI Direct marks via §8.9)
```



### 16.3 Roles & Authorization


| Role         | Permissions                                               |
| ------------ | --------------------------------------------------------- |
| **viewer**   | Read dashboards, trade log, metrics                       |
| **operator** | Configure feeds, strategies, kill-switch, resume bot      |
| **admin**    | Broker credentials, adaptation overrides, user management |


Kill-switch and broker credential changes require **operator** or **admin** role. All privileged actions append to immutable audit log (`audit_log` table, append-only).

### 16.4 Operational Security


| Concern                | Mitigation                                                                   |
| ---------------------- | ---------------------------------------------------------------------------- |
| Secrets rotation       | Broker keys (`ICICI_DIRECT_*`) and `GROQ_API_KEY` rotatable via Secret Manager new versions without code change |
| ICICI Direct session rotate   | Midnight IST logout / re-login via `session_manager` (§11.9); never reuse overnight JWT |
| Audit log immutability | `audit_log` append-only; no UPDATE/DELETE                                                    |
| ChromaDB backup        | Filestore snapshot or GCS export weekly; full re-ingest path documented (§7.6)                |
| Session security       | HTTPS; secure cookies; JWT expiry 24h; refresh token rotation                |




### 16.5 Network Boundaries


| Boundary              | Rule                           |
| --------------------- | ------------------------------ |
| Frontend ↔ Backend    | HTTPS + WSS only               |
| Backend ↔ ICICI Direct   | TLS; **live order APIs** from Cloud NAT **static egress IP** registered in Breeze API portal (§11.11, §17.8) |
| Backend ↔ Vector DB   | Internal network / localhost   |
| Backend ↔ Market URLs | Egress with SSRF protections   |


---



## 17. Deployment Architecture

Deployment is **phased by execution maturity**:

| Phase | Purpose | Frontend | Backend | Data tier |
| ----- | ------- | -------- | ------- | --------- |
| **Paper** (validation / soak) | `paper_sim` + supervised → autonomy ramp; **no** ICICI Direct `place_order` | **Vercel** | **Railway** | Railway Postgres + Redis |
| **Live** (after paper evidence) | ICICI Direct `EXECUTION_MODE=live` | **Cloud Run** | **Cloud Run** (API + worker) | Cloud SQL + Memorystore + Filestore Chroma |

Paper stack details: **§17.0**. Live GCP inventory remains **§17.8** (`asia-south1`). Do not run live order APIs on the Railway paper service.

### 17.0 Paper Trading Deployment (Railway + Vercel)

Hosted paper rehearsal uses the same `frontend/` + `backend/` folders with a lighter PaaS split. Authoritative paper behavior: `Docs/Paper_Simulator.md`.

```mermaid
flowchart TB
    subgraph Vercel_FE["Vercel — frontend/"]
        FE[Next.js App\nDashboard · Monitor · Chat · Kill Switch]
    end

    subgraph Railway_BE["Railway — backend/"]
        BE[FastAPI + Bot Scheduler\npaper_sim · Quant · RAG · Learning]
        PG[(Railway PostgreSQL)]
        REDIS[(Railway Redis)]
    end

    subgraph External
        GROQ[Groq API]
        ANGEL[ICICI Direct Breeze API\nmarks / instrument master only]
    end

    USER[User Browser] --> FE
    FE -->|REST + WSS\nNEXT_PUBLIC_API_URL| BE
    BE --> PG
    BE --> REDIS
    BE --> GROQ
    BE -->|LTP only — no place_order| ANGEL
```

#### Paper deployment units


| Unit | Source | Platform | Notes |
| ---- | ------ | -------- | ----- |
| Frontend | `frontend/` | **Vercel** | Set `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` to Railway public URL at build time |
| Backend | `backend/` | **Railway** | **Nixpacks** remote build of `backend/` (`PROCESS_ROLE=all`); keep awake during market hours — no local containers |
| PostgreSQL | — | Railway plugin | Trades, config, paper ledger persistence |
| Redis | — | Railway plugin | Cache, bot state, leader lock |
| Secrets | — | Railway variables | `GROQ_API_KEY`, ICICI Direct data credentials — never on Vercel |
| CI/CD | — | Vercel Git + Railway Git | Independent deploys per folder |

#### Paper deploy steps


| Step | Action |
| ---- | ------ |
| 1 | Create Railway project; add Postgres + Redis; deploy `backend/` with **Nixpacks** (`nixpacks.toml` / `Procfile` — no Dockerfile; no Docker Desktop) |
| 2 | Set Railway vars: `DATABASE_URL`, `REDIS_URL`, `GROQ_*`, ICICI Direct data keys, `EXECUTION_MODE=paper`, `PROCESS_ROLE=all` |
| 3 | Note public Railway HTTPS URL; confirm `GET /health` and `GET /api/v1/paper-sim/health` |
| 4 | Create Vercel project rooted at `frontend/`; set `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` |
| 5 | Set Railway `CORS_ORIGINS` to the Vercel URL(s) (+ custom domain if any); redeploy backend |
| 6 | Smoke: dashboard loads, paper account, WS events, automation start/stop |

**Hard rules on the paper stack:** `EXECUTION_MODE` stays `paper` (or `shadow`); ICICI Direct credentials are **data-only**; never enable Breeze API `place_order` on Railway. Live promotion moves to GCP (§17.8) with static egress IP for order APIs (§11.11).

Env templates: `infra/env/railway.paper.env.example`, `infra/env/vercel.paper.env.example`.

### 17.1 Environment Topology (Live — GCP)

For **ICICI Direct live** and production uptime, use **Google Cloud Platform**. The `frontend/` and `backend/` folders each build via **Google Cloud Buildpacks** (no Dockerfiles) into OCI images stored in **Artifact Registry** and run as separate **Cloud Run** services. Managed data stores (**Cloud SQL**, **Memorystore**) and persistent vector storage (**Filestore** for Chroma) live in the same GCP project (`asia-south1`) with private VPC connectivity.

```mermaid
flowchart TB
    subgraph GCP_Frontend["Cloud Run — frontend/ (VC-FE-01)"]
        FE[Next.js App\nDashboard · Monitor · Chat · Kill Switch]
    end

    subgraph GCP_Backend["Cloud Run — backend/ (VC-BE-*)"]
        BE[FastAPI + Bot Scheduler\nQuant · RAG · Learning · Execution]
    end

    subgraph GCP_Managed["GCP Managed Services"]
        PG[(Cloud SQL PostgreSQL)]
        REDIS[(Memorystore Redis)]
        CHROMA[Cloud Run ChromaDB\n+ Filestore NFS]
    end

    subgraph External
        GROQ[Groq API]
        BROKER[ICICI Direct Breeze API\n+ paper_sim ledger]
    end

    USER[User Browser] --> FE
    FE -->|REST + WSS\nNEXT_PUBLIC_API_URL| BE
    BE --> PG
    BE --> REDIS
    BE --> CHROMA
    BE --> GROQ
    BE --> BROKER
```



> **MVP topology** (above): single `BE` Cloud Run service with `PROCESS_ROLE=all`. **Production topology** (§17.7): split into `trading-api` + `trading-worker` Cloud Run services sharing Cloud SQL and Memorystore.



### 17.2 Deployment Units


| Unit                   | Source Folder | GCP service / product                                              | Scaling                             | Phase                         |
| ---------------------- | ------------- | ------------------------------------------------------------------ | ----------------------------------- | ----------------------------- |
| **Frontend**           | `frontend/`   | **Cloud Run** (`VC-FE-01`)                                         | Request-based; optional CDN/LB      | MVP                           |
| **Backend (combined)** | `backend/`    | **Cloud Run** (Buildpacks image, `PROCESS_ROLE=all`)               | `min-instances=1`; CPU always on    | MVP                           |
| **Backend API**        | `backend/`    | **Cloud Run** (`PROCESS_ROLE=api`)                                 | Horizontal (stateless)              | Production uptime             |
| **Backend worker**     | `backend/`    | **Cloud Run** (`PROCESS_ROLE=worker`)                              | **`max-instances=1`** + Redis lock  | Production uptime             |
| **PostgreSQL**         | —             | **Cloud SQL for PostgreSQL** 16                                    | Managed HA (optional prod)          | MVP                           |
| **Redis**              | —             | **Memorystore for Redis** 7                                        | Managed service                     | MVP                           |
| **Vector DB**          | —             | **Cloud Run** + **Filestore** (Chroma HTTP) or **Chroma Cloud**    | NFS volume 10 GB; `min-instances=1` | MVP → separate service uptime |
| **Container registry** | —             | **Artifact Registry** (`asia-south1-docker.pkg.dev/...`)           | Immutable Buildpacks image tags     | MVP                           |
| **Secrets**            | —             | **Secret Manager**                                                 | Versioned secrets                   | MVP                           |
| **CI/CD**              | —             | **Cloud Build** (+ optional GitHub Actions invoking `gcloud`)      | Per-folder triggers                 | MVP                           |




### 17.3 Cloud Run Deployment — Frontend (`frontend/`)


| Step | Action                                                                                          |
| ---- | ----------------------------------------------------------------------------------------------- |
| 1    | Enable APIs: Cloud Run, Cloud Build, Artifact Registry, Secret Manager                           |
| 2    | Create Artifact Registry repo `volatality` (format: Docker/OCI, region `asia-south1`)          |
| 3    | Configure Cloud Build trigger on `frontend/**` → **Cloud Buildpacks** → push image              |
| 4    | Deploy Cloud Run service `volatality-frontend` (`VC-FE-01`) from image                          |
| 5    | Set env vars: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL` (backend API URL)                     |
| 6    | Map custom domain (optional): Cloud Load Balancing + managed SSL certificate + Cloud DNS        |


The frontend container runs Next.js in standalone mode. It never holds secrets—only public backend URLs in `NEXT_PUBLIC_*` variables baked at build time or injected via Cloud Run env.

### 17.4 Cloud Run Deployment — Backend (`backend/`)


| Step | Action                                                                                                                                                                                     |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1    | Create GCP project(s): `volatality-staging`, `volatality-production` (recommended separate projects)                                                                                     |
| 2    | Provision **Cloud SQL** (MS-DB-01) and **Memorystore** (MS-DB-02) in `asia-south1`                                                                                                          |
| 3    | Create **Serverless VPC Access connector**; configure private IP for Cloud SQL and Memorystore                                                                                             |
| 4    | Deploy **Chroma** (VC-BE-04): Cloud Run + **Filestore** NFS mount at `/chroma/chroma`                                                                                                      |
| 5    | Store secrets in **Secret Manager**; grant Cloud Run service account `secretAccessor`                                                                                                      |
| 6    | Cloud Build trigger on `backend/**` → **Cloud Buildpacks** (`backend/cloudbuild.yaml`) → deploy Cloud Run |
| 7    | Configure env vars and secret references: `GROQ_API_KEY`, `DATABASE_URL`, `REDIS_URL`, `CHROMA_HOST`, `CORS_ORIGINS`, `BROKER_API_KEY`, `PROCESS_ROLE`                                     |
| 8    | Set startup/liveness probe per `PROCESS_ROLE` (§6.1.4); enable **CPU always allocated** for `all` and `worker` roles                                                                     |


**MVP (single service):** Deploy one Cloud Run service `volatality-trading` with `PROCESS_ROLE=all`, `min-instances=1`, CPU always allocated. Health probe hits `GET /health`.

**Production uptime (split services):** Deploy two Cloud Run services from the same image — `volatality-trading-api` (`PROCESS_ROLE=api`, probe `/health/api`) and `volatality-trading-worker` (`PROCESS_ROLE=worker`, probe `/health/bot`, **`max-instances=1`**). Point frontend `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` at the API service URL only. See §17.7.

ChromaDB data must survive redeploys via the Filestore NFS mount (not ephemeral Cloud Run storage).

### 17.5 CI/CD Pipeline (Cloud Build)

```
Push to main
    │
    ├── frontend/ changed ──► Cloud Build trigger
    │         ├── npm ci + lint + build
    │         ├── Cloud Buildpacks → Artifact Registry
    │         └── gcloud run deploy volatality-frontend
    │
    └── backend/ changed ──► Cloud Build trigger
              ├── ruff / mypy lint
              ├── pytest unit + integration
              ├── OSS parity tests (§8.5.12)
              ├── RAG golden eval — faithfulness ≥ 0.85 (§7, §22)
              ├── Cloud Buildpacks → Artifact Registry
              ├── Deploy gate (production, market hours):
              │     POST /api/v1/bot/pause → wait for safe state
              │     → gcloud run deploy → verify /health/bot → POST /api/v1/bot/resume
              └── Smoke test → staging/production
```

**Cloud Build config files:**

| File                              | Purpose                                      |
| --------------------------------- | -------------------------------------------- |
| `frontend/cloudbuild.yaml`        | Build + deploy frontend Cloud Run service    |
| `backend/cloudbuild.yaml`         | Test + build + deploy backend Cloud Run service |
| `infra/gcp/cloudbuild-staging.yaml` | Optional unified pipeline with substitutions |

**Service account permissions (least privilege):**

| SA                         | Roles                                                                 |
| -------------------------- | --------------------------------------------------------------------- |
| `volatality-cloudbuild@`   | `cloudbuild.builds.builder`, Artifact Registry writer, Cloud Run admin |
| `volatality-api-run@`      | Secret Manager accessor, Cloud SQL client, VPC Access user              |
| `volatality-worker-run@`   | Same as API SA; no public invoker on worker (internal health only)    |



### 17.6 Knowledge Document Ingestion Job

Knowledge-document ingestion runs as an **offline/batch job** (not in the hot trading path):

- Triggered on deploy, document version change, or manual API call
- Ingests the four RAG PDFs (`Volatility Trading`, `Gamma Scalping`, `Vega Scalping`, `Trading_Strategies`)
- Writes to ChromaDB `knowledge_base` collection
- Emits completion event for monitoring



### 17.7 Process Topology Evolution (MVP → 99% Uptime)

A single Cloud Run service running API + bot scheduler shares one failure domain: deploys, crashes, and resource contention take down both surfaces simultaneously. The **modular monolith** code layout is retained; **runtime topology** evolves in phases (0–3 below).

#### Failure modes (single process)


| Failure                                 | Impact                                      |
| --------------------------------------- | ------------------------------------------- |
| Deploy on `main` push                   | Trading loop stops for container restart    |
| API load spike (chat, dashboards)       | CPU/memory contention on bot decision cycle |
| Unhandled exception in any module       | Whole process dies — API and bot together   |
| `/health` passes, scheduler wedged      | Silent trading outage                       |
| Horizontal replicas without leader lock | Duplicate bot instances → duplicate orders  |




#### Phase 0 — Uptime-aware MVP (`PROCESS_ROLE=all`)

Ship the monolith, but build the seams required for a clean split:

- [ ] `PROCESS_ROLE` env var with `all` / `api` / `worker` entrypoints (§6.1.4)
- [ ] Split health endpoints: `/health/api`, `/health/bot`
- [ ] Redis leader lock (`bot:leader`) acquired before trading loop
- [ ] Bot state checkpointed in Redis each tick (§19 recoverability)
- [ ] Deploy gate: pause bot → deploy → verify `/health/bot` → resume (§17.5)
- [ ] Heavy jobs (knowledge-doc ingestion, adaptation backtests) never run in the API hot path

**NFR stance for MVP:** Measure **recoverability** (resume after crash within 60s) rather than claiming 99% uptime.

#### Phase 1 — Split processes (required for 99% target)

Two Cloud Run services, same container image, different `PROCESS_ROLE`:

```mermaid
flowchart LR
    subgraph CloudRun_FE["Cloud Run — Frontend"]
        FE[Next.js]
    end

    subgraph CloudRun_BE["Cloud Run — Backend"]
        API[trading-api\nPROCESS_ROLE=api]
        WRK[trading-worker\nPROCESS_ROLE=worker\nmax-instances=1]
    end

    subgraph GCP_Data["GCP Managed"]
        PG[(Cloud SQL)]
        RD[(Memorystore)]
    end

    FE -->|REST + WSS| API
    API --> PG
    API --> RD
    WRK --> PG
    WRK --> RD
    WRK -.->|bot:events pub/sub| API
    WRK -->|orders| BROKER[Broker API]
```




| Win                             | How                                                |
| ------------------------------- | -------------------------------------------------- |
| API deploy does not restart bot | Separate Cloud Run services                        |
| API crash does not stop trading | Worker is independent service                      |
| Dashboard/chat load isolated    | Worker not serving public HTTP                     |
| Safe API scaling                | `api` role is stateless; worker stays at 1 instance |


**Gate to promote from MVP to Phase 1:** Before claiming 99% availability during market hours (§19).

#### Phase 2 — Async job queue (optional hardening)

Move non-latency-critical work to **Celery + Redis** (§18.1):


| Job                                              | Runner                                   |
| ------------------------------------------------ | ---------------------------------------- |
| Trading tick / hedge loop                        | Dedicated worker (`PROCESS_ROLE=worker`) |
| Knowledge-doc ingestion, golden eval, adaptation backtests | Celery worker (burst, retryable)         |
| Learning / adaptation cycle                      | Celery Beat trigger                      |


Keeps the trading worker lean; batch work cannot starve the decision cycle.

#### Phase 3 — External uptime controls


| Control                                                         | Purpose                                                               |
| --------------------------------------------------------------- | --------------------------------------------------------------------- |
| External monitor on `/health/bot` (e.g. Better Uptime, Checkly) | Detect silent scheduler death                                         |
| Alert on `missed_ticks >= 2` (§13.4)                            | Operator notification + auto-pause                                    |
| Deploy only outside market hours (or blue/green worker swap)    | Avoid largest downtime source                                         |
| Chroma HTTP service (separate Cloud Run + Filestore)            | Vector DB restart does not take down bot                              |
| Platform SLA review                                             | Move worker to **Compute Engine** VM if Cloud Run cold starts exceed budget |




#### Uptime measurement

During configured market hours, track **bot tick success rate**, not container uptime:

```
uptime = successful_ticks / expected_ticks
```


| Phase                 | Target                                                                 |
| --------------------- | ---------------------------------------------------------------------- |
| MVP (Phase 0)         | Recoverability: resume within 60s of crash; no duplicate-bot incidents |
| Production (Phase 1+) | ≥ 99% tick success rate during market hours                            |




### 17.8 Cloud Infrastructure & Virtual Compute Provisioning (Live — GCP)

**Scope:** ICICI Direct **live** and production uptime. Paper trading does **not** use this inventory — use Railway + Vercel (§17.0) until promotion.

Live facilities are provisioned entirely on **Google Cloud Platform** in **`asia-south1`**. **Cloud Run** services are the project's **virtual computers** — containerized workloads with defined CPU, memory, and scaling policies. **Cloud SQL**, **Memorystore**, and **Filestore** provide managed persistence. The canonical inventory lives in `infra/cloud-inventory.yaml`; step-by-step setup is in `infra/provision/PROVISIONING.md`.

#### Cloud platform strategy


| Platform / product         | Role                                               | Compute model                                        |
| -------------------------- | -------------------------------------------------- | ---------------------------------------------------- |
| **Cloud Run**              | Frontend, backend API, bot worker, ChromaDB        | Serverless containers; scale-to-zero (except worker)  |
| **Cloud SQL**              | PostgreSQL 16                                      | Fully managed relational DB                          |
| **Memorystore**            | Redis 7                                            | Fully managed in-memory store                        |
| **Filestore**              | Chroma persistent NFS volume                       | Managed NFS; mounted into Chroma Cloud Run service   |
| **Artifact Registry**      | OCI images from Buildpacks                         | Immutable build artifacts                            |
| **Secret Manager**         | API keys, DB credentials                           | Versioned secrets injected at runtime                |
| **Cloud Build**            | CI/CD pipelines                                    | Buildpacks build, test, deploy on git push           |
| **Cloud Logging / Monitoring** | Logs, metrics, alerts                          | Structured JSON logs; uptime checks on `/health/bot` |
| **Local native toolchain** | Dev-only (Python + Node; optional winget PG/Redis) | No Compose / Docker Desktop (`Docs/LOCAL_DEV.md`)    |


MVP uses Cloud Run for all application tiers — no self-managed GCE VMs required. A dedicated **Compute Engine** instance for the trading worker (`VC-BE-06`, optional) is a Phase 3 fallback if Cloud Run restart latency exceeds the uptime budget (§17.7).

#### GCP projects and environments


| Environment     | Where it runs                         | Services                                      | Purpose                                       |
| --------------- | ------------------------------------- | --------------------------------------------- | --------------------------------------------- |
| **Development** | Local                                 | `npm run dev` + `uvicorn` (+ optional native PG/Redis) | Feature development                    |
| **Paper**       | **Vercel** + **Railway** (§17.0)      | Vercel frontend + Railway Nixpacks backend (+ PG/Redis)| Paper-sim validation, soak, supervision ramp  |
| **Live / prod** | **GCP** `volatality-production` (§17.8) | Split Cloud Run API + worker + Cloud SQL    | ICICI Direct `live` after paper evidence         |


**Primary region:** `asia-south1` (Mumbai) — aligned with NSE / BSE / NFO session hours (IST) and ICICI Direct Breeze API latency. Co-locate Cloud Run, Cloud SQL, Memorystore, and Filestore in the same region to minimize latency.

#### Virtual compute inventory


| ID            | Name                        | GCP product    | Type                    | vCPU | RAM           | Storage           | Phase    | Role                         |
| ------------- | --------------------------- | -------------- | ----------------------- | ---- | ------------- | ----------------- | -------- | ---------------------------- |
| **VC-FE-01**  | `volatality-frontend`       | Cloud Run      | Next.js (Buildpacks)    | 1    | 512 MB–1 GB   | —                 | MVP      | Dashboard, chat, kill-switch |
| **VC-BE-01**  | `volatality-trading`        | Cloud Run      | Buildpacks (`backend/`) | 2    | 4 GB          | ephemeral         | MVP      | `PROCESS_ROLE=all`           |
| **VC-BE-02**  | `volatality-trading-api`    | Cloud Run      | Buildpacks (`backend/`) | 1    | 2 GB          | —                 | Prod     | REST + WebSocket API         |
| **VC-BE-03**  | `volatality-trading-worker` | Cloud Run      | Buildpacks (`backend/`) | 2    | 4 GB          | —                 | Prod     | Bot scheduler (`max-instances=1`) |
| **VC-BE-04**  | `volatality-chroma`         | Cloud Run      | Chroma HTTP + NFS       | 1    | 2 GB          | 10 GB Filestore   | MVP      | Chroma HTTP server           |
| **VC-BE-05**  | `volatality-celery-worker`  | Cloud Run Jobs | Buildpacks (`backend/`) | 2    | 4 GB          | —                 | Optional | Async batch jobs             |
| **VC-BE-06**  | `volatality-trading-worker-vm` | Compute Engine | e2-medium VM         | 2    | 4 GB          | 20 GB boot PD     | Optional | Worker fallback (Phase 3)    |
| **VC-LOC-01** | `volatality-postgres-local` | Native install | PostgreSQL 16           | —    | —             | local disk        | Dev      | Optional `LOCAL_INFRA=native` |
| **VC-LOC-02** | `volatality-redis-local`    | Native install | Redis 7                 | —    | —             | local disk        | Dev      | Optional `LOCAL_INFRA=native` |
| **VC-LOC-03** | `volatality-chroma-local`    | Embedded       | Chroma PersistentClient | —    | —             | `CHROMA_PERSIST_DIRECTORY` | Dev | Default local RAG mode |




#### Managed services


| ID           | Name                  | GCP product              | Version | Sizing (staging)       | Role                                          |
| ------------ | --------------------- | ------------------------ | ------- | ---------------------- | --------------------------------------------- |
| **MS-DB-01** | `volatality-postgres` | Cloud SQL for PostgreSQL | 16      | db-f1-micro / 10 GB SSD | Trades, config, analytics, learning           |
| **MS-DB-02** | `volatality-redis`    | Memorystore for Redis    | 7       | Basic tier, 1 GB       | Market cache, bot state, pub/sub, leader lock |
| **MS-ST-01** | `volatality-chroma-fs`| Cloud Filestore          | —       | BASIC_HDD, 1 TB (min)  | NFS backing store for Chroma persistence      |




#### Networking topology

```mermaid
flowchart TB
    subgraph Dev["Development (native local)"]
        LOC_PG[(VC-LOC-01 Postgres optional)]
        LOC_RD[(VC-LOC-02 Redis optional)]
        LOC_CH[VC-LOC-03 Embedded Chroma]
        LOC_BE[backend uvicorn\nlocalhost:8000]
        LOC_FE[frontend npm dev\nlocalhost:3000]
        LOC_BE --> LOC_PG
        LOC_BE --> LOC_RD
        LOC_BE --> LOC_CH
        LOC_FE --> LOC_BE
    end

    subgraph Staging["Staging / Production (GCP)"]
        VFE[VC-FE-01 Cloud Run Frontend]
        VAPI[VC-BE-02 trading-api\nor VC-BE-01 MVP]
        VWRK[VC-BE-03 trading-worker]
        VCH[VC-BE-04 Chroma + Filestore]
        PG[(MS-DB-01 Cloud SQL)]
        RD[(MS-DB-02 Memorystore)]
        VPC[Serverless VPC Access Connector]
        VFE -->|HTTPS + WSS| VAPI
        VAPI --> VPC
        VWRK --> VPC
        VCH --> VPC
        VPC --> PG
        VPC --> RD
        VAPI --> VCH
        VWRK --> VCH
        VWRK -.->|bot:events| VAPI
    end
```





#### Local development — native toolchain

See **`Docs/LOCAL_DEV.md`**. No Compose / Docker Desktop.

```powershell
.\scripts\dev\check-env.ps1
.\scripts\dev\start-backend.ps1
.\scripts\dev\start-frontend.ps1   # second terminal
```


| Service    | Endpoint                | Dev credentials                                               |
| ---------- | ----------------------- | ------------------------------------------------------------- |
| API        | `http://127.0.0.1:8000` | —                                                             |
| UI         | `http://127.0.0.1:3000` | —                                                             |
| PostgreSQL | `localhost:5432`        | Optional `LOCAL_INFRA=native`: user `volatality`, password `volatality_dev`, db `volatality` |
| Redis      | `localhost:6379`        | Optional `LOCAL_INFRA=native`: no auth (dev only)             |
| ChromaDB   | embedded on disk        | `CHROMA_PERSIST_DIRECTORY=./backend/data/chroma`              |


Backend `.env` for Phase 0 local (default):

```
LOCAL_INFRA=none
DATABASE_URL=
REDIS_URL=
CHROMA_PERSIST_DIRECTORY=./backend/data/chroma
PROCESS_ROLE=all
```

Optional native persistence:

```
LOCAL_INFRA=native
DATABASE_URL=postgresql+psycopg://volatality:volatality_dev@localhost:5432/volatality
REDIS_URL=redis://localhost:6379/0
PROCESS_ROLE=all
```



#### Cloud provisioning steps (summary)

Full checklist: `infra/provision/PROVISIONING.md`.


| Step | Action                                                                                      |
| ---- | ------------------------------------------------------------------------------------------- |
| 1    | Create GCP project (`volatality-staging` or `volatality-production`); enable billing        |
| 2    | Enable APIs: Run, Build, SQL Admin, Redis, Filestore, Secret Manager, VPC Access, Artifact Registry |
| 3    | Create VPC + **Serverless VPC Access connector** in `asia-south1`                          |
| 4    | Provision **MS-DB-01** (Cloud SQL PostgreSQL 16) and **MS-DB-02** (Memorystore Redis)       |
| 5    | Provision **MS-ST-01** (Filestore BASIC_HDD); deploy **VC-BE-04** (Chroma Cloud Run + NFS mount) |
| 6    | Create Artifact Registry repo; store secrets in **Secret Manager**                          |
| 7    | Deploy **VC-BE-01** (MVP) or **VC-BE-02** + **VC-BE-03** (production split) via Cloud Build |
| 8    | Deploy **VC-FE-01** (frontend Cloud Run); set `NEXT_PUBLIC_*` URLs to API service           |
| 9    | Set backend `CORS_ORIGINS` to frontend URL; verify `/health` and frontend connectivity      |
| 10   | Configure Cloud Monitoring uptime check on `/health/bot` (production worker)                |




#### Environment variable templates


| File                                      | Target                            |
| ----------------------------------------- | --------------------------------- |
| `infra/env/gcp.staging.env.example`       | Cloud Run env vars (staging)      |
| `infra/env/gcp.production.env.example`    | Cloud Run env vars (production)   |


Secrets (`GROQ_API_KEY`, broker keys, `DATABASE_URL`) are stored in **Secret Manager** — never committed. Cloud Run references secrets by resource name (e.g. `projects/.../secrets/groq-api-key/versions/latest`).

#### Estimated monthly cost (MVP staging, asia-south1)


| Resource                                  | Approx. cost   |
| ----------------------------------------- | -------------- |
| Cloud Run backend (`VC-BE-01`, always-on) | $25–40         |
| Cloud Run frontend (`VC-FE-01`)           | $5–15          |
| Cloud SQL db-f1-micro + 10 GB             | $10–15         |
| Memorystore Basic 1 GB                    | $35–45         |
| Filestore BASIC_HDD (1 TB minimum)        | $200+ *        |
| Cloud Run Chroma (`VC-BE-04`)             | $10–20         |
| Secret Manager + Cloud Build              | $5–10          |
| Groq API                                  | usage-based    |
| **Total infrastructure**                  | **~$90–150/mo** (excl. Filestore min) |

\* **Filestore cost note:** Filestore BASIC_HDD has a **1 TB minimum** allocation (~$200/mo). For MVP staging, prefer **Chroma Cloud** (external) or run Chroma on a small **Compute Engine e2-small** with a persistent disk (~$15/mo) instead of Filestore until production. See §20.2 trade-offs.

Production split topology (API + worker) adds ~$30–50/mo for the second always-on Cloud Run service.

#### ChromaDB persistence options (GCP)


| Option | GCP resources | Best for | Approx. cost |
| ------ | ------------- | -------- | ------------ |
| **A — GCE + persistent disk (recommended MVP)** | e2-small VM + 20 GB PD + Chroma HTTP process | Staging, cost-sensitive MVP | ~$15–25/mo |
| **B — Chroma Cloud (external)** | Cloud Run backend → Chroma Cloud API | Zero Chroma ops; fastest MVP | Chroma Cloud pricing |
| **C — Cloud Run + Filestore NFS** | VC-BE-04 + MS-ST-01 | Production HA path | ~$200+/mo (Filestore 1 TB min) |
| **D — Embedded in backend process** | Not recommended for live | Local / paper only | Ephemeral on Cloud Run redeploy |


Use **Option A or B** for Phase 1a vertical slice; migrate to **Option C** when production uptime and backup SLAs require managed NFS.

---



## 18. Technology Stack



### 18.1 Summary


| Layer                   | Technology                                                               |
| ----------------------- | ------------------------------------------------------------------------ |
| **Frontend**            | Next.js, Tailwind CSS, shadcn/ui, TanStack Query, Lightweight Charts     |
| **Backend API**         | Python, FastAPI (REST + WebSocket)                                       |
| **Bot scheduler**       | APScheduler or Celery Beat                                               |
| **Orchestration**       | LangChain or LlamaIndex                                                  |
| **Markdown parsing**    | Python-Markdown (AST) + custom table splitter                            |
| **Embeddings**          | `bge-m3` (primary); `bge-large-en-v1.5` fallback                         |
| **Vector DB**           | **ChromaDB** (`chromadb` client; embedded or HTTP server)                |
| **Keyword search**      | BM25 (`rank_bm25` in application layer, fused with Chroma dense results) |
| **Re-ranker**           | `bge-reranker-large`                                                     |
| **Historical data**     | Parquet (replay/OHLCV) + PostgreSQL metadata                             |
| **Orchestration**       | Direct `chromadb` / `groq` clients; LangChain optional for chains only   |
| **LLM**                 | **Groq API** (`groq` SDK) — `llama-3.3-70b-versatile` (primary)          |
| **Quant / ML**          | pandas, numpy, scipy, statsmodels, scikit-learn, Optuna                  |
| **Broker**              | ICICI Direct Breeze API (`breeze-connect` / REST + WS)                   |
| **Persistence**         | PostgreSQL + Redis                                                       |
| **RAG evaluation**      | Ragas + DeepEval                                                         |
| **Frontend deployment** | **Paper: Vercel** · **Live: Cloud Run** (Buildpacks from `frontend/`)    |
| **Backend deployment**  | **Paper: Railway Nixpacks** · **Live: Cloud Run** (Buildpacks) + Cloud SQL + Memorystore |
| **CI/CD**               | **Paper:** Vercel + Railway Git · **Live:** Cloud Buildpacks → Artifact Registry → Cloud Run |
| **Secrets**             | **Paper:** Railway vars · **Live:** Secret Manager                       |
| **Local toolchain**     | Python + Node; optional native Postgres/Redis — **no Docker / Compose** (`Docs/LOCAL_DEV.md`) |




### 18.2 Local Development Stack

Local development uses a **native** toolchain. Frontend and backend run as separate host processes. Optional Postgres/Redis are native Windows installs (`LOCAL_INFRA=native`). Chroma defaults to embedded disk persistence. There is **no** `docker-compose.yml` and no local container runtime.

```
Project root/
├── frontend/                   # npm run dev (port 3000)
├── backend/                    # uvicorn backend.main:app --reload (port 8000)
└── Docs/LOCAL_DEV.md           # Canonical local workflow
```

**Local env files:**

- `frontend/.env.local` → `NEXT_PUBLIC_API_URL=http://localhost:8000`
- `backend/.env` / root `.env` → `GROQ_API_KEY`, optional `DATABASE_URL` / `REDIS_URL`, `CHROMA_PERSIST_DIRECTORY=./backend/data/chroma`

**Paper remote:** Railway **Nixpacks** (`backend/nixpacks.toml`, `Procfile`, `scripts/start_remote.sh`).  
**Live remote:** Google **Cloud Buildpacks** (`backend/cloudbuild.yaml`).

---



## 19. Non-Functional Requirements


| Requirement        | Target                                                                                                             |
| ------------------ | ------------------------------------------------------------------------------------------------------------------ |
| **Availability**   | ≥ 99% bot tick success rate during configured market hours (Phase 1+); MVP measures recoverability instead (§17.7) |
| **Latency**        | Decision cycle < 5s (excluding LLM); order submission < 2s                                                         |
| **Data freshness** | Market data stale threshold configurable (e.g., 60s)                                                               |
| **Recoverability** | Bot state persisted in Redis; resume after crash                                                                   |
| **Auditability**   | Full decision log retained 1+ year                                                                                 |
| **Testability**    | Unit + integration + replay E2E tests; paper-sim + ICICI Direct shadow (§22)                                          |
| **Extensibility**  | New strategy = new quant module; broker remains ICICI Direct                                                          |
| **Observability**  | Structured JSON logging, `/metrics`, health endpoints, alerting (§13.4–13.5)                                       |


---



## 20. Risks, Trade-offs & Open Decisions



### 20.1 Key Risks


| Risk                       | Impact                                             | Mitigation                                                                                                                      |
| -------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| RAG ingestion quality      | Poor AI decisions                                  | Golden eval suite + CI gate; chunk regression tests (§7)                                                                        |
| Paper ≠ live fills         | Overestimated performance                          | Conservative fill mode default (§11.7); transaction cost model (§9.4)                                                           |
| Adaptation overfitting     | Parameter churn                                    | Walk-forward validation; min 30 trades; 20% max change (§12.5)                                                                  |
| Broker API instability     | Missed hedges                                      | Retry logic; alert on failure                                                                                                   |
| URL data quality           | Bad signals                                        | JSON Schema validation; stale data rejection (§8.7)                                                                             |
| Groq rate limits / latency | Slow or throttled decision cycle                   | Retry with backoff; cached RAG; degraded quant-only mode (§10.6)                                                                |
| LLM over-reliance          | Inconsistent decisions                             | Quant-first; rule fast path for mechanical hedges (§10.6)                                                                       |
| **Autonomy risk**          | Wrong guardrails → bad trades at scale             | Graduated `EXECUTION_MODE`; portfolio circuit breakers (§11.4.1); auto-pause rules (§20.4.5); full control set in **§20.4**     |
| Single-process API + bot   | Deploy/crash takes down trading; misses 99% target | `PROCESS_ROLE` split → API + worker Cloud Run services; Redis leader lock; deploy pause gate; split health checks (§6.1.4, §17.7) |




### 20.2 Architectural Trade-offs


| Decision                     | Choice                                                                            | Rationale                                                                                          |
| ---------------------------- | --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| LLM provider                 | **Groq API**                                                                      | Low-latency inference; cost-effective; `llama-3.3-70b-versatile` for reasoning                     |
| Frontend deployment          | **Paper: Vercel** · **Live: Cloud Run**                                   | Fast paper UI deploys on Vercel; containerized GCP pairing for live        |
| Backend deployment           | **Paper: Railway** · **Live: Cloud Run** + Cloud SQL + Memorystore        | Always-on Railway for paper scheduler; GCP VPC + static egress for live orders |
| Repo layout                  | Standalone `frontend/` + `backend/` folders                               | Independent builds, clear deploy boundaries, separate env configs          |
| Monolith vs. microservices   | Modular monolith in `backend/`; split into API + worker **processes** at Phase 1  | Faster MVP; clear module boundaries; 99% uptime without microservice sprawl (§17.7)                |
| ChromaDB vs. Pinecone/Qdrant | **ChromaDB**                                                                      | Native Python integration, metadata filtering, embedded or server mode, no external vendor lock-in |
| bge-m3 vs. OpenAI embeddings | **bge-m3** + **bge-reranker-large**                                               | Strong on technical text; cost control; pinned stack                                               |
| Autonomous vs. manual      | **Graduated supervision** (`supervised` → `semi_autonomous` → `fully_autonomous`) + kill-switch | Phase 2 default on paper is supervised; autonomy earned via promotion checklist (§6.2.2, §21) |
| Quant vs. LLM authority      | **Quant leads**                                                                   | Rules for mechanical hedges; LLM gates discretionary entries                                       |
| Embedded vs. HTTP Chroma     | Embedded local / HTTP prod                                                        | Same `chromadb` API; GCE persistent disk or Chroma Cloud for MVP; Filestore for production (§17.8) |
| Cloud platform               | **Paper: Railway + Vercel** · **Live: GCP** (`asia-south1`)               | Cheap paper hosting; GCP for live inventory, VPC, Cloud NAT static IP      |
| Orchestration                | Direct clients over framework                                                     | Simpler modular monolith; LangChain optional                                                       |
| Historical data              | **Parquet + Postgres**                                                            | Parquet for time-series replay; Postgres for relational data                                       |
| Primary broker               | **ICICI Direct** (Indian markets only)                                               | Breeze API REST + WS; paper via `paper_sim` + `shadow` — no US brokers               |
| Feed / order integration     | **ICICI Direct direct** (no MCP registry)                                            | Marks + `place_order` via Breeze API; sentiment via `Market_News.txt` (§8.8)          |




### 20.3 Resolved & Remaining Decisions


| #   | Decision                                   | Choice                                                                                 | Status                           |
| --- | ------------------------------------------ | -------------------------------------------------------------------------------------- | -------------------------------- |
| 1   | Primary broker (MVP)                       | **ICICI Direct** (NSE / BSE / NFO only)                                                   | **Resolved**                     |
| 2   | Orchestration framework                    | Direct `chromadb`/`groq` clients; LangChain optional                                   | **Resolved**                     |
| 3   | Historical data storage                    | **Parquet** (replay/OHLCV) + PostgreSQL (metadata)                                     | **Resolved**                     |
| 4   | Regime classifier (initial)                | **Rule-based** (VIX percentile, HV/IV ratio, trend); ML/HMM Phase 4                    | **Resolved**                     |
| 5   | Multi-leg option orders                    | **Phase 1 paper_sim** auto-complete without consent (same open rules); live sequential + rollback Phase 5 | **Resolved**                     |
| 6   | Embedding / reranker stack                 | **bge-m3** + **bge-reranker-large**                                                    | **Resolved**                     |
| 7   | Primary broker (Phase 2+)                  | ICICI Direct remains sole broker; deepen multi-leg / NFO coverage                         | **Resolved**                     |
| 8   | Regime classifier (advanced)               | HMM vs. ML classifier                                                                  | Open                             |
| 9   | Process topology for production            | API + worker split (`PROCESS_ROLE`); MVP stays `all`                                   | **Resolved** — §6.1.4, §17.7     |
| 10  | Cloud compute platform                     | **Paper:** Railway + Vercel (§17.0); **Live:** GCP Cloud Run + Cloud SQL + Memorystore (`asia-south1`, §17.8) | **Resolved** — §17.0, §17.8 |
| 11  | Autonomy risk controls                     | Graduated execution modes, circuit breakers, auto-pause, config versioning             | **Resolved** — §20.4             |
| 12  | Supervision path + one trade at a time | `SUPERVISION_MODE`: supervised → semi → fully autonomous; single discretionary entry scope (§6.2.2, §20.4.11) | **Resolved** — §6.2.2, §6.4, §20.4.11 |
| 13  | Market news / sentiment source         | **`Market_News.txt` curated India sources**; drives strategy choice via `Trading_Strategies.md` Table SH-4 / scenarios | **Resolved** — §8.8 |
| 14  | ICICI Direct paper path                       | In-house `backend/paper_sim/` (ICICI Direct data-only marks + local ledger); never treat ICICI Direct `paper` as broker sandbox | **Resolved** — §11.7, `Docs/Paper_Simulator.md` |
| 15  | ICICI Direct daily session login | Operator refreshes `ICICI_DIRECT_SESSION_TOKEN` (`API_Session`) via Breeze login URL; bot exchanges via `customerdetails` | **Resolved** — §11.9 |
| 16  | Option chain assembly                  | Build from ICICI Direct instrument master + WS/REST quotes **in-adapter only** (no MCP / `user-nse-india` feed bus) | **Resolved** — §8.9.3 |
| 17  | Product type default for vol strategies | `INTRADAY` vs `CARRYFORWARD` for multi-day gamma/vega books | **Open** — §11.10 |
| 18  | Fill notification path (GCP)           | HTTPS postback vs outbound order-status WS as primary | **Open** — §11.10 |
| 19  | MCP feed registry                      | **None** — ICICI Direct owns marks + live orders; Market_News owns sentiment; retire `mcp_registry` | **Resolved** — §8.8–8.9, §11.2 |




### 20.4 Autonomy Risk Controls

Wrong guardrails can cause the bot to **trade badly at scale** — faster than a human reviewing each recommendation. Autonomy is treated as **graduated privileges** along two axes: `EXECUTION_MODE` (shadow → paper-sim → ICICI Direct live) and `SUPERVISION_MODE` (who authorizes discretionary entries). Hard limits under soft intelligence; pause-first on degradation; adapt second; **promote only after evidence**.

**Implementation modules:** `backend/execution/risk_gate.py`, `backend/execution/circuit_breakers.py`, `backend/execution/auto_pause.py`, `backend/execution/one_trade_scope.py`, `backend/execution/supervision.py`, `backend/learning/config_versioning.py`.

#### 20.4.1 Progressive execution ramp

See §6.2.1 for `EXECUTION_MODE` (`shadow` → `paper` → `live`) and §6.2.2 for `SUPERVISION_MODE` (`supervised` → `semi_autonomous` → `fully_autonomous`). Summary:


| Stage                     | `EXECUTION_MODE` | `SUPERVISION_MODE` (typical) | Autonomy scope |
| ------------------------- | ---------------- | ---------------------------- | -------------- |
| **Shadow**                | `shadow`         | `supervised`                 | Full pipeline; no submits; decisions logged / queued for review |
| **Paper (single module)** | `paper` (paper-sim) | `supervised`              | One strategy module; operator approves each discretionary entry |
| **Paper (multi-module)**  | `paper` (paper-sim) | `supervised` → `semi_autonomous` | Promote after checklist; high-confidence auto-submit optional |
| **Paper soak**            | `paper` (paper-sim) | `semi_autonomous` → `fully_autonomous` | 2–4 weeks (Phase 4 gate) before live |
| **Mature paper → live**   | `paper` → `live` | Keep or re-supervise on live           | Promote to ICICI Direct `place_order` with micro-size + §20.4.10 gates (Phase 5) |


**Two-key confidence for newly enabled modules:** discretionary entries require quant signal **and** LLM approval for the first **50 trades** after `strategy_enabled=true`. New modules start under `supervised` even if the bot is otherwise `semi_autonomous` or `fully_autonomous`.

#### 20.4.2 Portfolio circuit breakers

Authoritative checklist: §11.4.1. These limits apply **in addition to** per-order pre-trade gates (§11.4). No order path may bypass them.

#### 20.4.3 Extended pre-trade gates

Beyond §11.4 defaults:


| Gate                 | Rule                                                                                                   |
| -------------------- | ------------------------------------------------------------------------------------------------------ |
| Regime gate          | No discretionary entries when regime is `unknown` or `high_vol_stress`                                 |
| Integration health   | Broker reject rate > 10% / 1h → block all new orders                                                   |
| Idempotency          | Redis key `order:idempotency:{strategy_id}:{signal_hash}:{tick_id}` prevents duplicate submit on retry |
| Market hours         | Orders outside configured session rejected unless strategy explicitly allows                           |
| New-module probation | First 50 trades after module enable: elevated confidence threshold (+0.05)                             |




#### 20.4.4 Post-trade auto-pause rules

Configured in `configuration.auto_pause_rules`. **Immediate** action — no adaptation/optimization cycle required:


| Signal                                                  | Default action                              |
| ------------------------------------------------------- | ------------------------------------------- |
| Daily loss > 2% equity                                  | `scheduler_mode=paused`; alert              |
| ≥ 5 consecutive losses                                  | Discretionary pause; mechanical hedges only |
| Broker reject rate > 10% / 1h                           | Pause all new orders                        |
| Win rate drops > 15% vs 7-day baseline within 20 trades | `scheduler_mode=reduced_exposure`           |
| P&L vs decision-log expectation diverges > threshold    | Pause module; alert for review              |
| Slippage / fill quality degrades vs conservative model  | Pause module; flag fill model               |
| Decision cycle latency > 2× baseline                    | Discretionary pause; hedges only            |
| Unhandled exception in trading path                     | Immediate pause; Sentry alert               |


**Auto-resume policy:** `configuration.auto_resume` defaults to `false`. After any auto-pause (except intentional operator pause), resuming requires **explicit operator action** via API or frontend — no silent resume.

#### 20.4.5 Extended adaptation guards

Authoritative rules: §12.5 (walk-forward, cooldown, rollback, etc.). Additional autonomy-specific guards:


| Guard                | Rule                                                           |
| -------------------- | -------------------------------------------------------------- |
| Freeze on drawdown   | No adaptation deploy while drawdown > 5%                       |
| Config versioning    | Snapshot before every deploy; one-click rollback API           |
| Module weight cap    | ±15% max weight change per cycle                               |
| No auto-enable       | Optimizer cannot set `strategy_enabled=true`                   |
| Replay-before-deploy | Walk-forward on Parquet replay, not live stream, before deploy |
| Human ack (Phase 4+) | Threshold/weight changes > 10% require operator confirm in UI  |




#### 20.4.6 LLM autonomy controls

Enforce §10.6 without exception in code paths:


| Rule                   | Behavior                                                                                            |
| ---------------------- | --------------------------------------------------------------------------------------------------- |
| Discretionary entry    | LLM reject → **skip**; never overridden by quant-only path                                          |
| Groq unavailable > 60s | Mechanical hedges only; **no** cached LLM output used for new entry gates                           |
| RAG faithfulness       | Discretionary entries blocked if < 0.85; **mandatory for live** even if relaxed on paper during dev |
| Quant vs LLM dissent   | Log every quant-enter / LLM-skip for weekly operator review                                         |
| Order submission path  | LLM **never** in broker submit path — quant + risk gates only                                       |




#### 20.4.7 Operator oversight & safety controls

Operator involvement scales with `SUPERVISION_MODE` (§6.2.2):

| Mode | Operator role |
| ---- | ------------- |
| `supervised` | Per-trade Approve / Reject on pre-approval packets (`Docs/UI_Dashboard.md`, `Trading_Strategies.md` Supervised Execution Runbook) |
| `semi_autonomous` | Async review of auto-submitted high-confidence trades; override / kill-switch; residual queue for low confidence |
| `fully_autonomous` | Monitor-only: dashboards, alerts, kill-switch, post-session review |


| Control            | Mechanism                                                                                                      |
| ------------------ | -------------------------------------------------------------------------------------------------------------- |
| Kill-switch        | Frontend → `POST /api/v1/bot/pause` (immediate)                                                                |
| Scheduler modes    | Active / Learning / Reduced / Paused (§6.2)                                                                    |
| Supervision mode   | `GET`/`PUT /api/v1/bot/supervision` — promote / demote with checklist gates (§6.2.2)                           |
| Decision queue     | `GET /api/v1/decisions/pending`; Approve / Reject endpoints                                                    |
| Decision audit log | `GET /api/v1/decisions` — immutable log of every decision and outcome                                          |
| Config audit trail | `configuration_audit` table: who, when, before/after JSON                                                      |
| Daily summary      | End-of-session alert: trades, P&L, drawdown, pauses, adaptations, pending approvals                            |
| Weekly review      | Operator reviews decision logs + module attribution before promoting supervision or expanding limits           |
| Break-glass resume | After auto-pause, resume requires explicit operator action                                                     |
| Limit expansion    | Raising circuit breaker ceilings requires audit-logged API call                                                |
| Mechanical hedges  | Delta-drift and rule-based hedges on **existing** positions bypass discretionary path (§10.6 fast path)        |




#### 20.4.8 Validation before scaling autonomy


| Test                     | When                                | Gate                                                                     |
| ------------------------ | ----------------------------------- | ------------------------------------------------------------------------ |
| Replay E2E               | Every backend PR / nightly          | Merge block on inconsistent decision log                                 |
| Shadow week              | Before first `EXECUTION_MODE=paper` | Operator sign-off                                                        |
| Conservative paper fills | All validation                      | `paper_optimistic` dev-only (§11.7)                                      |
| Chaos tests              | Phase 4                             | Stale feed, Groq down, broker disconnect → must pause, not trade blindly |
| Paper soak               | Phase 4                             | 2–4 weeks; §2.2 metrics                                                  |


Chaos test scenarios (`backend/tests/chaos/`): feed stale mid-tick, Groq timeout, broker 503, Redis disconnect, duplicate tick replay.

#### 20.4.9 Observability & forensics


| Requirement              | Implementation                                                      |
| ------------------------ | ------------------------------------------------------------------- |
| Immutable decision log   | Append-only `decisions` table with per-gate results                 |
| Config lineage           | `config_snapshot_id` on every decision (§13.3)                      |
| Signal → P&L attribution | §12.7 lineage for incident review                                   |
| Exception → pause        | Unhandled errors in scheduler/execution pause bot                   |
| Operator dashboard       | Trades last hour, reject reasons, active breakers, `EXECUTION_MODE`, `SUPERVISION_MODE`, pending approvals |




#### 20.4.10 Live trading gates (future — `mode=live`)

Live trading is **out of scope** for initial build. If `broker_connections.mode=live` is ever enabled:


| Gate                | Rule                                                                 |
| ------------------- | -------------------------------------------------------------------- |
| `live_enabled` flag | Separate boolean; distinct from paper; default `false`               |
| Position limits     | 50% of paper circuit breaker ceilings                                |
| Operator confirm    | `live_enabled=true` requires authenticated confirm (2FA recommended) |
| No hot adaptation   | No adaptation deploy on live without replay soak pass                |
| Canary              | One symbol, one module for first live week                           |
| RAG gate            | Faithfulness ≥ 0.85 **non-negotiable** on live                       |




#### 20.4.11 One trade at a time (blast-radius control)

Limits session-level exposure if decision logic is wrong — aligned with the previous recommendation model's single-trade scope.


| Rule                  | Behavior                                                                                                                 |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Scope                 | Applies to **discretionary entries** only; mechanical hedges on existing positions are exempt (§10.6)                    |
| Concurrent limit      | At most **one** open discretionary entry per trading session                                                             |
| New signal while busy | Quant/LLM may evaluate, but scheduler **does not open** a second discretionary entry; log as `deferred_one_trade_scope` |
| Close to unlock       | Next discretionary entry allowed only after the current trade is **closed**                                              |
| Circuit breaker       | `configuration.circuit_breakers.max_concurrent_discretionary_entries` defaults to **1** (§11.4.1)                        |
| Frontend              | Dashboard shows active discretionary trade and one-trade lock status                                                     |


**Implementation:** `backend/execution/one_trade_scope.py` — checked in risk gate before broker submit.

#### 20.4.12 Implementation priority


| Priority | Deliverable                                                    | Phase     |
| -------- | -------------------------------------------------------------- | --------- |
| **P0**   | `paper_sim` + ICICI Direct data-only + Railway/Vercel (§21 Phase 0–1) | Phase 0–1 |
| **P0**   | Supervised decision queue + Approve / Reject APIs (§6.2.2)     | Phase 2   |
| **P0**   | `SUPERVISION_MODE` + promotion checklist                       | Phase 2   |
| **P0**   | One-trade-at-a-time gate (§20.4.11)                            | Phase 2   |
| **P0**   | `EXECUTION_MODE` shadow → paper ramp; §11.4.1 circuit breakers | Phase 0–2 |
| **P0**   | `auto_pause_rules` + `auto_resume=false` default               | Phase 2   |
| **P0**   | Config versioning + rollback API                               | Phase 3   |
| **P1**   | Semi-autonomous high-confidence auto-submit                    | Phase 3   |
| **P1**   | Fully autonomous ranked fallback (§6.4)                        | Phase 4   |
| **P1**   | Order idempotency keys; symbol whitelist                       | Phase 2   |
| **P1**   | Freeze adaptation on drawdown; replay-before-deploy            | Phase 3   |
| **P1**   | Daily summary alerts; config audit trail                       | Phase 2–3 |
| **P2**   | Human ack for large config changes; live gates                 | Phase 5   |
| **P2**   | RAG chat + golden eval (Track B)                               | Parallel  |


---



## 21. Phased Implementation Roadmap

> **Authoritative build order:** paper trading first → graduated autonomy on `paper_sim` → ICICI Direct live last.  
> ICICI Direct phases **A0–A6** are defined in §11.15. Paper API/behavior: `Docs/Paper_Simulator.md`. Context: `Docs/context.md` §2.3.1.

### 21.0 Master Sequence (Two Axes)

Implement along two independent axes. **Never** enable ICICI Direct `place_order` until the paper axis has earned autonomy evidence.

```mermaid
flowchart TB
  subgraph axisE["EXECUTION_MODE"]
    E0[shadow] --> E1[paper via paper_sim]
    E1 --> E2[live ICICI Direct place_order]
  end
  subgraph axisS["SUPERVISION_MODE — only after EXECUTION_MODE=paper"]
    S0[supervised] --> S1[semi_autonomous]
    S1 --> S2[fully_autonomous]
  end
  E1 -.-> S0
  S2 -.-> E2
```

| Order | Stage | `EXECUTION_MODE` | `SUPERVISION_MODE` | Deploy | ICICI Direct |
| ----- | ----- | ---------------- | ------------------ | ------ | --------- |
| **0** | Scaffold + data-only marks | `shadow` | n/a | Local → Railway/Vercel | Session + LTP / instrument master **only** |
| **1** | Paper rehearsal (manual + automation API) | `paper` | n/a (manual / paper-sim loop) | Railway + Vercel | Data-only → `paper_sim` ledger |
| **2** | Supervised paper bot | `paper` | `supervised` | Railway + Vercel | No `place_order` |
| **3** | Semi-autonomous paper | `paper` | `semi_autonomous` | Railway + Vercel | No `place_order` |
| **4** | Fully autonomous paper soak | `paper` | `fully_autonomous` | Railway + Vercel | No `place_order` |
| **5** | Live micro-size (optional) | `live` | keep prior or re-supervise | **GCP** `asia-south1` | Static IP + `place_order` |

**Promotion gates (summary — detail §6.2.1–6.2.2):**

| From → To | Gate |
| --------- | ---- |
| Shadow → Paper | ≥ 1 week shadow; zero pipeline errors |
| Paper single-module → multi-module | ≥ 30 closed trades / module; risk gates green |
| `supervised` → `semi_autonomous` | ≥ 30 closed supervised paper trades; §2.2 bands; checklist |
| `semi_autonomous` → `fully_autonomous` | ≥ 30 closed semi trades; low override; soak without critical auto-pause |
| Paper soak → `live` | 2–4 week soak meets §2.2; chaos tests; GCP + micro-size + §20.4.10 |

### 21.1 Critical Path — Paper First (Track A)

Prove fills, marks, playbook, and risk **before** autonomy or live capital:

```mermaid
flowchart LR
    P0[Phase 0: Scaffold + ICICI Direct data] --> P1[Phase 1: paper_sim playbook]
    P1 --> P2[Phase 2: Supervised paper bot]
    P2 --> P3[Phase 3: Semi-auto on paper]
    P3 --> P4[Phase 4: Full-auto soak]
    P4 --> P5[Phase 5: Live ICICI Direct GCP]
```

| Phase | Deliverable | Validates |
| ----- | ----------- | --------- |
| **0** | FastAPI scaffold, Postgres/Redis, ICICI Direct session + LTP, Railway/Vercel wire-up | Deploy + marks without orders |
| **1** | `paper_sim` ledger, SH-4 + news + GARCH/IV z + γ–θ, OSS/BSM minimal | Paper P&L path end-to-end |
| **2** | Decision queue, risk gates, one-trade, kill-switch, `SUPERVISION_MODE=supervised` | Operator-in-the-loop paper bot |
| **3** | High-confidence auto-submit + learning/hardening on paper | Semi-autonomy earned |
| **4** | Ranked fallback + 2–4 week soak vs §2.2 | Full autonomy on paper only |
| **5** | GCP inventory + static egress + micro-size `place_order` | Live after paper evidence |

### 21.2 Parallel Track B — RAG / Chat (Non-Blocking)

RAG powers explanations and LLM validation. It **must not delay** Phase 0–1 paper rehearsal. Start after scaffold exists; **complete before** Groq gates discretionary entries in Phase 2+.

| Step | Deliverable | When |
| ---- | ----------- | ---- |
| **B1** | One PDF → ChromaDB → `POST /api/v1/chat` → `/chat` UI + golden eval CI | Parallel with Phase 0–1 |
| **B2** | Remaining three PDFs + faithfulness ≥ 0.85 | Before LLM-gated trading |
| **B3** | Ask AI from decision cards | Phase 2 cockpit |

### Phase 0: Paper Scaffold & ICICI Direct Data-Only (Weeks 1–2)

- [ ] Native local toolchain (`Docs/LOCAL_DEV.md`); no Compose / Docker Desktop
- [ ] `backend/` scaffold: FastAPI, `GET /health`, `backend/.env.example`
- [ ] ICICI Direct **session manager** + connection test API (**A0** — §11.15) — secrets server-side only
- [ ] Instrument master cache + LTP REST → normalized ticks (**A1** — §11.15)
- [ ] `GET /api/v1/paper-sim/health` stub; `EXECUTION_MODE=shadow` default
- [ ] **Paper host:** Railway Nixpacks (`backend/`) + Vercel (`frontend/`) linked (§17.0); `CORS_ORIGINS` + `NEXT_PUBLIC_*`
- [ ] Frontend shell: bot status, health, kill-switch placeholder (`Docs/UI_Dashboard.md`)
- [ ] GCP live inventory **deferred** until Phase 5 (`infra/cloud-inventory.yaml`, §17.8)

**Exit:** ICICI Direct marks refresh on Railway; no Breeze API `place_order`; frontend talks to Railway API.

### Phase 1: Paper Simulator Playbook (Weeks 3–5)

Authoritative API/behavior: `Docs/Paper_Simulator.md`. ICICI Direct phases **A0–A2** (data) + **A3** shadow dry-run payloads (mandatory; no live `place_order`).

- [ ] `backend/paper_sim/`: account, positions, fills, multi-leg `POST /orders`, close, marks refresh
- [ ] Conservative slippage default; capital caps (₹10L / ₹1L / leg) per playbook
- [ ] Option chain from scrip master + ICICI Direct LTP
- [ ] **Market_News** pipeline (§8.8) → `GET /news`; SH-4 strategy selection (`Trading_Strategies.md`)
- [ ] GARCH / IV z-score signals + `POST /signals/evaluate`
- [ ] Continuous γ–θ re-hedge automation (`/automation/start|stop|status`)
- [ ] **Post-entry multi-leg auto-complete** without consent; same open-trade gates (§11.7)
- [ ] BSM pricing + Greeks minimal + OSS parity smoke tests (§8.5.12)
- [ ] Transaction cost model (§9.4); pre-trade risk gate thresholds (§11.4)
- [ ] Volatility module (HV, IV) enough for cheap-vol / vega frames; gamma re-hedge path
- [x] `EXECUTION_MODE=paper` on Railway — **never** `live` on this stack
- [ ] ICICI Direct WS Streaming 2.0 freshness (**A2**) for sub-second marks (mandatory Phase 1.8)
- [ ] ICICI Direct **A3** shadow dry-run: place/cancel/status payloads logged via `IciciDirectBrokerAdapter` + `/broker/shadow-order*` (mandatory Phase 1.9)

**Exit:** Manual + automated paper trades produce local P&L; playbook + news gates honored; intended multi-leg structures may auto-complete after entry without consent under the same open-trade rules; A3 shadow payloads logged; zero `place_order`.

### Phase 2: Supervised Paper Bot (Weeks 6–9)

- [ ] Bot scheduler + `EXECUTION_MODE=shadow` dry week, then `paper` single-module (§6.2.1)
- [ ] `SUPERVISION_MODE=supervised`: pre-approval packets + Approve / Reject APIs (§6.2.2)
- [ ] Frontend supervised cockpit (decision queue, Zone A/B/C — `Docs/UI_Dashboard.md`)
- [ ] One-trade-at-a-time gate (`one_trade_scope.py`) (§20.4.11)
- [ ] Portfolio circuit breakers + `auto_pause_rules` + `auto_resume=false` (§11.4.1, §20.4.4)
- [ ] Order idempotency keys + symbol whitelist (§20.4.3)
- [ ] AI decision engine: rule fast path + Groq validator (requires Track B golden eval green)
- [ ] Gamma + vega modules wired into paper-sim (discretionary still supervised)
- [ ] Stat arb module (optional second module after ≥ 30 closed trades on first)
- [ ] Live-path multi-leg order builder polish; ICICI Direct sequential multi-leg (**A4**) only as dry-run until Phase 5 (paper multi-leg auto-complete already in Phase 1)
- [ ] WebSocket events (`decisions.pending`, trades, alerts); config audit trail
- [ ] Frontend bot monitor + kill-switch + role-based auth (§16.3)

**Exit:** Operator approves paper **entries**; mechanical hedges **and** Phase 1 multi-leg opening completion auto; promotion checklist for semi-auto ready.

### Phase 3: Semi-Autonomy on Paper (Weeks 10–12)

- [ ] Promote to `semi_autonomous` after supervised checklist (§6.2.2) — still `EXECUTION_MODE=paper`
- [ ] High-confidence auto-submit (`semi_auto_confidence_min`, default 0.85); residual queue
- [ ] Continuous learning engine + walk-forward validation (§12.5)
- [ ] Module reweighting + rule-based regime classifier; failure memory (§12.6–12.7)
- [ ] Config versioning + `POST /api/v1/learning/rollback` (§20.4.5)
- [ ] Chaos tests: stale feed, Groq down, Redis loss (§20.4.8)
- [ ] Paper multi-module enablement after ≥ 30 closed trades / module

**Exit:** Semi-auto paper metrics within §2.2 bands; override rate acceptable; demotion path proven.

### Phase 4: Full Autonomy Paper Soak (Weeks 13–16)

- [ ] Promote to `fully_autonomous` after semi checklist (§6.2.2)
- [ ] Recommendations ranked fallback auto-execute #1 → #2 → #3 (§6.4) — **paper-sim only**
- [ ] 2–4 week paper soak on Railway + Vercel vs §2.2 success criteria
- [ ] Full analytics dashboards; Chroma backup if Track B active
- [ ] `PROCESS_ROLE` + split health endpoints ready for GCP (§6.1.4) — deploy still paper
- [ ] Live readiness review doc drafted (§20.4.10) — **no** live submit yet

**Exit:** Soak passes at least one §2.2 metric set; chaos green; operator signs Phase 5 gate.

### Phase 5: Live ICICI Direct (Post–Paper Evidence — Optional)

Maps to ICICI Direct phases **A4–A6** (§11.15) + GCP §17.8. Do **not** flip the paper ledger.

- [ ] Provision GCP `asia-south1` (`infra/cloud-inventory.yaml`); Cloud NAT **static egress**
- [ ] API + worker Cloud Run split; migrate secrets to Secret Manager
- [ ] `IciciDirectBrokerAdapter` live place/cancel/status; sequential multi-leg + rollback (**A4–A5**)
- [ ] Order-status WS / postback; production rate limiter
- [ ] Re-confirm supervision mode (often re-start `supervised` on live, then re-promote)
- [ ] Micro-size + §20.4.10 gates; `EXECUTION_MODE=live` only on GCP
- [ ] Drop simulated / stub NSE quote paths; ICICI Direct sole live marks + orders (**A6**)
- [ ] External uptime monitor on `/health/bot` + market-hours deploy pause (§17.5, §17.7)

---



## 22. Testing & CI Strategy



### 22.1 Test Pyramid


| Layer              | Scope                                                   | Location                                 | Runs On                                             |
| ------------------ | ------------------------------------------------------- | ---------------------------------------- | --------------------------------------------------- |
| **Unit**           | BSM pricing, Greeks, z-score, chunking, cost model      | `backend/tests/unit/`                    | Every push                                          |
| **Integration**    | Chroma retrieve, Groq mock, feed parser, paper-sim fills | `backend/tests/integration/`             | Every push                                          |
| **RAG regression** | Golden queries → expected `chunk_id`s + faithfulness    | `backend/tests/knowledge/`               | Every push; **blocks merge** if faithfulness < 0.85 |
| **OSS parity**     | Pricing/Greeks vs OSS fixtures                          | `backend/tests/quant/test_oss_parity.py` | Every push                                          |
| **Replay E2E**     | Parquet replay day → decision log (no live broker)      | `backend/tests/e2e/`                     | Nightly                                             |
| **Shadow run**     | Full decision path; zero broker submits                 | Staging                                  | ≥ 1 week before `EXECUTION_MODE=paper`              |
| **Chaos**          | Feed stale, Groq down, broker 503, Redis loss           | `backend/tests/chaos/`                   | Phase 3–4 gate                                      |
| **Paper soak**     | 2–4 weeks supervised → semi → full-auto paper run       | Railway + Vercel                         | Phase 4 gate                                        |




### 22.2 CI Pipeline (GitHub Actions)

```
Push / PR
    │
    ├── frontend/ changed → lint + build (Next.js)
    │
    └── backend/ changed
              ├── ruff / mypy lint
              ├── pytest unit + integration
              ├── OSS parity tests
              ├── RAG golden eval (faithfulness ≥ 0.85)
              ├── (optional) Nixpacks / Buildpacks smoke on CI runners
              └── (nightly) replay E2E
```



### 22.3 Required Fixtures


| Fixture             | Path                                           | Purpose                     |
| ------------------- | ---------------------------------------------- | --------------------------- |
| OSS reference JSON  | `backend/tests/fixtures/oss/`                  | BSM parity                  |
| Golden Q&A          | `backend/knowledge/evaluation/golden_qa.jsonl` | RAG regression              |
| Chunk golden files  | `backend/tests/fixtures/chunks/`               | Equation/table preservation |
| Replay Parquet      | `backend/tests/fixtures/replay/`               | Deterministic E2E           |
| Market data samples | `backend/tests/fixtures/feeds/`                | Feed adapter tests          |




### 22.4 Definition of Done (Phase Gates)


| Phase  | Gate                                                                                  |
| ------ | ------------------------------------------------------------------------------------- |
| **1a** | Chat returns cited answers; RAG faithfulness ≥ 0.85 on golden set                     |
| **1b** | OSS parity tests pass; both knowledge docs ingested                                   |
| **2**  | Replay E2E produces decision log; ICICI Direct shadow order mapping + paper-sim round-trip |
| **3**  | Bot runs one full market day in `supervised` with Approve/Reject; kill-switch works |
| **4**  | 2–4 week soak meets ≥ 1 of 4 success metrics (§2.2); `semi_autonomous` checklist passable |
| **5**  | Optional: `fully_autonomous` ranked fallback (§6.4) after promotion checklist |


---



## Appendix A: Glossary


| Term                        | Definition                                                                                    |
| --------------------------- | --------------------------------------------------------------------------------------------- |
| **RAG**                     | Retrieval-Augmented Generation — LLM answers grounded in retrieved documents                  |
| **BM25**                    | Keyword-based ranking for lexical search                                                      |
| **Greeks**                  | Option sensitivities: Delta (Δ), Gamma (Γ), Vega (ν), Theta (Θ)                               |
| **HV / IV / RV**            | Historical, Implied, and Realized Volatility                                                  |
| **Cointegration**           | Linear combination of non-stationary series that is stationary                                |
| **Z-score**                 | Standardized spread deviation for entry/exit signals                                          |
| **Broker Adapter**          | Translates internal orders to broker API calls                                                |
| **Kill Switch**             | Frontend control that immediately pauses trading                                          |
| **Adaptation Cycle**        | Metric breach → optimization → backtest → config deploy                                       |
| **Failure Memory**          | ChromaDB `failure_memory` collection of losing trade contexts for avoidance                   |
| **ChromaDB**                | Embedded or HTTP-server vector database for RAG knowledge, failure memory, and trade insights |
| **Walk-Forward Validation** | Out-of-sample backtest: train on window N, validate on window M, roll forward                 |
| **Replay Mode**             | Deterministic bot run using recorded Parquet market snapshots (§8.7)                          |
| **Paper Conservative Fill** | Slippage + spread penalty applied to paper fills for realistic P&L (§11.7)                    |
| **Golden Eval Set**         | Curated Q&A pairs with expected citations; CI gate for RAG quality (§7, §22)                  |
| **EXECUTION_MODE**          | `shadow` \| `paper` (paper-sim) \| `live` — submit path (§6.2.1; `Docs/Paper_Simulator.md`)                    |
| **SUPERVISION_MODE**        | `supervised` \| `semi_autonomous` \| `fully_autonomous` — who authorizes discretionary entries (§6.2.2) |
| **Pre-Approval Packet**     | Structured decision card for operator Approve / Reject (`Trading_Strategies.md`, `UI_Dashboard.md`) |
| **Circuit Breaker**         | Portfolio-level hard limit that no single order may override (§11.4.1)                        |
| **Auto-Pause**              | Immediate bot pause on post-trade anomaly; default `auto_resume=false` (§20.4.4)              |
| **Graduated Supervision**   | Promote supervised → semi → fully autonomous only after paper evidence (§6.2.2)               |
| **One Trade at a Time**     | At most one pending or open discretionary entry per session (§20.4.11)                        |
| **Breeze API**                | ICICI Direct broker API (REST + WS Streaming 2.0) — sole execution/marks vendor (§8.9, §11)     |
| **symboltoken**             | ICICI Direct exchange token for order + WS subscribe; resolved via instrument master (§11.8)   |
| **A0–A6**                   | ICICI Direct implementation phases nested under §21 (§11.15)                                   |


---



## Appendix B: Document Cross-Reference


| Topic                                                | Primary Source                                                                      |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Autonomous bot vision & success criteria             | `context.md` §1, §2.5, §10                                                          |
| Graduated supervision path                           | Architecture §6.2.2, `Docs/UI_Dashboard.md`, `Docs/Trading_Strategies.md`            |
| Frontend/backend separation                          | `context.md` §5.2                                                                   |
| RAG pipeline stages 1–14 + user chatbot              | Four PDFs (§3.2), `Docs/Strategy_Ingestion_Pipeline.txt`, Architecture §7 / §7.7                   |
| Trading playbook & parameter catalog (ops refs)      | `Docs/Trading_Strategies.md`, `Docs/Trading_Parameters.md`                                         |
| Trading metadata taxonomy                            | `Docs/Strategy_Ingestion_Pipeline.txt` §Stage 6                                     |
| Quant module requirements                            | `context.md` §3, `Docs/Problem_Statement.txt` §3                                    |
| Continuous learning                                  | `context.md` §3.9, §5.6                                                             |
| Technology recommendations                           | `Docs/Strategy_Ingestion_Pipeline.txt` §Recommended Stack                           |
| LLM provider (Groq)                                  | Architecture §10.1                                                                  |
| Deployment (paper Railway + Vercel; live GCP) | Architecture §5.4, §17.0, §17.8, `Docs/Paper_Simulator.md`                    |
| Cloud infrastructure & virtual compute (live) | Architecture §17.8, `infra/cloud-inventory.yaml`, `infra/provision/PROVISIONING.md` |
| Process roles & uptime topology                      | Architecture §6.1.4, §17.7                                                          |
| Trade input & option strategy model (OSS)            | `Docs/OSS (1).xlsm`, `Docs/OSS_Guide (1).pdf`, Architecture §8.5                    |
| ICICI Direct integrations (live feeds + broker + paper-sim) | Architecture §8.6, §8.9, §11 (esp. §11.8–11.15); `Docs/Paper_Simulator.md` |
| Market sentiment & news (India)                      | `Market_News.txt`, Architecture §8.8; strategy mapping via `Docs/Trading_Strategies.md` (Table SH-4); paper rehearsal via `Docs/Paper_Simulator.md` |
| Implementation build plan                            | `Docs/implementation_plan.md` (aligned with Architecture §21)              |
| Testing & CI gates                                   | Architecture §22                                                                    |
| Resolved architectural decisions                     | Architecture §20.3                                                                  |
| Autonomy risk controls                               | Architecture §20.4                                                                  |
| Architecture evolution (previous vs. current)        | Architecture Appendix D                                                             |




### Appendix C: Document Alignment Notes


| Document                     | Relationship                                                                                                                                       |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `architecture.md`            | **Authoritative** technical reference for implementation — includes ICICI Direct Breeze API (§8.9, §11); **no MCP registry** |
| `Docs/implementation_plan.md` | Build sequence aligned with §21; ICICI Direct marks/orders + Market_News sentiment |
| `context.md`                 | Consolidated project context; must stay aligned with architecture (e.g. ChromaDB, ICICI Direct sole broker)                                            |
| Four RAG PDFs (§3.2)         | **Authoritative RAG corpus** for chatbot + AI decision grounding                                   |
| `Docs/Trading_Strategies.md` | Consolidated strategy playbook (ops/UI); supervised-first execution assumptions; **strategy selection authority** with §8.8 sentiment |
| `Docs/Paper_Simulator.md`    | In-house paper path: ICICI Direct marks + local ledger; **Railway + Vercel** hosting (§17.0); **acts per Trading_Strategies.md** with **Market_News.txt** sentiment overlay |
| `Market_News.txt`            | India news source list + daily workflow; **sentiment input** — Architecture §8.8; consumed by paper-sim and recommendations |
| `Docs/Trading_Parameters.md` | Execution-ready parameter catalog for OSS keys, thresholds, limits (ops config — not RAG corpus); Part U news keys |
| `Docs/UI_Dashboard.md`       | Supervised cockpit UI spec; mode-specific frontend behavior                                       |
| `Docs/Problem_Statement.txt` | Original academic scope; assistant/recommendation model — **superseded** by graduated bot stance (§1.2); see **Appendix D** |
| `Docs/ICICI_Direct_Architecture.md` | **Superseded** — content merged into this document (§8.9, §11.8–11.15); keep only as redirect stub |
| `DECISIONS.md`               | Recommended living log of dated architectural decisions (create at Phase 1a)                                                                       |




### Appendix D: Architecture Evolution (Previous vs. Current)

This appendix records how the current architecture (v1.27) evolved from the original academic scope in `Docs/Problem_Statement.txt` and early stack notes in `Docs/Strategy_Ingestion_Pipeline.txt`. The original documents remain valuable for domain requirements and RAG pipeline stages; the **operating model and engineering spec** are superseded by this document and `context.md`.

**v1.27 change:** Feed-bound recommendation universe (G11–G12) loads **all NSE F&O underlyings** from ICICI Direct `FONSEScripMaster.txt` (SecurityMaster.zip); G12 bindings auto-map to ICICI Direct NSE quotes + NFO option chain. Instrument master zip parser uses file→exchange mapping (NSE + NFO only).

**v1.26 change:** **No MCP registry.** Market data (quotes, chains, historical) and live order placement use **ICICI Direct Breeze API** only. India sentiment stays on the **`Market_News.txt` pipeline** (§8.8). Retire assignable MCP ids (`user-broker-feed`, `user-nse-india`, `user-market-news`) and `backend/services/mcp_registry.py`. Recommendation `feed_sources` report ICICI Direct + news health directly (§8.9.3, §20.3 #19).

**v1.25 change:** Underlying price cap ≤ **INR 1000** applies **only** when the bot trades **options and its underlying**; **options-only** has no underlying price cap (§2.3). Index / cash-equity gates (T11a/T11b) scoped to options+underlying mode. Parameters catalog v1.5 (`max_underlying_price_applies_when`).

**v1.24 change:** Tradeable universe locked to **cash-equity underlyings with spot ≤ INR 1000** to minimize stock-hedge capital (§2.3). Index underlyings (NIFTY, BANKNIFTY, …) are excluded — no exemption. Examples and feed bindings use equities (e.g. SBIN). Parameters catalog v1.4 (`exclude_index_underlyings`, `require_cash_equity_underlying`).

**v1.23 change:** India NFO sizing uses each symbol’s real ICICI Direct instrument-master `lotsize` (`nfo_lot_sizing` in `trading_parameters.defaults.json` v1.3) — do not copy OSS workbook `default_contract_multiplier=100` (§8.5.2–8.5.3, §11.10). Also: OSS Iron Condor reference valuation corrected to **`2024-01-04T10:35:00+05:30` (IST)** — matches `Docs/OSS (1).xlsm` C3/C4 and `Trading_Parameters.md`; naive clocks for NSE/NFO interpreted in `Asia/Kolkata`.

**v1.22 change:** **ICICI Direct Breeze API** vendor adapter fully inlined from former `Docs/ICICI_Direct_Architecture.md` into §8.9 and §11.8–11.15. `architecture.md` is now the **single build reference** for the entire project (paper + live).

**v1.21 change:** **Paper trading** hosted on **Railway** (backend) + **Vercel** (frontend) — §17.0, `Docs/Paper_Simulator.md`. **Live** remains **GCP** Cloud Run / Cloud SQL / Memorystore in `asia-south1` (§17.8).

**v1.19 change:** RAG corpus restored to the **four domain PDFs** (`Volatility Trading.pdf`, `Gamma Scalping.pdf`, `Vega Scalping.pdf`, `Trading_Strategies.pdf`). **User chatbot** specified as a permanent final-UI component (§7.7). Markdown playbook/parameter docs remain operational references, not the primary RAG corpus.

**v1.18 change:** Operating model is **supervised → semi-autonomous → fully autonomous** (`SUPERVISION_MODE`). Phase 3 default is `supervised`; ranked fallback auto-execute (§6.4) is the `fully_autonomous` end state. Aligns with `Trading_Strategies.md` and `UI_Dashboard.md`.

**v1.17 change:** Temporarily used `Trading_Strategies.md` / `Trading_Parameters.md` as RAG sources (superseded by v1.19 PDF corpus).

**v1.13 change:** Deployment target migrated from Railway + Vercel to **Google Cloud Platform** (Cloud Run, Cloud SQL, Memorystore, Secret Manager, Cloud Build) for the live inventory. **v1.21** restores Railway + Vercel specifically for the **paper** phase while keeping GCP for live.

#### Summary verdict


| Dimension            | Previous (`Problem_Statement.txt`)                             | Current (`architecture.md`)                                                    |
| -------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| **Primary goal**     | AI-assisted framework; trader education + recommendations      | Continuously learning volatility **bot** with graduated supervision            |
| **Execution model**  | Entry/exit/hedge **recommendations**; manual or semi-automated | Broker pipeline with **supervised → semi → autonomous** path (§6.2.2)          |
| **Human role**       | Trader reads recommendations and acts                          | Operator **approves** in Phase 3; promotes to monitor-only after evidence      |
| **Learning loop**    | Mentioned at end of methodology flow; lightly specified        | First-class §12: triggers, guards, walk-forward, failure memory                |
| **Spec maturity**    | Conceptual / academic                                          | Engineering-grade: modules, APIs, deploy, CI, uptime path                      |
| **Build complexity** | Lower (RAG + analytics + UI)                                   | Higher (integrations, scheduler, adaptation, ops)                              |


**Current architecture is significantly stronger** for building a real trading bot with engineering-grade controls. **Previous architecture was appropriate** for a decision-support or thesis prototype. Implementation has not started (§1.3) — this comparison is **design quality only**. On **one-trade-at-a-time blast-radius control**, the current design retains equivalent safeguards via §20.4.11 (see **Dimension-by-dimension** and **Scorecard** below).

#### Dimension-by-dimension comparison


| Dimension                                                | Previous                                                  | Current                                                         | Winner                                                     |
| -------------------------------------------------------- | --------------------------------------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------- |
| **Goal clarity**                                         | AI-assisted framework; trader education + recommendations | Graduated bot: supervised first, autonomy earned                | **Current** — sharper product definition                   |
| **Execution model**                                      | Recommendations; manual/semi-automated                    | Supervision modes + broker adapter (§6.2.2, §11.1)              | **Current** (for bot vision)                               |
| **Spec maturity**                                        | Conceptual / academic                                     | Engineering-grade: modules, APIs, deploy, CI                    | **Current**                                                |
| **Learning loop**                                        | Lightly specified at end of flow                          | First-class §12: triggers, guards, walk-forward                 | **Current**                                                |
| **Integrations**                                         | Implicit / underspecified                                 | Broker adapters, URL feed registry, OSS multi-leg model         | **Current**                                                |
| **Ops & deploy**                                         | Streamlit-or-Next, Qdrant-or-Chroma                       | **Paper: Railway + Vercel**; **Live: GCP** Cloud Run + Cloud SQL | **Current**                                                |
| **Validation discipline**                                | Backtesting mentioned                                     | Golden RAG eval CI, vertical slice, replay-before-deploy        | **Current**                                                |
| **Build complexity**                                     | Lower (~RAG + analytics + UI)                             | Higher (~16 weeks, many failure modes)                          | **Previous**                                               |
| **Time to first demo**                                   | Faster                                                    | Slower until Phase 1a slice lands                               | **Previous**                                               |
| **Blast radius if logic is wrong (one trade at a time)** | ★★★★☆ (4/5) — one trade at a time                         | ★★★★☆ (4/5) — one discretionary entry per session (§20.4.11)    | **Tie**                                                    |




#### Philosophical shift

The original problem statement defined the AI as an *"intelligent quantitative trading assistant rather than an autonomous trader"* and scoped execution to *"entry recommendations, exit recommendations, hedge recommendations rather than fully automated order execution."*

Current stance (§1.2):


| Principle                              | Implication                                                               |
| -------------------------------------- | ------------------------------------------------------------------------- |
| **Supervised → semi → autonomous**     | Start with operator approval; promote only after paper evidence (§6.2.2) |
| **One trade at a time**                | Limits blast radius if logic is wrong (§20.4.11)                          |
| **Continuous learning as first-class** | Every trade feeds the adaptation loop (§12)                               |
| **Quant leads, LLM validates**         | Rules for mechanical hedges; Groq gates discretionary entries             |
| **Paper trading first**                | Full lifecycle on in-house `paper_sim` before any ICICI Direct live mode |


Research question #4 shifted from *"Can AI-assisted decision support improve understanding?"* to *"Can graduated AI decision-making and continuous learning improve success ratio over static strategies?"* (`context.md` §4).

#### What was preserved


| Domain capability (previous)                  | Current treatment                                                         |
| --------------------------------------------- | ------------------------------------------------------------------------- |
| Four domain PDFs → RAG knowledge base + user chatbot | 14-stage PDF pipeline (§7) + `/chat` UI (§7.7) + golden eval CI gate      |
| Stat arb, vol, gamma, vega modules            | Same modules; integrated into bot scheduler (§9)                          |
| Greeks and risk management                    | Pre-trade risk gates with concrete thresholds (§11.4)                     |
| Retail constraints (costs, liquidity, margin) | Transaction cost model, conservative paper fills (§9.4, §11.7)            |
| Explainability                                | Decision logs, RAG citations, frontend chat — retained alongside autonomy |
| Human judgment on discretionary entries       | Restored as Phase 3 default via `SUPERVISION_MODE=supervised`             |




#### What was added (major upgrades)


| Addition                                   | Section                | Why it matters                                           |
| ------------------------------------------ | ---------------------- | -------------------------------------------------------- |
| Bot scheduler + market-hours loop          | §6.2, §6.3             | Turns analytics into an always-on agent                  |
| Broker + feed adapter layers               | §8.6, §11.6            | Closes observe → execute gap                             |
| URL-based live feed registry               | §8.2, §8.7             | Decouples data from hard-coded vendors                   |
| OSS multi-leg trade input model            | §8.5                   | Matches how vol strategies are actually expressed        |
| Frontend/backend separation                | §5                     | Security, testability, deploy independence               |
| Adaptation safety guards                   | §12.5                  | Prevents reckless self-modification                      |
| Failure memory + attribution               | §12.6, §12.7           | Enables evidence-based reweighting                       |
| Testing pyramid + CI gates                 | §22                    | Validates before production trust                        |
| Deployment + cloud inventory               | §17.0 (paper), §17.8 (live) | Runnable infrastructure spec                     |
| Process split for uptime                   | §6.1.4, §17.7          | API/worker separation for 99% target                     |
| Phased roadmap (vertical slice first)      | §21.1                  | Reduces big-bang delivery risk                           |
| Autonomy risk controls                     | §20.4, §6.2.1, §11.4.1 | Graduated execution, circuit breakers, auto-pause        |
| Graduated supervision + one trade at a time | §6.2.2, §6.4, §20.4.11 | Supervised first; autonomy earned; single-entry scope |




#### Stack evolution


| Layer          | Previous (pipeline doc)  | Current (resolved)                                |
| -------------- | ------------------------ | ------------------------------------------------- |
| LLM            | GPT-5.5 (generic API)    | **Groq** — `llama-3.3-70b-versatile`              |
| Vector DB      | Qdrant or Chroma (local) | **ChromaDB** (embedded dev / HTTP prod)           |
| Embeddings     | bge-m3 or OpenAI         | **bge-m3** + **bge-reranker-large**               |
| Orchestration  | LangChain or LlamaIndex  | Direct clients; LangChain optional                |
| Frontend       | Streamlit or Next.js     | **Next.js** — Vercel (paper) / Cloud Run (live)   |
| Backend deploy | Railway (mentioned)      | **Railway** (paper) · **GCP Cloud Run** (live, `infra/cloud-inventory.yaml`) |




#### Architecture flow comparison

```
PREVIOUS (Problem_Statement.txt §7)          CURRENT (§4.3, §6.2.2, §12.1)
─────────────────────────────────          ────────────────────────────────
Knowledge docs → RAG → Quant modules           Knowledge docs → RAG (CI-gated) → Quant modules
       ↓                                            ↓
Trade Recommendation Engine                  Decision engine + risk gates + SUPERVISION_MODE
       ↓                                            ↓
Human executes                               supervised: Approve → broker
                                             semi: high-confidence auto-submit
                                             fully autonomous: ranked fallback (§6.4)
                                             (one trade at a time §20.4.11)
       ↓                                            ↓
Performance analytics                        Analytics → Learn → Adapt → deploy
       ↓                                            ↓
(vague "Continuous Learning")                Walk-forward + guards + failure memory
```



#### Trade-offs accepted


| Trade-off                                         | Rationale                                                                                         |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| **Higher build scope** (~16 weeks estimated, §21) | Required to deliver a real trading bot, not only a copilot                                        |
| **More integration failure modes**                | Feeds, broker, Groq, Chroma, Redis, Postgres — mitigated by health checks (§13.4) and kill-switch |
| **Autonomy risk**                                 | Wrong guardrails → bad trades at scale — mitigated by supervised-first promotion path             |
| **Longer path to first demo**                     | Vertical slice (Phase 1a) restores fast feedback without abandoning full vision                   |




#### Scorecard (autonomy & blast radius)

This scorecard compares **execution autonomy** and **one-trade-at-a-time blast-radius control** between the previous recommendation model and the current bot architecture.


| Dimension                                                | Previous (`Problem_Statement.txt`)                               | Current (`architecture.md`)                                                          | Preference                                                                             |
| -------------------------------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| **Discretionary execution**                              | ★★★★★ (5/5) — trader reads recommendations and executes manually | ★★★★★ (5/5) — supervised first; promote to auto-submit after evidence (§6.2.2)       | **Evolved** — Previous: human-in-loop only; Current: graduated path to autonomy        |
| **Blast radius if logic is wrong (one trade at a time)** | ★★★★☆ (4/5) — one trade at a time                                | ★★★★☆ (4/5) — one discretionary entry per session (§20.4.11)                         | **Tie** — single-trade scope limits cascade errors and session-level exposure          |


**Verdict:** The current architecture builds a **broker-connected trading bot** that **starts supervised** and promotes to semi-autonomous then fully autonomous only after paper evidence, while retaining **one-trade-at-a-time** blast-radius control and graduated `EXECUTION_MODE` ramp (§6.2.1–6.2.2).

See also the broader evolution summary above and **§20.4 Autonomy Risk Controls** for the full mitigation stack.

#### When to reference the previous scope


| Use `Problem_Statement.txt` for…            | Use `architecture.md` for…                      |
| ------------------------------------------- | ----------------------------------------------- |
| Module requirements (stat arb, gamma, vega) | Integration, execution, and deployment design   |
| Original research questions                 | Updated research questions (`context.md` §4)    |
| Academic deliverable framing                | Implementation, CI, and ops                     |
| RAG as knowledge engine (concept)           | RAG pipeline stages, eval gates, failure memory |


---

*This architecture document is the authoritative technical reference for design, implementation, and review of the Volatility Trading Bot (supervised → semi → autonomous).*