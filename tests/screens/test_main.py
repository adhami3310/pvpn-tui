from __future__ import annotations

import pytest

from pvpn_tui.screens.main import _human_bytes, _human_uptime


@pytest.mark.parametrize(
    "n,expected",
    [
        (0, "0 B"),
        (1, "1 B"),
        (1023, "1023 B"),
        (1024, "1.0 KiB"),
        (1536, "1.5 KiB"),
        (1024 * 1024, "1.0 MiB"),
        (1024 * 1024 * 1024 + 512 * 1024 * 1024, "1.5 GiB"),
    ],
)
def test_human_bytes(n: int, expected: str) -> None:
    assert _human_bytes(n) == expected


@pytest.mark.parametrize(
    "secs,expected",
    [
        (0, "0s"),
        (1, "1s"),
        (59, "59s"),
        (60, "1m 00s"),
        (61, "1m 01s"),
        (3599, "59m 59s"),
        (3600, "1h 00m 00s"),
        (3661, "1h 01m 01s"),
        (90061, "25h 01m 01s"),
    ],
)
def test_human_uptime(secs: int, expected: str) -> None:
    assert _human_uptime(secs) == expected


def test_human_uptime_negative_clamps_to_zero() -> None:
    assert _human_uptime(-5) == "0s"


def test_human_uptime_accepts_floats() -> None:
    assert _human_uptime(12.7) == "12s"
