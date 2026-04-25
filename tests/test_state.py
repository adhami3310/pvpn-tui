from __future__ import annotations

from pathlib import Path

import pytest

from pvpn_tui.state import AppState


@pytest.fixture
def state_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    return tmp_path / "pvpn-tui" / "state.json"


def test_load_returns_empty_when_missing(state_home: Path) -> None:
    assert not state_home.exists()
    s = AppState.load()
    assert s.last_server_id is None


def test_save_then_load_round_trip(state_home: Path) -> None:
    AppState(last_server_id="abc123").save()
    assert state_home.exists()
    assert AppState.load().last_server_id == "abc123"


def test_save_creates_parent_dir(state_home: Path) -> None:
    assert not state_home.parent.exists()
    AppState(last_server_id="x").save()
    assert state_home.parent.is_dir()


def test_load_corrupt_file_falls_back_to_empty(state_home: Path) -> None:
    state_home.parent.mkdir(parents=True)
    state_home.write_text("not json {")
    s = AppState.load()
    assert s.last_server_id is None


def test_load_unexpected_keys_are_ignored(state_home: Path) -> None:
    state_home.parent.mkdir(parents=True)
    state_home.write_text('{"last_server_id": "x", "future_field": 42}')
    assert AppState.load().last_server_id == "x"
