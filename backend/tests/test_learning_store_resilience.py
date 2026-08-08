"""Resilience tests for LearningService's on-disk JSON store.

Deliberately ASYMMETRIC to `test_iv_history_store_resilience.py`:
`learning_store.json` is the financial ledger (one-trade lock, open
positions, closed outcomes, realized P&L) — not a regenerable cache. So:

- WRITE becomes atomic (temp file + os.replace + bounded retry), same
  pattern as `IvHistoryStore._write`, so a crash or overlapping writer
  can never leave a half-written ledger on disk.
- READ must FAIL LOUD on a corrupt store — never degrade to `{}` or a
  partial store. A silent empty-store read would tell the bot it has no
  open position when it actually does, which is how a second position
  gets opened against a live one.

No test may touch the real backend/data/learning_store.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from backend.services.learning_service import LearningService


def _store(tmp_path: Path) -> tuple[LearningService, Path]:
    path = tmp_path / "learning_store.json"
    return LearningService(store_path=path), path


def test_successful_write_leaves_no_stray_temp_file(tmp_path: Path) -> None:
    svc, path = _store(tmp_path)

    svc._write({"seed_version": 3, "open_trades": [], "outcomes": []})

    leftovers = [p for p in tmp_path.iterdir() if p != path]
    assert leftovers == []


def test_round_trip_write_then_read(tmp_path: Path) -> None:
    svc, path = _store(tmp_path)
    payload = {
        "seed_version": 3,
        "open_trades": [{"trade_id": "trd_1"}],
        "outcomes": [],
        "failure_memories": [],
        "adaptation_history": [],
        "module_weights": {"simple_volatility": 1.0},
        "peak_equity_inr": 0.0,
        "equity_inr": 0.0,
    }

    svc._write(payload)
    result = svc._read()

    assert result == payload


def test_corrupt_store_raises_rather_than_returning_empty(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The asymmetry test: a corrupt ledger must fail loud, never {}.

    A dropped read here would tell the bot it has no open position when it
    actually does -- exactly the scenario that risks a second live position
    opening against one that is already open.

    Asserting the raise alone isn't enough to prove this exercises the new
    guarded path in `_read` -- the pre-existing unguarded `json.load` would
    also raise `json.JSONDecodeError` on its own. So this also asserts the
    diagnostic log record from the guard fires, which only happens if
    execution actually reached the `try/except` in `_read`. Deleting that
    guard (verified by hand) makes this specific assertion fail even though
    the bare `pytest.raises` would still pass -- that's the point.
    """
    svc, path = _store(tmp_path)
    path.write_text(
        '{"open_trades": [{"trade_id": "trd_1""trade_id": "trd_2"}]}',
        encoding="utf-8",
    )

    with caplog.at_level("ERROR", logger="backend.services.learning_service"):
        with pytest.raises(json.JSONDecodeError):
            svc._read()

    assert any(
        "corrupt ledger" in record.message for record in caplog.records
    ), "expected the guarded _read path's diagnostic log to fire alongside the raise"

    # And the corrupt bytes must still be sitting there -- no quarantine,
    # no silent rewrite. The read failure must be visible/diagnosable, not
    # papered over.
    assert path.exists()


def test_failed_write_leaves_original_store_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, path = _store(tmp_path)
    original = {
        "seed_version": 3,
        "open_trades": [{"trade_id": "trd_original"}],
        "outcomes": [],
        "failure_memories": [],
        "adaptation_history": [],
        "module_weights": {},
        "peak_equity_inr": 0.0,
        "equity_inr": 0.0,
    }
    svc._write(original)
    original_bytes = path.read_text(encoding="utf-8")

    def _always_fails(src, dst):  # noqa: ANN001 - matches os.replace signature
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(os, "replace", _always_fails)
    monkeypatch.setattr("backend.services.learning_service.time.sleep", lambda _s: None, raising=False)

    with pytest.raises(PermissionError):
        svc._write({"seed_version": 3, "open_trades": [{"trade_id": "trd_new_bad"}]})

    assert path.read_text(encoding="utf-8") == original_bytes
    assert json.loads(path.read_text(encoding="utf-8"))["open_trades"][0]["trade_id"] == "trd_original"

    # No stray temp files left behind by the failed write attempt.
    leftovers = [p for p in tmp_path.iterdir() if p != path]
    assert leftovers == []
