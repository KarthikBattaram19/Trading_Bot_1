#!/usr/bin/env python3
"""
ICICI Direct Breeze MCP Server

Exposes ICICI Direct Breeze trading and market data APIs as MCP tools.
Uses breeze-connect (BreezeConnect) with daily session token auth.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("icici-direct-trading")

breeze: Any = None
is_authenticated = False

API_KEY = os.getenv("ICICI_DIRECT_API_KEY")
API_SECRET = os.getenv("ICICI_DIRECT_API_SECRET")
SESSION_TOKEN = os.getenv("ICICI_DIRECT_SESSION_TOKEN")

MAX_ORDER_QUANTITY = int(os.getenv("MAX_ORDER_QUANTITY", "10000"))
DRY_RUN_MODE = os.getenv("DRY_RUN_MODE", "true").lower() == "true"


def validate_environment() -> None:
    required_vars = [
        "ICICI_DIRECT_API_KEY",
        "ICICI_DIRECT_API_SECRET",
        "ICICI_DIRECT_SESSION_TOKEN",
    ]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        raise ValueError(f"Missing required environment variables: {missing}")


def ensure_authenticated() -> bool:
    global breeze, is_authenticated

    if breeze is None:
        validate_environment()
        from breeze_connect import BreezeConnect

        breeze = BreezeConnect(api_key=API_KEY)

    if not is_authenticated:
        try:
            breeze.generate_session(
                api_secret=API_SECRET,
                session_token=SESSION_TOKEN,
            )
            is_authenticated = True
            logger.info("Successfully authenticated with ICICI Direct Breeze API")
        except Exception as exc:
            logger.error("Authentication error: %s", exc)
            raise

    return True


def handle_api_error(func_name: str, error: Exception) -> Dict[str, Any]:
    error_context = {
        "function": func_name,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "suggestion": (
            "Check parameters and try again. Verify market hours for trading. "
            "Refresh ICICI_DIRECT_SESSION_TOKEN via "
            "https://api.icicidirect.com/apiuser/login if session expired."
        ),
    }
    logger.error("API Error in %s: %s", func_name, error)
    return {"error": error_context}


@mcp.tool()
async def get_profile() -> Dict[str, Any]:
    """Get customer profile / session details from Breeze."""
    try:
        ensure_authenticated()
        return breeze.get_customer_details(api_session=SESSION_TOKEN)
    except Exception as e:
        return handle_api_error("get_profile", e)


@mcp.tool()
async def get_holdings(
    exchange_code: str = "NSE",
    from_date: str = "",
    to_date: str = "",
) -> Dict[str, Any]:
    """Get portfolio holdings."""
    try:
        ensure_authenticated()
        return breeze.get_portfolio_holdings(
            exchange_code=exchange_code,
            from_date=from_date,
            to_date=to_date,
            stock_code="",
            portfolio_type="",
        )
    except Exception as e:
        return handle_api_error("get_holdings", e)


@mcp.tool()
async def get_positions() -> Dict[str, Any]:
    """Get open portfolio positions."""
    try:
        ensure_authenticated()
        return breeze.get_portfolio_positions()
    except Exception as e:
        return handle_api_error("get_positions", e)


@mcp.tool()
async def get_rms_limit() -> Dict[str, Any]:
    """Get funds / margin limits."""
    try:
        ensure_authenticated()
        return breeze.get_funds()
    except Exception as e:
        return handle_api_error("get_rms_limit", e)


@mcp.tool()
async def place_order(
    stock_code: str,
    exchange_code: str,
    product: str,
    action: str,
    order_type: str,
    quantity: str,
    price: str = "0",
    validity: str = "day",
    stoploss: str = "0",
    expiry_date: str = "",
    right: str = "",
    strike_price: str = "",
    disclosed_quantity: str = "0",
    user_remark: str = "",
) -> Dict[str, Any]:
    """Place a buy/sell order via Breeze place_order.

    action: buy or sell (lowercase).
    order_type: limit or stoploss (Breeze has no true market orders).
    product: cash, futures, options, margin.
    """
    try:
        ensure_authenticated()
        if int(quantity) > MAX_ORDER_QUANTITY:
            return {
                "error": f"Order quantity {quantity} exceeds maximum allowed {MAX_ORDER_QUANTITY}"
            }

        order_params = {
            "stock_code": stock_code,
            "exchange_code": exchange_code,
            "product": product,
            "action": action.lower(),
            "order_type": order_type.lower(),
            "quantity": quantity,
            "price": price,
            "validity": validity,
            "stoploss": stoploss,
            "disclosed_quantity": disclosed_quantity,
            "expiry_date": expiry_date or None,
            "right": right or None,
            "strike_price": strike_price or None,
            "user_remark": user_remark or None,
        }
        # Drop Nones for dry-run clarity
        order_params = {k: v for k, v in order_params.items() if v is not None}

        if DRY_RUN_MODE:
            return {
                "status": "dry_run",
                "message": "Order would be placed",
                "params": order_params,
            }

        return breeze.place_order(**order_params)
    except Exception as e:
        return handle_api_error("place_order", e)


@mcp.tool()
async def modify_order(
    order_id: str,
    exchange_code: str,
    quantity: str = "",
    price: str = "",
    stoploss: str = "",
    validity: str = "day",
) -> Dict[str, Any]:
    """Modify an existing Breeze order."""
    try:
        ensure_authenticated()
        params = {
            "order_id": order_id,
            "exchange_code": exchange_code,
            "quantity": quantity or None,
            "price": price or None,
            "stoploss": stoploss or None,
            "validity": validity,
        }
        params = {k: v for k, v in params.items() if v is not None}
        if DRY_RUN_MODE:
            return {
                "status": "dry_run",
                "message": "Order would be modified",
                "params": params,
            }
        return breeze.modify_order(**params)
    except Exception as e:
        return handle_api_error("modify_order", e)


@mcp.tool()
async def cancel_order(order_id: str, exchange_code: str = "NSE") -> Dict[str, Any]:
    """Cancel an existing Breeze order."""
    try:
        ensure_authenticated()
        if DRY_RUN_MODE:
            return {
                "status": "dry_run",
                "message": f"Order {order_id} would be cancelled",
            }
        return breeze.cancel_order(exchange_code=exchange_code, order_id=order_id)
    except Exception as e:
        return handle_api_error("cancel_order", e)


@mcp.tool()
async def get_order_book(
    exchange_code: str = "NSE",
    from_date: str = "",
    to_date: str = "",
) -> Dict[str, Any]:
    """Get order list / order book."""
    try:
        ensure_authenticated()
        return breeze.get_order_list(
            exchange_code=exchange_code,
            from_date=from_date,
            to_date=to_date,
        )
    except Exception as e:
        return handle_api_error("get_order_book", e)


@mcp.tool()
async def get_trade_book(
    exchange_code: str = "NSE",
    from_date: str = "",
    to_date: str = "",
) -> Dict[str, Any]:
    """Get trade list."""
    try:
        ensure_authenticated()
        return breeze.get_trade_list(
            exchange_code=exchange_code,
            from_date=from_date,
            to_date=to_date,
        )
    except Exception as e:
        return handle_api_error("get_trade_book", e)


@mcp.tool()
async def get_ltp_data(
    stock_code: str,
    exchange_code: str,
    product_type: str = "cash",
    expiry_date: str = "",
    right: str = "",
    strike_price: str = "0",
) -> Dict[str, Any]:
    """Get real-time quotes / LTP for an instrument."""
    try:
        ensure_authenticated()
        return breeze.get_quotes(
            stock_code=stock_code,
            exchange_code=exchange_code,
            expiry_date=expiry_date,
            product_type=product_type,
            right=right or "others",
            strike_price=strike_price,
        )
    except Exception as e:
        return handle_api_error("get_ltp_data", e)


@mcp.tool()
async def get_candle_data(
    stock_code: str,
    exchange_code: str,
    interval: str,
    from_date: str,
    to_date: str,
    product_type: str = "cash",
    expiry_date: str = "",
    right: str = "",
    strike_price: str = "0",
) -> Dict[str, Any]:
    """Get historical OHLCV candles via get_historical_data_v2."""
    try:
        ensure_authenticated()
        return breeze.get_historical_data_v2(
            interval=interval,
            from_date=from_date,
            to_date=to_date,
            stock_code=stock_code,
            exchange_code=exchange_code,
            product_type=product_type,
            expiry_date=expiry_date,
            right=right or "others",
            strike_price=strike_price,
        )
    except Exception as e:
        return handle_api_error("get_candle_data", e)


@mcp.tool()
async def search_scrip(stock_code: str, exchange_code: str = "NSE") -> Dict[str, Any]:
    """Resolve instrument names / codes via get_names."""
    try:
        ensure_authenticated()
        return breeze.get_names(exchange_code=exchange_code, stock_code=stock_code)
    except Exception as e:
        return handle_api_error("search_scrip", e)


@mcp.tool()
async def get_option_chain(
    stock_code: str,
    exchange_code: str = "NFO",
    expiry_date: str = "",
    product_type: str = "options",
    right: str = "",
    strike_price: str = "",
) -> Dict[str, Any]:
    """Get option chain quotes."""
    try:
        ensure_authenticated()
        return breeze.get_option_chain_quotes(
            stock_code=stock_code,
            exchange_code=exchange_code,
            expiry_date=expiry_date,
            product_type=product_type,
            right=right,
            strike_price=strike_price,
        )
    except Exception as e:
        return handle_api_error("get_option_chain", e)


@mcp.tool()
async def estimate_charges(
    exchange_code: str,
    product: str,
    stock_code: str,
    action: str,
    quantity: str,
    price: str,
    order_type: str = "limit",
) -> Dict[str, Any]:
    """Preview order / estimate charges via preview_order when available."""
    try:
        ensure_authenticated()
        return breeze.preview_order(
            stock_code=stock_code,
            exchange_code=exchange_code,
            product=product,
            order_type=order_type,
            price=price,
            action=action,
            quantity=quantity,
        )
    except Exception as e:
        return handle_api_error("estimate_charges", e)


def main() -> None:
    try:
        validate_environment()
        logger.info("ICICI Direct Breeze MCP Server starting...")
        logger.info("DRY RUN MODE: %s", DRY_RUN_MODE)
        logger.info("MAX ORDER QUANTITY: %s", MAX_ORDER_QUANTITY)
        mcp.run(transport="stdio")
    except Exception as e:
        logger.error("Failed to start server: %s", e)
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
