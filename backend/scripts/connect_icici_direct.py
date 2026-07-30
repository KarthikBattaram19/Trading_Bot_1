"""Phase A0 — authenticate with ICICI Direct Breeze API and print non-secret health.

Usage (from repo root):
  python -m backend.scripts.connect_icici_direct

Requires .env:
  ICICI_DIRECT_API_KEY, ICICI_DIRECT_API_SECRET, ICICI_DIRECT_SESSION_TOKEN

Session token is the daily API_Session from Breeze API login:
  https://api.icicidirect.com/apiuser/login?api_key=<API_KEY>
"""

from __future__ import annotations

import asyncio
import json
import sys


async def main() -> int:
    from backend.config_env import load_project_env
    from backend.integrations.icici_direct.client import IciciDirectAPIError
    from backend.integrations.icici_direct.session_manager import get_session_manager
    from backend.integrations.credential_vault import load_icici_direct_credentials
    from backend.integrations.registry import get_broker_adapter

    load_project_env()
    load_icici_direct_credentials()
    session_mgr = get_session_manager()

    if not session_mgr.credentials_ready():
        print(
            "Missing credentials. Set in .env:\n"
            "  ICICI_DIRECT_API_KEY\n"
            "  ICICI_DIRECT_API_SECRET\n"
            "  ICICI_DIRECT_SESSION_TOKEN\n"
            "Customer login: https://secure.icicidirect.com/customer/login\n"
            "Breeze API login: https://api.icicidirect.com/apiuser/login\n"
            "Docs: https://api.icicidirect.com/breezeapi/documents/index.html",
            file=sys.stderr,
        )
        return 1

    try:
        adapter = get_broker_adapter("icici_direct")
        auth = await adapter.authenticate()
        client = await session_mgr.ensure_session()
        await client.ensure_public_ip()
        details = await client.get_customer_details()
        success = details.get("Success") or {}
        result = {
            "ok": True,
            "provider": "icici_direct",
            "customer_id": auth.get("customer_id"),
            "authenticated_at": auth.get("authenticated_at"),
            "has_session_token": auth.get("has_session_token"),
            "public_ip": client.public_ip,
            "customer_details_keys": sorted(success.keys()) if isinstance(success, dict) else [],
            "session": session_mgr.health(),
        }
        print(json.dumps(result, indent=2))
        return 0
    except IciciDirectAPIError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
