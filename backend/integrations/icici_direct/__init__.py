"""ICICI Direct (Breeze API) integration package."""

from backend.integrations.icici_direct.icici_direct_adapter import (
    IciciDirectBrokerAdapter,
    get_icici_direct_adapter,
    reset_icici_direct_adapter_for_tests,
)
from backend.integrations.icici_direct.market_data import (
    IciciDirectMarketDataAdapter,
    get_market_data_adapter,
)
from backend.integrations.icici_direct.session_manager import SessionManager, get_session_manager
from backend.integrations.icici_direct.ws_stream import BreezeMarketStream, decode_breeze_ws_auth

__all__ = [
    "BreezeMarketStream",
    "IciciDirectBrokerAdapter",
    "IciciDirectMarketDataAdapter",
    "SessionManager",
    "decode_breeze_ws_auth",
    "get_icici_direct_adapter",
    "get_market_data_adapter",
    "get_session_manager",
    "reset_icici_direct_adapter_for_tests",
]
