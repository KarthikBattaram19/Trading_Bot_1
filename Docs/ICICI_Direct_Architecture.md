# ICICI Direct (Breeze API) — Superseded stub

> **Status:** **Superseded**.  
> **Do not use this file for implementation.** All ICICI Direct Breeze content lives in **`Docs/architecture.md`**.

## Where to read now

| Former topic | Authoritative location |
| ------------ | ---------------------- |
| Purpose, placement, adapter registration | `architecture.md` §11 intro + §11.2 |
| Breeze API surface map, headers, instrument identity | `architecture.md` §11.8 |
| Authentication & session lifecycle (daily API_Session) | `architecture.md` §11.9 |
| Broker adapter module layout | `architecture.md` §11.2 |
| Market data (ICICI Direct only; no MCP registry) | `architecture.md` §8.9 |
| Order & position mapping | `architecture.md` §11.10 |
| SEBI / static IP / rate limits | `architecture.md` §11.11 |
| Execution modes & paper gap | `architecture.md` §11.7 |
| Configuration & secrets | `architecture.md` §11.12 |
| Health & failure modes | `architecture.md` §11.13 |
| Phases A0–A6 | `architecture.md` §11.15 + §21 |
| Paper P&L API behavior | `Docs/Paper_Simulator.md` |

**Build the entire project from `Docs/architecture.md` alone** (plus ops refs: `Paper_Simulator.md`, `Trading_Strategies.md`, `UI_Dashboard.md`, etc., as cross-linked there).

- Customer login: https://secure.icicidirect.com/customer/login
- Breeze API login: https://api.icicidirect.com/apiuser/login
- Docs: https://api.icicidirect.com/breezeapi/documents/index.html
- SDK: https://github.com/Idirect-Tech/Breeze-Python-SDK
