"""Concrete paper-sim rehearsal: NIFTY + BANKNIFTY ATM straddles via ICICI Direct marks.

Usage (from repo root):
  python -m backend.scripts.paper_sim_walkthrough

Never calls Breeze place_order — local ledger only.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from typing import Any


# Index spot identifiers commonly used for NSE (Breeze stock_code / token)
INDEX_SPOT = {
    "NIFTY": ("NSE", "Nifty 50", "NIFTY"),
    "BANKNIFTY": ("NSE", "Nifty Bank", "CNXBAN"),
}


def _parse_expiry(raw: str | None) -> datetime | None:
    if not raw:
        return None
    s = raw.upper().replace("-", "").replace(" ", "")
    for fmt in ("%d%b%Y", "%d%b%y", "%Y%m%d"):
        try:
            return datetime.strptime(s[:9] if fmt.startswith("%d") else s[:8], fmt)
        except ValueError:
            continue
    return None


def _nearest_expiry(records: list) -> str | None:
    today = datetime.utcnow().date()
    candidates: list[tuple[datetime, str]] = []
    for r in records:
        dt = _parse_expiry(r.expiry)
        if dt is None or not r.expiry:
            continue
        if dt.date() < today:
            continue
        candidates.append((dt, r.expiry))
    if not candidates:
        # fall back to any expiry present
        for r in records:
            if r.expiry:
                return r.expiry
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def _atm_straddle(records: list, spot: float) -> tuple[Any, Any] | None:
    """Pick CE+PE at strike closest to spot for a single expiry set."""
    by_strike: dict[float, dict[str, Any]] = {}
    for r in records:
        if r.strike is None:
            continue
        sym = r.tradingsymbol.upper()
        ot = "CE" if sym.endswith("CE") else "PE" if sym.endswith("PE") else None
        if ot is None:
            continue
        by_strike.setdefault(float(r.strike), {})[ot] = r
    paired = [(abs(k - spot), k, v) for k, v in by_strike.items() if "CE" in v and "PE" in v]
    if not paired:
        return None
    paired.sort(key=lambda x: x[0])
    _, _, legs = paired[0]
    return legs["CE"], legs["PE"]


async def _spot(feed, underlying: str) -> float | None:
    exch, symbol, token = INDEX_SPOT[underlying]
    try:
        tick = await feed.get_ltp(exch, symbol, token)
        if tick.ltp > 0:
            return float(tick.ltp)
    except Exception as exc:  # noqa: BLE001
        print(f"  spot lookup failed for {underlying}: {exc}", file=sys.stderr)
    return None


async def _rehearse_underlying(engine, underlying: str) -> dict[str, Any]:
    feed = engine.feed
    await feed.ensure_instruments()
    all_opts = feed.list_options(name=underlying, exchange="NFO", limit=5000)
    expiry = _nearest_expiry(all_opts)
    if not expiry:
        raise RuntimeError(f"no option contracts for {underlying}")

    expiry_opts = feed.list_options(name=underlying, exchange="NFO", expiry=expiry, limit=2000)
    spot = await _spot(feed, underlying)
    if spot is None:
        # crude fallback: median strike
        strikes = sorted({float(r.strike) for r in expiry_opts if r.strike})
        spot = strikes[len(strikes) // 2] if strikes else 0.0

    pair = _atm_straddle(expiry_opts, spot)
    if pair is None:
        raise RuntimeError(f"no CE/PE pair near spot for {underlying} {expiry}")
    ce, pe = pair
    lot = max(ce.lotsize, 1)

    from backend.paper_sim.models import PaperLegRequest, PaperOrderRequest, PaperSide

    order = PaperOrderRequest(
        strategy_tag="walkthrough_atm_straddle",
        underlying=underlying,
        note=f"paper walkthrough expiry={expiry} spot≈{spot:.2f}",
        legs=[
            PaperLegRequest(
                symbol=ce.tradingsymbol,
                side=PaperSide.buy,
                quantity=lot,
                exchange="NFO",
                symbol_token=ce.symboltoken,
            ),
            PaperLegRequest(
                symbol=pe.tradingsymbol,
                side=PaperSide.buy,
                quantity=lot,
                exchange="NFO",
                symbol_token=pe.symboltoken,
            ),
        ],
    )
    opened = await engine.submit_order(order)
    refreshed = await engine.refresh_marks()
    closed = await engine.close_position(opened["position"]["position_id"])

    return {
        "underlying": underlying,
        "expiry": expiry,
        "spot_used": spot,
        "legs": {
            "ce": ce.tradingsymbol,
            "pe": pe.tradingsymbol,
            "lotsize": lot,
            "strike": ce.strike,
        },
        "open": {
            "order_id": opened["order_id"],
            "broker_place_order": opened["broker_place_order"],
            "fills": [
                {
                    "symbol": f["symbol"],
                    "side": f["side"],
                    "qty": f["quantity"],
                    "mark_ltp": f["mark_ltp"],
                    "fill_price": f["fill_price"],
                    "notional_inr": f["notional_inr"],
                }
                for f in opened["fills"]
            ],
            "cash_after_open": opened["account"]["cash_inr"],
        },
        "marks_after_refresh": {
            "unrealized_pnl": refreshed["account"]["unrealized_pnl"],
            "equity_inr": refreshed["account"]["equity_inr"],
        },
        "close": {
            "realized_pnl": closed["realized_pnl"],
            "fills": [
                {
                    "symbol": f["symbol"],
                    "side": f["side"],
                    "qty": f["quantity"],
                    "mark_ltp": f["mark_ltp"],
                    "fill_price": f["fill_price"],
                }
                for f in closed["fills"]
            ],
            "cash_after_close": closed["account"]["cash_inr"],
        },
    }


async def main() -> int:
    from backend.config_env import load_project_env
    from backend.integrations.icici_direct.client import IciciDirectAPIError
    from backend.integrations.icici_direct.session_manager import get_session_manager
    from backend.integrations.credential_vault import load_icici_direct_credentials
    from backend.integrations.registry import get_broker_adapter
    from backend.paper_sim.service import get_paper_engine

    load_project_env()
    load_icici_direct_credentials()
    session_mgr = get_session_manager()

    if not session_mgr.credentials_ready():
        print("Missing ICICI Direct credentials in .env", file=sys.stderr)
        return 1

    try:
        adapter = get_broker_adapter("icici_direct")
        auth = await adapter.authenticate()
        client = await session_mgr.ensure_session()
        await client.ensure_public_ip()

        engine = get_paper_engine(reset=True)
        account0 = engine.reset()
        health = engine.health()
        n_inst = await engine.feed.ensure_instruments()

        results: dict[str, Any] = {
            "ok": True,
            "session": {
                "customer_id": auth.get("customer_id"),
                "authenticated_at": auth.get("authenticated_at"),
                "has_session_token": auth.get("has_session_token"),
                "public_ip": client.public_ip,
            },
            "paper": {
                "starting_cash_inr": account0.cash_inr,
                "slippage_bps": health["config"]["slippage_bps"],
                "broker_place_order": health["broker_place_order"],
                "instruments_loaded": n_inst,
            },
            "runs": [],
        }

        for underlying in ("NIFTY", "BANKNIFTY"):
            print(f"… rehearsing {underlying}", file=sys.stderr)
            results["runs"].append(await _rehearse_underlying(engine, underlying))

        results["final_account"] = engine.account().model_dump(mode="json")
        print(json.dumps(results, indent=2, default=str))
        return 0
    except IciciDirectAPIError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
