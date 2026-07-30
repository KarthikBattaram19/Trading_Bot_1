# ICICI Direct Breeze MCP Server

MCP server for ICICI Direct markets via [Breeze API](https://api.icicidirect.com/breezeapi/documents/index.html)
using the official [`breeze-connect`](https://github.com/Idirect-Tech/Breeze-Python-SDK) SDK.

## Setup

```bash
cd tools/icici-direct-mcp-server
pip install -r requirements.txt
pip install -e .
```

## Credentials

Set in the repo-root `.env` (or this package `.env`):

```bash
ICICI_DIRECT_API_KEY=
ICICI_DIRECT_API_SECRET=
ICICI_DIRECT_SESSION_TOKEN=
DRY_RUN_MODE=true
MAX_ORDER_QUANTITY=1000
```

1. Customer login: https://secure.icicidirect.com/customer/login  
2. Breeze API login (daily session): https://api.icicidirect.com/apiuser/login?api_key=`<API_KEY>`  
3. Copy the `API_Session` value into `ICICI_DIRECT_SESSION_TOKEN`

## Launch from Cursor

```bash
python tools/icici_direct_mcp_launcher.py
```

Or configure MCP:

```json
{
  "mcpServers": {
    "icici-direct-trading": {
      "command": "python",
      "args": ["tools/icici_direct_mcp_launcher.py"]
    }
  }
}
```

## Safety

- `DRY_RUN_MODE=true` by default — `place_order` / `modify_order` / `cancel_order` return dry-run payloads.
- Set `DRY_RUN_MODE=false` only when intentionally allowing live Breeze orders.
