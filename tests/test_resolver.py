from __future__ import annotations

from dataclasses import dataclass

import pytest

from pvpn_tui.resolver import resolve


@dataclass
class FakeServer:
    id: str
    name: str
    exit_country: str = "US"


class FakeServerList:
    """Just enough of ServerList for the resolver to work against."""

    def __init__(self, servers: list[FakeServer], fastest_idx: int = 0) -> None:
        self._servers = servers
        self._fastest_idx = fastest_idx

    def get_fastest(self) -> FakeServer:
        return self._servers[self._fastest_idx]

    def get_fastest_in_country(self, country: str) -> FakeServer:
        for s in self._servers:
            if s.exit_country == country:
                return s
        raise LookupError(country)

    def get_by_name(self, name: str) -> FakeServer:
        for s in self._servers:
            if s.name == name:
                return s
        raise LookupError(name)

    def get_by_id(self, sid: str) -> FakeServer:
        for s in self._servers:
            if s.id == sid:
                return s
        raise LookupError(sid)


@pytest.fixture
def sl() -> FakeServerList:
    return FakeServerList(
        [
            FakeServer("id-us-1", "US-CA#1", "US"),
            FakeServer("id-us-2", "US-NY#42", "US"),
            FakeServer("id-jp-1", "JP#5", "JP"),
        ],
        fastest_idx=0,
    )


def test_empty_selector_returns_none(sl: FakeServerList) -> None:
    assert resolve("", sl) is None
    assert resolve("   ", sl) is None


def test_fastest(sl: FakeServerList) -> None:
    assert resolve("fastest", sl).id == "id-us-1"


def test_fastest_case_insensitive(sl: FakeServerList) -> None:
    assert resolve("FASTEST", sl).id == "id-us-1"


def test_country_code(sl: FakeServerList) -> None:
    assert resolve("JP", sl).id == "id-jp-1"


def test_country_code_lowercase(sl: FakeServerList) -> None:
    assert resolve("jp", sl).id == "id-jp-1"


def test_unknown_country_falls_through_to_name_lookup(sl: FakeServerList) -> None:
    # 'ZZ' isn't a country; not a name either; not an id → None
    assert resolve("ZZ", sl) is None


def test_server_name(sl: FakeServerList) -> None:
    assert resolve("US-NY#42", sl).id == "id-us-2"


def test_server_id(sl: FakeServerList) -> None:
    assert resolve("id-jp-1", sl).id == "id-jp-1"


def test_last_returns_server_for_known_id(sl: FakeServerList) -> None:
    out = resolve("last", sl, last_server_id="id-us-2")
    assert out is not None and out.id == "id-us-2"


def test_last_returns_none_when_no_history(sl: FakeServerList) -> None:
    assert resolve("last", sl, last_server_id=None) is None


def test_last_with_unknown_id_returns_none(sl: FakeServerList) -> None:
    assert resolve("last", sl, last_server_id="gone") is None
