"""Resilience tests for IvHistoryStore against a corrupt on-disk JSON file.

Corruption signature seen in production: two JSON strings concatenated with
no separator (interleaved/interrupted write), e.g.:
    "2026-08-01T18:17:30.019920+00:00""2026-08-01T18:17:29.139344+00:00"

_read must degrade to {} (never raise) and quarantine the bad file so the
next _write starts clean and the corrupt evidence survives for diagnosis.
_write must be atomic (temp file + os.replace) so a crash mid-write cannot
reproduce this corruption.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from backend.services.iv_history_store import IvHistoryStore

CORRUPT_BYTES = (
    '{"NIFTY|2026-08-01": [{"ts": "2026-08-01T18:17:30.019920+00:00"'
    '"2026-08-01T18:17:29.139344+00:00", "iv": 0.21}]}'
)


def _store(tmp_path: Path) -> tuple[IvHistoryStore, Path]:
    path = tmp_path / "iv_history.json"
    return IvHistoryStore(store_path=path), path


def test_read_returns_empty_dict_on_corrupt_file(tmp_path: Path) -> None:
    store, path = _store(tmp_path)
    path.write_text(CORRUPT_BYTES, encoding="utf-8")

    data = store._read()

    assert data == {}


def test_corrupt_file_is_quarantined(tmp_path: Path) -> None:
    store, path = _store(tmp_path)
    path.write_text(CORRUPT_BYTES, encoding="utf-8")

    store._read()

    quarantine = path.with_name(path.name + ".corrupt")
    assert quarantine.exists()
    assert quarantine.read_text(encoding="utf-8") == CORRUPT_BYTES
    # Original path no longer holds the corrupt bytes (removed/renamed away).
    assert not path.exists() or path.read_text(encoding="utf-8") != CORRUPT_BYTES


def test_quarantine_overwrites_existing_target(tmp_path: Path) -> None:
    store, path = _store(tmp_path)
    quarantine = path.with_name(path.name + ".corrupt")
    quarantine.write_text("stale-previous-quarantine", encoding="utf-8")
    path.write_text(CORRUPT_BYTES, encoding="utf-8")

    data = store._read()

    assert data == {}
    assert quarantine.read_text(encoding="utf-8") == CORRUPT_BYTES


def test_append_succeeds_against_previously_corrupt_store(tmp_path: Path) -> None:
    store, path = _store(tmp_path)
    path.write_text(CORRUPT_BYTES, encoding="utf-8")

    store.append(symbol="NIFTY", session_date="2026-08-08", ts_iso="2026-08-08T10:00:00+05:30", iv=0.20)

    series = store.series(symbol="NIFTY", session_date="2026-08-08")
    assert series == [0.20]


def test_series_on_corrupt_store_returns_empty_list(tmp_path: Path) -> None:
    store, path = _store(tmp_path)
    path.write_text(CORRUPT_BYTES, encoding="utf-8")

    assert store.series(symbol="NIFTY", session_date="2026-08-01") == []


def test_successful_write_leaves_no_stray_temp_file(tmp_path: Path) -> None:
    store, path = _store(tmp_path)

    store.append(symbol="NIFTY", session_date="2026-08-08", ts_iso="2026-08-08T10:00:00+05:30", iv=0.20)

    leftovers = [p for p in tmp_path.iterdir() if p != path]
    assert leftovers == []


def test_round_trip_append_then_series(tmp_path: Path) -> None:
    store, path = _store(tmp_path)

    store.append(symbol="INFY", session_date="2026-08-08", ts_iso="2026-08-08T10:00:00+05:30", iv=0.30)
    store.append(symbol="INFY", session_date="2026-08-08", ts_iso="2026-08-08T10:01:00+05:30", iv=0.31)

    assert store.series(symbol="INFY", session_date="2026-08-08") == [0.30, 0.31]


def test_concurrent_writes_never_corrupt_the_store(tmp_path: Path) -> None:
    """Regression test for a shared fixed temp filename.

    _write() must give every writer its own temp file. A fixed temp name
    (e.g. `<store>.tmp` reused by all writers) lets concurrent `open(path,
    "w")` calls truncate/interleave each other's bytes on the *shared* temp
    file before the atomic rename ever happens — reproducing the exact
    "two JSON strings concatenated mid-file" corruption this whole fix
    exists to eliminate. os.replace() only makes the rename atomic; it does
    not protect a temp file that multiple writers share.

    Each writer's payload is large (many keys) to widen the write window,
    and many threads run against one store with a `Barrier` to start them
    together, maximizing the chance of interleaving if temp files collide.
    """
    store, path = _store(tmp_path)
    n_writers = 12
    n_keys_per_payload = 500
    barrier = threading.Barrier(n_writers)
    errors: list[BaseException] = []

    def _writer(writer_id: int) -> None:
        # Distinct payload per writer/call, with enough bulk that the
        # dump-to-tempfile step takes measurable time.
        payload = {
            f"SYM{writer_id}-{i}|2026-08-08": [{"ts": f"2026-08-08T10:{i % 60:02d}:00+05:30", "iv": 0.2}]
            for i in range(n_keys_per_payload)
        }
        try:
            barrier.wait(timeout=5)
            store._write(payload)
        except BaseException as exc:  # noqa: BLE001 - surfaced via `errors`
            errors.append(exc)

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(n_writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"writer thread(s) raised: {errors}"

    # The real assertion: the store must parse as valid JSON. Under the old
    # shared-fixed-temp-name implementation this reliably raised
    # JSONDecodeError from concatenated/truncated bytes.
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert isinstance(data, dict)

    # The surviving content must be exactly one writer's complete payload,
    # never a blend of two (which would show up as a mix of SYM{i} prefixes
    # from more than one writer_id, or a truncated/partial key count).
    prefixes = {key.split("-", 1)[0] for key in data}
    assert len(prefixes) == 1, f"expected exactly one writer's keys, got prefixes: {prefixes}"
    assert len(data) == n_keys_per_payload

    # No stray temp files left behind by any writer.
    leftovers = [p.name for p in tmp_path.iterdir() if p != path]
    assert leftovers == [], f"stray temp files left behind: {leftovers}"


def test_replace_retry_recovers_from_transient_permission_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """os.replace() can transiently raise PermissionError under Windows
    replace-contention (see the concurrency test above). _write() must
    retry rather than fail outright on the first such error."""
    store, path = _store(tmp_path)
    real_replace = os.replace
    calls: list[int] = []

    def _flaky_replace(src, dst):  # noqa: ANN001 - matches os.replace signature
        calls.append(1)
        if len(calls) <= 2:
            raise PermissionError(13, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _flaky_replace)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    store.append(symbol="NIFTY", session_date="2026-08-08", ts_iso="2026-08-08T10:00:00+05:30", iv=0.22)

    assert len(calls) == 3, "expected exactly 2 failures then a successful 3rd replace call"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"NIFTY|2026-08-08": [{"ts": "2026-08-08T10:00:00+05:30", "iv": 0.22}]}
    assert store.series(symbol="NIFTY", session_date="2026-08-08") == [0.22]


def test_replace_retry_exhaustion_reraises_and_cleans_up_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If os.replace() never succeeds, _write() must re-raise (write
    failures are not swallowed — only read-side corruption degrades) and
    must not leave a stray temp file behind."""
    store, path = _store(tmp_path)

    def _always_fails(src, dst):  # noqa: ANN001 - matches os.replace signature
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(os, "replace", _always_fails)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    with pytest.raises(PermissionError):
        store._write({"NIFTY|2026-08-08": [{"ts": "2026-08-08T10:00:00+05:30", "iv": 0.22}]})

    assert not path.exists(), "store file must not exist when the only write attempt exhausted retries"
    leftovers = list(tmp_path.iterdir())
    assert leftovers == [], f"stray temp files left behind after exhaustion: {leftovers}"
