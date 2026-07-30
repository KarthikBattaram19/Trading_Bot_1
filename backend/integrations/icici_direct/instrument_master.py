"""Instrument master cache: tradingsymbol ↔ stock_code / token (A1)."""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime, timezone
from typing import Any

from backend.integrations.icici_direct.client import IciciDirectClient
from backend.integrations.icici_direct.models import InstrumentRecord

logger = logging.getLogger(__name__)


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
        # case-insensitive fallback
        for rk, rv in row.items():
            if rk.lower() == key.lower() and rv not in (None, ""):
                return rv
    return None


class InstrumentMaster:
    """In-memory index over ICICI Direct Breeze security master."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], InstrumentRecord] = {}
        self._by_token: dict[str, InstrumentRecord] = {}
        self._loaded_at: datetime | None = None
        self._count = 0

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

    def upsert(self, record: InstrumentRecord) -> None:
        key = (record.exchange.upper(), record.tradingsymbol.upper())
        self._by_key[key] = record
        self._by_token[record.symboltoken] = record
        if record.stock_code:
            self._by_token[record.stock_code.upper()] = record

    def load_rows(self, rows: list[dict[str, Any]]) -> int:
        self.clear()
        for row in rows:
            exchange = str(
                _row_get(row, "exch_seg", "exchange", "ExchangeCode", "Exchange") or ""
            ).upper()
            symbol = str(
                _row_get(
                    row,
                    "symbol",
                    "tradingsymbol",
                    "ShortName",
                    "StockCode",
                    "stock_code",
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
                instrumenttype=str(_row_get(row, "instrumenttype", "InstrumentType") or "")
                or None,
                expiry=str(_row_get(row, "expiry", "ExpiryDate") or "") or None,
                strike=_parse_strike(_row_get(row, "strike", "StrikePrice")),
                lotsize=_parse_lot(_row_get(row, "lotsize", "LotSize", "BoardLotQuantity")),
                tick_size=_parse_tick(_row_get(row, "tick_size", "ticksize", "TickSize")),
                stock_code=stock_code,
            )
            self.upsert(record)
        self._loaded_at = datetime.now(timezone.utc)
        self._count = len(self._by_key)
        logger.info("ICICI Direct instrument master loaded: %s instruments", self._count)
        return self._count

    def load_from_zip_bytes(self, data: bytes) -> int:
        rows: list[dict[str, Any]] = []
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                if not name.lower().endswith((".csv", ".txt")):
                    continue
                with zf.open(name) as fh:
                    text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
                    reader = csv.DictReader(text)
                    rows.extend(list(reader))
        return self.load_rows(rows)

    async def refresh(self, client: IciciDirectClient) -> int:
        data = await client.fetch_security_master_zip()
        return self.load_from_zip_bytes(data)

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
            if q in symbol or (record.name and q in record.name.upper()):
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
        """Return option contracts for an underlying name (read-only chain helper)."""
        target = name.upper().strip()
        exch = exchange.upper()
        expiry_norm = expiry.upper().replace("-", "").replace(" ", "") if expiry else None
        results: list[InstrumentRecord] = []
        for record in self._by_key.values():
            if record.exchange.upper() != exch:
                continue
            rec_name = (record.name or "").upper()
            symbol = record.tradingsymbol.upper()
            stock = (record.stock_code or "").upper()
            if rec_name != target and not symbol.startswith(target) and stock != target:
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
        # Quotes can confirm a stock_code exists even if master is empty
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
