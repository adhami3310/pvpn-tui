from __future__ import annotations

import pytest

from pvpn_tui.widgets import _pretty_key


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("escape", "esc"),
        ("slash", "/"),
        ("enter", "↵"),
        ("space", "␣"),
        ("tab", "⇥"),
        ("up", "↑"),
        ("down", "↓"),
        ("left", "←"),
        ("right", "→"),
        ("ctrl+q", "^q"),
        ("ctrl+c", "^c"),
        ("ctrl+shift+a", "^shift+a"),
        ("f", "f"),
        ("L", "L"),
    ],
)
def test_pretty_key(raw: str, expected: str) -> None:
    assert _pretty_key(raw) == expected
