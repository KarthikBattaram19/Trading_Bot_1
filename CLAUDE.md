# Trading Bot 1 — Volatility Trading (Phase 0)

Paper-first volatility bot: ICICI Direct Breeze marks (data-only), in-house `paper_sim`, Next.js dashboard.

## Quick start (local)

```powershell
copy .env.example .env
# Edit .env — ICICI_DIRECT_* (never commit .env)

python -m pip install -r backend\requirements-dev.txt
cd frontend && npm ci && cd ..

.\scripts\dev\check-env.ps1
.\scripts\dev\start-backend.ps1   # terminal 1
.\scripts\dev\start-frontend.ps1  # terminal 2
```

- API: http://127.0.0.1:8000/health
- Docs: `Docs/implementation_plan.md`, `Docs/LOCAL_DEV.md`, `Docs/architecture.md`

## Tests

```powershell
pytest                       # backend/ tests; asyncio_mode=auto
pytest -m "not integration"  # default CI selection — skips live/broker checks
```

## Architecture

- `backend/` — FastAPI app (`main.py`), `routers/`, `services/`, `paper_sim/` (fill engine), `quant/` (signals), `execution/`, `integrations/` (Breeze), `models/`, `schemas/`, `analytics/`, `knowledge/`, `llm/`
- `frontend/` — Next.js dashboard (`src/`), deployed to Vercel
- `infra/` — cloud inventory / provisioning (GCP)
- `Docs/` — architecture, implementation plan, deploy guides (source `.md` at repo root, exported to `Docs/*.pdf`)

## Deploy

- Backend → Railway, see `Docs/RAILWAY_DEPLOY.md` (use Option A: empty Root Directory)
- Frontend → Vercel (`frontend/`)

## Docs → PDF

```powershell
python scripts/md_to_pdf.py architecture.md implementation_plan.md -o Docs
```
Re-run after editing `architecture.md` or `implementation_plan.md`. Mermaid blocks render as text placeholders in PDF only.

## ICICI Direct Breeze API — vendor constraints

Authoritative source: [Breeze API Reference](https://api.icicidirect.com/breezeapi/documents/index.html). Don't invent request shapes — use vendor docs. Project mapping: `Docs/architecture.md` §8.9 / §11.8–11.15.

- **Do not implement GTT** (Good Till Triggered orders) — out of scope for this project.
- Order APIs only from a **registered static IP**; static IP change ≤ once/week.
- Unregistered algo: **single API key** for order routing.
- ≤ **10 combined order ops/sec** (place/modify/cancel/square-off).
- **No market orders** — limit only.
- No Margin / Option Plus place-modify-cancel via Breeze.
- Rate envelope: ~100 calls/min, ~5000/day (non-order APIs count too).
- NSE equity/futures/options only — treat BSE/MCX as unavailable unless docs change.
- Resolve `session_token` via `customerdetails` before signed calls (`X-Checksum` = `token ` + SHA256(`timestamp`+payload+`secret_key`)).

## Cloud / GCP

- Primary region is **`asia-south1` (Mumbai)** — for Indian markets (NSE/BSE/NFO), ICICI Direct/Breeze, IST. Never use `us-west1` or other US regions for this project's cloud inventory.
- When provisioning infra, create/update `infra/cloud-inventory.yaml` with all services co-located in `asia-south1` (Cloud Run, Artifact Registry, Cloud SQL, Memorystore, Filestore, VPC connector). Keep `Docs/architecture.md` §17.8 and `Docs/context.md` aligned.

## Priority backlog — must-fix before claiming performance

Full source of truth: `.cursor/rules/must-fix-before-claiming-performance.mdc`, checked each run by the `Guruji_for_Bhale_Bullodu` skill (`.claude/skills/Guruji_for_Bhale_Bullodu/`) against `Docs/bot_health/BACKLOG.md`.

Do not treat P&L targets, Sharpe goals, or "edge proven" language as met until P0–P1 are real in code with evidence:

- **P0**: wire recommend → supervised approve → `paper_sim` → learning as one real ledger (no fills outside `paper_sim`); enforce breakers/market-hours durably (survives restart, not dashboard-only).
- **P1**: walk-forward/replay OOS evidence for SH-4 expectancy before "top performing" claims; skew/term/India VIX regime filters + IV quality checks.
- **P2**: delta/vega-based position sizing with real costs; fill/reconcile FSM before live micro-capital (Phase 5).

When asked to improve this project or "make it better," prefer closing P0 over net-new strategy/UI features, and never imply the vol edge is validated without OOS evidence.
