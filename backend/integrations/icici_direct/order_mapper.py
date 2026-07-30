"""Map InternalOrder legs → Breeze place_order payloads."""

from __future__ import annotations

import hashlib
from typing import Any

from backend.integrations.base import InternalOrder, OrderLeg
from backend.integrations.icici_direct.models import PlaceOrderPayload


# Breeze does not permit true market orders — map to aggressive limit (limit).
_ORDER_TYPE_MAP = {
    "market": "limit",
    "limit": "limit",
    "stop": "stoploss",
    "stoploss": "stoploss",
    "stoploss_limit": "stoploss",
    "stoploss_market": "stoploss",
}

_PRODUCT_MAP = {
    "intraday": "margin",
    "mis": "margin",
    "cnc": "cash",
    "delivery": "cash",
    "cash": "cash",
    "carryforward": "futures",
    "nrml": "futures",
    "margin": "margin",
    "futures": "futures",
    "options": "options",
}


class OrderMapper:
    def __init__(
        self,
        *,
        product_default: str = "margin",
    ) -> None:
        self.product_default = product_default

    def map_leg(
        self,
        order: InternalOrder,
        leg: OrderLeg,
        *,
        tradingsymbol: str,
        symboltoken: str,
        exchange: str,
        lotsize: int = 1,
        tick_size: float = 0.05,
        stock_code: str | None = None,
        expiry: str | None = None,
        strike: float | None = None,
        right: str | None = None,
        instrumenttype: str | None = None,
    ) -> PlaceOrderPayload:
        if leg.quantity <= 0:
            raise ValueError("quantity must be positive")
        if lotsize > 1 and leg.quantity % lotsize != 0:
            raise ValueError(
                f"quantity {leg.quantity} must be a multiple of lotsize {lotsize}"
            )

        order_type = _ORDER_TYPE_MAP.get(leg.order_type.lower(), leg.order_type.lower())
        product = _PRODUCT_MAP.get(
            (leg.product or self.product_default).lower(),
            (leg.product or self.product_default).lower(),
        )
        # NFO options default product
        itype = (instrumenttype or "").upper()
        if exchange.upper() == "NFO" and ("OPT" in itype or right):
            product = "options"
        elif exchange.upper() == "NFO" and "FUT" in itype:
            product = "futures"

        side = leg.side.lower()
        if side not in {"buy", "sell"}:
            raise ValueError(f"invalid side: {leg.side}")

        price = "0"
        if order_type == "limit" and leg.limit_price is not None:
            price = _format_price(leg.limit_price, tick_size)
        elif order_type == "limit" and leg.limit_price is None:
            # Aggressive limit placeholder — live path must supply LTP-aware price
            price = "0"

        stoploss = "0"
        if order_type == "stoploss" and leg.stop_price is not None:
            stoploss = _format_price(leg.stop_price, tick_size)

        tag = order.order_tag or _short_tag(order.signal_id or order.internal_order_id)
        code = stock_code or tradingsymbol

        return PlaceOrderPayload(
            stock_code=code,
            exchange_code=exchange.upper(),
            product=product,
            action=side,
            order_type=order_type,
            quantity=str(leg.quantity),
            price=price,
            validity="day",
            stoploss=stoploss,
            expiry_date=expiry,
            right=right,
            strike_price=str(int(strike)) if strike is not None else None,
            user_remark=(tag[:50] if tag else None),
        )

    def map_order_legs(
        self,
        order: InternalOrder,
        resolved: list[dict[str, Any]],
    ) -> list[PlaceOrderPayload]:
        if len(resolved) != len(order.legs):
            raise ValueError("resolved instrument count must match order legs")
        payloads: list[PlaceOrderPayload] = []
        for leg, meta in zip(order.legs, resolved, strict=True):
            payloads.append(
                self.map_leg(
                    order,
                    leg,
                    tradingsymbol=meta["tradingsymbol"],
                    symboltoken=meta["symboltoken"],
                    exchange=meta["exchange"],
                    lotsize=int(meta.get("lotsize") or 1),
                    tick_size=float(meta.get("tick_size") or 0.05),
                    stock_code=meta.get("stock_code"),
                    expiry=meta.get("expiry"),
                    strike=meta.get("strike"),
                    right=meta.get("right"),
                    instrumenttype=meta.get("instrumenttype"),
                )
            )
        return payloads


def _format_price(price: float, tick_size: float) -> str:
    if tick_size <= 0:
        return f"{price:.2f}"
    ticks = round(price / tick_size)
    snapped = ticks * tick_size
    decimals = max(
        0,
        len(str(tick_size).rstrip("0").split(".")[-1]) if "." in str(tick_size) else 0,
    )
    return f"{snapped:.{decimals}f}"


def _short_tag(raw: str) -> str:
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"sig{digest}"
