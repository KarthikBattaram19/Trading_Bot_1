"""In-house options paper trading simulator.

This package is intentionally separate from ICICI Direct live execution
(`backend.integrations.icici_direct`). It may use ICICI Direct only as a
market-data feed (LTP / instrument master). It never calls place_order.
"""

from backend.paper_sim.service import get_paper_engine

__all__ = ["get_paper_engine"]
