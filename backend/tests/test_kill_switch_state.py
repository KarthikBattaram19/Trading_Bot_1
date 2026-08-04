from __future__ import annotations

from backend.services.kill_switch_state import KillSwitchState


def test_defaults_to_unarmed_when_no_file_exists(tmp_path):
    state = KillSwitchState(store_path=tmp_path / "kill_switch_state.json")
    assert state.is_armed() is False


def test_armed_state_survives_simulated_process_restart(tmp_path):
    """
    A fresh KillSwitchState instance (standing in for a restarted process —
    the original process's Python object is gone) reading the same file
    must still see the switch as armed, per Docs/bot_health/BACKLOG.md P0.
    """
    store_path = tmp_path / "kill_switch_state.json"
    state = KillSwitchState(store_path=store_path)
    state.set_armed(True)

    restarted = KillSwitchState(store_path=store_path)
    assert restarted.is_armed() is True

    restarted.set_armed(False)
    respawned = KillSwitchState(store_path=store_path)
    assert respawned.is_armed() is False


def test_bot_router_reads_persisted_state(tmp_path, monkeypatch):
    """bot.is_kill_switch_armed() must reflect the persisted store, not a
    process-local flag — this is what the paper_sim automation loop and
    risk gate both read to halt trading."""
    from backend.routers import bot as bot_router
    from backend.services import kill_switch_state

    state = KillSwitchState(store_path=tmp_path / "kill_switch_state.json")
    monkeypatch.setattr(kill_switch_state, "_kill_switch_state", state)

    assert bot_router.is_kill_switch_armed() is False
    state.set_armed(True)
    assert bot_router.is_kill_switch_armed() is True
