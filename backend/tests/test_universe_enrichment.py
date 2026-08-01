"""Unit tests for live LTP + option-chain universe enrichment."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from backend.integrations.icici_direct.instrument_master import InstrumentMaster
from backend.services.universe_enrichment import (
    UniverseEnricher,
    expiry_to_breeze_iso,
    parse_atm_from_chain,
    reset_universe_enricher_for_tests,
    select_preferred_expiry,
)


def _future_expiry(days: int = 21) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%d-%b-%Y")


def _fonse_zip(expiry: str) -> bytes:
    fonse = (
        "Token,InstrumentName,ShortName,Series,ExpiryDate,StrikePrice,OptionType,"
        "LotSize,TickSize,CompanyName,ExchangeCode\n"
        f"40123,OPTIDX,NIFTY,OPTION,{expiry},22000,CE,25,0.05,NIFTY 50,NIFTY 50\n"
        f"40124,OPTIDX,NIFTY,OPTION,{expiry},22000,PE,25,0.05,NIFTY 50,NIFTY 50\n"
        f"30451,OPTSTK,STABAN,OPTION,{expiry},800,CE,1500,0.05,STATE BANK OF INDIA,SBIN\n"
        f"30452,OPTSTK,STABAN,OPTION,{expiry},800,PE,1500,0.05,STATE BANK OF INDIA,SBIN\n"
        f"30453,OPTSTK,RELIND,OPTION,{expiry},2800,CE,250,0.05,RELIANCE INDUSTRIES,RELIANCE\n"
        f"30454,OPTSTK,RELIND,OPTION,{expiry},2800,PE,250,0.05,RELIANCE INDUSTRIES,RELIANCE\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("FONSEScripMaster.txt", fonse)
        zf.writestr("NSEScripMaster.txt", "Token,ShortName,Series\n1,SBIN,EQ\n")
    return buf.getvalue()


def test_expiry_to_breeze_iso():
    assert expiry_to_breeze_iso("28-Aug-2026") == "2026-08-28T06:00:00.000Z"


def test_parse_atm_from_chain_uses_spot_and_liquidity():
    rows = [
        {
            "strike_price": 800.0,
            "right": "Call",
            "ltp": 20.0,
            "best_bid_price": 19.5,
            "best_offer_price": 20.5,
            "total_quantity_traded": "5000",
            "open_interest": 25000,
            "spot_price": "802",
            "stock_code": "STABAN",
        },
        {
            "strike_price": 800.0,
            "right": "Put",
            "ltp": 18.0,
            "best_bid_price": 17.8,
            "best_offer_price": 18.2,
            "total_quantity_traded": "4000",
            "open_interest": 22000,
            "spot_price": "802",
            "stock_code": "STABAN",
        },
        {
            "strike_price": 850.0,
            "right": "Call",
            "ltp": 5.0,
            "best_bid_price": 4.5,
            "best_offer_price": 5.5,
            "total_quantity_traded": "100",
            "open_interest": 500,
            "spot_price": "802",
        },
    ]
    marks = parse_atm_from_chain(rows, spot_hint=None, expiry_raw=_future_expiry(21))
    assert marks is not None
    assert marks.und_price == 802.0
    assert marks.atm_strike == 800.0
    assert marks.atm_premium_inr == pytest.approx(20.0)  # max(CE mid, PE mid)
    assert marks.volume == 4000  # min CE/PE
    assert marks.open_interest == 22000
    assert marks.spread_pct == pytest.approx(5.0)  # CE (20.5-19.5)/20
    assert marks.dte >= 20
    assert marks.iv_annualized > 0


def test_select_preferred_expiry_in_window():
    expiry = _future_expiry(21)
    master = InstrumentMaster()
    master.load_from_zip_bytes(_fonse_zip(expiry))
    chosen = select_preferred_expiry(master, "SBIN", min_dte=10, max_dte=30)
    assert chosen is not None
    assert chosen[0] == expiry
    assert 10 <= chosen[1] <= 30


@pytest.mark.asyncio
async def test_enrich_many_fetches_spot_and_chain(monkeypatch):
    reset_universe_enricher_for_tests()
    expiry = _future_expiry(21)
    master = InstrumentMaster()
    master.load_from_zip_bytes(_fonse_zip(expiry))

    class _FakeTick:
        def __init__(self, ltp: float) -> None:
            self.ltp = ltp

    class _FakeMD:
        def __init__(self) -> None:
            self.spot_calls = 0
            self.chain_calls = 0

            class _Sess:
                async def ensure_session(self):
                    return object()

            self.session_manager = _Sess()

        async def get_ltp(self, exchange: str, tradingsymbol: str, symboltoken=None):  # noqa: ANN001
            self.spot_calls += 1
            return _FakeTick(812.0 if tradingsymbol == "SBIN" else 24500.0)

        async def get_option_chain(self, **kwargs):  # noqa: ANN003
            self.chain_calls += 1
            code = kwargs["stock_code"]
            spot = "812" if code == "STABAN" else "24500"
            strike = 800.0 if code == "STABAN" else 24500.0
            return [
                {
                    "strike_price": strike,
                    "right": "Call",
                    "ltp": 95.0,
                    "best_bid_price": 94.0,
                    "best_offer_price": 96.0,
                    "total_quantity_traded": "12000",
                    "open_interest": 30000,
                    "spot_price": spot,
                    "stock_code": code,
                },
                {
                    "strike_price": strike,
                    "right": "Put",
                    "ltp": 90.0,
                    "best_bid_price": 89.0,
                    "best_offer_price": 91.0,
                    "total_quantity_traded": "11000",
                    "open_interest": 28000,
                    "spot_price": spot,
                    "stock_code": code,
                },
            ]

    md = _FakeMD()
    enricher = UniverseEnricher(
        market_data=md,  # type: ignore[arg-type]
        instruments=master,
        cache_ttl_sec=60,
        max_concurrency=2,
        min_interval_ms=1,
        fetch_spot_ltp=True,
    )
    out, stats = await enricher.enrich_many(["SBIN", "NIFTY"])
    assert set(out) == {"SBIN", "NIFTY"}
    assert out["SBIN"].und_price == 812.0
    assert out["SBIN"].atm_premium_inr == pytest.approx(95.0)
    assert out["SBIN"].volume == 11000
    assert stats.delivered == 2
    assert stats.failed == 0
    assert md.spot_calls == 2
    assert md.chain_calls == 2

    # Second pass should hit cache (no extra REST).
    out2, stats2 = await enricher.enrich_many(["SBIN", "NIFTY"])
    assert stats2.cache_hits == 2
    assert stats2.spot_calls == 0
    assert md.spot_calls == 2
    assert set(out2) == {"SBIN", "NIFTY"}


@pytest.mark.asyncio
async def test_build_universe_prefers_live_marks(monkeypatch):
    reset_universe_enricher_for_tests()
    expiry = _future_expiry(21)
    master = InstrumentMaster()
    master.load_from_zip_bytes(_fonse_zip(expiry))

    from backend.integrations.icici_direct import instrument_master as imod
    from backend.services import recommendation_engine as eng
    from backend.services.universe_enrichment import LiveMarks

    monkeypatch.setattr(imod, "_instrument_master", master)
    monkeypatch.setattr(eng, "get_instrument_master", lambda: master)

    async def _fake_enrich_many(self, symbols):  # noqa: ANN001
        marks = {
            s.upper(): LiveMarks(
                symbol=s.upper(),
                und_price=100.0 + i,
                atm_premium_inr=50.0,
                volume=5000,
                open_interest=20000,
                spread_pct=1.0,
                dte=21,
                iv_annualized=0.25,
            )
            for i, s in enumerate(symbols)
        }
        from backend.services.universe_enrichment import EnrichmentStats

        return marks, EnrichmentStats(requested=len(symbols), live_ok=len(symbols))

    monkeypatch.setattr(UniverseEnricher, "enrich_many", _fake_enrich_many)
    monkeypatch.setattr(
        "backend.services.recommendation_engine.get_universe_enricher",
        lambda cfg=None: UniverseEnricher(instruments=master, min_interval_ms=1),
    )

    async def _fake_daily(symbol, stock_code=None, lookback_days=60, as_of_date=None, adapter=None):
        return [100.0 * (1.0 + 0.001 * ((i % 5) - 2)) for i in range(40)]

    async def _fake_rv(symbol, stock_code=None, as_of_date=None, adapter=None):
        return 0.02

    monkeypatch.setattr(
        "backend.services.recommendation_engine.fetch_daily_closes",
        _fake_daily,
    )
    monkeypatch.setattr(
        "backend.services.recommendation_engine.fetch_realized_vol_intraday",
        _fake_rv,
    )
    # Relax coverage for tiny fixture universes
    real_load = eng._load_config

    def _cfg():
        cfg = real_load()
        cfg["strategy_coverage"] = {
            "min_coverage_ratio": 0.5,
            "min_eligible_symbols": 1,
            "abort_unavailable_strategies": True,
        }
        return cfg

    monkeypatch.setattr(eng, "_load_config", _cfg)

    universe, bindings, source, stats, snapshots = await eng._build_universe()
    assert source.startswith("icici_direct")
    assert len(universe) == 3  # NIFTY, RELIANCE, SBIN
    assert all(c.marks_source == "live" for c in universe)
    assert len(snapshots) == 3
    assert stats is not None
    assert stats.live_ok == 3
