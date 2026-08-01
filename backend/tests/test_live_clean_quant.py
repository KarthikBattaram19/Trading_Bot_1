"""IV history store + earnings calendar + SH-4 available_strategies."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.models.recommendations import MarketNewsSummary, StrategyType
from backend.services.earnings_calendar import EarningsCalendarStore
from backend.services.iv_history_store import IvHistoryStore
from backend.services.strategy_selection import QuantRegimeInputs, select_strategy_sh4


def _news() -> MarketNewsSummary:
    return MarketNewsSummary(
        headline_count=0,
        dominant_sentiment="Neutral",
        dominant_tone="neutral",
        earnings_mentions=0,
        macro_risk_flags=[],
        interpretation="test",
        items=[],
        news_not_blocking=True,
    )


def test_iv_history_append_and_series(tmp_path: Path):
    store = IvHistoryStore(store_path=tmp_path / "iv.json")
    store.append(symbol="SBIN", session_date="2026-08-01", ts_iso="2026-08-01T10:00:00+05:30", iv=0.25)
    store.append(symbol="SBIN", session_date="2026-08-01", ts_iso="2026-08-01T10:05:00+05:30", iv=0.24)
    series = store.series(symbol="SBIN", session_date="2026-08-01")
    assert series == [0.25, 0.24]


def test_earnings_calendar_days_to_earnings(tmp_path: Path):
    path = tmp_path / "earnings.json"
    path.write_text(
        '{"SBIN": ["2026-08-05"], "INFY": ["2026-09-01"]}',
        encoding="utf-8",
    )
    cal = EarningsCalendarStore(store_path=path)
    assert cal.days_to_earnings("SBIN", as_of_date="2026-08-01") == 4
    assert cal.days_to_earnings("MISSING", as_of_date="2026-08-01") is None


def test_sh4_skips_aborted_vega_falls_through_to_simple():
    news = _news()
    quant = QuantRegimeInputs(
        symbol="SBIN",
        iv_annualized=0.20,
        garch_forecast=0.30,
        iv_z_score=-2.5,
        garch_distorted=False,
    )
    # Without restriction → vega
    full = select_strategy_sh4(quant, news)
    assert full.selected_strategy == StrategyType.vega_scalping

    # Vega aborted → fall through to simple_volatility (cheap vol)
    sel = select_strategy_sh4(
        quant,
        news,
        available_strategies={StrategyType.simple_volatility, StrategyType.gamma_scalping},
    )
    assert sel.selected_strategy == StrategyType.simple_volatility
    assert any("strategy_coverage_abort" in r for r in sel.rejected_strategies)


def test_sh4_all_strategies_aborted_returns_blocked():
    news = _news()
    quant = QuantRegimeInputs(
        symbol="SBIN",
        iv_annualized=0.20,
        garch_forecast=0.30,
        iv_z_score=None,
        garch_distorted=False,
    )
    sel = select_strategy_sh4(quant, news, available_strategies=set())
    assert sel.selected_strategy == StrategyType.blocked
    assert "strategy_coverage_abort" in sel.primary_signal


@pytest.mark.asyncio
async def test_enrichment_fail_does_not_load_demo_ranking_universe(monkeypatch, tmp_path):
    """Production ranking must not promote _DEMO_SPECS when live enrichment fails."""
    from backend.integrations.icici_direct.instrument_master import (
        InstrumentMaster,
        reset_instrument_master_for_tests,
    )
    from backend.services import recommendation_engine as eng
    from backend.services.universe_enrichment import EnrichmentStats, UniverseEnricher

    reset_instrument_master_for_tests()
    fonse = (
        "Token,InstrumentName,ShortName,Series,ExpiryDate,StrikePrice,OptionType,"
        "LotSize,TickSize,CompanyName,ExchangeCode\n"
        "40123,OPTIDX,NIFTY,OPTION,28-Mar-2024,22000,CE,25,0.05,NIFTY 50,NIFTY 50\n"
        "30451,OPTSTK,STABAN,OPTION,28-Mar-2024,800,CE,1500,0.05,STATE BANK OF INDIA,SBIN\n"
    )
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("FONSEScripMaster.txt", fonse)
        zf.writestr("NSEScripMaster.txt", 'Token, "ShortName"\n1, "SBIN"\n')
    master = InstrumentMaster()
    master.load_from_zip_bytes(buf.getvalue())

    from backend.integrations.icici_direct import instrument_master as imod

    monkeypatch.setattr(imod, "_instrument_master", master)
    monkeypatch.setattr(eng, "get_instrument_master", lambda: master)

    async def _fail_enrich(self, symbols):  # noqa: ANN001
        return {}, EnrichmentStats(requested=len(symbols), failed=len(symbols))

    monkeypatch.setattr(UniverseEnricher, "enrich_many", _fail_enrich)
    monkeypatch.setattr(
        eng,
        "get_universe_enricher",
        lambda cfg=None: UniverseEnricher(instruments=master, min_interval_ms=1),
    )

    universe, _bindings, source, stats, snapshots = await eng._build_universe()
    assert source.startswith("icici_direct")
    assert universe == []
    assert all(not s.marks_live for s in snapshots)
    assert stats is not None and stats.delivered == 0
    assert not any(c.marks_source == "demo" for c in universe)
