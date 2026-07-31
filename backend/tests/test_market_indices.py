"""Global index marks for situational bar (NIFTY / India VIX)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.integrations.icici_direct.market_data import (
    IciciDirectMarketDataAdapter,
    reset_market_data_for_tests,
)
from backend.integrations.icici_direct.models import IndexMark


class _FakeClient:
    async def get_quotes(self, **kwargs: Any) -> dict[str, Any]:
        code = str(kwargs.get("stock_code") or "").upper()
        if code == "NIFTY":
            return {
                "Success": [
                    {
                        "ltp": 24500.5,
                        "previous_close": 24400.0,
                        "ltp_percent_change": 0.41,
                        "best_bid_price": 24499.0,
                        "best_ask_price": 24501.0,
                    }
                ]
            }
        if code == "INDVIX":
            return {
                "Success": [
                    {
                        "ltp": 13.25,
                        "previous_close": 13.5,
                        "ltp_percent_change": -1.85,
                    }
                ]
            }
        return {"Success": []}


class _FakeSession:
    async def ensure_session(self) -> _FakeClient:
        return _FakeClient()


@pytest.mark.asyncio
async def test_get_global_indices_from_quotes():
    reset_market_data_for_tests()
    adapter = IciciDirectMarketDataAdapter(session_manager=_FakeSession())  # type: ignore[arg-type]
    marks = await adapter.get_global_indices()
    assert len(marks) == 2
    nifty = marks[0]
    vix = marks[1]
    assert nifty.label == "NIFTY 50"
    assert nifty.ltp == pytest.approx(24500.5)
    assert nifty.change_pct == pytest.approx(0.41)
    assert nifty.stale is False
    assert vix.stock_code == "INDVIX"
    assert vix.ltp == pytest.approx(13.25)
    assert vix.change_pct == pytest.approx(-1.85)


@pytest.mark.asyncio
async def test_get_global_indices_degrades_on_error():
    class BoomSession:
        async def ensure_session(self) -> Any:
            raise RuntimeError("no session")

    adapter = IciciDirectMarketDataAdapter(session_manager=BoomSession())  # type: ignore[arg-type]
    marks = await adapter.get_global_indices()
    assert len(marks) == 2
    assert all(m.stale for m in marks)
    assert all(m.ltp is None for m in marks)
    assert all(m.error for m in marks)


def test_market_indices_endpoint(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    reset_market_data_for_tests()

    async def _fake_indices(self) -> list[IndexMark]:  # noqa: ANN001
        return [
            IndexMark(
                label="NIFTY 50",
                stock_code="NIFTY",
                exchange="NSE",
                ltp=25000.0,
                previous_close=24900.0,
                change_pct=0.4,
                ts=datetime.now(timezone.utc),
                stale=False,
            ),
            IndexMark(
                label="INDIA VIX",
                stock_code="INDVIX",
                exchange="NSE",
                ltp=14.0,
                previous_close=14.2,
                change_pct=-1.41,
                ts=datetime.now(timezone.utc),
                stale=False,
            ),
        ]

    monkeypatch.setattr(
        IciciDirectMarketDataAdapter,
        "get_global_indices",
        _fake_indices,
    )

    from backend.main import app

    client = TestClient(app)
    res = client.get("/api/v1/market/indices")
    assert res.status_code == 200
    body = res.json()
    assert len(body["indices"]) == 2
    assert body["indices"][0]["stock_code"] == "NIFTY"
    assert body["indices"][0]["ltp"] == 25000.0
    assert body["indices"][1]["stock_code"] == "INDVIX"
