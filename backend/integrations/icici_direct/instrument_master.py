"""Instrument master cache: tradingsymbol ↔ stock_code / token (A1).

Loads ICICI Direct Breeze SecurityMaster.zip (daily ~08:00 IST):
https://directlink.icicidirect.com/NewSecurityMaster/SecurityMaster.zip

FONSEScripMaster.txt is the authoritative NSE F&O contract list used for the
feed-bound recommendation universe (G11–G12).
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

import httpx

from backend.integrations.icici_direct.client import SECURITY_MASTER_ZIP_URL, IciciDirectClient
from backend.integrations.icici_direct.models import InstrumentRecord

logger = logging.getLogger(__name__)

# SecurityMaster.zip member → exchange_code (vendor file naming).
_ZIP_MEMBER_EXCHANGE: dict[str, str] = {
    "fonsescripmaster.txt": "NFO",
    "fobsescripmaster.txt": "BFO",
    "nsescripmaster.txt": "NSE",
    "bsescripmaster.txt": "BSE",
    "cdnsescripmaster.txt": "CDS",
}

# ICICI ShortName → display / G11 underlying for index options.
_INDEX_UNDERLYING_BY_SHORT: dict[str, str] = {
    "NIFTY": "NIFTY",
    "CNXBAN": "BANKNIFTY",
    "NIFFIN": "FINNIFTY",
    "NIFSEL": "MIDCPNIFTY",
    "NIFNEX": "NIFTYNXT50",
}

_FNO_INSTRUMENT_TYPES = frozenset({"OPTSTK", "OPTIDX", "FUTSTK", "FUTIDX", "OPT", "FUT"})


def _parse_strike(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _parse_lot(raw: Any) -> int:
    try:
        return max(int(float(raw)), 1)
    except (TypeError, ValueError):
        return 1


def _parse_tick(raw: Any) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.05


def _row_get(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
        for rk, rv in row.items():
            if rk.lower() == key.lower() and rv not in (None, ""):
                return rv
    return None


def _normalize_header(key: str) -> str:
    return str(key).strip().strip('"').strip()


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {_normalize_header(k): v for k, v in row.items() if k is not None}


def _expiry_compact(expiry: str) -> str:
    """25-Aug-2026 → 25AUG26 (Breeze-style contract token fragment)."""
    raw = expiry.strip()
    if not raw:
        return ""
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%d%b%y").upper()
        except ValueError:
            continue
    return raw.replace("-", "").replace(" ", "").upper()


def _fno_tradingsymbol(
    short_name: str,
    *,
    instrument_name: str,
    expiry: str,
    strike: float | None,
    option_type: str,
) -> str:
    exp = _expiry_compact(expiry)
    itype = instrument_name.upper()
    if itype.startswith("FUT"):
        return f"{short_name}{exp}FUT" if exp else f"{short_name}FUT"
    right = (option_type or "").upper()
    if right in {"CE", "PE", "CA", "PA"}:
        pass
    elif right in {"CALL", "C"}:
        right = "CE"
    elif right in {"PUT", "P"}:
        right = "PE"
    else:
        right = right or "XX"
    if strike is None:
        return f"{short_name}{exp}{right}"
    if float(strike).is_integer():
        strike_part = str(int(strike))
    else:
        strike_part = str(strike).rstrip("0").rstrip(".")
    return f"{short_name}{exp}{strike_part}{right}"


def _underlying_for_fno(
    short_name: str,
    *,
    exchange_code: str | None,
    instrument_name: str,
) -> str:
    sn = short_name.upper().strip()
    if sn in _INDEX_UNDERLYING_BY_SHORT:
        return _INDEX_UNDERLYING_BY_SHORT[sn]
    if instrument_name.upper().startswith("OPTIDX") or instrument_name.upper().startswith("FUTIDX"):
        if sn in _INDEX_UNDERLYING_BY_SHORT:
            return _INDEX_UNDERLYING_BY_SHORT[sn]
        return sn
    code = (exchange_code or "").strip().upper()
    # FONSE ExchangeCode is the NSE equity ticker (RELIANCE, SBIN, …).
    if code and " " not in code and code not in {"NFO", "NSE", "BSE", "BFO", "CDS"}:
        return code
    return sn


def data_feed_bindings_for(underlying_symbol: str, *, stock_code: str | None = None) -> dict[str, str]:
    """G12 — ICICI Direct feed ids for spot + NFO option chain."""
    sym = underlying_symbol.upper().strip()
    code = (stock_code or sym).upper().strip()
    return {
        "und_price": f"icici_direct:NSE:{sym}:quotes",
        "option_chain": f"icici_direct:NFO:{code}:option_chain",
    }


class InstrumentMaster:
    """In-memory index over ICICI Direct Breeze security master."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], InstrumentRecord] = {}
        self._by_token: dict[str, InstrumentRecord] = {}
        self._loaded_at: datetime | None = None
        self._count = 0
        self._fno_underlyings: list[str] = []
        self._underlying_to_stock_code: dict[str, str] = {}

    @property
    def loaded_at(self) -> datetime | None:
        return self._loaded_at

    @property
    def count(self) -> int:
        return self._count

    def clear(self) -> None:
        self._by_key.clear()
        self._by_token.clear()
        self._loaded_at = None
        self._count = 0
        self._fno_underlyings = []
        self._underlying_to_stock_code.clear()

    def upsert(self, record: InstrumentRecord) -> None:
        key = (record.exchange.upper(), record.tradingsymbol.upper())
        self._by_key[key] = record
        self._by_token[record.symboltoken] = record
        if record.stock_code:
            self._by_token[record.stock_code.upper()] = record

    def load_rows(self, rows: list[dict[str, Any]], *, default_exchange: str | None = None) -> int:
        """Load normalized or test rows. Optional default_exchange for SecurityMaster members."""
        if default_exchange is None:
            self.clear()
        fno_map: dict[str, str] = dict(self._underlying_to_stock_code)

        for row in rows:
            row = _normalize_row(row)
            exchange = str(
                default_exchange
                or _row_get(row, "exch_seg", "exchange", "Exchange")
                or ""
            ).upper()
            instrument_name = str(
                _row_get(row, "InstrumentName", "instrumenttype", "InstrumentType") or ""
            ).upper()

            if exchange == "NFO" or (default_exchange or "").upper() == "NFO":
                token = str(_row_get(row, "Token", "token", "symboltoken") or "")
                symbol = str(_row_get(row, "tradingsymbol", "symbol") or "")
                short = str(
                    _row_get(row, "ShortName", "stock_code", "StockCode")
                    or _row_get(row, "name")
                    or ""
                ).upper()
                if not token:
                    continue
                expiry = str(_row_get(row, "ExpiryDate", "expiry") or "") or None
                strike = _parse_strike(_row_get(row, "StrikePrice", "strike"))
                option_type = str(_row_get(row, "OptionType", "right") or "")
                if symbol.upper().endswith("CE"):
                    option_type = option_type or "CE"
                elif symbol.upper().endswith("PE"):
                    option_type = option_type or "PE"
                if not instrument_name:
                    if option_type.upper() in {"CE", "PE", "CALL", "PUT"} or symbol.upper().endswith(
                        ("CE", "PE")
                    ):
                        instrument_name = "OPTIDX" if short in _INDEX_UNDERLYING_BY_SHORT else "OPTSTK"
                    else:
                        instrument_name = "FUTSTK"
                if not short and symbol:
                    body = symbol.upper()
                    for suffix in ("CE", "PE", "FUT"):
                        if body.endswith(suffix):
                            body = body[: -len(suffix)]
                            break
                    short = "".join(ch for ch in body if ch.isalpha())
                if not short:
                    continue
                if not symbol:
                    symbol = _fno_tradingsymbol(
                        short,
                        instrument_name=instrument_name,
                        expiry=expiry or "",
                        strike=strike,
                        option_type=option_type,
                    )
                equity_code = str(_row_get(row, "ExchangeCode") or "") or None
                underlying = str(_row_get(row, "underlying") or "") or _underlying_for_fno(
                    short,
                    exchange_code=equity_code,
                    instrument_name=instrument_name,
                )
                # Prefer explicit name as underlying for test fixtures (e.g. name=NIFTY).
                name_val = str(_row_get(row, "CompanyName", "name") or "") or None
                if name_val and name_val.upper() in {
                    "NIFTY",
                    "BANKNIFTY",
                    "FINNIFTY",
                    "MIDCPNIFTY",
                }:
                    underlying = name_val.upper()
                    short = short or name_val.upper()
                record = InstrumentRecord(
                    exchange="NFO",
                    tradingsymbol=symbol,
                    symboltoken=token,
                    name=name_val,
                    instrumenttype=instrument_name or None,
                    expiry=expiry,
                    strike=strike,
                    lotsize=_parse_lot(_row_get(row, "LotSize", "lotsize", "MinimumLotQty")),
                    tick_size=_parse_tick(_row_get(row, "TickSize", "tick_size", "ticksize")),
                    stock_code=short.upper(),
                    underlying=underlying.upper(),
                )
                self.upsert(record)
                if instrument_name in _FNO_INSTRUMENT_TYPES or instrument_name.startswith(
                    ("OPT", "FUT")
                ):
                    fno_map[record.underlying.upper()] = short.upper()
                continue

            # Equity / other cash scrips (tests + NSE/BSE masters)
            symbol = str(
                _row_get(
                    row,
                    "symbol",
                    "tradingsymbol",
                    "ShortName",
                    "StockCode",
                    "stock_code",
                    "Symbol",
                )
                or ""
            )
            token = str(
                _row_get(row, "token", "symboltoken", "Token", "stock_code", "StockCode") or ""
            )
            if not exchange or not symbol or not token:
                continue
            stock_code = str(_row_get(row, "stock_code", "StockCode", "ShortName") or symbol)
            record = InstrumentRecord(
                exchange=exchange,
                tradingsymbol=symbol,
                symboltoken=token,
                name=str(_row_get(row, "name", "CompanyName", "StockName") or "") or None,
                instrumenttype=str(_row_get(row, "instrumenttype", "InstrumentType", "Series") or "")
                or None,
                expiry=str(_row_get(row, "expiry", "ExpiryDate") or "") or None,
                strike=_parse_strike(_row_get(row, "strike", "StrikePrice")),
                lotsize=_parse_lot(_row_get(row, "lotsize", "LotSize", "Lotsize", "BoardLotQuantity")),
                tick_size=_parse_tick(
                    _row_get(row, "tick_size", "ticksize", "TickSize", "ticksize")
                ),
                stock_code=stock_code,
                underlying=str(_row_get(row, "underlying", "Symbol") or stock_code) or None,
            )
            self.upsert(record)

        self._loaded_at = datetime.now(timezone.utc)
        self._count = len(self._by_key)
        self._underlying_to_stock_code = fno_map
        self._fno_underlyings = sorted(fno_map.keys())
        logger.info(
            "ICICI Direct instrument master loaded: %s instruments (%s FNO underlyings)",
            self._count,
            len(self._fno_underlyings),
        )
        return self._count

    def load_from_zip_bytes(self, data: bytes) -> int:
        self.clear()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                base = PurePosixPath(name).name.lower()
                exchange = _ZIP_MEMBER_EXCHANGE.get(base)
                if exchange is None:
                    continue
                # Project scope: NSE cash + NSE F&O (NFO). Skip BSE/CDS masters.
                if exchange not in {"NSE", "NFO"}:
                    continue
                with zf.open(name) as fh:
                    text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
                    reader = csv.DictReader(text)
                    rows = [_normalize_row(row) for row in reader]
                # Accumulate without clearing between members
                if exchange == "NFO":
                    self._load_nfo_rows(rows)
                else:
                    self._load_equity_rows(rows, exchange=exchange)
        self._loaded_at = datetime.now(timezone.utc)
        self._count = len(self._by_key)
        self._fno_underlyings = sorted(self._underlying_to_stock_code.keys())
        logger.info(
            "ICICI Direct instrument master loaded: %s instruments (%s FNO underlyings)",
            self._count,
            len(self._fno_underlyings),
        )
        return self._count

    def _load_nfo_rows(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            short = str(_row_get(row, "ShortName") or "").upper()
            token = str(_row_get(row, "Token") or "")
            if not short or not token:
                continue
            instrument_name = str(_row_get(row, "InstrumentName") or "").upper()
            expiry = str(_row_get(row, "ExpiryDate") or "") or None
            strike = _parse_strike(_row_get(row, "StrikePrice"))
            option_type = str(_row_get(row, "OptionType") or "")
            equity_code = str(_row_get(row, "ExchangeCode") or "") or None
            underlying = _underlying_for_fno(
                short, exchange_code=equity_code, instrument_name=instrument_name
            )
            symbol = _fno_tradingsymbol(
                short,
                instrument_name=instrument_name or "OPTSTK",
                expiry=expiry or "",
                strike=strike,
                option_type=option_type,
            )
            record = InstrumentRecord(
                exchange="NFO",
                tradingsymbol=symbol,
                symboltoken=token,
                name=str(_row_get(row, "CompanyName") or "") or None,
                instrumenttype=instrument_name or None,
                expiry=expiry,
                strike=strike,
                lotsize=_parse_lot(_row_get(row, "LotSize", "MinimumLotQty")),
                tick_size=_parse_tick(_row_get(row, "TickSize")),
                stock_code=short,
                underlying=underlying,
            )
            self.upsert(record)
            if instrument_name.startswith(("OPT", "FUT")) or instrument_name in _FNO_INSTRUMENT_TYPES:
                self._underlying_to_stock_code[underlying.upper()] = short

    def _load_equity_rows(self, rows: list[dict[str, Any]], *, exchange: str) -> None:
        for row in rows:
            symbol = str(
                _row_get(row, "ShortName", "Symbol", "symbol", "tradingsymbol") or ""
            )
            token = str(_row_get(row, "Token", "token") or "")
            if not symbol or not token or token == "0":
                continue
            series = str(_row_get(row, "Series") or "").upper()
            # Prefer equity series for cash underlyings
            if series and series not in {"EQ", "BE", "SM", "ST", "BZ", ""}:
                # Still index non-EQ so resolve works; skip debt-heavy noise when Series=DR etc.
                if series in {"DR", "GS", "GB", "TB"}:
                    continue
            record = InstrumentRecord(
                exchange=exchange,
                tradingsymbol=symbol,
                symboltoken=token,
                name=str(_row_get(row, "CompanyName", "name") or "") or None,
                instrumenttype=series or "EQ",
                lotsize=_parse_lot(_row_get(row, "LotSize", "Lotsize")),
                tick_size=_parse_tick(_row_get(row, "TickSize", "ticksize")),
                stock_code=symbol,
                underlying=symbol,
            )
            self.upsert(record)

    async def refresh(self, client: IciciDirectClient) -> int:
        data = await client.fetch_security_master_zip()
        return self.load_from_zip_bytes(data)

    async def refresh_public(self) -> int:
        """Download SecurityMaster.zip without a Breeze session (public CDN)."""
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            response = await client.get(SECURITY_MASTER_ZIP_URL)
            response.raise_for_status()
            return self.load_from_zip_bytes(response.content)

    def list_fno_underlyings(self, *, exchange: str = "NFO") -> list[str]:
        """Unique G11 underlyings with NFO futures/options in the master."""
        if exchange.upper() == "NFO" and self._fno_underlyings:
            return list(self._fno_underlyings)
        found: set[str] = set()
        for record in self._by_key.values():
            if record.exchange.upper() != exchange.upper():
                continue
            itype = (record.instrumenttype or "").upper()
            if not (
                itype.startswith("OPT")
                or itype.startswith("FUT")
                or (record.tradingsymbol or "").upper().endswith(("CE", "PE", "FUT"))
            ):
                continue
            name = (record.underlying or record.stock_code or record.name or "").upper()
            if name:
                found.add(name)
        return sorted(found)

    def stock_code_for_underlying(self, underlying_symbol: str) -> str | None:
        key = underlying_symbol.upper().strip()
        if key in self._underlying_to_stock_code:
            return self._underlying_to_stock_code[key]
        # Direct ShortName hit
        if key in {v for v in self._underlying_to_stock_code.values()}:
            return key
        return None

    def feed_bindings_for(self, underlying_symbol: str) -> dict[str, str]:
        """G12 bindings for one feed-bound universe member."""
        code = self.stock_code_for_underlying(underlying_symbol)
        return data_feed_bindings_for(underlying_symbol, stock_code=code)

    def resolve(
        self,
        *,
        exchange: str | None = None,
        tradingsymbol: str | None = None,
        symboltoken: str | None = None,
    ) -> InstrumentRecord | None:
        if symboltoken and symboltoken in self._by_token:
            return self._by_token[symboltoken]
        if symboltoken and symboltoken.upper() in self._by_token:
            return self._by_token[symboltoken.upper()]
        if exchange and tradingsymbol:
            return self._by_key.get((exchange.upper(), tradingsymbol.upper()))
        return None

    def search(
        self, query: str, *, exchange: str | None = None, limit: int = 20
    ) -> list[InstrumentRecord]:
        q = query.upper()
        results: list[InstrumentRecord] = []
        for (exch, symbol), record in self._by_key.items():
            if exchange and exch != exchange.upper():
                continue
            hay = " ".join(
                filter(
                    None,
                    [
                        symbol,
                        record.name,
                        record.stock_code,
                        record.underlying,
                    ],
                )
            ).upper()
            if q in hay:
                results.append(record)
                if len(results) >= limit:
                    break
        return results

    def list_options(
        self,
        *,
        name: str,
        exchange: str = "NFO",
        expiry: str | None = None,
        limit: int = 500,
    ) -> list[InstrumentRecord]:
        """Return option contracts for an underlying name / NSE symbol / ShortName."""
        target = name.upper().strip()
        stock = self.stock_code_for_underlying(target) or target
        exch = exchange.upper()
        expiry_norm = expiry.upper().replace("-", "").replace(" ", "") if expiry else None
        results: list[InstrumentRecord] = []
        for record in self._by_key.values():
            if record.exchange.upper() != exch:
                continue
            rec_underlying = (record.underlying or "").upper()
            rec_name = (record.name or "").upper()
            symbol = record.tradingsymbol.upper()
            rec_stock = (record.stock_code or "").upper()
            if not (
                rec_underlying == target
                or rec_stock == target
                or rec_stock == stock
                or rec_name == target
                or symbol.startswith(target)
                or symbol.startswith(stock)
            ):
                continue
            if not (symbol.endswith("CE") or symbol.endswith("PE")):
                itype = (record.instrumenttype or "").upper()
                if "OPT" not in itype and "OPTION" not in itype:
                    continue
            if expiry_norm:
                rec_exp = (record.expiry or "").upper().replace("-", "").replace(" ", "")
                if expiry_norm not in rec_exp and rec_exp not in expiry_norm:
                    continue
            results.append(record)
            if len(results) >= limit:
                break
        results.sort(key=lambda r: (r.expiry or "", r.strike or 0.0, r.tradingsymbol))
        return results

    async def resolve_or_search(
        self,
        client: IciciDirectClient,
        *,
        exchange: str,
        tradingsymbol: str,
    ) -> InstrumentRecord | None:
        found = self.resolve(exchange=exchange, tradingsymbol=tradingsymbol)
        if found:
            return found
        try:
            payload = await client.get_quotes(
                stock_code=tradingsymbol,
                exchange_code=exchange,
                product_type="cash" if exchange.upper() in {"NSE", "BSE"} else "options",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("quotes lookup failed for %s/%s: %s", exchange, tradingsymbol, exc)
            return None
        success = payload.get("Success")
        rows = success if isinstance(success, list) else ([success] if success else [])
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("stock_code") or tradingsymbol)
            token = str(row.get("token") or row.get("stock_code") or symbol)
            record = InstrumentRecord(
                exchange=exchange.upper(),
                tradingsymbol=symbol,
                symboltoken=token,
                stock_code=symbol,
                underlying=symbol,
                lotsize=_parse_lot(row.get("lot_size") or row.get("lotsize")),
            )
            self.upsert(record)
            return record
        return None


_instrument_master: InstrumentMaster | None = None


def get_instrument_master() -> InstrumentMaster:
    global _instrument_master
    if _instrument_master is None:
        _instrument_master = InstrumentMaster()
    return _instrument_master


def reset_instrument_master_for_tests() -> None:
    global _instrument_master
    _instrument_master = None
