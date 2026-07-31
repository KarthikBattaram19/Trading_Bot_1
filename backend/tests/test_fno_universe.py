"""G11–G12 feed-bound universe from ICICI Direct FONSE scrip master."""

from __future__ import annotations

import io
import zipfile

import pytest

from backend.integrations.icici_direct.instrument_master import (
    InstrumentMaster,
    data_feed_bindings_for,
    reset_instrument_master_for_tests,
)
from backend.services.recommendation_engine import _build_universe, generate_recommendations


def _fonse_zip_bytes() -> bytes:
    """Minimal SecurityMaster.zip with FONSE + NSE members."""
    fonse = (
        "Token,InstrumentName,ShortName,Series,ExpiryDate,StrikePrice,OptionType,"
        "LotSize,TickSize,CompanyName,ExchangeCode\n"
        "40123,OPTIDX,NIFTY,OPTION,28-Mar-2024,22000,CE,25,0.05,NIFTY 50,NIFTY 50\n"
        "30451,OPTSTK,STABAN,OPTION,28-Mar-2024,800,CE,1500,0.05,STATE BANK OF INDIA,SBIN\n"
        "30452,OPTSTK,RELIND,OPTION,28-Mar-2024,2800,PE,250,0.05,RELIANCE INDUSTRIES,RELIANCE\n"
        "30453,FUTSTK,INFTEC,FUTURE,28-Mar-2024,0,XX,400,0.05,INFOSYS LTD,INFY\n"
    )
    nse = (
        'Token, "ShortName", "Series", "CompanyName", "ticksize", "Lotsize"\n'
        '3045, "SBIN", "EQ", "STATE BANK OF INDIA", "0.05", "1"\n'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("FONSEScripMaster.txt", fonse)
        zf.writestr("NSEScripMaster.txt", nse)
        zf.writestr("BSEScripMaster.txt", "Token,ShortName\n1,SKIP\n")
    return buf.getvalue()


def test_load_fonse_lists_all_fno_underlyings():
    master = InstrumentMaster()
    count = master.load_from_zip_bytes(_fonse_zip_bytes())
    assert count >= 4
    underlyings = master.list_fno_underlyings()
    assert underlyings == ["INFY", "NIFTY", "RELIANCE", "SBIN"]
    assert master.stock_code_for_underlying("SBIN") == "STABAN"
    assert master.stock_code_for_underlying("RELIANCE") == "RELIND"
    assert master.feed_bindings_for("SBIN") == {
        "und_price": "icici_direct:NSE:SBIN:quotes",
        "option_chain": "icici_direct:NFO:STABAN:option_chain",
    }
    opts = master.list_options(name="SBIN")
    assert len(opts) == 1
    assert opts[0].stock_code == "STABAN"
    assert opts[0].underlying == "SBIN"


def test_data_feed_bindings_helper():
    assert data_feed_bindings_for("ITC", stock_code="ITC")["und_price"].endswith(":ITC:quotes")


@pytest.mark.asyncio
async def test_recommendation_universe_uses_fno_master(monkeypatch):
    reset_instrument_master_for_tests()
    master = InstrumentMaster()
    master.load_from_zip_bytes(_fonse_zip_bytes())

    from backend.integrations import icici_direct as icici_pkg
    from backend.integrations.icici_direct import instrument_master as imod

    monkeypatch.setattr(imod, "_instrument_master", master)
    monkeypatch.setattr(
        "backend.services.recommendation_engine.get_instrument_master",
        lambda: master,
    )

    async def _no_refresh(self, *, max_age_sec=None):  # noqa: ANN001
        return master.count

    monkeypatch.setattr(
        "backend.integrations.icici_direct.market_data.IciciDirectMarketDataAdapter.ensure_instruments",
        _no_refresh,
    )

    universe, bindings, source = await _build_universe()
    assert source.startswith("icici_direct")
    assert len(universe) == 4
    symbols = {c.symbol for c in universe}
    assert symbols == {"INFY", "NIFTY", "RELIANCE", "SBIN"}
    assert "SBIN" in bindings
    assert bindings["SBIN"]["option_chain"].startswith("icici_direct:NFO:")

    result = await generate_recommendations()
    assert result.universe_scanned == 4
    assert any("FONSEScripMaster" in n for n in result.analysis_notes)
