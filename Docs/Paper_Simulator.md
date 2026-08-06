# In-House Options Paper Simulator

> **Indian markets only.** Paper rehearsal uses ICICI Direct marks; live progression uses ICICI Direct Breeze API. No US / third-party paper brokers.  
> Parent: `Docs/architecture.md` §11.7 (paper path), §8.9 (ICICI Direct marks)  
> Strategy authority: `Docs/Trading_Strategies.md` (Table SH-4, scenarios, kill conditions)  
> Parameters: `Docs/Trading_Parameters.md` (Parts H, J, K, U)  
> News / sentiment curation: `Market_News.txt` (Architecture §8.8)  
> **Hosting (paper):** backend **Railway** · frontend **Vercel** (Architecture §17.0)

## Purpose

Practice multi-leg options strategies with **live ICICI Direct market marks** and an **in-house fill/ledger engine**. This path does **not** call Breeze API `place_order`.

v1 is a **full paper rehearsal of the playbook**, not only a ledger:

1. **Act per `Trading_Strategies.md`** — strategy selection (SH-4), entry/sizing/management/exit, capital prerequisites, shared kill conditions.  
2. **Use `Market_News.txt`** — India news sources and daily workflow windows drive sentiment / event flags that **gate and overlay** quant signals (Architecture §8.8).  
3. **GARCH / IV z-score signals** — cheap-vol and intraday IV mean-reversion frames.  
4. **Continuous gamma–theta re-hedge automation** — re-neutralize when spot moves past the breakeven from the last hedge point.  

Promotion to live ICICI Direct remains a later, explicit step on the broker adapter path (`EXECUTION_MODE=live`).

## Two paths (do not mix)

| Path | Package | Uses ICICI Direct for | Places broker orders? |
|------|---------|--------------------|------------------------|
| **Paper rehearsal** | `backend/paper_sim/` | LTP + instrument master only | **No** |
| **Live progression** | `backend/integrations/icici_direct/` | Auth, marks, **and** orders | Only when `EXECUTION_MODE=live` |

```
Market_News.txt  ──► market_news / sentiment (§8.8)
        │
Trading_Strategies.md (SH-4, scenarios, kills)
        │
        ├── paper_sim  ──► select strategy + signals (GARCH / IV z)
        │                      │
        │                      ├── IciciDirectDataOnlyFeed (LTP/chain)
        │                      └── auto re-hedge / exit loop ──► local PaperLedger
        │
        └── icici_direct adapter ──► shadow dry-run logs ──► later live place_order
```

`EXECUTION_MODE=paper` on the ICICI Direct adapter is still only a dry-run log (no sandbox). Prefer **`/api/v1/paper-sim/*`** for real paper P&L.

## Capital defaults

Aligned with `Trading_Strategies.md` Capital Prerequisites:

- Total virtual capital: ₹10,00,000  
- Max investment to open a trade: ₹1,00,000  
- Max investment per leg: ₹1,00,000  
- Default slippage: 50 bps (0.50%)  
- **Tradeable universe (options-only hard lock):** paper-sim opens Call/Put option legs only. It rejects stock/underlying legs and cash-share hedge paths, has no ₹1,000 spot cap, and allows index underlyings when ATM / premium / liquidity / risk gates pass. Same gate as live (`Trading_Parameters.md` Part T / `Trading_Strategies.md`).
- ATM + high-liquidity + premium gates per playbook / Part I

## API (v1)

Base: `/api/v1/paper-sim`

| Method | Path | Action |
|--------|------|--------|
| GET | `/health` | Module + feed + news freshness (`broker_place_order: false`) |
| GET | `/account` | Cash, equity, realized/unrealized P&L |
| POST | `/reset` | Reset virtual cash / clear positions |
| GET | `/positions` | Open (or filtered) paper positions |
| GET | `/fills` | Recent simulated fills |
| POST | `/orders` | Multi-leg paper fill at LTP ± slippage (manual / override). After entry, remaining **intended** multi-leg opening legs may auto-complete **without consent** under the same open-trade rules |
| POST | `/positions/{id}/close` | Flatten position at current marks |
| POST | `/positions/{id}/complete-multi-leg` | Retry auto-completion of intended opening legs (no consent; same open rules) |
| POST | `/marks/refresh` | Re-mark open legs via ICICI Direct LTP |
| GET | `/chain?underlying=SBIN` | Option chain for an underlying (+ optional LTP); no spot cap under the options-only hard lock |
| GET | `/news` | Current `MarketNewsSummary` from `Market_News.txt` pipeline |
| GET | `/signals?underlying=…` | GARCH, IV, IV z-score, **news flags**, SH-4 recommendation |
| POST | `/signals/evaluate` | Evaluate candidate vs playbook + news gates; stock/underlying structures fail `OPTIONS_ONLY_REQUIRED` |
| POST | `/strategies/select` | Force or dry-run SH-4 selection given quant + news inputs |
| POST | `/automation/start` | Start signal + γ–θ re-hedge (+ news kill) loop |
| POST | `/automation/stop` | Stop the automation loop |
| GET | `/automation/status` | Loop state, hedge points, last signal, news impact, last actions |

Example open (simple_vol — long ATM CE + PE). **`quantity` must be a multiple of that contract’s ICICI Direct NFO `lotsize`** (never assume OSS US 100). Example uses a mock lot of 25; live lots come from instrument master (see `nfo_lot_sizing` in `trading_parameters.defaults.json`). `SBIN` is illustrative; index underlyings are also allowed when the selected options pass gates. A **stock** hedge is rejected.

```json
POST /api/v1/paper-sim/orders
{
  "strategy_tag": "simple_vol",
  "underlying": "SBIN",
  "legs": [
    { "symbol": "SBIN28MAR24500CE", "side": "buy", "quantity": 25, "exchange": "NFO" },
    { "symbol": "SBIN28MAR24500PE", "side": "buy", "quantity": 25, "exchange": "NFO" }
  ]
}
```

## Strategy brain (v1)

Paper-sim **must** behave as a paper execution of `Trading_Strategies.md`, with sentiment from the `Market_News.txt` pipeline (Architecture §8.8). Quant signals remain primary; news **overlays and gates**.

### Market news (`Market_News.txt`)

Honor the curation contract:

| Window (IST) | Sources |
|--------------|---------|
| Pre-open 08:00–09:00 | Reuters India, Economic Times Markets, CNBC TV18 |
| Session | Moneycontrol Live, Pulse by Zerodha, NSE announcements |
| After close | ET analysis, earnings, FII/DII, sector performance |

Bot ingestion priority: Reuters → Moneycontrol → Economic Times → NSE corporate announcements → SEBI circulars.

`GET /news` / signal payloads expose at least: `dominant_tone`, `topics`, `symbol_tags`, `macro_risk_flags`, `source_freshness`, `news_impact`.

### Strategy selection (Table SH-4)

| Market / news condition | First choice | Paper-sim action |
|-------------------------|--------------|------------------|
| Normal; IV < GARCH; no adverse event news | Simple vol → gamma if IV path uncertain | Prefer `simple_volatility` / `cheap_vol_mode` |
| Earnings / company event (news + calendar) | Gamma scalping | `gamma_scalping` + `earnings_gap_mode`; **reject** plain long-vega through event |
| IV high; large realized moves; news confirms agitation | Gamma scalping | `gamma_scalping` + `high_realized_vol_mode` |
| Intraday IV −2σ; news not blocking | Vega scalping | `vega_scalping`; same-day flatten |
| Post-shock / crisis tone; GARCH distorted | Reduce / block | `stand_aside` / `blocked`; set `garch_distorted` / `block_model_trades` |
| Breaking news after live long-vol entry | Favorable long vega/gamma | Display-only tone (`breaking_bullish`) — no automatic action; position exits only via strategy exit rules |
| Quiet tape + adverse news after entry | Theta / IV-fall risk | Display-only tone (`adverse_tone`) — no automatic early exit; exits only via strategy stop/target/time rules |

Unplanned earnings/news the setup was not designed to absorb never closes or flattens an open position — it can only block a *new* entry (SH-4 / `news_blocks_model_trades`). Open positions exit solely via strategy exit rules or the mechanical γ–θ re-hedge.

### GARCH / IV z-score signals

Aligned with playbook + `Trading_Parameters.md` Part H:

| Signal | Rule | Typical use |
|--------|------|-------------|
| **GARCH(1,1) cheap vol** | Annualized option IV **&lt;** annualized GARCH forecast (`σ_annual = σ_daily × √252`) | Simple vol / gamma cheap-vol entry |
| **IV z-score** | Intraday IV vs recent mean/σ (e.g. entry when z ≤ −2) | Vega scalping / regime filter |
| **Post-shock block** | If `garch_distorted` or crisis news tone | Avoid blind GARCH entries |

`GET /signals` returns at least:

- `garch_forecast_annual`, `option_iv_annual`, `iv_minus_garch`, `iv_zscore`, `garch_distorted`  
- `market_news` summary + `news_impact`  
- `selected_strategy` / `entry_mode` / `scenario_tag` (SH-4)  
- `recommendation` (`enter_long_vol` \| `enter_gamma` \| `enter_vega` \| `stand_aside` \| `blocked` \| …)  

Manual `POST /orders` remains allowed as supervised override; automated entries follow signals + news gates.

### Post-entry multi-leg auto-complete (Phase 1)

After an entry fills, if the bot **intends** a multi-leg opening structure (`intended_legs` on the order, or strategy-inferred — e.g. `simple_vol` ATM CE+PE, gamma/vega option+stock), remaining opening legs may be submitted **automatically without operator consent**.

**Same rules as the first entry (mandatory):**

- Fresh marks gate (reject if any completing leg is stale / missing LTP)
- Quantity multiple of NFO `lotsize`
- Pre-trade risk gate (buying power, drawdown, circuit breakers)
- Options-only hard lock (`OPTIONS_ONLY_REQUIRED` for stock/underlying legs or cash-share hedge paths)
- Per-leg max investment ₹1,00,000
- **Cumulative** max investment to open the trade ₹1,00,000 (`opening_investment_inr` across entry + completion legs)

This is **opening-structure completion**, not γ–θ management re-hedge. Set `auto_complete_multi_leg: false` on `POST /orders` to leave the structure incomplete for manual control. Automation ticks also attempt completion before re-hedge.

### Continuous gamma–theta re-hedge automation

Aligned with `Trading_Parameters.md` Part J and playbook management rules:

1. On entry (or after each re-hedge), store `hedge_point_price`.  
2. Compute `gamma_theta_breakeven_pct` from current Greeks (do **not** hard-code ~1%).  
3. Each automation tick: refresh marks; re-check news kills; if spot moved ≥ breakeven from hedge point, auto-submit re-neutralizing paper order.  
4. Update `hedge_point_price`, `breakeven_paid_count`, and P&L attribution.  
5. Enforce capital caps and Part I / Shared Kill flags on every re-hedge.  

Re-hedge methods: `adjust_call_put_mix` (default) \| `reduce_options` \| `increase_hedge`. All methods adjust Call/Put option legs only; no stock shares are added or removed.

## What v1 does / does not do

**Does**

- Resolve NFO contracts from ICICI Direct instrument master (`FONSEScripMaster.txt`)
- Recommendation / paper universe (G11–G12): **all** unique NSE F&O underlyings from that master, with auto feed bindings for spot + option chain
- Fill at ICICI Direct LTP with configurable slippage  
- Track multi-leg positions, cash, realized & unrealized P&L  
- Enforce playbook capital / liquidity / ATM / premium caps  
- Ingest / honor **`Market_News.txt`** sentiment and event flags  
- **Select and manage strategies per `Trading_Strategies.md`** (SH-4, scenarios, exits, kills)  
- Compute **GARCH(1,1)** and **IV z-score** signals  
- Run **continuous gamma–theta re-hedge automation** into the local paper ledger  
- **Auto-complete intended multi-leg opening legs** after entry without consent (same open-trade rules)  

**Does not (yet)**

- Bid/ask depth or partial fills  
- Couple into `IciciDirectBrokerAdapter.submit_order`  

## Hosted paper trading (Railway + Vercel)

Paper rehearsal is hosted as a lightweight split stack — **not** the GCP live inventory (`infra/cloud-inventory.yaml` / Architecture §17.8). Promote to GCP only when moving toward ICICI Direct `live`.

| Tier | Platform | Source | Role |
|------|----------|--------|------|
| **Backend** | **Railway** | `backend/` | FastAPI + `paper_sim` + bot scheduler (`PROCESS_ROLE=all`); Postgres + Redis as Railway plugins (or Railway Postgres / Redis add-ons) |
| **Frontend** | **Vercel** | `frontend/` | Next.js dashboard / monitor / chat; public API URL only — no secrets |

### Wiring

| Variable | Where set | Value |
|----------|-----------|--------|
| `NEXT_PUBLIC_API_URL` | Vercel project env (Production / Preview) | Railway public HTTPS URL (e.g. `https://<service>.up.railway.app`) |
| `NEXT_PUBLIC_WS_URL` | Vercel project env | Same host with `wss://` (or derived from API URL in client) |
| `CORS_ORIGINS` | Railway service variables | Vercel app URL(s), e.g. `https://<app>.vercel.app` (+ custom domain if any) |
| `EXECUTION_MODE` | Railway | `paper` (paper-sim path) — never `live` on this stack |
| `GROQ_API_KEY`, ICICI Direct data credentials | Railway secrets | Server-side only |
| `DATABASE_URL`, `REDIS_URL` | Railway | From linked Postgres / Redis plugins |

### Deploy notes

1. **Railway:** Deploy `backend/` via **Nixpacks** (`nixpacks.toml`, `Procfile`, `scripts/start_remote.sh` — no Dockerfile; see `Docs/LOCAL_DEV.md`). Keep **one always-on** instance for the paper automation / γ–θ loop (`min` replicas = 1; avoid sleep if the scheduler must tick during market hours).  
2. **Vercel:** Connect `frontend/`; set `NEXT_PUBLIC_*` at **build time**. Redeploy frontend after the Railway URL is known.  
3. **Chroma (optional on paper):** Embedded or a small Railway volume / sidecar for RAG chat; full Filestore-backed Chroma is a GCP live concern (§17.8).  
4. **WebSockets:** Prefer Railway public URL with `wss://` for live dashboard streams; confirm proxy idle timeouts cover market-hours sessions.  
5. **Region preference:** Prefer Railway / Vercel regions with low latency to India (IST session) when the platform offers a choice; ICICI Direct marks still originate in India.

Canonical detail and phase boundary vs GCP live: Architecture **§17.0** (paper) and **§17.8** (live). UI wiring: `Docs/UI_Dashboard.md`.

## Going live later

When ready for ICICI Direct live (`architecture.md` §21 Phase 5):

1. Keep practicing on hosted `/api/v1/paper-sim` (Railway + Vercel) through supervised → semi → full autonomy (Phases 2–4) until SH-4 + news + re-hedge behavior is stable and soak metrics pass.  
2. Use ICICI Direct adapter **A3 shadow** (`POST /api/v1/config/integrations/broker/shadow-order`, cancel/status + `GET .../shadow-orders`) to validate order payload mapping — logged only; never `place_order`.  
3. Promote to `EXECUTION_MODE=live` on the **GCP** stack (Cloud Run + Cloud SQL + Memorystore, §17.8) with micro-size + risk gates — a **separate** code path and deploy target, not a flip of the paper ledger or Railway service.
