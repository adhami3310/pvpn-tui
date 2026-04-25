from __future__ import annotations

from dataclasses import dataclass

import pytest

from pvpn_tui.proton_api import ServerFeature
from pvpn_tui.screens.servers import (
    ServerRow,
    SortKey,
    _build_rows,
    _matches,
    _sort_keyfn,
)

# ---- ServerRow.features_str ------------------------------------------------


def test_features_str_empty() -> None:
    r = _row(features=())
    assert r.features_str == ""


def test_features_str_orders_by_input() -> None:
    r = _row(features=(ServerFeature.P2P, ServerFeature.STREAMING))
    assert r.features_str == "P2P Stream"


def test_features_str_renders_secure_core_and_tor() -> None:
    r = _row(features=(ServerFeature.SECURE_CORE, ServerFeature.TOR))
    assert "SC" in r.features_str
    assert "Tor" in r.features_str


# ---- _matches ------------------------------------------------------------


@pytest.mark.parametrize(
    "needle,want",
    [
        ("", True),
        ("us", True),
        ("US", False),  # _matches expects already-lowercased needle
        ("francisco", True),
        ("ZZ", False),
        ("ny#42", True),
    ],
)
def test_matches(needle: str, want: bool) -> None:
    r = _row(country="United States", city="San Francisco", name="US-NY#42")
    assert _matches(r, needle) is want


# ---- _sort_keyfn ---------------------------------------------------------


def test_sort_by_country_alphabetical() -> None:
    rows = [
        _row(country="Japan", city="Tokyo"),
        _row(country="Albania", city="Tirana"),
        _row(country="United States", city="NY"),
    ]
    rows.sort(key=_sort_keyfn(SortKey.COUNTRY))
    assert [r.country for r in rows] == ["Albania", "Japan", "United States"]


def test_sort_by_load_ascending() -> None:
    rows = [_row(load=80), _row(load=10), _row(load=50)]
    rows.sort(key=_sort_keyfn(SortKey.LOAD))
    assert [r.load for r in rows] == [10, 50, 80]


def test_sort_by_score_ascending() -> None:
    rows = [_row(score=2.5), _row(score=0.5), _row(score=1.5)]
    rows.sort(key=_sort_keyfn(SortKey.SCORE))
    assert [r.score for r in rows] == [0.5, 1.5, 2.5]


def test_sort_by_name_alphabetical() -> None:
    rows = [_row(name="JP#5"), _row(name="DE#1"), _row(name="US#10")]
    rows.sort(key=_sort_keyfn(SortKey.NAME))
    assert [r.name for r in rows] == ["DE#1", "JP#5", "US#10"]


# ---- _build_rows ---------------------------------------------------------


@dataclass
class FakePhysical:
    enabled: bool = True


@dataclass
class FakeLogical:
    id: str
    name: str
    exit_country: str
    exit_country_name: str
    city: str
    load: int
    score: float
    features: tuple
    enabled: bool = True
    under_maintenance: bool = False
    tier: int = 0
    physical_servers: tuple = ()


def _logical(**kw) -> FakeLogical:
    base = {
        "id": "id-x",
        "name": "X#1",
        "exit_country": "US",
        "exit_country_name": "United States",
        "city": "NY",
        "load": 30,
        "score": 1.0,
        "features": (ServerFeature.P2P,),
    }
    base.update(kw)
    return FakeLogical(**base)


def test_build_rows_drops_disabled() -> None:
    out = _build_rows([_logical(enabled=False)], user_tier=2)
    assert out == []


def test_build_rows_drops_under_maintenance() -> None:
    out = _build_rows([_logical(under_maintenance=True)], user_tier=2)
    assert out == []


def test_build_rows_drops_tiers_above_user() -> None:
    above = _logical(id="hi", tier=2)
    same = _logical(id="ok", tier=1)
    below = _logical(id="lo", tier=0)
    out = _build_rows([above, same, below], user_tier=1)
    ids = {r.server_id for r in out}
    assert ids == {"ok", "lo"}


def test_build_rows_falls_back_to_country_code() -> None:
    out = _build_rows([_logical(exit_country_name="", exit_country="JP")], user_tier=2)
    assert out[0].country == "JP"


def test_build_rows_falls_back_to_question_mark() -> None:
    out = _build_rows(
        [_logical(exit_country_name="", exit_country="")],
        user_tier=2,
    )
    assert out[0].country == "?"


# ---- helpers -------------------------------------------------------------


def _row(
    *,
    server_id: str = "id-1",
    country: str = "United States",
    city: str = "San Francisco",
    name: str = "US-CA#1",
    load: int = 30,
    score: float = 1.5,
    features: tuple = (),
) -> ServerRow:
    return ServerRow(
        server_id=server_id,
        country=country,
        city=city,
        name=name,
        load=load,
        score=score,
        features=features,
    )
