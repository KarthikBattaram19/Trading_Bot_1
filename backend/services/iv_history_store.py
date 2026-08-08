"""Session IV sample history for intraday IV z-score (N4)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

DEFAULT_STORE_PATH = Path(__file__).resolve().parents[1] / "data" / "iv_history.json"

logger = logging.getLogger(__name__)


class IvHistoryStore:
    """JSON store of intraday ATM IV samples keyed by SYMBOL|session_date."""

    def __init__(self, store_path: Path | None = None) -> None:
        self.store_path = store_path or DEFAULT_STORE_PATH

    def _key(self, symbol: str, session_date: str) -> str:
        return f"{symbol.upper().strip()}|{session_date}"

    def _quarantine_path(self) -> Path:
        return self.store_path.with_name(self.store_path.name + ".corrupt")

    def _read(self) -> dict[str, Any]:
        if not self.store_path.exists():
            return {}
        try:
            with open(self.store_path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            # The file itself is bad JSON — quarantine it so the next
            # _write starts clean and the corrupt bytes survive for
            # diagnosis.
            logger.warning(
                "iv_history_store: corrupt store at %s, quarantining and continuing with empty cache",
                self.store_path,
                exc_info=True,
            )
            self._quarantine_corrupt_file()
            return {}
        except OSError:
            # Transient I/O failure (Windows sharing violation, EMFILE,
            # momentary disk hiccup, ...) says nothing about whether the
            # file's contents are valid. Degrade for this call only —
            # do NOT quarantine, or a passing glitch on a perfectly good
            # store would rename it away and the next _write would wipe
            # every symbol's history down to just the new sample.
            logger.warning(
                "iv_history_store: transient read error on %s, returning empty cache for this call only",
                self.store_path,
                exc_info=True,
            )
            return {}
        return data if isinstance(data, dict) else {}

    def _quarantine_corrupt_file(self) -> None:
        quarantine = self._quarantine_path()
        try:
            # os.replace() already overwrites an existing destination on
            # both Windows and POSIX — no need to unlink it first.
            os.replace(self.store_path, quarantine)
        except OSError:
            logger.warning(
                "iv_history_store: failed to quarantine corrupt store at %s",
                self.store_path,
                exc_info=True,
            )

    def _write(self, data: dict[str, Any]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        # Unique per-writer temp name (pid + random suffix via mkstemp) so
        # concurrent writers never share a temp file — os.replace() only
        # makes the *rename* atomic, not writes into a shared temp path.
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.store_path.parent),
            prefix=self.store_path.name + ".",
            suffix=".tmp",
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            self._replace_with_retry(tmp_path)
        except BaseException:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _replace_with_retry(self, tmp_path: Path, attempts: int = 8) -> None:
        # os.replace(tmp, dst) is atomic, but on Windows two writers racing
        # to replace the *same* dst at the same instant can transiently see
        # PermissionError (WinError 5) while the OS resolves the rename —
        # not corruption, just contention. Retry briefly before giving up.
        for attempt in range(attempts):
            try:
                os.replace(tmp_path, self.store_path)
                return
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.01 * (attempt + 1))

    def append(
        self,
        *,
        symbol: str,
        session_date: str,
        ts_iso: str,
        iv: float,
    ) -> None:
        """Append one IV sample.

        Known, accepted limitation: the on-disk write (`_write`) is atomic
        and safe against interleaved/corrupt bytes, but this read-modify-
        write is not itself locked, so two concurrent `append` calls can
        race and one sample can be lost. Acceptable here — this is a
        regenerable intraday IV cache that can tolerate a dropped sample,
        but must never tolerate a corrupt file.
        """
        if iv <= 0:
            return
        data = self._read()
        key = self._key(symbol, session_date)
        rows: list[dict[str, Any]] = list(data.get(key) or [])
        rows.append({"ts": ts_iso, "iv": float(iv)})
        data[key] = rows
        self._write(data)

    def series(self, *, symbol: str, session_date: str) -> list[float]:
        data = self._read()
        rows = list(data.get(self._key(symbol, session_date)) or [])
        out: list[float] = []
        for r in rows:
            try:
                v = float(r.get("iv"))
            except (TypeError, ValueError):
                continue
            if v > 0:
                out.append(v)
        return out
