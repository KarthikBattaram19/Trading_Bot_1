"""
Launch ICICI Direct Breeze MCP server for Cursor.
Loads project .env (ICICI_DIRECT_API_KEY / SECRET / SESSION_TOKEN).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# Safe default for market-data use; set DRY_RUN_MODE=false in .env to allow live orders
os.environ.setdefault("DRY_RUN_MODE", "true")
os.environ.setdefault("MAX_ORDER_QUANTITY", "1000")

sys.path.insert(0, str(ROOT / "tools" / "icici-direct-mcp-server" / "src"))

from icici_direct_mcp.server import main  # noqa: E402

if __name__ == "__main__":
    main()
