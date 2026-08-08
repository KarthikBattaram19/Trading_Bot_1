"""Live LTP + option-chain enrichment for the G11–G12 recommendation universe.

Fetches ICICI Direct Breeze spot quotes and GetOptionChain for each FNO
underlying, paced under the vendor ~100 calls/min envelope. Results are TTL-
cached so recommendation refresh cycles reuse fresh marks.
"""

from __future__ import annotations

import asyncio
import logging
import math
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable
from zoneinfo import ZoneInfo

from backend.integrations.icici_direct.instrument_master import (
    InstrumentMaster,
    get_instrument_master,
)
from backend.integrations.icici_direct.market_data import (
    IciciDirectMarketDataAdapter,
    get_market_data_adapter,
)
from backend.services.breeze_pacing import AsyncRateLimiter
from backend.services.atm_liquidity_history import (
    DEFAULT_STORE_PATH as ATM_HISTORY_STORE_PATH,
    AtmLiquidityHistoryStore,
)
logger = logging.getLogger(__name__)

_INDEX_UNDERLYINGS = frozenset(
    {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
)

# Breeze index cash stock_codes (NSE quotes).
_INDEX_SPOT_STOCK_CODE: dict[str, str] = {
    "NIFTY": "NIFTY",
    "BANKNIFTY": "CNXBAN",
    "FINNIFTY": "NIFFIN",
    "MIDCPNIFTY": "NIFSEL",
    "NIFTYNXT50": "NIFNEX",
}

# Strikes each side of ATM used as the same-session liquidity peer group
# (§3.2 chain-relative fallback for expiries with < atm_history_min_days of
# logged history — see backend/services/atm_liquidity.py).
NEAR_ATM_PEER_WINDOW = 3


@dataclass
class EnrichmentStats:
    requested: int = 0
    live_ok: int = 0
    cache_hits: int = 0
    failed: int = 0
    spot_calls: int = 0
    chain_calls: int = 0
    elapsed_sec: float = 0.0
    errors: list[str] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @property
    def delivered(self) -> int:
        return self.live_ok + self.cache_hits

    def note_lines(self) -> list[str]:
        lines = [
            (
                f"Live marks: {self.delivered}/{self.requested} underlyings enriched "
                f"(fresh={self.live_ok}, cache_hits={self.cache_hits}, failed={self.failed}, "
                f"spot_calls={self.spot_calls}, chain_calls={self.chain_calls}, "
                f"{self.elapsed_sec:.1f}s)."
            )
        ]
        if self.errors:
            sample = "; ".join(self.errors[:5])
            more = f" (+{len(self.errors) - 5} more)" if len(self.errors) > 5 else ""
            lines.append(f"Live enrichment errors (sample): {sample}{more}")
        return lines

    async def add_error(self, msg: str) -> None:
        async with self._lock:
            self.errors.append(msg)

    async def incr(self, field_name: str, n: int = 1) -> None:
        async with self._lock:
            setattr(self, field_name, getattr(self, field_name) + n)


@dataclass
class LiveMarks:
    """Parsed live fields for one G11 underlying."""

    symbol: str
    und_price: float
    atm_premium_inr: float
    volume: int
    open_interest: int
    spread_pct: float
    dte: int
    iv_annualized: float
    atm_strike: float | None = None
    expiry: str | None = None
    stock_code: str | None = None
    near_atm_volume_median: float | None = None
    near_atm_oi_median: float | None = None


@dataclass
class _CacheEntry:
    marks: LiveMarks
    stored_at: float


def _parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _expiry_to_date(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    for fmt in (
        "%d-%b-%Y",
        "%d-%b-%y",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%Y-%m-%dT%H:%M:%S.000Z",
        "%Y-%m-%dT%H:%M:%SZ",
    ):
        try:
            return datetime.strptime(text[: len(fmt) + 8], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # ISO with extras
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def expiry_to_breeze_iso(raw: str) -> str | None:
    """Convert master / chain expiry to Breeze optionchain ISO timestamp."""
    dt = _expiry_to_date(raw)
    if dt is None:
        return None
    # Vendor samples use 06:00:00.000Z on the expiry calendar day.
    return dt.strftime("%Y-%m-%d") + "T06:00:00.000Z"


def _dte_from_expiry(raw: str, *, now: datetime | None = None) -> int:
    dt = _expiry_to_date(raw)
    if dt is None:
        return 0
    now = now or datetime.now(timezone.utc)
    delta = dt.date() - now.astimezone(timezone.utc).date()
    return max(0, delta.days)


def select_preferred_expiry(
    master: InstrumentMaster,
    symbol: str,
    *,
    min_dte: int = 10,
    max_dte: int = 30,
) -> tuple[str, int] | None:
    """Pick nearest NFO option expiry in the retail DTE window (else ≥ min_dte)."""
    records = master.list_options(name=symbol, exchange="NFO", limit=5000)
    expiries: dict[str, int] = {}
    for rec in records:
        if not rec.expiry:
            continue
        dte = _dte_from_expiry(rec.expiry)
        # Keep first-seen raw expiry string for each unique day key.
        key = rec.expiry
        if key not in expiries or dte < expiries[key]:
            expiries[key] = dte

    if not expiries:
        return None

    in_window = [(exp, dte) for exp, dte in expiries.items() if min_dte <= dte <= max_dte]
    if in_window:
        in_window.sort(key=lambda x: (x[1], x[0]))
        return in_window[0]

    future = [(exp, dte) for exp, dte in expiries.items() if dte >= min_dte]
    if future:
        future.sort(key=lambda x: (x[1], x[0]))
        return future[0]

    # Fall back to any future/zero DTE expiry (nearest).
    all_sorted = sorted(expiries.items(), key=lambda x: (x[1], x[0]))
    return all_sorted[0]


def _mid(bid: float | None, ask: float | None, ltp: float | None) -> float | None:
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    if ltp is not None and ltp > 0:
        return ltp
    if ask is not None and ask > 0:
        return ask
    if bid is not None and bid > 0:
        return bid
    return None


def _spread_pct(bid: float | None, ask: float | None, mid: float | None) -> float:
    if bid is None or ask is None or mid is None or mid <= 0:
        return 99.0
    if ask < bid:
        return 99.0
    return ((ask - bid) / mid) * 100.0


def _right_key(raw: Any) -> str | None:
    text = str(raw or "").strip().upper()
    if text in {"CE", "CALL", "C"}:
        return "CE"
    if text in {"PE", "PUT", "P"}:
        return "PE"
    return None


def estimate_atm_iv(
    *,
    premium: float,
    spot: float,
    dte: int,
) -> float:
    """Rough ATM IV (annualized decimal) via Brenner–Subrahmanyam approximation."""
    if premium <= 0 or spot <= 0 or dte <= 0:
        return 0.0
    t = max(dte, 1) / 365.0
    # σ ≈ √(2π/T) × (C/S)
    iv = math.sqrt(2.0 * math.pi / t) * (premium / spot)
    return float(min(max(iv, 0.01), 3.0))


def _leg_metrics(leg: dict[str, Any] | None) -> tuple[float | None, int, int, float]:
    if not leg:
        return None, 0, 0, 99.0
    bid = _parse_float(leg.get("best_bid_price") or leg.get("bid"))
    ask = _parse_float(leg.get("best_offer_price") or leg.get("ask") or leg.get("best_ask_price"))
    ltp = _parse_float(leg.get("ltp") or leg.get("LTP"))
    mid = _mid(bid, ask, ltp)
    vol = _parse_int(leg.get("total_quantity_traded") or leg.get("volume") or leg.get("ltq"))
    oi = _parse_int(leg.get("open_interest") or leg.get("oi"))
    return mid, vol, oi, _spread_pct(bid, ask, mid)


def _strike_vol_oi(sides: dict[str, dict[str, Any]]) -> tuple[int, int]:
    """Conservative min(CE, PE) volume/OI for one strike — same blend rule as the ATM strike."""
    _, ce_vol, ce_oi, _ = _leg_metrics(sides.get("CE"))
    _, pe_vol, pe_oi, _ = _leg_metrics(sides.get("PE"))
    if ce_vol > 0 and pe_vol > 0:
        volume = min(ce_vol, pe_vol)
    elif ce_vol > 0:
        volume = ce_vol
    elif pe_vol > 0:
        volume = pe_vol
    else:
        volume = 0
    open_interest = min(ce_oi, pe_oi) if (ce_oi > 0 and pe_oi > 0) else max(ce_oi, pe_oi)
    return volume, open_interest


def _near_atm_peer_medians(
    by_strike: dict[float, dict[str, dict[str, Any]]],
    atm_strike: float,
    *,
    window: int = NEAR_ATM_PEER_WINDOW,
) -> tuple[float | None, float | None]:
    """Same-session chain-relative peer group: the `window` closest strikes on
    each side of ATM (ATM itself excluded — this is a peer comparison, not a
    self-comparison). Used as the cold-start liquidity fallback when an
    expiry has too little history for the temporal T13b/T14b average (§3.2)."""
    other_strikes = sorted(
        (k for k in by_strike if k != atm_strike),
        key=lambda k: abs(k - atm_strike),
    )[: 2 * window]
    vols: list[int] = []
    ois: list[int] = []
    for strike in other_strikes:
        vol, oi = _strike_vol_oi(by_strike[strike])
        if vol > 0:
            vols.append(vol)
        if oi > 0:
            ois.append(oi)
    vol_median = float(statistics.median(vols)) if vols else None
    oi_median = float(statistics.median(ois)) if ois else None
    return vol_median, oi_median


def parse_atm_from_chain(
    rows: list[dict[str, Any]],
    *,
    spot_hint: float | None,
    expiry_raw: str,
) -> LiveMarks | None:
    """Extract ATM CE/PE liquidity + premium metrics from Breeze optionchain rows."""
    if not rows:
        return None

    spot = spot_hint
    for row in rows:
        sp = _parse_float(row.get("spot_price") or row.get("spot") or row.get("underlying_value"))
        if sp is not None and sp > 0:
            spot = sp
            break
    if spot is None or spot <= 0:
        return None

    by_strike: dict[float, dict[str, dict[str, Any]]] = {}
    for row in rows:
        strike = _parse_float(row.get("strike_price") or row.get("strike"))
        right = _right_key(row.get("right") or row.get("option_type"))
        if strike is None or right is None:
            continue
        by_strike.setdefault(strike, {})[right] = row

    if not by_strike:
        return None

    atm_strike = min(by_strike.keys(), key=lambda k: (abs(k - spot), k))
    sides = by_strike[atm_strike]
    ce = sides.get("CE")
    pe = sides.get("PE")
    if ce is None and pe is None:
        return None

    ce_mid, ce_vol, ce_oi, ce_spread = _leg_metrics(ce)
    pe_mid, pe_vol, pe_oi, pe_spread = _leg_metrics(pe)

    # T1 uses ATM option premium — prefer call mid (long-entry conservative ask if only one side).
    premium_candidates = [p for p in (ce_mid, pe_mid) if p is not None and p > 0]
    if not premium_candidates:
        return None
    atm_premium = max(premium_candidates) if (ce_mid and pe_mid) else premium_candidates[0]
    # Conservative liquidity: both legs must clear retail floors → use min.
    volume = min(v for v in (ce_vol, pe_vol) if v > 0) if (ce_vol > 0 or pe_vol > 0) else 0
    if ce_vol > 0 and pe_vol > 0:
        volume = min(ce_vol, pe_vol)
    elif ce_vol > 0:
        volume = ce_vol
    elif pe_vol > 0:
        volume = pe_vol

    if ce_oi > 0 and pe_oi > 0:
        open_interest = min(ce_oi, pe_oi)
    else:
        open_interest = max(ce_oi, pe_oi)

    spreads = [s for s in (ce_spread, pe_spread) if s < 99.0]
    spread_pct = max(spreads) if spreads else 99.0

    dte = _dte_from_expiry(expiry_raw)
    # Prefer vendor IV when present on either leg.
    iv = 0.0
    for leg in (ce, pe):
        if not leg:
            continue
        raw_iv = _parse_float(
            leg.get("implied_volatility")
            or leg.get("iv")
            or leg.get("annual_iv")
            or leg.get("volatility")
        )
        if raw_iv is None:
            continue
        # Breeze often returns IV in percent.
        iv = raw_iv / 100.0 if raw_iv > 3.0 else raw_iv
        break
    if iv <= 0:
        iv = estimate_atm_iv(premium=float(atm_premium), spot=float(spot), dte=dte)

    symbol = str(
        (ce or pe or {}).get("stock_code")
        or ""
    ).upper()

    near_atm_volume_median, near_atm_oi_median = _near_atm_peer_medians(by_strike, atm_strike)

    marks = LiveMarks(
        symbol=symbol,
        und_price=float(spot),
        atm_premium_inr=float(atm_premium),
        volume=int(volume),
        open_interest=int(open_interest),
        spread_pct=float(spread_pct),
        dte=int(dte),
        iv_annualized=float(iv),
        atm_strike=float(atm_strike),
        expiry=expiry_raw,
        near_atm_volume_median=near_atm_volume_median,
        near_atm_oi_median=near_atm_oi_median,
    )
    _snapshot_atm_liquidity(marks, ce_vol=ce_vol, pe_vol=pe_vol, ce_oi=ce_oi, pe_oi=pe_oi)
    return marks


def _session_date_ist() -> str:
    try:
        return datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc).date().isoformat()


def _snapshot_atm_liquidity(
    marks: LiveMarks,
    *,
    ce_vol: int,
    pe_vol: int,
    ce_oi: int,
    pe_oi: int,
) -> None:
    if not marks.symbol or not marks.expiry:
        return
    if ce_vol <= 0 or pe_vol <= 0 or ce_oi <= 0 or pe_oi <= 0:
        return
    store = AtmLiquidityHistoryStore(ATM_HISTORY_STORE_PATH)
    store.upsert_snapshot(
        underlying=marks.symbol,
        expiry_key=str(marks.expiry),
        session_date=_session_date_ist(),
        atm_strike=float(marks.atm_strike or 0.0),
        atm_volume=int(min(ce_vol, pe_vol)),
        atm_oi=int(min(ce_oi, pe_oi)),
    )
    store.prune(keep_days=60)


class UniverseEnricher:
    """Enrich G11 underlyings with live ICICI Direct LTP + option chain."""

    def __init__(
        self,
        *,
        market_data: IciciDirectMarketDataAdapter | None = None,
        instruments: InstrumentMaster | None = None,
        cache_ttl_sec: float = 90.0,
        max_concurrency: int = 4,
        min_interval_ms: float = 700.0,
        fetch_spot_ltp: bool = True,
        prefer_dte_min: int = 10,
        prefer_dte_max: int = 30,
    ) -> None:
        self._md = market_data or get_market_data_adapter()
        self._instruments = instruments or get_instrument_master()
        self.cache_ttl_sec = float(cache_ttl_sec)
        self.max_concurrency = max(1, int(max_concurrency))
        self.fetch_spot_ltp = bool(fetch_spot_ltp)
        self.prefer_dte_min = int(prefer_dte_min)
        self.prefer_dte_max = int(prefer_dte_max)
        self._limiter = AsyncRateLimiter(min_interval_ms)
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()

    def clear_cache(self) -> None:
        self._cache.clear()

    def _cache_get(self, symbol: str) -> LiveMarks | None:
        entry = self._cache.get(symbol.upper())
        if entry is None:
            return None
        if (time.monotonic() - entry.stored_at) > self.cache_ttl_sec:
            return None
        return entry.marks

    def _cache_put(self, marks: LiveMarks) -> None:
        self._cache[marks.symbol.upper()] = _CacheEntry(marks=marks, stored_at=time.monotonic())

    async def _paced(self, coro: Awaitable[Any]) -> Any:
        await self._limiter.acquire()
        return await coro

    async def _spot_ltp(
        self,
        symbol: str,
        stats: EnrichmentStats,
        stock_code: str | None = None,
    ) -> float | None:
        if not self.fetch_spot_ltp:
            return None
        und = symbol.upper()
        # Indices: Breeze cash stock_codes first (CNXBAN, NIFFIN, …). Display
        # names like BANKNIFTY burn rate budget and often 503 / "not available".
        if und in _INDEX_UNDERLYINGS:
            primary = _INDEX_SPOT_STOCK_CODE.get(und, und)
            fallbacks = [primary]
            if und != primary:
                fallbacks.append(und)
        else:
            # Equities: the resolved ICICI stock_code (already used for the
            # option-chain fetch) first — many Breeze short codes differ from
            # the NSE tradingsymbol. Fall back to the raw symbol if unmapped.
            primary = (stock_code or und).upper()
            fallbacks = [primary]
            if und != primary:
                fallbacks.append(und)

        for code in fallbacks:
            try:
                tick = await self._paced(self._md.get_ltp("NSE", code))
                await stats.incr("spot_calls")
                if tick.ltp and tick.ltp > 0:
                    return float(tick.ltp)
            except Exception as exc:  # noqa: BLE001
                label = (
                    f"{und} spot"
                    if code == fallbacks[0]
                    else f"{und} spot/{code}"
                )
                await stats.add_error(f"{label}: {exc}")
                logger.debug("Spot LTP failed for %s (%s): %s", und, code, exc)
        return None

    async def _fetch_option_chain_sides(
        self,
        *,
        stock_code: str,
        expiry_iso: str,
        stats: EnrichmentStats,
    ) -> list[dict[str, Any]]:
        """Fetch call + put sides; Breeze requires a non-empty right or strike."""
        merged: list[dict[str, Any]] = []
        last_exc: Exception | None = None
        for right in ("call", "put"):
            rows: list[dict[str, Any]] = []
            for product_type in ("options", "Options"):
                try:
                    rows = await self._paced(
                        self._md.get_option_chain(
                            stock_code=stock_code,
                            expiry_date=expiry_iso,
                            exchange_code="NFO",
                            product_type=product_type,
                            right=right,
                            strike_price="",
                        )
                    )
                    await stats.incr("chain_calls")
                    if rows:
                        break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    await stats.incr("chain_calls")
                    logger.debug(
                        "Option chain %s/%s failed for %s: %s",
                        right,
                        product_type,
                        stock_code,
                        exc,
                    )
            if rows:
                merged.extend(rows)
        if not merged and last_exc is not None:
            raise last_exc
        return merged

    async def enrich_one(self, symbol: str, stats: EnrichmentStats | None = None) -> LiveMarks | None:
        und = symbol.upper().strip()
        local_stats = stats or EnrichmentStats()
        cached = self._cache_get(und)
        if cached is not None:
            await local_stats.incr("cache_hits")
            return cached

        stock_code = self._instruments.stock_code_for_underlying(und) or und
        chosen = select_preferred_expiry(
            self._instruments,
            und,
            min_dte=self.prefer_dte_min,
            max_dte=self.prefer_dte_max,
        )
        if chosen is None:
            await local_stats.incr("failed")
            await local_stats.add_error(f"{und}: no NFO option expiry in master")
            return None
        expiry_raw, _dte = chosen
        expiry_iso = expiry_to_breeze_iso(expiry_raw)
        if not expiry_iso:
            await local_stats.incr("failed")
            await local_stats.add_error(f"{und}: bad expiry '{expiry_raw}'")
            return None

        spot = await self._spot_ltp(und, local_stats, stock_code=stock_code)

        try:
            rows = await self._fetch_option_chain_sides(
                stock_code=stock_code,
                expiry_iso=expiry_iso,
                stats=local_stats,
            )
        except Exception as exc:  # noqa: BLE001
            await local_stats.incr("failed")
            await local_stats.add_error(f"{und} chain: {exc}")
            logger.warning("Option chain failed for %s (%s): %s", und, stock_code, exc)
            return None

        marks = parse_atm_from_chain(rows, spot_hint=spot, expiry_raw=expiry_raw)
        if marks is None:
            await local_stats.incr("failed")
            await local_stats.add_error(f"{und}: empty/unusable option chain")
            return None

        # Prefer explicit cash LTP when present; else chain spot_price.
        if spot is not None and spot > 0:
            marks.und_price = spot
        marks.symbol = und
        marks.stock_code = stock_code
        marks.expiry = expiry_raw
        self._cache_put(marks)
        await local_stats.incr("live_ok")
        return marks

    async def enrich_many(
        self,
        symbols: list[str],
        *,
        deadline_monotonic: float | None = None,
        max_symbols: int | None = None,
    ) -> tuple[dict[str, LiveMarks], EnrichmentStats]:
        started = time.monotonic()
        capped = list(symbols)
        if max_symbols is not None and max_symbols > 0:
            capped = capped[:max_symbols]
        stats = EnrichmentStats(requested=len(capped))
        if not capped:
            return {}, stats

        # Fail fast when Breeze session is unavailable — avoid 213× timed-out calls.
        try:
            await self._md.session_manager.ensure_session()
        except Exception as exc:  # noqa: BLE001
            stats.failed = len(capped)
            stats.errors.append(f"ICICI session unavailable — skipping live enrichment ({exc})")
            stats.elapsed_sec = time.monotonic() - started
            logger.warning("Skipping live universe enrichment: %s", exc)
            return {}, stats

        sem = asyncio.Semaphore(self.max_concurrency)
        out: dict[str, LiveMarks] = {}
        out_lock = asyncio.Lock()
        deadline_hit = False

        async def _one(sym: str) -> None:
            nonlocal deadline_hit
            if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                deadline_hit = True
                return
            async with sem:
                if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                    deadline_hit = True
                    return
                marks = await self.enrich_one(sym, stats)
                if marks is not None:
                    async with out_lock:
                        out[sym.upper()] = marks

        await asyncio.gather(*[_one(s) for s in capped])
        if deadline_hit or (
            deadline_monotonic is not None and time.monotonic() >= deadline_monotonic
        ):
            skipped = max(0, len(symbols) - len(capped))
            remaining = max(0, len(capped) - len(out) - stats.failed - stats.cache_hits)
            stats.errors.append(
                "generation_budget: enrichment deadline reached "
                f"(live_ok={stats.live_ok}, skipped_symbols≈{skipped + remaining})"
            )
        if max_symbols is not None and len(symbols) > len(capped):
            stats.errors.append(
                f"max_symbols={max_symbols}: enriched subset of {len(symbols)} FNO underlyings"
            )
        stats.elapsed_sec = time.monotonic() - started
        return out, stats


_enricher: UniverseEnricher | None = None


def get_universe_enricher(cfg: dict[str, Any] | None = None) -> UniverseEnricher:
    global _enricher
    section = (cfg or {}).get("recommendation_universe_enrichment") or {}
    if _enricher is None:
        _enricher = UniverseEnricher(
            cache_ttl_sec=float(section.get("cache_ttl_sec", 90)),
            max_concurrency=int(section.get("max_concurrency", 4)),
            min_interval_ms=float(section.get("min_interval_ms", 700)),
            fetch_spot_ltp=bool(section.get("fetch_spot_ltp", True)),
            prefer_dte_min=int(section.get("prefer_dte_min", 10)),
            prefer_dte_max=int(section.get("prefer_dte_max", 30)),
        )
        return _enricher
    # Keep singleton but allow config refresh of pacing knobs.
    _enricher.cache_ttl_sec = float(section.get("cache_ttl_sec", _enricher.cache_ttl_sec))
    _enricher.max_concurrency = max(1, int(section.get("max_concurrency", _enricher.max_concurrency)))
    _enricher.fetch_spot_ltp = bool(section.get("fetch_spot_ltp", _enricher.fetch_spot_ltp))
    _enricher.prefer_dte_min = int(section.get("prefer_dte_min", _enricher.prefer_dte_min))
    _enricher.prefer_dte_max = int(section.get("prefer_dte_max", _enricher.prefer_dte_max))
    return _enricher


def reset_universe_enricher_for_tests() -> None:
    global _enricher
    if _enricher is not None:
        _enricher.clear_cache()
    _enricher = None


def live_marks_to_candidate_fields(
    marks: LiveMarks,
    cfg: dict[str, Any],
    *,
    price_history_daily: list[float] | None = None,
    iv_series_intraday: list[float] | None = None,
    days_to_earnings: int | None = None,
    realized_vol_intraday: float | None = None,
) -> dict[str, Any]:
    """Map LiveMarks → InstrumentCandidate kwargs via live-clean QuantSnapshot.

    Does **not** invent flat spot history or synthetic GARCH (0.28 / IV×1.05).
    Pass real ``price_history_daily`` / IV series for usable GARCH / IV z.
    """
    from backend.services.quant_snapshot import build_quant_snapshot, snapshot_to_candidate_fields

    snap = build_quant_snapshot(
        marks=marks,
        price_history_daily=list(price_history_daily or []),
        iv_series_intraday=list(iv_series_intraday or []),
        days_to_earnings=days_to_earnings,
        realized_vol_intraday=realized_vol_intraday,
        cfg=cfg,
    )
    fields = snapshot_to_candidate_fields(snap)
    fields["symbol"] = marks.symbol
    if marks.expiry:
        fields["atm_history_prior"] = AtmLiquidityHistoryStore(ATM_HISTORY_STORE_PATH).prior_points(
            underlying=marks.symbol,
            expiry_key=str(marks.expiry),
            before_date=_session_date_ist(),
            lookback_days=20,
        )
    else:
        fields["atm_history_prior"] = None
    return fields
