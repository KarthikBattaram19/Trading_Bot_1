"""Unit tests for backend/paper_sim/structure_builder.py's gamma_scalping
vega-neutral calendar-spread construction (Docs/Trading_Strategies.md Table GS-4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.integrations.icici_direct.models import InstrumentRecord, NormalizedTick
from backend.paper_sim.config import PaperSimConfig
from backend.paper_sim.models import PaperLegRequest, PaperSide
from backend.paper_sim.structure_builder import (
    _append_vega_neutral_far_dated_pair,
    _resolve_far_expiry,
    build_intended_legs_from_entry,
)
from backend.quant.pricing.bsm import BSMInputs, option_greeks
from backend.services.universe_enrichment import _dte_from_expiry


def _expiry_str(days_from_now: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=days_from_now)
    return dt.strftime("%d-%b-%Y")


class _ChainFeed:
    """Minimal feed stub exposing only list_options, for resolver-level tests."""

    def __init__(self, records: list[InstrumentRecord]) -> None:
        self._records = records

    def list_options(self, *, name, exchange="NFO", expiry=None, limit=500):
        rows = [r for r in self._records if (r.name or "").upper() == name.upper()]
        return rows[:limit]


def _opt(expiry: str, strike: float, right: str, token: str) -> InstrumentRecord:
    return InstrumentRecord(
        exchange="NFO",
        tradingsymbol=f"SBIN{token}{right}",
        symboltoken=token,
        name="SBIN",
        expiry=expiry,
        strike=strike,
        lotsize=25,
        instrumenttype="OPTSTK",
    )


def test_resolve_far_expiry_picks_nearest_expiry_clearing_the_gap():
    near = _expiry_str(15)
    just_short = _expiry_str(15 + 27)  # gap 27 < 28, must be skipped
    far = _expiry_str(15 + 30)  # gap 30 >= 28
    farther = _expiry_str(15 + 60)  # gap 60 >= 28, but not nearest
    feed = _ChainFeed(
        [
            _opt(near, 500.0, "CE", "1"),
            _opt(just_short, 500.0, "CE", "2"),
            _opt(far, 500.0, "CE", "3"),
            _opt(farther, 500.0, "CE", "4"),
        ]
    )
    result = _resolve_far_expiry(feed, name="SBIN", near_expiry=near, min_gap_days=28)
    assert result is not None
    resolved_expiry, resolved_dte = result
    assert resolved_expiry == far


def test_resolve_far_expiry_returns_none_when_no_expiry_clears_the_gap():
    near = _expiry_str(15)
    only_short = _expiry_str(15 + 10)
    feed = _ChainFeed([_opt(near, 500.0, "CE", "1"), _opt(only_short, 500.0, "CE", "2")])
    result = _resolve_far_expiry(feed, name="SBIN", near_expiry=near, min_gap_days=28)
    assert result is None


SPOT = 500.0


class _FullFeed(_ChainFeed):
    """Adds resolve/get_ltp so the vega-solve path can run end to end."""

    def __init__(self, records: list[InstrumentRecord], *, underlying_token: str = "U1") -> None:
        super().__init__(records)
        self._underlying = InstrumentRecord(
            exchange="NSE",
            tradingsymbol="SBIN",
            symboltoken=underlying_token,
            name="SBIN",
            lotsize=1,
            instrumenttype="EQ",
        )

    def resolve(self, *, exchange=None, tradingsymbol=None, symboltoken=None):
        if tradingsymbol and tradingsymbol.upper() == "SBIN" and (exchange is None or exchange.upper() == "NSE"):
            return self._underlying
        for rec in self._records:
            if symboltoken and rec.symboltoken == symboltoken:
                return rec
            if tradingsymbol and rec.tradingsymbol.upper() == tradingsymbol.upper():
                return rec
        return None

    async def get_ltp(self, exchange, tradingsymbol, symboltoken=None):
        return NormalizedTick(
            exchange=exchange,
            symbol=tradingsymbol,
            provider_symbol_id=symboltoken or "U1",
            ltp=SPOT,
            ts=datetime.now(timezone.utc),
        )


def _entry_leg(expiry: str) -> tuple[PaperLegRequest, InstrumentRecord]:
    record = _opt(expiry, SPOT, "CE", "N1")
    leg = PaperLegRequest(
        symbol=record.tradingsymbol,
        side=PaperSide.buy,
        quantity=record.lotsize,
        exchange="NFO",
        symbol_token=record.symboltoken,
        option_type="CE",
        strike=SPOT,
        expiry=expiry,
    )
    return leg, record


@pytest.mark.asyncio
async def test_append_vega_neutral_far_dated_pair_appends_sell_legs():
    near_expiry = _expiry_str(15)
    far_expiry = _expiry_str(15 + 35)
    feed = _FullFeed(
        [
            _opt(near_expiry, SPOT, "CE", "N1"),
            _opt(near_expiry, SPOT, "PE", "N2"),
            _opt(far_expiry, SPOT, "CE", "F1"),
            _opt(far_expiry, SPOT, "PE", "F2"),
        ]
    )
    first, record = _entry_leg(near_expiry)
    intended: list[PaperLegRequest] = [first]

    await _append_vega_neutral_far_dated_pair(
        intended,
        feed=feed,
        first=first,
        record=record,
        underlying="SBIN",
        qty=5 * record.lotsize,
        paper_sim_config=PaperSimConfig(),
        min_gap_days=28,
    )

    assert len(intended) == 3
    far_legs = intended[1:]
    assert {lg.option_type for lg in far_legs} == {"CE", "PE"}
    for lg in far_legs:
        assert lg.side == PaperSide.sell
        assert lg.expiry == far_expiry
        assert lg.strike == SPOT

    # The two far legs must carry identical quantity (GS-4 step 4: mirror, not re-solve).
    assert far_legs[0].quantity == far_legs[1].quantity

    # Quantity must actually be vega-solved, not a 1:1 copy of the near leg's
    # quantity — same spot/strike/rate/yield/vol at two different DTEs always
    # gives a different vega, so a correct solve can't land back on 1:1 here.
    assert far_legs[0].quantity != first.quantity


@pytest.mark.asyncio
async def test_append_vega_neutral_far_dated_pair_skips_when_no_far_expiry():
    near_expiry = _expiry_str(15)
    feed = _FullFeed([_opt(near_expiry, SPOT, "CE", "N1"), _opt(near_expiry, SPOT, "PE", "N2")])
    first, record = _entry_leg(near_expiry)
    intended: list[PaperLegRequest] = [first]

    await _append_vega_neutral_far_dated_pair(
        intended,
        feed=feed,
        first=first,
        record=record,
        underlying="SBIN",
        qty=first.quantity,
        paper_sim_config=PaperSimConfig(),
        min_gap_days=28,
    )

    assert intended == [first]


@pytest.mark.asyncio
async def test_append_vega_neutral_far_dated_pair_skips_on_degenerate_vega(monkeypatch):
    """Even when a far expiry clears the min-gap check, a degenerate (~0)
    far vega must still fail closed to no-append, not a division blow-up
    or a nonsense quantity."""
    near_expiry = _expiry_str(15)
    far_expiry = _expiry_str(15 + 35)
    feed = _FullFeed(
        [
            _opt(near_expiry, SPOT, "CE", "N1"),
            _opt(near_expiry, SPOT, "PE", "N2"),
            _opt(far_expiry, SPOT, "CE", "F1"),
            _opt(far_expiry, SPOT, "PE", "F2"),
        ]
    )
    first, record = _entry_leg(near_expiry)
    intended: list[PaperLegRequest] = [first]

    import backend.paper_sim.structure_builder as sb

    real_option_greeks = sb.option_greeks

    def _fake_option_greeks(inputs):
        result = real_option_greeks(inputs)
        if inputs.time_years * 365.0 > 40:  # the far leg
            result = dict(result, vega=0.0)
        return result

    monkeypatch.setattr(sb, "option_greeks", _fake_option_greeks)

    await _append_vega_neutral_far_dated_pair(
        intended,
        feed=feed,
        first=first,
        record=record,
        underlying="SBIN",
        qty=first.quantity,
        paper_sim_config=PaperSimConfig(),
        min_gap_days=28,
    )

    assert intended == [first]


@pytest.mark.asyncio
async def test_append_vega_neutral_far_dated_pair_reduces_net_vega():
    """GS-4 step 5: the solved structure's net vega must be materially
    smaller than the unhedged near-only straddle's vega — proves the solve
    actually neutralizes vega, not just that it runs without error."""
    near_expiry = _expiry_str(15)
    far_expiry = _expiry_str(15 + 35)
    feed = _FullFeed(
        [
            _opt(near_expiry, SPOT, "CE", "N1"),
            _opt(near_expiry, SPOT, "PE", "N2"),
            _opt(far_expiry, SPOT, "CE", "F1"),
            _opt(far_expiry, SPOT, "PE", "F2"),
        ]
    )
    first, record = _entry_leg(near_expiry)
    intended: list[PaperLegRequest] = [first]
    cfg = PaperSimConfig()

    await _append_vega_neutral_far_dated_pair(
        intended,
        feed=feed,
        first=first,
        record=record,
        underlying="SBIN",
        qty=5 * record.lotsize,
        paper_sim_config=cfg,
        min_gap_days=28,
    )
    assert len(intended) == 3  # entry + 2 far legs

    near_dte = _dte_from_expiry(near_expiry)
    far_dte = _dte_from_expiry(far_expiry)

    def _vega(days: int, option_type: str) -> float:
        inputs = BSMInputs.from_api(
            und_price=SPOT,
            strike=SPOT,
            days_to_expiry=days,
            int_rate=cfg.risk_free_rate_pct,
            div_yield=cfg.dividend_yield_pct,
            volatility=cfg.default_iv_annual_pct,
            option_type=option_type,
        )
        return option_greeks(inputs)["vega"]

    near_lotsize = record.lotsize
    near_contracts = 5
    far_contracts = intended[1].quantity // record.lotsize

    unhedged_vega = near_contracts * (_vega(near_dte, "call") + _vega(near_dte, "put"))
    net_vega = unhedged_vega - far_contracts * (_vega(far_dte, "call") + _vega(far_dte, "put"))

    assert abs(net_vega) < abs(unhedged_vega) * 0.25


@pytest.mark.asyncio
async def test_build_intended_legs_gamma_scalping_produces_four_leg_calendar():
    near_expiry = _expiry_str(15)
    far_expiry = _expiry_str(15 + 35)
    feed = _FullFeed(
        [
            _opt(near_expiry, SPOT, "CE", "N1"),
            _opt(near_expiry, SPOT, "PE", "N2"),
            _opt(far_expiry, SPOT, "CE", "F1"),
            _opt(far_expiry, SPOT, "PE", "F2"),
        ]
    )
    first, _record = _entry_leg(near_expiry)

    intended = await build_intended_legs_from_entry(
        strategy_tag="gamma_scalping",
        underlying="SBIN",
        entry_legs=[first],
        feed=feed,
        paper_sim_config=PaperSimConfig(),
    )

    assert len(intended) == 4
    by_side = {PaperSide.buy: 0, PaperSide.sell: 0}
    for lg in intended:
        by_side[lg.side] += 1
    assert by_side[PaperSide.buy] == 2
    assert by_side[PaperSide.sell] == 2
    sell_expiries = {lg.expiry for lg in intended if lg.side == PaperSide.sell}
    assert sell_expiries == {far_expiry}
    buy_expiries = {lg.expiry for lg in intended if lg.side == PaperSide.buy}
    assert buy_expiries == {near_expiry}


@pytest.mark.asyncio
async def test_build_intended_legs_gamma_scalping_falls_back_to_straddle_only():
    near_expiry = _expiry_str(15)
    feed = _FullFeed([_opt(near_expiry, SPOT, "CE", "N1"), _opt(near_expiry, SPOT, "PE", "N2")])
    first, _record = _entry_leg(near_expiry)

    intended = await build_intended_legs_from_entry(
        strategy_tag="gamma_scalping",
        underlying="SBIN",
        entry_legs=[first],
        feed=feed,
        paper_sim_config=PaperSimConfig(),
    )

    assert len(intended) == 2
    assert all(lg.side == PaperSide.buy for lg in intended)
