# Trading Bot 1 — Volatility trading (Phase 0)

Paper-first volatility bot: **ICICI Direct Breeze** marks (data-only), in-house **paper_sim**, Next.js dashboard.

| Layer | Local | Paper hosting |
| ----- | ----- | ------------- |
| API | `scripts/dev/start-backend.ps1` | [Railway](Docs/RAILWAY_DEPLOY.md) |
| UI | `scripts/dev/start-frontend.ps1` | Vercel (`frontend/`) |

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
- Docs: `Docs/implementation_plan.md`, `Docs/LOCAL_DEV.md`

## Deploy backend to Railway

See **[Docs/RAILWAY_DEPLOY.md](Docs/RAILWAY_DEPLOY.md)** — connect [Trading_Bot_1](https://github.com/KarthikBattaram19/Trading_Bot_1) to your Railway project and use **Option A** (empty Root Directory) unless you prefer `backend/` + `/backend/railway.toml`.
